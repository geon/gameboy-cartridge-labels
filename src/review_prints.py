# review-prints: a tool, not a step: a local page for splitting and joining prints (the user, 2026-11-14), the decisions
# kept in print-corrections.json (src/print_corrections.py) and applied by the next make prints. The page shows the
# prints as that run will make them: the prints step's own grouping (<generated>/prints/automatic.json; prints.json
# before the prints step wrote it) with the decisions applied. A print as prints.json has it shows its id and restored
# image; one the decisions changed shows the ids it's made from (its image comes with make prints restore).
# Three tabs, and the decisions:
#   - Same serial: the serials (or releases, where no serial was read) of several prints, the most prints first,
#     SERIALS_PER_PAGE at a time: join some, "Join all" (its prints joined as "Join ticked" would; the user, 2026-11-15),
#     or "All different", which hides the serial while its prints are these.
#   - Every print, worst first, PRINTS_PER_PAGE at a time: the most label photos whose serial read isn't the print's
#     first, then the most differing tiles between two of its label photos (the prints step's pair cache).
#   - Search: a serial, a stem or an id (its start), up to SEARCH_MAX prints.
#   - Decisions: every decision, the latest first, each to undo.
# Each print: its label photos (straighten's image as is: full resolution and uncropped, for pinch-zooming; the user,
# 2026-11-14), each with its serial read and a tick box: "Split off ticked" makes the ticked a print of their own. A
# print's own tick box marks it for joining: "Join ticked" in the bar at the bottom joins the ticked prints, from any
# tab. Frozen prints (src/frozen.py) can't be split, and two can't be joined. "Delete label photo" under each label
# photo (the user, 2026-11-14: a bootleg with the wrong serial; 2026-11-15: the label photo, not the photo): a photo
# holding no other label photo (find's) is deleted from photos/ (photos.delete: the file and its record in
# photo-sources.json); else the label photo's area is marked in find's NOT_LABELS as fit-by-hand's "Not a label" does
# (solve's cut and find's outline, in the photo's pixels; "why": "deleted in review-prints"), and the next make find
# makes no label photo there. Not a frozen print's. A deleted label photo leaves a hole of its size at once, as does a
# print left with none, so nothing moves (the user, 2026-11-20); both are gone on reload. Each print on its own row.
# Each print's serial typed in by hand ("Set serial", the user 2026-11-14): every label photo of the print gets it in
# serial-corrections.json (read_serials.CORRECTIONS, which make read-serials applies last; the page shows it at once);
# not a frozen print's. Joining leaves a hole of the same size where each joined print sat, so the page doesn't move
# (the user, 2026-11-14); the joined print shows on the next page turn, tab or search.
# Freeze and Unfreeze on each print (the user, 2026-11-15; as in remove-photos: frozen.freeze, frozen.unfreeze): a print
# as prints.json has it, with its image from make restore, can be frozen; unfreezing asks first (its frozen image is
# deleted). A frozen print shows its frozen image; what's frozen is read from frozen-prints.json, so it shows at once. The next make read-serials and make prints give the print its id with that serial. Buttons only, no keys (the user: keys next to S are too easy to hit).
# Usage: review_prints.py [port]
import json, os, re, sys, threading, urllib.parse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, numpy as np
import photos, steps, shapes, straighten, frozen, find as find_step, print_corrections, prints as prints_step, serials as serials_db
from read_serials import CORRECTIONS

GEN = photos.generated(False)
SERIALS_PER_PAGE = 10
PRINTS_PER_PAGE = 20
SEARCH_MAX = 50
lock = threading.Lock()


def pair_tiles(gen):
    """{(key, key): differing tiles} from the prints step's pair cache (pairs within a family)."""
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
        P = os.path.join(GEN, "prints")
        self.result = json.load(open(os.path.join(P, "prints.json")))
        auto_file = os.path.join(P, "automatic.json")
        self.auto = json.load(open(auto_file))["prints"] if os.path.exists(auto_file) else [p for p in self.result["prints"] if p["keys"]]
        self.serials = json.load(open(os.path.join(GEN, "read-serials", "serials.json")))
        self.solved = json.load(open(os.path.join(GEN, "solve", "solve.json")))["label_photos"]
        found = json.load(open(os.path.join(GEN, "find", "label-photos.json")))["label_photos"]
        self.outlines = {lp["key"]: lp["outline"] for lp in found}
        self.by_keys = {frozenset(p["keys"]): p for p in self.result["prints"] if p["keys"]}
        self.id_of_key = {k: p["id"] for p in self.result["prints"] for k in p["keys"]}
        self.tiles = pair_tiles(GEN)
        self.present = set(photos.all_photos())
        self.photo_keys = {}
        for k in self.outlines:
            self.photo_keys.setdefault(k.split("@")[0], set()).add(k)
        self.release_of = serials_db.load_database()
        self.compute()

    def mapper(self, decisions):
        keys = {k for p in self.auto for k in p["keys"]}
        old = {k for d in decisions for k in d.get("keys", []) + [k for g in d.get("prints", []) for k in g]} - keys
        return print_corrections.key_mapper(keys, self.outlines, prints_step.photo_sizes({k.split("@")[0] for k in old}, GEN))

    def corrections(self):
        return json.load(open(CORRECTIONS)) if os.path.exists(CORRECTIONS) else {"corrections": {}}

    def not_labels(self):
        return json.load(open(find_step.NOT_LABELS)) if os.path.exists(find_step.NOT_LABELS) else {}

    def compute(self):
        entries = frozen.load()
        marked = self.not_labels()
        self.frozen_of = {k: pid for pid, e in entries.items() for k in e["label_photos"]}
        hand = self.corrections()["corrections"]
        for k, serial in hand.items():  # as make read-serials will have them
            r_ = serials_db.release(serial, self.release_of)
            self.serials[k] = {**self.serials.get(k, {}), "serial": serial, "release": r_["id"] if r_ else None,
                               "decided_by": "corrected by hand"}
        self.decisions = print_corrections.load()["decisions"]
        mapped = self.mapper(self.decisions)
        groups, self.applied = print_corrections.apply([p["keys"] for p in self.auto], self.decisions, mapped, self.frozen_of)
        out, self.whole = [], {}
        for whole in groups:
            p = self.by_keys.get(frozenset(whole))
            g = sorted(k for k in whole if k.split("@")[0] in self.present and k not in marked)  # deleted ones gone
            if not g:
                continue
            self.whole[frozenset(g)] = sorted(whole)  # decisions are recorded with the deleted ones too
            read = lambda k, f: (self.serials.get(k) or {}).get(f)
            ser = Counter(read(k, "serial") for k in g if read(k, "serial"))
            rel = Counter(read(k, "release") for k in g if read(k, "release"))
            serial = ser.most_common(1)[0][0] if ser else None
            frozen_ids = {self.frozen_of[k] for k in g if k in self.frozen_of}
            restored = p and os.path.exists(os.path.join(GEN, "restore", straighten.file_name(p["id"])))
            image = p and (os.path.exists(frozen.image_path(p["id"])) if p["id"] in entries else restored)
            disagree = sum(1 for k in g if read(k, "serial") and read(k, "serial") != serial)
            tiles = max((self.tiles.get((a, b), 0) for i, a in enumerate(g) for b in g[i + 1:]), default=0)
            out.append({"keys": [{"key": k, "serial": read(k, "serial"), "release": read(k, "release"),
                                  "by_hand": k in hand} for k in g],
                        "id": p["id"] if p else None,
                        "from": sorted({self.id_of_key[k] for k in whole if k in self.id_of_key}) if not p else [],
                        "serial": serial, "release": rel.most_common(1)[0][0] if rel else None,
                        "shape": self.solved[g[0]]["shape"] if g[0] in self.solved else None,
                        "families": len({self.solved[k]["family"] for k in g if k in self.solved}),
                        "frozen": sorted(frozen_ids), "image": bool(image), "restored": bool(restored), "disagree": disagree, "tiles": tiles})
        # the same serial (or release): several prints; hidden where an "apart" decision has these prints
        by_serial = {}
        for i, p in enumerate(out):
            s = p["serial"] or p["release"]
            if s:
                by_serial.setdefault(s, []).append(i)
        apart = {}
        for d in self.decisions:
            if d["kind"] == "apart":
                apart.setdefault(d["serial"], []).append({frozenset(mapped(k) for k in g) - {None} for g in d["prints"]})
        same = []
        for s, idx in by_serial.items():
            if len(idx) < 2:
                continue
            now = {frozenset(self.whole[frozenset(k["key"] for k in out[i]["keys"])]) for i in idx}
            same.append({"serial": s, "prints": idx, "looked_at": now in apart.get(s, [])})
        same.sort(key=lambda e: (-len(e["prints"]), -sum(len(out[i]["keys"]) for i in e["prints"]), e["serial"]))
        worst = sorted(range(len(out)), key=lambda i: (-out[i]["disagree"], -out[i]["tiles"], -len(out[i]["keys"])))
        self.state_json = {"prints": out, "same": same, "worst": worst,
                           "decisions": [{**d, "index": n, "applied": a} for n, (d, a) in enumerate(zip(self.decisions, self.applied))],
                           "per_page": {"serials": SERIALS_PER_PAGE, "prints": PRINTS_PER_PAGE, "search": SEARCH_MAX}}
        self.groups = {frozenset(k["key"] for k in p["keys"]): p for p in out}

    def group_of(self, keys):
        return self.groups.get(frozenset(keys))

    def decide(self, decision):
        """A decision added (checked against the prints as shown): None, or why not."""
        kind = decision.get("kind")
        if kind == "join":
            gs = [self.group_of(g) for g in decision.get("prints", [])]
            if len(gs) < 2 or any(g is None for g in gs):
                return "Tick two or more prints (the page may be out of date: reload)."
            if sum(1 for g in gs if g["frozen"]) > 1:
                return "Two frozen prints can't be joined: unfreeze one first."
            d = {"kind": "join", "prints": [self.whole[frozenset(g)] for g in decision["prints"]]}
        elif kind == "split":
            keys, rest = decision.get("keys", []), decision.get("rest", [])
            g = self.group_of(keys + rest)
            if g is None or not keys or not rest:
                return "Tick some of a print's label photos, not all (the page may be out of date: reload)."
            if g["frozen"]:
                return "A frozen print can't be split: unfreeze it first."
            d = {"kind": "split", "keys": keys, "rest": sorted(set(self.whole[frozenset(keys + rest)]) - set(keys))}
        elif kind == "apart":
            if not decision.get("serial") or any(self.group_of(g) is None for g in decision.get("prints", [])):
                return "The page may be out of date: reload."
            d = {"kind": "apart", "serial": decision["serial"], "prints": [self.whole[frozenset(g)] for g in decision["prints"]]}
        else:
            return "Unknown decision."
        data = print_corrections.load()
        data["decisions"].append({**d, "datetime": print_corrections.now()})
        print_corrections.save(data)
        self.compute()
        return None

    def set_frozen(self, keys, on):
        """Freezes the print shown with keys (its id and image from make restore) or unfreezes it: None, or why not."""
        g = self.group_of(keys or [])
        if g is None:
            return "The page may be out of date: reload."
        if not on:
            for pid in g["frozen"]:
                frozen.unfreeze(pid)
                print(f"unfrozen {pid}", flush=True)
        else:
            if g["frozen"]:
                return "Already frozen."
            if not g["id"] or not g["restored"]:
                return "Only a print with its image from make restore can be frozen (after make prints restore)."
            p = self.by_keys.get(frozenset(keys))
            if p is None:
                return "A label photo of this print was deleted: freeze it after the next make all."
            frozen.freeze(p["id"], p, self.solved, self.outlines, os.path.join(GEN, "restore", straighten.file_name(p["id"])[:-5]))
            print(f"frozen {p['id']}", flush=True)
        self.compute()
        return None

    def set_serial(self, keys, serial):
        """Every label photo of a print (keys, as shown) gets serial in serial-corrections.json: None, or why not."""
        serial = (serial or "").strip().upper()
        g = self.group_of(keys or [])
        if g is None:
            return "The page may be out of date: reload."
        if g["frozen"]:
            return "A frozen print's serial can't be set: unfreeze it first."
        if not re.fullmatch(r"[A-Z0-9]+(-[A-Z0-9]+)+", serial):
            return f"Not a serial: {serial!r} (like DMG-APSJ-JPN)."
        data = self.corrections()
        data["corrections"] = dict(sorted({**data["corrections"], **{k: serial for k in keys}}.items()))
        tmp = CORRECTIONS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CORRECTIONS)
        print(f"serial {serial}: {len(keys)} label photos", flush=True)
        self.compute()
        return None

    def delete(self, key):
        """Deletes a label photo: its photo if it holds no other, else its area marked not a label. None, or why not."""
        sha1 = (key or "").split("@")[0]
        if key in self.frozen_of:
            return "A frozen print's label photo can't be deleted: unfreeze it first."
        if sha1 not in self.present:
            return None
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
                           "datetime": print_corrections.now()}
            steps.write_json(find_step.NOT_LABELS, marked)
            print(f"label photo {key} marked not a label", flush=True)
        else:
            if sha1 not in photos.all_photos():
                return "Not in photos/ any more: reload."
            photos.delete(sha1)
            print(f"deleted {sha1}", flush=True)
            self.present.discard(sha1)
        self.compute()
        return None

    def undo(self, index, when):
        data = print_corrections.load()
        if not (0 <= index < len(data["decisions"])) or data["decisions"][index]["datetime"] != when:
            return "The decisions changed: reload."
        del data["decisions"][index]
        print_corrections.save(data)
        self.compute()
        return None


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
<button class="tab" data-tab="worst">Every print, worst first</button>
<button class="tab" data-tab="search">Search</button>
<button class="tab" data-tab="decisions">Decisions</button>
<span id="searchbox" style="display:none"><input id="q" placeholder="serial, stem or id" size="24"> <button id="go">Search</button></span>
<label id="lookedbox" style="display:none"><input type="checkbox" id="looked"> show serials looked at</label>
</header>
<main id="main">loading…</main>
<div id="bar"><span id="count">No prints ticked for joining.</span><button id="join" disabled>Join ticked</button><button id="clear" disabled>Clear</button><span id="msg"></span></div>
<script>
let S = null, tab = "same", page = 0, query = "";
const joinTicks = new Map();  // print handle (its first key) -> its keys
const lpTicks = new Set();    // label photo keys ticked for splitting
const $ = id => document.getElementById(id);
const handle = p => p.keys[0].key;

async function load(show = true) {
  const r = await fetch("/state");
  if (r.status === 503) { setTimeout(() => load(show), 1000); return; }
  S = await r.json();
  const now = new Set(S.prints.map(handle));
  for (const h of [...joinTicks.keys()]) if (!now.has(h)) joinTicks.delete(h);
  if (show) { lpTicks.clear(); render(); }
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

function printCard(p) {
  const keys = p.keys.map(k => k.key);
  const card = el("div", {class: "print" + (joinTicks.has(handle(p)) ? " ticked" : "")});
  card.handle = handle(p);
  const tick = el("input", {type: "checkbox"});
  tick.checked = joinTicks.has(handle(p));
  tick.onchange = () => { if (tick.checked) joinTicks.set(handle(p), keys); else joinTicks.delete(handle(p)); card.classList.toggle("ticked", tick.checked); bar(); };
  const name = p.id ? p.id : "new print, from " + (p.from.join(" + ") || "?");
  const count = el("span", {}, `${p.keys.length}`);
  const head = el("div", {class: "head"}, el("label", {}, tick, " join"), el("b", {}, name),
    el("span", {class: "note"}, `${p.serial || p.release || "no serial"} · `, count, ` label photos` + (p.families > 1 ? ` · ${p.families} families` : "") +
      (p.disagree ? ` · ${p.disagree} read another serial` : "") + (p.tiles ? ` · up to ${p.tiles} tiles differ` : "")));
  if (p.frozen.length) head.append(el("span", {class: "frozen"}, "frozen"));
  const fz = el("button", {onclick: () => {
    if (p.frozen.length && !confirm(`Unfreeze ${p.frozen.join(", ")}? Its frozen image is deleted; the next make restore restores it again.`)) return;
    post("/freeze", {keys, on: !p.frozen.length});
  }}, p.frozen.length ? "Unfreeze" : "Freeze");
  if (!p.frozen.length && !(p.id && p.restored)) { fz.disabled = true; fz.title = "only a print with its image from make restore"; }
  head.append(fz);
  card.append(head);
  if (p.image) card.append(el("img", {class: "restored", loading: "lazy", src: "/print/" + encodeURIComponent(p.id)}));
  else if (p.keys.length >= 3) card.append(el("div", {class: "note"}, p.id ? "no restored image" : "restored after make prints restore"));
  const lps = el("div", {class: "lps"});
  for (const k of p.keys) {
    const box = el("input", {type: "checkbox"});
    box.checked = lpTicks.has(k.key);
    const lp = el("div", {class: "lp" + (box.checked ? " ticked" : "")},
      el("label", {}, el("img", {loading: "lazy", src: "/label/" + encodeURIComponent(k.key)}),
        box, el("span", {class: (k.serial && k.serial !== p.serial) ? "odd" : ""}, " " + (k.serial || k.release || "no serial read"))));
    if (!p.frozen.length) lp.append(el("div", {}, el("button", {class: "del", onclick: async () => {
      if (!await post("/delete", {key: k.key}, false)) return;
      // a hole where it was, so the page doesn't move; the card's other buttons act on the label photos left
      lpTicks.delete(k.key);
      keys.splice(keys.indexOf(k.key), 1);
      if (!keys.length) { joinTicks.delete(card.handle); holes(new Set([card.handle]), "deleted"); bar(); return; }
      const r = lp.getBoundingClientRect();
      lp.replaceWith(el("div", {class: "lp hole", style: `width:${r.width}px;height:${r.height}px`}, "deleted"));
      count.textContent = keys.length;
      card.handle = keys[0];
      if (tick.checked) joinTicks.set(keys[0], keys);  // load() dropped it if the deleted one was its handle
      split.disabled = !canSplit(); bar();
    }}, "Delete label photo")));
    box.onchange = () => { if (box.checked) lpTicks.add(k.key); else lpTicks.delete(k.key); lp.classList.toggle("ticked", box.checked); split.disabled = !canSplit(); };
    lps.append(lp);
  }
  const canSplit = () => { const n = keys.filter(k => lpTicks.has(k)).length; return n > 0 && n < keys.length && !p.frozen.length; };
  const split = el("button", {onclick: () => {
    const ticked = keys.filter(k => lpTicks.has(k));
    post("/decide", {kind: "split", keys: ticked, rest: keys.filter(k => !lpTicks.has(k))});
  }}, "Split off ticked");
  split.disabled = !canSplit();
  if (p.frozen.length) split.title = "frozen: can't be split";
  const input = el("input", {size: "16", placeholder: "serial", value: p.serial || ""});
  const set = el("button", {onclick: () => post("/serial", {keys, serial: input.value})}, "Set serial");
  if (p.frozen.length) { set.disabled = true; set.title = "frozen: can't be changed"; }
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

function render() {
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  $("searchbox").style.display = tab === "search" ? "" : "none";
  $("lookedbox").style.display = tab === "same" ? "" : "none";
  const m = $("main"); m.innerHTML = "";
  if (!S) { m.textContent = "loading…"; return; }
  if (tab === "same") {
    const list = S.same.filter(e => $("looked").checked || !e.looked_at);
    const per = S.per_page.serials;
    m.append(el("p", {class: "note"}, `${list.length} serials (or releases) of several prints` + ($("looked").checked ? "" : `; ${S.same.length - list.length} looked at, hidden`) + ". The most prints first."), pager(list.length, per));
    for (const e of list.slice(page * per, (page + 1) * per)) {
      const ps = e.prints.map(i => S.prints[i]);
      const apart = el("button", {onclick: () => post("/decide", {kind: "apart", serial: e.serial, prints: ps.map(p => p.keys.map(k => k.key))})}, "All different");
      apart.title = "these prints are different prints: hide this serial while its prints are these";
      const box = el("div", {class: "serial"}, el("h2", {}, `${e.serial}: ${ps.length} prints` + (e.looked_at ? " (looked at)" : "")));
      ps.forEach(p => box.append(printCard(p)));
      const all = el("button", {}, "Join all");
      const frozenCount = ps.filter(p => p.frozen.length).length;
      if (frozenCount > 1) { all.disabled = true; all.title = "two frozen prints can't be joined: unfreeze one first"; }
      else all.title = "these prints are one print: join them all";
      all.onclick = async () => {
        const handles = new Set(ps.map(handle));
        if (!await post("/decide", {kind: "join", prints: ps.map(p => p.keys.map(k => k.key))}, false)) return;
        holes(handles, "joined");
        for (const h of handles) joinTicks.delete(h);
        all.disabled = apart.disabled = true; bar();
      };
      box.append(el("div", {}, all, " ", apart));
      m.append(box);
    }
    m.append(pager(list.length, per));
  } else if (tab === "worst") {
    const per = S.per_page.prints;
    m.append(el("p", {class: "note"}, `${S.prints.length} prints: the most label photos reading another serial first, then the most differing tiles between two of its label photos.`), pager(S.worst.length, per));
    for (const i of S.worst.slice(page * per, (page + 1) * per)) m.append(printCard(S.prints[i]));
    m.append(pager(S.worst.length, per));
  } else if (tab === "search") {
    const q = query.trim().toUpperCase();
    if (!q) { m.append(el("p", {class: "note"}, "A serial (DMG-APSJ-JPN), a stem (DMG-APS) or an id (DMG-APSJ-JPN-lisa).")); return; }
    const hits = S.prints.filter(p => [p.serial, p.release, p.id, ...p.from].some(s => s && s.toUpperCase().startsWith(q)));
    m.append(el("p", {class: "note"}, `${hits.length} prints` + (hits.length > S.per_page.search ? `, the first ${S.per_page.search} shown` : "")));
    hits.sort((a, b) => (a.serial || a.release || "").localeCompare(b.serial || b.release || "") || b.keys.length - a.keys.length);
    hits.slice(0, S.per_page.search).forEach(p => m.append(printCard(p)));
  } else {
    m.append(el("p", {class: "note"}, `${S.decisions.length} decisions in print-corrections.json, the latest first; applied by the next make prints.`));
    for (const d of [...S.decisions].reverse()) {
      const what = d.kind === "join" ? `join ${d.prints.length} prints (${d.prints.map(g => g.length).join(" + ")} label photos)` :
                   d.kind === "split" ? `split off ${d.keys.length} label photos (from ${d.keys.length + d.rest.length})` :
                   `${d.serial}: ${d.prints.length} prints all different`;
      const undo = el("button", {onclick: () => post("/undo", {index: d.index, datetime: d.datetime})}, "Undo");
      m.append(el("div", {style: "margin:6px 0"}, `${d.datetime} · ${what}` + (d.applied ? "" : " · (nothing to do now)") + " ", undo));
    }
  }
}

function bar() {
  const n = joinTicks.size;
  $("count").textContent = n ? `${n} prints ticked for joining.` : "No prints ticked for joining.";
  $("join").disabled = n < 2; $("clear").disabled = n === 0;
}
// each card of these prints replaced by a hole of its size, so the page doesn't move
function holes(handles, text) {
  for (const card of document.querySelectorAll(".print")) {
    if (!handles.has(card.handle)) continue;
    const r = card.getBoundingClientRect();
    card.replaceWith(el("div", {class: "print hole", style: `width:${r.width}px;height:${r.height}px`}, text));
  }
}
$("join").onclick = async () => {
  const handles = new Set(joinTicks.keys());
  if (!await post("/decide", {kind: "join", prints: [...joinTicks.values()]}, false)) return;
  holes(handles, "joined");
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
            if not (name in frozen.load() and os.path.exists(file)):
                file = os.path.join(GEN, "restore", straighten.file_name(name))
            return self.send(open(file, "rb").read(), "image/avif") if os.path.exists(file) else self.send_error(404)
        self.send_error(404)

    def do_POST(self):
        if self.path not in ("/decide", "/undo", "/delete", "/serial", "/freeze") or tool is None:
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with lock:
            why = (tool.decide(data) if self.path == "/decide" else tool.delete(data.get("key")) if self.path == "/delete"
                   else tool.set_serial(data.get("keys"), data.get("serial")) if self.path == "/serial"
                   else tool.set_frozen(data.get("keys"), bool(data.get("on"))) if self.path == "/freeze"
                   else tool.undo(data.get("index", -1), data.get("datetime")))
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
    print(f"loaded: {len(tool.state_json['prints'])} prints, {len(tool.decisions)} decisions", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
