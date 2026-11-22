# review-prints: a tool, not a step: a local page for the stored prints (stored-prints.md; src/stored_prints.py,
# prints.json in the repo root), the user's changes made in the store at once, through its interface as manual changes
# (rule 10): a change to a frozen print unfreezes it, without asking (rule 8). The page shows the store itself.
# Tabs:
#   - Same serial: the serials of several stored prints, the most prints first, SERIALS_PER_PAGE at a time: join some,
#     "Join all", or "All different" (looked_at.same_serial: hidden while its prints are these).
#   - Several serials: prints whose label photos' straightened serials (read-serials' straightened_serial) differ (label
#     photos without one don't count). A print of several serials is nonsense, to be fixed by hand (the user,
#     2026-11-22: split or set the serial), and isn't restored until it is. The most label photos reading another
#     serial first.
#   - No serial: prints without a serial (label photos without a straightened serial that joined no print).
#   - New: the prints the last make prints made or added label photos to (<generated>/prints/id-changes.json).
#   - Every print, worst first: the most label photos reading another serial, then the most differing tiles between two
#     of its label photos (the prints step's pair cache).
#   - Search: a serial, a stem or an id (its start), up to SEARCH_MAX prints.
#   - Recent changes: the store's change log, the latest first; Undo on the latest manual change (Store.undo).
# Each print: its label photos sorted by straightened serial (none last), straighten's image as is (full resolution
# and uncropped, for pinch-zooming), each with a tick box: "Split off ticked" makes the ticked a print of their own (the
# serial their straightened reads give most, else the print's). A print's tick box marks it for joining: "Join ticked"
# in the bar at the bottom joins the ticked prints (into the one with the most label photos). "Delete label photo": out
# of its print; a photo holding no other label photo (find's) is deleted from photos/ (photos.delete), else its area is
# marked in find's NOT_LABELS ("why": "deleted in review-prints") and the next make find makes no label photo there.
# "Set serial": the print's serial (it's renamed: Store.set_serial) and every label photo's in serial-corrections.json
# (read_serials.CORRECTIONS); setting the serial it has only does the latter (a frozen print stays frozen). Freeze:
# a print with its image from make restore under its id (frozen.freeze); Unfreeze doesn't ask. A deleted label photo or
# a joined print leaves a hole of its size, so nothing moves. Buttons only, no keys (the user: keys next to S are too
# easy to hit).
# Usage: review_prints.py [port]
import json, os, re, sys, threading, urllib.parse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, numpy as np
import photos, steps, shapes, straighten, frozen, find as find_step, stored_prints, prints as prints_step, serials as serials_db
from read_serials import CORRECTIONS

GEN = photos.generated(False)
SERIALS_PER_PAGE = 10
PRINTS_PER_PAGE = 20
SEARCH_MAX = 50
LOG_SHOWN = 200
lock = threading.Lock()


def pair_tiles(gen):
    """{(key, key): differing tiles} from the prints step's pair cache."""
    path = os.path.join(gen, "prints", "pairs.npz")
    if not os.path.exists(path):
        return {}
    z = np.load(path)
    bits = np.unpackbits(z["bits"]).astype(np.int32)
    ends = z["starts"] * 8
    sums = np.add.reduceat(bits, ends[:-1]) if len(bits) else np.zeros(0, int)
    sums = np.where(ends[1:] > ends[:-1], sums, 0)  # an empty entry: reduceat gives the next one's first bit
    out = {}
    for name, n in zip(z["names"], sums):
        a, b = str(name).split("|")[:2]
        out[a, b] = out[b, a] = int(n)
    return out


class Tool:
    def __init__(self):
        self.serials = json.load(open(os.path.join(GEN, "read-serials", "serials.json")))
        self.solved = json.load(open(os.path.join(GEN, "solve", "solve.json")))["label_photos"]
        found = json.load(open(os.path.join(GEN, "find", "label-photos.json")))["label_photos"]
        self.outlines = {lp["key"]: lp["outline"] for lp in found}
        self.photo_keys = {}
        for k in self.outlines:
            self.photo_keys.setdefault(k.split("@")[0], set()).add(k)
        changes_file = os.path.join(GEN, "prints", "id-changes.json")
        self.last_run = json.load(open(changes_file)) if os.path.exists(changes_file) else []
        self.tiles = pair_tiles(GEN)
        self.present = set(photos.all_photos())
        self.release_of = serials_db.load_database()
        self.load_store()

    def load_store(self):
        self.store = stored_prints.Store()
        self.store_mtime = os.path.getmtime(stored_prints.FILE) if os.path.exists(stored_prints.FILE) else 0
        self.compute()

    def fresh(self):
        """The store as on disk (make prints may have written it since)."""
        if os.path.exists(stored_prints.FILE) and os.path.getmtime(stored_prints.FILE) != self.store_mtime:
            self.load_store()

    def save(self):
        self.store.save()
        self.store_mtime = os.path.getmtime(stored_prints.FILE)
        self.compute()

    def corrections(self):
        return json.load(open(CORRECTIONS)) if os.path.exists(CORRECTIONS) else {"corrections": {}}

    def write_corrections(self, corrections):
        data = self.corrections()
        data["corrections"] = dict(sorted((k, v) for k, v in corrections.items() if v))
        tmp = CORRECTIONS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CORRECTIONS)

    def not_labels(self):
        return json.load(open(find_step.NOT_LABELS)) if os.path.exists(find_step.NOT_LABELS) else {}

    def label_serial(self, k, hand):
        """A label photo's straightened serial (a serial set by hand wins: as make read-serials will have it)."""
        return hand.get(k) or (self.serials.get(k) or {}).get("straightened_serial")

    def compute(self):
        hand = self.corrections()["corrections"]
        looked = self.store.data["looked_at"]
        out = []
        for pid, p in sorted(self.store.prints.items()):
            keys = sorted(p["label_photos"])
            ser = p.get("serial")
            read = {k: self.label_serial(k, hand) for k in keys}
            release = lambda k: (self.serials.get(k) or {}).get("release")
            disagree = sum(1 for k in keys if read[k] and read[k] != ser)
            restored = os.path.exists(os.path.join(GEN, "restore", straighten.file_name(pid)))
            image = os.path.exists(frozen.image_path(pid)) if p.get("frozen") else restored
            tiles = max((self.tiles.get((a, b), 0) for i, a in enumerate(keys) for b in keys[i + 1:]), default=0)
            fams = {self.solved[k]["family"] for k in keys if k in self.solved}
            out.append({"id": pid, "keys": [{"key": k, "serial": read[k], "release": release(k), "by_hand": k in hand} for k in keys],
                        "serial": ser, "frozen": bool(p.get("frozen")), "image": bool(image), "restored": restored,
                        "families": len(fams), "disagree": disagree, "tiles": tiles})
        index = {p["id"]: i for i, p in enumerate(out)}
        by_serial = {}
        for i, p in enumerate(out):
            if p["serial"]:
                by_serial.setdefault(p["serial"], []).append(i)
        same = []
        for s, idx in by_serial.items():
            if len(idx) > 1:
                ids = sorted(out[i]["id"] for i in idx)
                same.append({"serial": s, "prints": idx, "looked_at": ids in looked["same_serial"].get(s, [])})
        same.sort(key=lambda e: (-len(e["prints"]), -sum(len(out[i]["keys"]) for i in e["prints"]), e["serial"]))
        nserials = lambda i: len({k["serial"] for k in out[i]["keys"] if k["serial"]})
        several = [i for i in range(len(out)) if nserials(i) > 1]
        several.sort(key=lambda i: (-out[i]["disagree"], -nserials(i), -len(out[i]["keys"])))
        worst = sorted(range(len(out)), key=lambda i: (-out[i]["disagree"], -out[i]["tiles"], -len(out[i]["keys"])))
        none = sorted((i for i in range(len(out)) if not out[i]["serial"]), key=lambda i: -len(out[i]["keys"]))
        new = []
        for c in self.last_run:
            if c["kind"] in ("new", "added") and c["id"] in index and index[c["id"]] not in new:
                new.append(index[c["id"]])
        log = self.store.data["log"]
        latest_manual = next((n for n in range(len(log) - 1, -1, -1) if log[n]["manual"]), None)
        shown_log = [{"index": n, "datetime": e["datetime"], "kind": e["kind"], "manual": e["manual"],
                      "before": {pid: (s and len(s["keys"])) for pid, s in e["before"].items()},
                      "after": {pid: (s and len(s["keys"])) for pid, s in e["after"].items()}}
                     for n, e in list(enumerate(log))[-LOG_SHOWN:]][::-1]
        self.state_json = {"prints": out, "same": same, "worst": worst, "several": several, "none": none, "new": new,
                           "log": shown_log, "log_total": len(log), "undoable": latest_manual,
                           "per_page": {"serials": SERIALS_PER_PAGE, "prints": PRINTS_PER_PAGE, "search": SEARCH_MAX}}

    # --- changes, all manual (stored-prints.md rule 10)
    def known(self, ids):
        missing = [pid for pid in ids if pid not in self.store.prints]
        return f"Not a stored print any more: {missing[0]} (reload)." if missing else None

    def join(self, ids):
        self.fresh()
        if len(set(ids)) < 2:
            return "Tick two or more prints."
        why = self.known(ids)
        if why:
            return why
        into = self.store.join(sorted(set(ids)), manual=True)
        print(f"joined {len(ids)} prints into {into}", flush=True)
        self.save()

    def split(self, pid, keys):
        self.fresh()
        why = self.known([pid])
        if why:
            return why
        lps = self.store.prints[pid]["label_photos"]
        keys = [k for k in keys if k in lps]
        if not keys or len(keys) == len(lps):
            return "Tick some of a print's label photos, not all (reload)."
        hand = self.corrections()["corrections"]
        reads = Counter(self.label_serial(k, hand) for k in keys if self.label_serial(k, hand))
        new = self.store.split(pid, keys, manual=True, serial=reads.most_common(1)[0][0] if reads else None)
        print(f"split {len(keys)} label photos off {pid}: {new}", flush=True)
        self.save()

    def looked_same(self, serial, ids):
        self.fresh()
        self.store.data["looked_at"]["same_serial"].setdefault(serial, []).append(sorted(ids))
        self.save()

    def set_frozen(self, pid, on):
        self.fresh()
        why = self.known([pid])
        if why:
            return why
        p = self.store.prints[pid]
        if not on:
            frozen.unfreeze(pid)
            print(f"unfrozen {pid}", flush=True)
        else:
            if p.get("frozen"):
                return "Already frozen."
            base = os.path.join(GEN, "restore", straighten.file_name(pid)[:-5])
            if not os.path.exists(base + ".avif"):
                return "Only a print with its image from make restore can be frozen (after make prints restore)."
            keys = sorted(p["label_photos"])
            shape = next((self.solved[k]["shape"] for k in keys if k in self.solved), None)
            frozen.freeze(pid, {"keys": keys, "shape": shape}, self.solved, self.outlines, base)
            print(f"frozen {pid}", flush=True)
        self.load_store()

    def set_serial(self, pid, serial):
        """The print's serial (renamed) and every label photo's in serial-corrections.json: None, or why not."""
        self.fresh()
        serial = re.sub(r"\s+", " ", (serial or "").strip().upper())
        why = self.known([pid])
        if why:
            return why
        if not re.fullmatch(r"[A-Z0-9]+(-[A-Z0-9]+)+( [A-Z]{3})?", serial):  # DMG-133 CHN: Chinese, as in releases.json
            return f"Not a serial: {serial!r} (like DMG-APSJ-JPN, or DMG-133 CHN)."
        keys = sorted(self.store.prints[pid]["label_photos"])
        data = self.corrections()
        before = {k: data["corrections"].get(k) for k in keys}
        self.write_corrections({**data["corrections"], **{k: serial for k in keys}})
        logged = len(self.store.data["log"])
        new = self.store.set_serial(pid, serial, manual=True)
        if len(self.store.data["log"]) > logged:  # for Undo
            self.store.data["log"][-1]["corrections_before"] = before
        print(f"serial {serial}: {pid}" + (f" renamed {new}" if new != pid else "") + f", {len(keys)} label photos", flush=True)
        self.save()

    def delete(self, key):
        """A label photo out of its print: its photo deleted if it holds no other, else its area marked not a label."""
        self.fresh()
        sha1 = (key or "").split("@")[0]
        pid = self.store.print_of().get(key)
        if pid is None:
            return "Not in a stored print any more: reload."
        if sha1 in self.present:
            if self.photo_keys.get(sha1, set()) - {key}:
                r = self.solved.get(key)
                area = None
                if r:
                    w, h = shapes.LABEL_MM[r["shape"]]
                    area = cv2.perspectiveTransform(np.float64([[[0, 0]], [[w, 0]], [[w, h]], [[0, h]]]),
                                                    np.float64(r["cut_to_photo"])).reshape(-1, 2)
                    area = np.round(area, 1).tolist()
                marked = self.not_labels()
                marked[key] = {"photo": sha1, "area": area, "found": self.outlines.get(key), "why": "deleted in review-prints",
                               "datetime": stored_prints.now()}
                steps.write_json(find_step.NOT_LABELS, marked)
                print(f"label photo {key} marked not a label", flush=True)
            else:
                photos.delete(sha1)
                print(f"deleted {sha1}", flush=True)
                self.present.discard(sha1)
        self.store.remove(pid, [key], manual=True, why="deleted in review-prints")
        self.save()

    def undo(self, index):
        self.fresh()
        if index != self.state_json["undoable"]:
            return "The changes changed: reload."
        e = self.store.data["log"][index]
        dropped = list(e.get("dropped", {}))
        if e["kind"] == "remove" and any(k.split("@")[0] not in self.present for k in dropped):
            return "Its photo was deleted from photos/: that can't be undone here."
        why = self.store.undo()
        if why:
            return why
        if "corrections_before" in e:  # Set serial: the label photos' serials as they were
            self.write_corrections({**self.corrections()["corrections"], **e["corrections_before"]})
        if e["kind"] == "remove":  # a deleted label photo: not marked "not a label" any more
            marked = self.not_labels()
            if any(marked.get(k, {}).get("why") == "deleted in review-prints" for k in dropped):
                steps.write_json(find_step.NOT_LABELS, {k: v for k, v in marked.items() if not (k in dropped and v.get("why") == "deleted in review-prints")})
        print("undone", flush=True)
        self.save()


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>review prints</title>
<style>
body{font:14px system-ui;margin:0 0 70px;background:#2b2b2b;color:#eee}
header{position:sticky;top:0;background:#1d1d1d;padding:8px 16px;z-index:2;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
header button.tab.on{background:#5a8;color:#000}
main{padding:8px 16px}
button{font:inherit;padding:4px 10px;border-radius:4px;border:1px solid #777;background:#444;color:#eee;cursor:pointer}
button:disabled{opacity:.4;cursor:default}
.serial{margin:12px 0 24px;padding:8px;border:1px solid #555;border-radius:6px}
.serial h2{font-size:16px;margin:0 0 6px}
.print{display:block;width:fit-content;margin:4px 0 8px;padding:6px;border:1px solid #666;border-radius:6px;background:#333;max-width:100%}
.print.hole{box-sizing:border-box;border:1px dashed #555;background:none;color:#777;display:flex;align-items:center;justify-content:center}
.lp.hole{box-sizing:border-box;border:1px dashed #555;color:#777;display:flex;align-items:center;justify-content:center}
.print.ticked{border-color:#5a8;box-shadow:0 0 0 2px #5a8}
.print .head{display:flex;gap:8px;align-items:center;margin-bottom:4px;flex-wrap:wrap}
.print .restored{width:220px;display:block;margin-bottom:4px}
.lps{display:flex;flex-wrap:wrap;gap:4px;max-width:860px}
.lp{width:160px;font-size:11px;position:relative}
.lp img{width:160px;display:block}
.lp.ticked img{outline:3px solid #fa0}
.lp .odd{color:#f96}
.lp .del{font-size:11px;padding:1px 6px;margin-top:2px}
.frozen{color:#6bf}
.note{color:#aaa;font-size:12px}
#bar{position:fixed;bottom:0;left:0;right:0;background:#1d1d1d;padding:10px 16px;display:flex;gap:10px;align-items:center;z-index:2}
#msg{color:#fa0}
.pager{margin:8px 0}
</style></head><body>
<header>
<button class="tab" data-tab="same">Same serial</button>
<button class="tab" data-tab="several">Several serials</button>
<button class="tab" data-tab="none">No serial</button>
<button class="tab" data-tab="new">New</button>
<button class="tab" data-tab="worst">Every print, worst first</button>
<button class="tab" data-tab="search">Search</button>
<button class="tab" data-tab="log">Recent changes</button>
<span id="searchbox" style="display:none"><input id="q" placeholder="serial, stem or id" size="24"> <button id="go">Search</button></span>
<label id="lookedbox" style="display:none"><input type="checkbox" id="looked"> show serials looked at</label>
</header>
<main id="main">loading…</main>
<div id="bar"><span id="count">No prints ticked for joining.</span><button id="join" disabled>Join ticked</button><button id="clear" disabled>Clear</button><span id="msg"></span></div>
<script>
let S = null, tab = "same", page = 0, query = "";
const joinTicks = new Set();  // print ids ticked for joining
const lpTicks = new Set();    // label photo keys ticked for splitting
const $ = id => document.getElementById(id);

async function load(show = true) {
  const r = await fetch("/state");
  if (r.status === 503) { setTimeout(() => load(show), 1000); return; }
  S = await r.json();
  const now = new Set(S.prints.map(p => p.id));
  for (const id of [...joinTicks]) if (!now.has(id)) joinTicks.delete(id);
  if (show) { lpTicks.clear(); render(); }
  bar();
}

async function post(path, body, show = true) {
  $("msg").textContent = "";
  const r = await fetch(path, {method: "POST", body: JSON.stringify(body)});
  if (!r.ok) { $("msg").textContent = await r.text(); return false; }
  await load(show);
  return true;
}

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) { if (k === "class") e.className = v; else if (k.startsWith("on")) e[k] = v; else e.setAttribute(k, v); }
  for (const k of kids) e.append(k);
  return e;
}

function printCard(p, extra) {
  const keys = p.keys.map(k => k.key);
  const card = el("div", {class: "print" + (joinTicks.has(p.id) ? " ticked" : "")});
  card.pid = p.id;
  const tick = el("input", {type: "checkbox"});
  tick.checked = joinTicks.has(p.id);
  tick.onchange = () => { if (tick.checked) joinTicks.add(p.id); else joinTicks.delete(p.id); card.classList.toggle("ticked", tick.checked); bar(); };
  const count = el("span", {}, `${p.keys.length}`);
  const head = el("div", {class: "head"}, el("label", {}, tick, " join"), el("b", {}, p.id),
    el("span", {class: "note"}, `${p.serial || "no serial"} · `, count, ` label photos` + (p.families > 1 ? ` · ${p.families} families` : "") +
      (p.disagree ? ` · ${p.disagree} read another serial` : "") + (p.tiles ? ` · up to ${p.tiles} tiles differ` : "")));
  if (p.frozen) head.append(el("span", {class: "frozen"}, "frozen"));
  const fz = el("button", {onclick: () => post("/freeze", {id: p.id, on: !p.frozen})}, p.frozen ? "Unfreeze" : "Freeze");
  if (!p.frozen && !p.restored) { fz.disabled = true; fz.title = "only a print with its image from make restore"; }
  head.append(fz);
  if (extra) head.append(extra);
  card.append(head);
  if (p.image) card.append(el("img", {class: "restored", loading: "lazy", src: "/print/" + encodeURIComponent(p.id)}));
  else if (p.keys.length >= 3) card.append(el("div", {class: "note"}, "no restored image yet (make restore)"));
  const lps = el("div", {class: "lps"});
  // sorted by straightened serial, none last (the user, 2026-11-21)
  const bySerial = [...p.keys].sort((a, b) => !a.serial - !b.serial || (a.serial || "").localeCompare(b.serial || "") || a.key.localeCompare(b.key));
  for (const k of bySerial) {
    const box = el("input", {type: "checkbox"});
    box.checked = lpTicks.has(k.key);
    const lp = el("div", {class: "lp" + (box.checked ? " ticked" : "")},
      el("label", {}, el("img", {loading: "lazy", src: "/label/" + encodeURIComponent(k.key)}),
        box, el("span", {class: k.serial && k.serial !== p.serial ? "odd" : ""}, " " + (k.serial || "no serial read"))));
    lp.append(el("div", {}, el("button", {class: "del", onclick: async () => {
      if (!await post("/delete", {key: k.key}, false)) return;
      // a hole where it was, so the page doesn't move; the card's other buttons act on the label photos left
      lpTicks.delete(k.key);
      keys.splice(keys.indexOf(k.key), 1);
      if (!keys.length) { joinTicks.delete(p.id); holes(new Set([p.id]), "deleted"); bar(); return; }
      const r = lp.getBoundingClientRect();
      lp.replaceWith(el("div", {class: "lp hole", style: `width:${r.width}px;height:${r.height}px`}, "deleted"));
      count.textContent = keys.length;
      split.disabled = !canSplit(); bar();
    }}, "Delete label photo")));
    box.onchange = () => { if (box.checked) lpTicks.add(k.key); else lpTicks.delete(k.key); lp.classList.toggle("ticked", box.checked); split.disabled = !canSplit(); };
    lps.append(lp);
  }
  const canSplit = () => { const n = keys.filter(k => lpTicks.has(k)).length; return n > 0 && n < keys.length; };
  const split = el("button", {onclick: () => post("/split", {id: p.id, keys: keys.filter(k => lpTicks.has(k))})}, "Split off ticked");
  split.disabled = !canSplit();
  const input = el("input", {size: "16", placeholder: "serial", value: p.serial || ""});
  const set = el("button", {onclick: () => post("/serial", {id: p.id, serial: input.value})}, "Set serial");
  const hand = p.keys.every(k => k.by_hand) ? el("span", {class: "note"}, " entered by hand") : "";
  card.append(lps, el("div", {style: "margin-top:4px;display:flex;gap:6px;align-items:center;flex-wrap:wrap"}, split, input, set, hand));
  return card;
}

function pager(n, per) {
  const pages = Math.max(1, Math.ceil(n / per));
  page = Math.min(page, pages - 1);
  const prev = el("button", {onclick: () => { page--; render(); scrollTo(0, 0); }}, "Previous");
  const next = el("button", {onclick: () => { page++; render(); scrollTo(0, 0); }}, "Next");
  prev.disabled = page === 0; next.disabled = page >= pages - 1;
  return el("div", {class: "pager"}, prev, ` page ${page + 1} of ${pages} `, next);
}

function list(indexes, note, extra) {
  const m = $("main"), per = S.per_page.prints;
  m.append(el("p", {class: "note"}, note), pager(indexes.length, per));
  for (const i of indexes.slice(page * per, (page + 1) * per)) m.append(printCard(S.prints[i], extra && extra(S.prints[i])));
  m.append(pager(indexes.length, per));
}

function render() {
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  $("searchbox").style.display = tab === "search" ? "" : "none";
  $("lookedbox").style.display = tab === "same" ? "" : "none";
  const m = $("main"); m.innerHTML = "";
  if (!S) { m.textContent = "loading…"; return; }
  if (tab === "same") {
    const shown = S.same.filter(e => $("looked").checked || !e.looked_at);
    const per = S.per_page.serials;
    m.append(el("p", {class: "note"}, `${shown.length} serials of several prints` + ($("looked").checked ? "" : `; ${S.same.length - shown.length} looked at, hidden`) + ". The most prints first."), pager(shown.length, per));
    for (const e of shown.slice(page * per, (page + 1) * per)) {
      const ps = e.prints.map(i => S.prints[i]);
      const cards = ps.map(p => printCard(p));
      const left = () => cards.filter(c => c.isConnected).map(c => c.pid);  // a print whose label photos were all deleted is a hole
      const apart = el("button", {onclick: () => post("/apart", {serial: e.serial, ids: left()})}, "All different");
      apart.title = "these prints are different prints: hide this serial while its prints are these";
      const box = el("div", {class: "serial"}, el("h2", {}, `${e.serial}: ${ps.length} prints` + (e.looked_at ? " (looked at)" : "")));
      cards.forEach(c => box.append(c));
      const all = el("button", {}, "Join all");
      all.title = "these prints are one print: join them all";
      all.onclick = async () => {
        const ids = left();
        if (!await post("/join", {ids}, false)) return;
        holes(new Set(ids), "joined");
        for (const id of ids) joinTicks.delete(id);
        all.disabled = apart.disabled = true; bar();
      };
      box.append(el("div", {}, all, " ", apart));
      m.append(box);
    }
    m.append(pager(shown.length, per));
  } else if (tab === "several") {
    list(S.several, `${S.several.length} prints whose label photos read several serials (label photos without one don't count): fix each by splitting or setting the serial. Not restored until fixed. The most label photos reading another serial first.`);
  } else if (tab === "none") {
    list(S.none, `${S.none.length} prints without a serial: label photos whose straightened image gave none and matched no print. Join them into a print, or set the serial.`);
  } else if (tab === "new") {
    list(S.new, `${S.new.length} prints the last make prints made or added label photos to.`);
  } else if (tab === "worst") {
    list(S.worst, `${S.prints.length} prints: the most label photos reading another serial first, then the most differing tiles between two of its label photos.`);
  } else if (tab === "search") {
    const q = query.trim().toUpperCase();
    if (!q) { m.append(el("p", {class: "note"}, "A serial (DMG-APSJ-JPN), a stem (DMG-APS) or an id (DMG-APSJ-JPN-lisa).")); return; }
    const hits = S.prints.filter(p => [p.serial, p.id].some(s => s && s.toUpperCase().startsWith(q)));
    m.append(el("p", {class: "note"}, `${hits.length} prints` + (hits.length > S.per_page.search ? `, the first ${S.per_page.search} shown` : "")));
    hits.sort((a, b) => (a.serial || "").localeCompare(b.serial || "") || b.keys.length - a.keys.length);
    hits.slice(0, S.per_page.search).forEach(p => m.append(printCard(p)));
  } else {
    m.append(el("p", {class: "note"}, `${S.log_total} changes to the stored prints; the latest ${S.log.length} shown, the latest first. Undo: the latest change by hand, while what it made is unchanged.`));
    for (const e of S.log) {
      const ids = Object.keys(e.after).map(id => `${id} (${e.before[id] ?? "–"} → ${e.after[id] ?? "–"})`).join(", ");
      const row = el("div", {style: "margin:6px 0"}, `${e.datetime} · ${e.manual ? "by hand" : "make prints"} · ${e.kind} · ${ids} `);
      if (e.index === S.undoable) row.append(el("button", {onclick: () => post("/undo", {index: e.index})}, "Undo"));
      m.append(row);
    }
  }
}

function bar() {
  const n = joinTicks.size;
  $("count").textContent = n ? `${n} prints ticked for joining.` : "No prints ticked for joining.";
  $("join").disabled = n < 2; $("clear").disabled = n === 0;
}
// each card of these prints replaced by a hole of its size, so the page doesn't move
function holes(ids, text) {
  for (const card of document.querySelectorAll(".print")) {
    if (!ids.has(card.pid)) continue;
    const r = card.getBoundingClientRect();
    card.replaceWith(el("div", {class: "print hole", style: `width:${r.width}px;height:${r.height}px`}, text));
  }
}
$("join").onclick = async () => {
  const ids = new Set(joinTicks);
  if (!await post("/join", {ids: [...ids]}, false)) return;
  holes(ids, "joined");
  joinTicks.clear(); bar();
};
$("clear").onclick = () => { joinTicks.clear(); bar(); render(); };
$("go").onclick = () => { query = $("q").value; render(); };
$("q").onkeydown = e => { if (e.key === "Enter") { query = $("q").value; render(); } };
$("looked").onchange = () => { page = 0; render(); };
document.querySelectorAll(".tab").forEach(b => b.onclick = () => { tab = b.dataset.tab; page = 0; render(); });
bar(); load();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send(self, body, kind="application/json", status=200, cache=False):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        if path == "/":
            return self.send(PAGE.encode(), "text/html; charset=utf-8")
        if tool is None:
            return self.send(b"loading", "text/plain", 503)
        if path == "/state":
            with lock:
                return self.send(tool.state_json)
        part, _, name = path[1:].partition("/")
        if part == "label":
            file = os.path.join(GEN, "straighten", straighten.file_name(name))
            return self.send(open(file, "rb").read(), "image/avif", cache=True) if os.path.exists(file) else self.send_error(404)
        if part == "print":
            file = frozen.image_path(name)
            if not (tool.store.prints.get(name, {}).get("frozen") and os.path.exists(file)):
                file = os.path.join(GEN, "restore", straighten.file_name(name))
            return self.send(open(file, "rb").read(), "image/avif") if os.path.exists(file) else self.send_error(404)
        self.send_error(404)

    def do_POST(self):
        actions = {"/join": lambda d: tool.join(d.get("ids") or []),
                   "/split": lambda d: tool.split(d.get("id"), d.get("keys") or []),
                   "/apart": lambda d: tool.looked_same(d.get("serial"), d.get("ids") or []),
                   "/delete": lambda d: tool.delete(d.get("key")),
                   "/serial": lambda d: tool.set_serial(d.get("id"), d.get("serial")),
                   "/freeze": lambda d: tool.set_frozen(d.get("id"), bool(d.get("on"))),
                   "/undo": lambda d: tool.undo(d.get("index"))}
        if self.path not in actions or tool is None:
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with lock:
            why = actions[self.path](data)
        if why:
            return self.send(why.encode(), "text/plain", 409)
        self.send({"ok": True})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8774
    tool = None
    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"review prints at http://localhost:{PORT}/ (ctrl-C to stop); the page waits until the prints are loaded", flush=True)
    tool = Tool()
    print(f"loaded: {len(tool.state_json['prints'])} stored prints", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
