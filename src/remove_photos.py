# remove-photos: a tool, not a step: a local page for deleting photos from photos/ (the file and its record in
# photo-sources.json, photos.delete). The steps drop what they made from a deleted photo on their next run. Three tabs:
#   - Unused: the photos none of whose label photos is used (unused), 5 x 4 at a time, the fewest matched features
#     first (its distinct points among the inliers of its matches with other photos, match's), each with why: delete
#     one, OK one (a good photo: kept in OK_FILE, never listed again), mark the page's photos all OK, or delete the
#     page's photos not OK-ed. No confirm(): they're unused, though prints.json may list them (a family of approximate
#     cuts). (Before 2026-11-12 only the photos find found no label photo in; on the full set, 48 of the 71 matched
#     nothing.)
#   - Restored prints: every print's restored image (restore), 18 at a time in 2 columns, the unmarked first, each to mark Good or
#     Bad (MARKS_FILE). A mark is of that image file (its SHA-1): a print restored differently is unmarked again. An
#     image the pipeline has changed since the page loaded is not shown, nor can it be marked (restart the tool).
#     Freeze (and Unfreeze, without asking) beside Good and Bad: a print the user accepts is frozen (the store,
#     prints.json, stored-prints.md; src/frozen.py; its image at frozen/<id>.avif): no step changes it. A deleted photo's
#     label photos leave their stored prints, by hand (a frozen one is unfrozen). A button only, no key (the user: keys
#     next to S are too easy to hit).
# The tabs keep their pages as loaded (the user, 2026-11-12: a photo deleted or OK-ed leaves its place, nothing moves).
#   - Bad photos: every print (prints.json) with its label photos (in prints.json's order), by print id (a game's prints
#     together); a search box keeps the prints whose id holds every word typed. Each label photo: "Delete"; deleting a
#     photo that also holds label photos of other prints asks first (confirm()). Each shows its px/mm at the label and
#     whether solve's fit is poor. (Until 2026-11-15 also a badness per label photo, from comparing it with the print's
#     other label photos at start, for a worst-first order; it didn't order usefully and made the start slow: removed,
#     the user.)
# Restored prints: sorted by print id by default, or the unmarked first; the same search box.
# Usage: remove_photos.py [port]
import json, os, re, sys, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, numpy as np
import photos, steps, straighten, shapes, publish, frozen, stored_prints

GEN = "generated"
THUMB_PX = 600
MARKS_FILE = "print-marks.json"  # {image sha1: {mark: good|bad, serial, print, label_photos, date}}: restored prints judged
OK_FILE = "ok-photos.json"  # {sha1: date OK-ed}: photos the user judged good in Unused, not listed there again
lock = threading.Lock()


def sha1_file(path):
    import hashlib
    return hashlib.sha1(open(path, "rb").read()).hexdigest()


def restored(pid):
    """A print's restored image (without .avif): restore's, or a frozen print's frozen one."""
    if os.path.exists(frozen.image_path(pid)):
        return frozen.image_path(pid)[:-5]
    return os.path.join(GEN, "restore", straighten.file_name(pid)[:-5])


def crop_of(pid, frozen_prints):
    """restore's crop of a print (its family's; a frozen print's as frozen: frozen_prints, frozen.load()), or None."""
    e = frozen_prints.get(pid)
    if e:
        return e["crop"]
    path = restored(pid) + ".json"
    return json.load(open(path))["crop"] if os.path.exists(path) else None


def unused(all_photos, found, solved):
    """sha1 -> why, for the photos none of whose label photos is used: find found none in it, or each is unsolved, a
    poor fit, or an approximate cut whose family has no precise fit (alone in its family, or among approximate cuts
    only: a box's art matching other photos of the box, 2026-11-12). A label photo merged into another (solve: the
    same sticker) is that one."""
    import solve as solve_step
    precise_families = {r["family"] for r in solved.values() if not solve_step.poor_fit(r) and not solve_step.approximate_cut(r)}
    def why_not(k):
        r = solved.get(k)
        if r is None:
            return "unsolved"
        if solve_step.poor_fit(r):
            return "poor fit"
        if solve_step.approximate_cut(r) and r["family"] not in precise_families:
            return "approximate cut alone" if r["family_size"] <= 1 else "approximate cuts only in its family"
        return None
    merged = {d for r in solved.values() for d in r.get("merged", [])}
    of_photo = {}
    for lp in found:
        if lp["key"] not in merged:
            of_photo.setdefault(lp["photo"], []).append(why_not(lp["key"]))
    out = {}
    for s in all_photos:
        whys = of_photo.get(s)
        if not whys:
            out[s] = "no label photo found"
        elif all(whys):
            out[s] = ", ".join(sorted(set(whys)))
    return out


class Tool:
    def __init__(self):
        import solve as solve_step
        say = lambda m: print(m, flush=True)
        say("loading photos/, find's, solve's and prints' results")
        self.photos = photos.all_photos()
        self.ok = json.load(open(OK_FILE)) if os.path.exists(OK_FILE) else {}
        self.marks = json.load(open(MARKS_FILE)) if os.path.exists(MARKS_FILE) else {}
        found = json.load(open(os.path.join(GEN, "find", "label-photos.json")))["label_photos"]
        prints = json.load(open(os.path.join(GEN, "prints", "prints.json")))["prints"]
        solved = json.load(open(os.path.join(GEN, "solve", "solve.json")))["label_photos"]
        self.solved, self.found_outlines = solved, {lp["key"]: lp["outline"] for lp in found}
        self.prints_json = {p["id"]: p for p in prints}
        self.why = unused(self.photos, found, solved)
        say(f"{len(self.why)} unused photos of {len(self.photos)}; counting their matched features")
        self.matched = matched_features(set(self.why))
        self.unused = sorted(self.why, key=lambda s: self.matched[s])
        say(f"listing {len(prints)} prints")
        self.crops = {}
        self.prints = []
        frozen_prints = frozen.load()
        for p in prints:
            crop = crop_of(p["id"], frozen_prints)
            entries = []
            for k in p["keys"]:
                r = solved.get(k, {})
                lw, lh = shapes.LABEL_MM[p["shape"]]
                ppm = solve_step.local_scale(np.array(r["cut_to_photo"]), [0, 0, lw, lh]) if "cut_to_photo" in r else 0
                entries.append({"key": k, "photo": k.split("@")[0], "px_per_mm": round(ppm, 1),
                                "poor_fit": solve_step.poor_fit(r)})
                self.crops[k] = (p["shape"], crop)
            image = restored(p["id"]) + ".avif"
            self.prints.append({"id": p["id"], "serial": p.get("serial") or p.get("release") or "?",
                                "has_image": os.path.exists(image),
                                "image_sha1": sha1_file(image) if os.path.exists(image) else None,
                                "label_photos": entries})
        natural = lambda pid: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", pid)]
        self.prints.sort(key=lambda p: natural(p["id"]))

    def state(self):
        have = set(photos.all_photos())
        photo_prints = {}
        for p in self.prints:
            for e in p["label_photos"]:
                photo_prints.setdefault(e["photo"], []).append(p["id"])
        return {"unused": [s for s in self.unused if s in have], "ok": sorted(self.ok),
                "marks": {k: v["mark"] for k, v in self.marks.items()}, "matched": self.matched,
                "frozen": sorted(frozen.load()),
                "why": self.why,
                "prints": self.prints, "photo_prints": photo_prints,
                "deleted": sorted((set(self.photos) | set(photo_prints)) - have)}  # gone, also before the page started

    def set_ok(self, sha1s, ok):
        import datetime
        with lock:
            for sha1 in sha1s:
                if ok:
                    self.ok[sha1] = datetime.date.today().isoformat()
                else:
                    self.ok.pop(sha1, None)
            steps.write_json(OK_FILE, dict(sorted(self.ok.items())))

    def set_mark(self, pid, mark):
        """Marks print pid's restored image good or bad (None: unmarks it); False if it has no image now."""
        import datetime
        p = next((p for p in self.prints if p["id"] == pid), None)
        if p is None or not p["image_sha1"] or self.current_image(pid) is None:
            return False
        with lock:
            if mark is None:
                self.marks.pop(p["image_sha1"], None)
            else:
                self.marks[p["image_sha1"]] = {"mark": mark, "serial": p["serial"], "print": pid,
                                               "label_photos": [e["key"] for e in p["label_photos"]],
                                               "date": datetime.date.today().isoformat()}
            steps.write_json(MARKS_FILE, dict(sorted(self.marks.items())))
        return True

    def current_image(self, pid):
        """Print pid's restored image file if it's still the one the page loaded (the pipeline may have restored it
        again since, or given its id to another print), else None."""
        p = next((p for p in self.prints if p["id"] == pid), None)
        file = restored(pid) + ".avif"
        if p is None or not p["image_sha1"] or not os.path.exists(file) or sha1_file(file) != p["image_sha1"]:
            return None
        return file

    def set_frozen(self, pid, on):
        """Freezes print pid (its restored image as the page shows it) or unfreezes it; False if it can't be."""
        with lock:
            if not on:
                frozen.unfreeze(pid)
                return True
            if pid not in self.prints_json or self.current_image(pid) is None:
                return False
            frozen.freeze(pid, self.prints_json[pid], self.solved, self.found_outlines,
                          os.path.join(GEN, "restore", straighten.file_name(pid)[:-5]))
        return True

    def delete(self, sha1s):
        """Deletes those of sha1s still in photos/; returns all of sha1s no longer there."""
        done = []
        with lock:
            have = photos.all_photos()
            store = stored_prints.Store()
            of = store.print_of()
            for s in sha1s:
                if s in have:
                    photos.delete(s)
                    print(f"deleted {s}", flush=True)
                    # its label photos out of their stored prints, by hand (a frozen print unfreezes: stored-prints.md)
                    by_print = {}
                    for k, pid in of.items():
                        if k.split("@")[0] == s:
                            by_print.setdefault(pid, []).append(k)
                    for pid, keys in by_print.items():
                        if pid in store.prints:
                            store.remove(pid, keys, manual=True, why="photo deleted in remove-photos")
                done.append(s)
            store.save()
        return done


def matched_features(wanted):
    """sha1 -> how many distinct points of the photo are inliers of its matches with other photos, for those wanted."""
    points = {s: [] for s in wanted}
    folder = os.path.join(GEN, "match")
    files = [f for f in os.listdir(folder) if f.endswith(".npz")]
    for n, f in enumerate(files, 1):
        if n % 1000 == 0 or n == len(files):
            print(f"matched features: {n} of {len(files)} match files read", flush=True)
        a = f[:-4]
        z = np.load(os.path.join(folder, f))
        others = z["others"]
        if not len(others) or (a not in wanted and not wanted.intersection(others)):
            continue
        inliers, starts = z["inliers"], z["starts"]
        for i, b in enumerate(others):
            pair = inliers[starts[i]:starts[i + 1]]
            if a in wanted:
                points[a].append(pair[:, :2])
            if b in wanted:
                points[b].append(pair[:, 2:])
    return {s: len(np.unique(np.round(np.concatenate(v)), axis=0)) if v else 0 for s, v in points.items()}


def thumbnail(path, side):
    img = photos.load(path)
    if img is None:
        return None
    f = side / max(img.shape[:2])
    if f < 1:
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Remove photos</title><style>
* { box-sizing: border-box }
[hidden] { display: none !important }
html, body { margin: 0; height: 100%; font: 14px system-ui, sans-serif; background: #f4f4f4; color: #222 }
header { display: flex; gap: 8px; align-items: center; padding: 8px 12px; height: 48px; background: #fff; border-bottom: 1px solid #ddd }
button { border: none; border-radius: 0.3em; padding: 6px 12px; font: inherit; background: #e4e4e4; cursor: pointer }
button:hover { background: #d4d4d4 }
button.tab.on { background: #333; color: #fff }
button.danger { background: #c62828; color: #fff }
button.danger:hover { background: #a31f1f }
.info { font-variant-numeric: tabular-nums; color: #555; margin-left: 8px }
.spacer { flex: 1 }
#grid { display: grid; grid-template-columns: repeat(5, 1fr); grid-template-rows: repeat(4, 1fr); gap: 6px; padding: 6px; height: calc(100% - 48px) }
#grid .cell { position: relative; min-height: 0; background: #ddd; display: flex; align-items: center; justify-content: center; overflow: hidden }
#grid img { max-width: 100%; max-height: 100%; object-fit: contain }
#grid .cell .buttons { position: absolute; right: 4px; bottom: 4px; display: flex; gap: 4px }
#grid .cell.ok { outline: 4px solid #2e7d32; outline-offset: -4px }
button.ok { background: #2e7d32; color: #fff }
.hole { background: #eee !important; color: #999; border: 2px dashed #ccc }
figure.hole { min-height: 120px; display: flex; align-items: center; justify-content: center }
#grid .cell .name { position: absolute; left: 4px; top: 4px; background: #fffc; padding: 0 4px; font: 11px ui-monospace, monospace }
#prints { padding: 6px 12px; height: calc(100% - 48px); overflow-y: auto }
.print { background: #fff; margin: 8px 0; padding: 8px; display: flex; gap: 10px; align-items: flex-start }
.print > .restored { width: 180px; flex: none }
.print .restored img { width: 100% }
.print .restored div { font: 12px ui-monospace, monospace; font-variant-numeric: tabular-nums }
.photos { display: flex; flex-wrap: wrap; gap: 8px }
figure { margin: 0; width: 180px }
figure img { width: 100%; display: block; background: #eee }
figcaption { font: 11px ui-monospace, monospace; font-variant-numeric: tabular-nums; color: #444; margin: 3px 0 }
figure .buttons { display: flex; gap: 4px }
figure .buttons button { padding: 4px 6px; font-size: 12px }
.poor { color: #c62828 }
#marks { display: grid; grid-template-columns: repeat(2, 1fr); align-content: start; gap: 6px; padding: 6px; height: calc(100% - 48px); overflow-y: auto }
#marks .cell { position: relative; background: #ddd; display: flex; align-items: center; justify-content: center; padding: 24px 0 40px }
#marks img { max-width: 100%; max-height: 80vh; object-fit: contain; display: block }
#marks .name { position: absolute; left: 4px; top: 4px; background: #fffc; padding: 0 4px; font: 11px ui-monospace, monospace }
#marks .buttons { position: absolute; left: 4px; right: 4px; bottom: 4px; display: flex; gap: 4px; justify-content: center }
#marks .cell.good, .print.good { outline: 4px solid #2e7d32; outline-offset: -4px }
#marks .cell.bad, .print.bad { outline: 4px solid #c62828; outline-offset: -4px }
button.bad { background: #c62828; color: #fff }
button.frozen { background: #1565c0; color: #fff }
</style></head><body>
<header>
  <button class="tab on" data-tab="nolabels">Unused</button>
  <button class="tab" data-tab="bad">Bad photos</button>
  <button class="tab" data-tab="marks">Restored prints</button>
  <input id="search" type="search" placeholder="Search print id" hidden>
  <select id="sort" hidden></select>
  <span class="info" id="count"></span>
  <span class="spacer"></span>
  <span id="controls"></span>
</header>
<div id="grid"></div>
<div id="prints" hidden></div>
<div id="marks" hidden></div>
<script>
let S = null, query = "", sortBy = {bad: "id", marks: "id"}, tab = "nolabels", page = 0, unusedList = [], printList = [], markList = [];
const MARKS_PER = 18;
const deleted = new Set(), ok = new Set();
const PER = 20, PRINTS_PER = 25;
const $ = s => document.querySelector(s);

async function load() {
  const r = await fetch("/state");
  if (r.status === 503) { $("#count").textContent = "loading (comparing label photos with their prints, see the console)"; setTimeout(load, 2000); return; }
  S = await r.json();
  S.deleted.forEach(s => deleted.add(s));
  S.ok.forEach(s => ok.add(s));
  // the lists as loaded: a photo deleted or OK-ed from here on leaves its place
  unusedList = S.unused.filter(s => !deleted.has(s) && !ok.has(s));
  printList = S.prints.map(p => ({...p, label_photos: p.label_photos.filter(e => !deleted.has(e.photo))}))
                      .filter(p => p.label_photos.length);
  const withImage = S.prints.filter(p => p.image_sha1);
  markList = [...withImage.filter(p => !S.marks[p.image_sha1]), ...withImage.filter(p => S.marks[p.image_sha1])];
  render();
}

async function setMark(p, mark) {
  const r = await fetch("/mark", {method: "POST", body: JSON.stringify({print: p.id, mark})});
  if (!r.ok) { alert(await r.text()); return; }
  if (mark) S.marks[p.image_sha1] = mark; else delete S.marks[p.image_sha1];
  render();
}

async function setFrozen(p, on) {
  const r = await fetch("/freeze", {method: "POST", body: JSON.stringify({print: p.id, on})});
  if (!r.ok) { alert(await r.text()); return; }
  S.frozen = on ? [...S.frozen, p.id] : S.frozen.filter(x => x !== p.id);
  render();
}

function markButtons(p) {
  const m = S.marks[p.image_sha1];
  return [button(m === "good" ? "Good ✓" : "Good", m === "good" ? "ok" : "", () => setMark(p, m === "good" ? null : "good")),
          button(m === "bad" ? "Bad ✓" : "Bad", m === "bad" ? "bad" : "", () => setMark(p, m === "bad" ? null : "bad")),
          button(S.frozen.includes(p.id) ? "Frozen ✓" : "Freeze", S.frozen.includes(p.id) ? "frozen" : "", () => setFrozen(p, !S.frozen.includes(p.id)))];
}

function renderMarks() {
  const list = view(markList);
  const pages = Math.max(1, Math.ceil(list.length / MARKS_PER));
  page = Math.min(page, pages - 1);
  const marked = list.filter(p => S.marks[p.image_sha1]).length;
  $("#count").textContent = `${list.length} restored prints, ${marked} marked, ${sortLabel()} (as when the page was loaded); page ${page + 1} of ${pages}`;
  $("#controls").innerHTML = "";
  $("#controls").append(button("Previous", "", () => { page = Math.max(0, page - 1); render(); $("#marks").scrollTop = 0; }),
                        button("Next", "", () => { page = Math.min(pages - 1, page + 1); render(); $("#marks").scrollTop = 0; }));
  const box = $("#marks");
  box.innerHTML = "";
  for (const p of list.slice(page * MARKS_PER, page * MARKS_PER + MARKS_PER)) {
    const cell = document.createElement("div");
    cell.className = "cell " + (S.marks[p.image_sha1] || "");
    cell.innerHTML = `<a href="/print/${encodeURIComponent(p.id)}" target="_blank"><img src="/print/${encodeURIComponent(p.id)}"></a><span class="name">${p.id} (${p.label_photos.length} photos)</span><span class="buttons"></span>`;
    cell.querySelector(".buttons").append(...markButtons(p));
    box.append(cell);
  }
}

async function setOk(sha1s, value) {
  const r = await fetch("/ok", {method: "POST", body: JSON.stringify({photos: sha1s, ok: value})});
  if (!r.ok) { alert(await r.text()); return; }
  sha1s.forEach(s => value ? ok.add(s) : ok.delete(s));
  render();
}

async function remove(sha1s, here, ask = true) {
  sha1s = [...new Set(sha1s)].filter(s => !deleted.has(s));
  if (!sha1s.length) return;
  const others = new Set();
  if (ask) for (const s of sha1s) for (const p of S.photo_prints[s] || []) if (p !== here) others.add(p);
  if (others.size) {
    const names = [...others];
    if (!confirm(`${sha1s.length === 1 ? "This photo also holds" : "These photos also hold"} label photos of ${others.size} other print${others.size > 1 ? "s" : ""}:\n${names.join("\n")}\n\nDelete anyway?`)) return;
  }
  const r = await fetch("/delete", {method: "POST", body: JSON.stringify({photos: sha1s})});
  if (!r.ok) { alert(await r.text()); return; }
  (await r.json()).deleted.forEach(s => deleted.add(s));
  render();
}

const SORTS = {bad: [["id", "by print id"]],
               marks: [["id", "by print id"], ["unmarked", "the unmarked first"]]};
// the tab's prints as loaded, searched and sorted: by id, or in the order the list was loaded in (unmarked first)
function view(list) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const out = list.filter(p => words.every(w => p.id.toLowerCase().includes(w)));
  if (sortBy[tab] === "id") out.sort((a, b) => a.id.localeCompare(b.id, undefined, {numeric: true}));
  return out;
}

function sortLabel() { return SORTS[tab].find(([k]) => k === sortBy[tab])[1] + (query.trim() ? `, matching "${query.trim()}"` : ""); }

function render() {
  const sort = $("#sort");
  $("#search").hidden = tab === "nolabels";
  sort.hidden = !(SORTS[tab] && SORTS[tab].length > 1);
  if (SORTS[tab]) {
    sort.innerHTML = SORTS[tab].map(([k, t]) => `<option value="${k}">${t}</option>`).join("");
    sort.value = sortBy[tab];
  }
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  $("#grid").hidden = tab !== "nolabels";
  $("#prints").hidden = tab !== "bad";
  $("#marks").hidden = tab !== "marks";
  tab === "nolabels" ? renderNoLabels() : tab === "bad" ? renderPrints() : renderMarks();
}

function renderNoLabels() {
  const left = unusedList.filter(s => !deleted.has(s) && !ok.has(s)).length;
  const pages = Math.max(1, Math.ceil(unusedList.length / PER));
  page = Math.min(page, pages - 1);
  const shown = unusedList.slice(page * PER, page * PER + PER);
  const doomed = shown.filter(s => !deleted.has(s) && !ok.has(s));
  $("#count").textContent = `${left} unused photos left to judge (no label photo used; OK-ed ones aren't listed), the fewest matched features first; page ${page + 1} of ${pages}`;
  $("#controls").innerHTML = "";
  const all = button(`Delete the ${doomed.length} not OK`, "danger", () => remove(doomed, null, false));
  all.disabled = !doomed.length;
  const allOk = button(`Mark all ${doomed.length} OK`, "ok", () => setOk(doomed, true));
  allOk.disabled = !doomed.length;
  $("#controls").append(button("Previous", "", () => { page = Math.max(0, page - 1); render(); }),
                        button("Next", "", () => { page = Math.min(pages - 1, page + 1); render(); }), " ", allOk, all);
  const grid = $("#grid");
  grid.innerHTML = "";
  for (const s of shown) {
    const cell = document.createElement("div");
    if (deleted.has(s)) {
      cell.className = "cell hole";
      cell.textContent = "deleted";
      grid.append(cell);
      continue;
    }
    cell.className = "cell" + (ok.has(s) ? " ok" : "");
    cell.innerHTML = `<a href="/photo/${s}" target="_blank"><img src="/thumb/${s}"></a><span class="name">${s.slice(0, 10)} matched ${S.matched[s]}<br>${S.why[s]}</span><span class="buttons"></span>`;
    cell.querySelector(".buttons").append(
      ok.has(s) ? button("OK ✓", "ok", () => setOk([s], false)) : button("OK", "", () => setOk([s], true)),
      button("Delete", "danger", () => remove([s], null, false)));
    grid.append(cell);
  }
}


function renderPrints() {
  const prints = view(printList);  // as loaded: a deleted label photo leaves a hole
  const pages = Math.max(1, Math.ceil(prints.length / PRINTS_PER));
  page = Math.min(page, pages - 1);
  $("#count").textContent = `${prints.length} prints, ${sortLabel()} (as when the page was loaded); page ${page + 1} of ${pages}`;
  $("#controls").innerHTML = "";
  $("#controls").append(button("Previous", "", () => { page = Math.max(0, page - 1); render(); $("#prints").scrollTop = 0; }),
                        button("Next", "", () => { page = Math.min(pages - 1, page + 1); render(); $("#prints").scrollTop = 0; }));
  const box = $("#prints");
  box.innerHTML = "";
  for (const p of prints.slice(page * PRINTS_PER, page * PRINTS_PER + PRINTS_PER)) {
    const div = document.createElement("div");
    div.className = "print " + (p.image_sha1 && S.marks[p.image_sha1] || "");
    div.innerHTML = `<div class="restored">${p.has_image ? `<img loading="lazy" src="/print/${encodeURIComponent(p.id)}">` : ""}<div>${p.id}<br>${p.label_photos.filter(e => !deleted.has(e.photo)).length} label photo(s) left</div></div><div class="photos"></div>`;
    const list = div.querySelector(".photos");
    if (p.image_sha1) { const b = document.createElement("div"); b.className = "buttons"; b.append(...markButtons(p)); div.querySelector(".restored").append(b); }
    p.label_photos.forEach(e => {
      const fig = document.createElement("figure");
      if (deleted.has(e.photo)) {
        fig.className = "hole";
        fig.textContent = "deleted";
        list.append(fig);
        return;
      }
      fig.innerHTML = `<a href="/photo/${e.photo}" target="_blank"><img loading="lazy" src="/label/${encodeURIComponent(e.key)}"></a>
        <figcaption>${e.px_per_mm.toFixed(1).padStart(4)} px/mm${e.poor_fit ? '<br><span class="poor">poor fit</span>' : ""}</figcaption><div class="buttons"></div>`;
      fig.querySelector(".buttons").append(button("Delete", "danger", () => remove([e.photo], p.id)));
      list.append(fig);
    });
    box.append(div);
  }
}

function button(text, cls, f) {
  const b = document.createElement("button");
  b.textContent = text;
  if (cls) b.className = cls;
  b.onclick = f;
  return b;
}

document.querySelectorAll(".tab").forEach(b => b.onclick = () => { tab = b.dataset.tab; page = 0; render(); });
$("#search").oninput = e => { query = e.target.value; page = 0; render(); };
$("#sort").onchange = e => { sortBy[tab] = e.target.value; page = 0; render(); };
load();
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
            return self.send(tool.state())
        part, _, name = path[1:].partition("/")
        if part in ("thumb", "photo"):
            file = photos.all_photos().get(name)
            body = file and thumbnail(file, THUMB_PX if part == "thumb" else 4000)
            return self.send(body, "image/jpeg", cache=True) if body else self.send_error(404)
        if part == "label" and name in tool.crops:
            img = cv2.imread(os.path.join(GEN, "straighten", straighten.file_name(name)))
            if img is None:
                return self.send_error(404)
            img = publish.cut(img, *tool.crops[name])
            return self.send(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes(), "image/jpeg", cache=True)
        if part == "print":
            file = tool.current_image(name)
            return self.send(open(file, "rb").read(), "image/avif") if file else self.send_error(404)
        self.send_error(404)

    def do_POST(self):
        if self.path not in ("/delete", "/ok", "/mark", "/freeze") or tool is None:
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/mark":
            mark = data.get("mark")
            if mark not in ("good", "bad", None) or not tool.set_mark(data.get("print"), mark):
                return self.send(b"This print's restored image changed since the page loaded (the pipeline restored it"
                                 b" again): reload the tool to mark the new image.", "text/plain", 409)
            return self.send({"marked": data.get("print")})
        if self.path == "/freeze":
            if not tool.set_frozen(data.get("print"), bool(data.get("on"))):
                return self.send(b"This print's restored image changed since the page loaded, or it has none: reload the tool.",
                                 "text/plain", 409)
            return self.send({"frozen": data.get("print")})
        if self.path == "/ok":
            sha1s = data.get("photos")
            if not isinstance(sha1s, list) or not all(isinstance(x, str) for x in sha1s):
                return self.send_error(400)
            tool.set_ok(sha1s, bool(data.get("ok")))
            return self.send({"ok": sha1s})
        done = tool.delete([s for s in data.get("photos", []) if isinstance(s, str)])
        self.send({"deleted": done})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8773
    tool = None
    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"remove photos at http://localhost:{PORT}/ (ctrl-C to stop); the page waits until the photos are loaded",
          flush=True)
    tool = Tool()
    print(f"loaded: {len(tool.unused)} unused photos, {len(tool.prints)} prints", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
