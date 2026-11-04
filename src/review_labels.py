import copy, json, os, sys, threading, urllib.parse, cv2, numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fits, photos
from cartridge import AGB_RECESS, CGB_RECESS, RECESS, SHELLS, project, shell_of
from fit_cartridge import load
from fit_label import OUT as DETAILS, label_pose
from review_fits import BUTTONS, FILTERS_JS, GIVEN, SHELL_NAMES, SHOWN, STATE_NAMES, VERDICTS_GIVEN, dense, facet, facet_counts, filters_of, matching, rounded_outline

# review-labels: a local page for judging the labels' fits (fits.json, src/fits.py; make fit-label) by eye, a page of
# photos at a time. Each shows the recess straightened (the photo seen through the plastic's fit, perspective removed),
# with 5 mm around it, all at the same scale whatever the photo's resolution, and the current label drawn red; a photo
# without one shows its latest rejected label on that plastic, or the fit fit-label rejected for sticking out of the
# recess (orange, from generated/fit-label/). The labels farthest from the recess's middle come first. A verdict
# (reject, almost, accept; clicked again, it's taken back; or for all the page's photos not yet judged at once) changes
# the label shown in fits.json (fits.judge_label). Labels placed by hand are shown as accepted, and can't be judged here.
# Where the plastic's fit turns out to be off, "Plastic: almost" beside the photo's name makes it almost and rejects the
# label (fitted on it); clicked again, the photo's fits are put back as they were. The filters (the label's verdict, the shell) are as the tool starts.
# Usage: review_labels.py [port]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
PER_PAGE = 24
# The straightened view: px per mm, and the margin around the recess (mm). Framed alike on every shell, around the
# recess's middle, as wide and high as the largest recess.
SCALE = 12
MARGIN = 5.0
FRAME = (max(r[2] - r[0] for r in (RECESS, CGB_RECESS, AGB_RECESS)) + 2 * MARGIN, max(r[3] - r[1] for r in (RECESS, CGB_RECESS, AGB_RECESS)) + 2 * MARGIN)
LABEL_RADIUS = 1.4


def straightened(path, fit):
    """The recess seen straight on, with the label drawn, as JPEG bytes: FRAME mm at SCALE px per mm."""
    photo = load(path)
    shell = SHELLS[fit["shell"]]
    recess = shell.recess
    H = np.asarray(fit["mm_to_photo"], np.float64)
    left, top = (recess[0] + recess[2] - FRAME[0]) / 2, (recess[1] + recess[3] - FRAME[1]) / 2
    to_mm = np.array([[1 / SCALE, 0, left], [0, 1 / SCALE, top], [0, 0, 1]])
    # Shrunk first to about twice the view's scale, so that a large photo isn't sampled sparsely (aliased).
    mx, my = (recess[0] + recess[2]) / 2, (recess[1] + recess[3]) / 2
    c = project(H, [[mx, my], [mx + 1, my], [mx, my + 1]])
    (ax, ay), (bx, by) = c[1] - c[0], c[2] - c[0]
    px_per_mm = np.sqrt(abs(ax * by - ay * bx))
    shrink = min(1.0, 2 * SCALE / px_per_mm)
    if shrink < 1:
        photo = cv2.resize(photo, None, fx=shrink, fy=shrink, interpolation=cv2.INTER_AREA)
        H = np.diag([shrink, shrink, 1]) @ H
    size = (round(FRAME[0] * SCALE), round(FRAME[1] * SCALE))
    view = cv2.warpPerspective(photo, H @ to_mm, size, flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=(80, 80, 80))
    at = lambda pts: ((np.asarray(pts) - [left, top]) * SCALE * 4).round().astype(np.int32)  # 2 bits of subpixel
    draw = lambda pts, color: cv2.polylines(view, [at(pts)], True, color, 1, cv2.LINE_AA, shift=2)
    label = dense(rounded_outline(shell.label, LABEL_RADIUS))
    if "error" not in fit:
        draw(project(np.linalg.inv(H) @ np.diag([shrink, shrink, 1]) @ np.asarray(fit["label_mm_to_photo"]), label), (0, 0, 255))
    elif "offset_mm" in fit:
        draw(project(label_pose(*fit["offset_mm"], np.radians(fit["angle_degrees"]), fit["width_mm"], shell.label), label), (0, 150, 255))
    return cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def notes(details):
    """What fit-label found on the label shown."""
    if details is None:
        return []
    if "error" in details:
        return [("REJECTED: " if "sticks out" in details["error"] else "") + details["error"]]
    dx, dy = details["offset_mm"]
    found = [f'shifted {dx:+.2f}, {dy:+.2f} mm, turned {details["angle_degrees"]:+.2f}°, {details["width_mm"]:.2f} mm wide']
    if details["width_at_limit"]:
        found.append("stopped at a width limit: fitted again at the median width")
    return found


class Review:
    """The photos with a good plastic fit, each with the label it shows, as the tool starts; verdicts go to fits.json
    at once."""

    def __init__(self):
        self.paths = {photos.stem(n): os.path.join(photos.ROOT, s, system, n) for s, system, n, _ in photos.all_sources()}
        sha1s = photos.sha1s()
        known = fits.load()
        self.entries, self.plastic, self.shown, self.details = {}, {}, {}, {}
        for name in sorted(self.paths):
            e = fits.of(known, name, sha1s[name])
            plastic = e["fit"].get("plastic")
            if not fits.good(plastic):
                continue
            path = os.path.join(DETAILS, name + ".json")
            details = json.load(open(path)) if os.path.exists(path) else None
            if details is not None and (details.get("sha1") != sha1s[name] or not fits.same(details["mm_to_photo"], plastic)):
                details = None
            label = e["fit"].get("label") or next((r["label"] for r in reversed(e["rejected"]) if "label" in r and fits.same(r["plastic"], plastic)), None)
            if label is None and (details is None or "offset_mm" not in details):
                continue  # no label yet
            self.entries[name], self.plastic[name] = e, plastic["mm_to_photo"]
            self.shown[name] = label and label["mm_to_photo"]
            # What fit-label found, if it's about the label shown.
            self.details[name] = details if details is not None and ("error" in details and label is None or "error" not in details and label is not None and fits.same(details["label_mm_to_photo"], label)) else None
        # Farthest from the recess's middle first (the shift, plus the turn's reach at the label's corners), then those
        # without what fit-label found (placed by hand); rejected by fit-label last.
        reach = lambda d: np.hypot(*d["offset_mm"]) + 28 * abs(np.radians(d["angle_degrees"]))
        self.order = sorted(self.entries, key=lambda n: (2, 0) if self.shown[n] is None else (1, 0) if self.details[n] is None else (0, -reach(self.details[n])))
        self.facets = {"label": facet(self.order, lambda n: "rejected by fit-label" if self.shown[n] is None else STATE_NAMES[self.state(n)], [*STATE_NAMES.values(), "rejected by fit-label"]),
                       "shell": facet(self.order, lambda n: SHELL_NAMES[shell_of(photos.serial_of(n)).name], SHELL_NAMES.values())}
        self.demoted = {}  # photo -> its entry before its plastic was demoted in this run
        self.cache, self.lock = {}, threading.Lock()

    def state(self, name):
        return fits.state(self.entries[name], self.plastic[name], self.shown[name])

    def view(self, name):
        """The label shown, as straightened draws it."""
        if self.shown[name] is None:
            return dict(self.details[name], shell=shell_of(photos.serial_of(name)).name)
        return {"shell": shell_of(photos.serial_of(name)).name, "mm_to_photo": self.plastic[name], "label_mm_to_photo": self.shown[name]}

    def image(self, name):
        """The straightened recess, rendered once (the last few pages are kept)."""
        with self.lock:
            if name in self.cache:
                return self.cache[name]
        image = straightened(self.paths[name], self.view(name))
        with self.lock:
            self.cache[name] = image
            while len(self.cache) > 4 * PER_PAGE:
                self.cache.pop(next(iter(self.cache)))
        return image

    def judge(self, names, verdict):
        """Gives the labels shown a verdict (None: takes it back)."""
        sha1s = photos.sha1s()
        with fits.editing() as known:
            for name in names:
                e = fits.entry(known, name, sha1s[name])
                if fits.good(e["fit"].get("plastic")) and fits.same(e["fit"]["plastic"], self.plastic[name]):
                    fits.judge_label(e, self.shown[name], GIVEN[verdict])
                    self.entries[name] = e

    def demote(self, name, demote):
        """Makes the plastic's fit almost and rejects the label on it, or puts the photo's fits back as they were."""
        sha1s = photos.sha1s()
        with fits.editing() as known:
            e = fits.entry(known, name, sha1s[name])
            if demote:
                self.demoted[name] = copy.deepcopy(e)
                if self.shown[name] is not None and self.state(name) != "hand-placed":
                    fits.judge_label(e, self.shown[name], "rejected")
                fits.judge_plastic(e, self.plastic[name], "almost")
            else:
                known[name] = e = self.demoted.pop(name)
            self.entries[name] = e

    def summary(self, filters):
        """How many photos the filters choose, and the verdicts on their labels shown."""
        chosen = matching(self.order, self.facets, filters)
        judged = [SHOWN[self.state(n)] for n in chosen if self.shown[n] is not None]
        return {"photos": len(chosen), **{v: judged.count(v) for v in VERDICTS_GIVEN}}

    def page(self, filters, number):
        chosen = matching(self.order, self.facets, filters)
        names = chosen[number * PER_PAGE:(number + 1) * PER_PAGE]
        items = []
        for name in names:
            state = self.state(name) if self.shown[name] is not None else None
            more = ["placed by hand"] if state == "hand-placed" else []
            items.append({"name": name, "path": self.paths[name], "judgeable": self.shown[name] is not None and state != "hand-placed" and name not in self.demoted,
                          "notes": notes(self.details[name]) + more, "verdict": SHOWN[state], "demoted": name in self.demoted})
        return {"items": items, "pages": max(1, -(-len(chosen) // PER_PAGE)), "summary": self.summary(filters)}


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Review labels</title>
<style>
body{font:14px system-ui;margin:0;background:#f4f4f4;color:#222}
header{position:sticky;top:0;background:#fff;padding:8px 16px;border-bottom:1px solid #ddd;display:flex;gap:12px;align-items:center;flex-wrap:wrap;z-index:1}
#position{display:inline-block;width:12ch;text-align:center;font-variant-numeric:tabular-nums}
#filters{display:flex;gap:12px}
#summary{color:#555;font-variant-numeric:tabular-nums}
main{padding:12px 16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px}
section{background:#fff;border-radius:6px;padding:8px;display:flex;flex-direction:column;gap:6px;min-width:0}
.top{display:flex;gap:6px;align-items:center}
h2{flex:1;font-size:14px;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
button.plastic{flex:none;width:17ch;font-size:12px;padding:2px 8px}button.plastic.on{background:#c70;color:#fff}
.photo{display:block;aspect-ratio:%ASPECT%;background:#eee}
.photo img{width:100%;height:100%;display:block}
.verdicts{display:flex;gap:6px}.verdicts button{flex:1}
section .verdicts{margin-top:auto}
button{font:inherit;padding:4px 10px;border:none;border-radius:0.3em}
button.on[data-verdict=rejected]{background:#b00;color:#fff}button.on[data-verdict=almost]{background:#c70;color:#fff}button.on[data-verdict=accepted]{background:#070;color:#fff}
.notes{margin:0;font-size:12px;color:#555}.notes b{color:#b00}
</style>
<header>
<span id="filters"></span><span id="summary"></span>
<button id="prev">← prev</button><span id="position"></span><button id="next">next →</button>
<span>Not yet judged on this page:</span><span class="verdicts" id="rest"></span>
</header>
<main id="entries"></main>
<script>
const VERDICTS = %VERDICTS%;
const BUTTONS = %BUTTONS%;
let page = 0, pages = 1;
const $ = id => document.getElementById(id);
const esc = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
%FILTERS_JS%
async function load() {
  const data = await (await fetch("/list")).json(), hash = fromHash();
  showFilters(data.facets, hash);
  page = Math.max(0, (parseInt(hash.page) || 1) - 1);
  show();
}
function showSummary(c) {
  $("summary").textContent = `${c.photos} photos: ` + VERDICTS.map(v => `${c[v]} ${v}`).join(", ");
}
async function show() {
  const data = await (await fetch(`/page/${page}?${filterQuery()}`)).json();
  pages = data.pages;
  if (page >= pages) { page = pages - 1; return show(); }
  setHash({page: page + 1});
  showSummary(data.summary);
  $("position").textContent = `page ${page + 1} / ${pages}`;
  $("entries").innerHTML = data.items.map(item => `<section data-name="${esc(item.name)}" data-judged="${item.verdict ? 1 : ""}">
    <div class="top"><h2 title="${esc(item.path)}">${esc(item.name)}</h2><button class="plastic ${item.demoted ? "on" : ""}">${item.demoted ? "Plastic demoted" : "Plastic: almost"}</button></div>
    <a class="photo" href="/image/${encodeURIComponent(item.name)}" target="_blank"><img src="/image/${encodeURIComponent(item.name)}" loading="lazy"></a>
    <p class="notes">${item.notes.map(n => /^[A-Z ]+:/.test(n) ? `<b>${esc(n)}</b>` : esc(n)).join("<br>")}</p>
    ${item.judgeable ? `<div class="verdicts">${VERDICTS.map(v => `<button data-verdict="${v}" class="${item.verdict === v ? "on" : ""}">${BUTTONS[v]}</button>`).join("")}</div>` : ""}
  </section>`).join("");
  window.scrollTo(0, 0);
}
$("entries").onclick = async e => {
  const plastic = e.target.closest("button.plastic");
  if (plastic) {
    const demote = !plastic.classList.contains("on");  // clicked again: put back
    const response = await fetch("/plastic", {method: "POST", body: JSON.stringify({name: plastic.closest("section").dataset.name, demote, filters: chosenFilters()})});
    if (!response.ok) return alert("Not changed: " + (await response.text()));
    const data = await response.json(), section = plastic.closest("section");
    plastic.classList.toggle("on", demote);
    plastic.textContent = demote ? "Plastic demoted" : "Plastic: almost";
    section.dataset.judged = data.verdict ? 1 : "";
    section.querySelectorAll(".verdicts button").forEach(b => b.classList.toggle("on", b.dataset.verdict === data.verdict));
    showSummary(data.summary);
    return;
  }
  const button = e.target.closest("button[data-verdict]");
  if (!button) return;
  const verdict = button.classList.contains("on") ? null : button.dataset.verdict;  // clicked again: taken back
  judge([button.closest("section")], verdict);
};
$("rest").innerHTML = VERDICTS.map(v => `<button data-verdict="${v}">${BUTTONS[v]}</button>`).join("");
$("rest").onclick = e => {
  const button = e.target.closest("button[data-verdict]");
  if (button) judge([...document.querySelectorAll("section")].filter(s => s.querySelector(".verdicts") && !s.dataset.judged), button.dataset.verdict);
};
async function judge(sections, verdict) {
  if (!sections.length) return;
  const names = sections.map(s => s.dataset.name);
  const data = await (await fetch("/verdict", {method: "POST", body: JSON.stringify({names, verdict, filters: chosenFilters()})})).json();
  for (const s of sections) {
    s.dataset.judged = verdict ? 1 : "";
    s.querySelectorAll(".verdicts button").forEach(b => b.classList.toggle("on", b.dataset.verdict === verdict));
  }
  showSummary(data.summary);
}
const go = p => { if (p >= 0 && p < pages) { page = p; show(); } };
$("filters").onchange = () => { page = 0; show(); };
$("prev").onclick = () => go(page - 1);
$("next").onclick = () => go(page + 1);
document.onkeydown = e => {
  if (e.target.tagName === "SELECT") return;
  if (e.key === "ArrowLeft") go(page - 1);
  if (e.key === "ArrowRight") go(page + 1);
};
load();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def send(self, body, kind="application/json"):
        body = json.dumps(body).encode() if kind == "application/json" else body
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parts = [urllib.parse.unquote(p) for p in self.path.split("?")[0].split("/")[1:]]
        if parts == [""]:
            page = PAGE.replace("%FILTERS_JS%", FILTERS_JS).replace("%VERDICTS%", json.dumps(VERDICTS_GIVEN)).replace("%BUTTONS%", json.dumps(BUTTONS)).replace("%ASPECT%", f"{FRAME[0]}/{FRAME[1]}")
            self.send(page.encode(), "text/html; charset=utf-8")
        elif parts == ["list"]:
            self.send({"facets": facet_counts(review.facets)})
        elif len(parts) == 2 and parts[0] == "page" and parts[1].isdigit():
            self.send(review.page(filters_of(self.path), int(parts[1])))
        elif len(parts) == 2 and parts[0] == "image" and parts[1] in review.entries:
            self.send(review.image(parts[1]), "image/jpeg")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ("/verdict", "/plastic"):
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/plastic":
            if data["name"] not in review.entries or data["demote"] == (data["name"] in review.demoted):
                return self.send_error(400)
            review.demote(data["name"], data["demote"])
            state = review.state(data["name"]) if review.shown[data["name"]] is not None else None
            return self.send({"summary": review.summary(data["filters"]), "verdict": SHOWN[state]})
        if any(n not in review.entries or review.shown[n] is None or review.state(n) == "hand-placed" or n in review.demoted for n in data["names"]) or data["verdict"] not in VERDICTS_GIVEN + (None,):
            return self.send_error(400)
        review.judge(data["names"], data["verdict"])
        self.send({"summary": review.summary(data["filters"])})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    review = Review()
    print(f"{len(review.entries)} photos with a label, {len(review.facets['label']['not judged'])} not judged; review them at http://localhost:{PORT}/ (ctrl-C to stop)")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
