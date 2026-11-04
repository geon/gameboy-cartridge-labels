import json, os, sys, threading, urllib.parse, cv2, numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fits, photos
from cartridge import (AGB_RECESS, agb_camera, agb_creases, agb_outline_points, seen_straight, ARROW_HALF_ANGLE, CGB_RIDGE_DEPTH, ARROW_HALF_WIDTH, ARROW_TOP, BODY, CGB_ARROW_HEIGHT, CGB_ARROW_TIP_RADIUS, CGB_ARROW_TOP, CGB_ARROW_TOP_RADIUS, CGB_ARROW_WIDTH, CGB_RECESS, PILL,
                       PILL_RADIUS, RECESS, RECESS_RADIUS, camera_of, cgb_outline_seen, cgb_ridge_lines, corners_of, groove_edges, project, seen_at, shell_of)
from fit_cartridge import OUT as DETAILS, load

# review-fits: a local page for judging the plastic's fits (fits.json, src/fits.py; make fit-cartridge) by eye, a page
# of photos at a time, each with its current fit drawn on it (red: the front face with its notch, and the bevels' inner
# edges, or the Game Boy Color only cartridge's bowed outline, or the Game Boy Advance's with its shoulders (its top, sides and shoulders 2 mm behind the face, seen from cartridge.agb_camera); green: the recess; orange: the arrow, the pill and the
# grooves, or the CGB's smaller arrow, or the AGB's creases); a photo without one shows its latest rejected fit. Fits flagged by fit-cartridge
# (generated/fit-cartridge/: ambiguous, broken recess line) first, then the lowest quality first; photos it couldn't fit
# are listed with why. A verdict (reject, almost, accept; clicked again, it's taken back; or for all the page's photos
# not yet judged at once) changes the fit shown in fits.json (fits.judge_plastic): accepted or almost, it's the current
# fit with that review; rejected, it goes to the rejected fits, and fit-cartridge fits the photo anew on its next run.
# Almost is off, but nearly right (a corner off by a bit): worth placing by hand (make fit-by-hand). Fits placed by hand
# are shown as accepted, and can't be judged here. The filters (the plastic's verdict, fit-cartridge's flags, the shell) are as the tool starts. A photo not worth keeping can be
# deleted from photos/ (photos.delete), its fits with it; the steps drop what they made of it on their next run.
# Usage: review_fits.py [port]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8767

# The sides step in by 0.3 mm 26.7 mm down; below, the bevel's inner edge is 1.7 mm in from the upper side's edge (see
# cartridge.FACE_RUNS).
FACE_STEP = 26.7
BEVEL_IN = 1.7


def rounded_outline(rect, r, per_corner=8):
    """A rectangle's outline with its corners rounded to radius r, in mm, clockwise from the top left."""
    x1, y1, x2, y2 = rect
    points = []
    for (cx, cy), a0 in (((x1 + r, y1 + r), np.pi), ((x2 - r, y1 + r), 1.5 * np.pi), ((x2 - r, y2 - r), 0.0), ((x1 + r, y2 - r), 0.5 * np.pi)):
        for t in np.linspace(a0, a0 + np.pi / 2, per_corner):
            points.append((cx + r * np.cos(t), cy + r * np.sin(t)))
    return np.array(points, np.float64)


def face_outline():
    """The front face's outline in mm: the notch at the top right and the sides' step."""
    return np.array([(0, 0), (52, 0), (52, 3), (56.85, 3), (56.85, FACE_STEP), (56.55, FACE_STEP), (56.55, 64.85), (0.3, 64.85),
                     (0.3, FACE_STEP), (0, FACE_STEP)], np.float64)


def bevel_lines():
    """The bevels' inner edges along the lower sides, in mm."""
    return [np.array([(BEVEL_IN, FACE_STEP), (BEVEL_IN, 64.85)]), np.array([(56.85 - BEVEL_IN, FACE_STEP), (56.85 - BEVEL_IN, 64.85)])]


def pill_outline(per_end=24):
    """The pill's outline in mm."""
    x1, y1, x2, y2 = PILL
    cy = (y1 + y2) / 2
    right = [(x2 - PILL_RADIUS + PILL_RADIUS * np.cos(a), cy + PILL_RADIUS * np.sin(a)) for a in np.linspace(-np.pi / 2, np.pi / 2, per_end)]
    left = [(x1 + PILL_RADIUS + PILL_RADIUS * np.cos(a), cy + PILL_RADIUS * np.sin(a)) for a in np.linspace(np.pi / 2, 3 * np.pi / 2, per_end)]
    return np.array(right + left)


def arrow_outline(top_radius=0.56, tip_radius=0.4, per_corner=8, top=ARROW_TOP, half_width=ARROW_HALF_WIDTH, half_angle=ARROW_HALF_ANGLE):
    """The arrow's visible outline in mm: the sharp triangle with its corners rounded (on the DMG the top corners so that
    the visible width is 8.3 mm). Another arrow: its top edge's height, half width and half the tip's angle."""
    tip = np.array([28.5, top + half_width / np.tan(half_angle)])
    corners = [np.array([28.5 - half_width, top]), np.array([28.5 + half_width, top]), tip]
    points = []
    for k, (c, r) in enumerate(zip(corners, (top_radius, top_radius, tip_radius))):
        u, v = corners[k - 1] - c, corners[(k + 1) % 3] - c
        u, v = u / np.linalg.norm(u), v / np.linalg.norm(v)
        half = np.arccos(np.clip(u @ v, -1, 1)) / 2
        center = c + (u + v) / np.linalg.norm(u + v) * r / np.sin(half)
        start, end = c + u * r / np.tan(half), c + v * r / np.tan(half)
        a0, a1 = np.arctan2(*(start - center)[::-1]), np.arctan2(*(end - center)[::-1])
        a1 = a0 + (a1 - a0 + np.pi) % (2 * np.pi) - np.pi  # the short way round
        for t in np.linspace(a0, a1, per_corner):
            points.append(center + r * np.array([np.cos(t), np.sin(t)]))
    return np.array(points)


VERDICTS_GIVEN = ("rejected", "almost", "accepted")
BUTTONS = {"rejected": "Reject", "almost": "Almost", "accepted": "Accept"}
# fits.state -> the verdict shown.
SHOWN = {True: "accepted", "hand-placed": "accepted", "almost": "almost", "rejected": "rejected", None: None}
GIVEN = {"accepted": True, "almost": "almost", "rejected": "rejected", None: None}
PER_PAGE = 24
# fits.state -> its name in the filters.
STATE_NAMES = {None: "not judged", "rejected": "rejected", "almost": "almost", True: "accepted", "hand-placed": "placed by hand"}
SHELL_NAMES = {"dmg": "Game Boy", "cgb": "Game Boy Color only", "agb": "Game Boy Advance"}


def facet(names, key, values):
    """A filter's values, each with the photos having it (key(name) is the value)."""
    return {v: {n for n in names if key(n) == v} for v in values}


def matching(order, facets, filters):
    """The photos, in order, having every filter's value chosen (filters: {facet: value}; one not chosen keeps all)."""
    chosen = [facets[f].get(v, set()) for f, v in filters.items() if f in facets and v != "any"]
    return [n for n in order if all(n in names for names in chosen)]


def facet_counts(facets):
    """The filters, as the page shows them: each value with how many photos have it."""
    return {f: [[v, len(names)] for v, names in values.items()] for f, values in facets.items()}


def filters_of(path):
    """The filters chosen in a request's query."""
    return {k: v[-1] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(path).query).items()}


# The page's filters: a select per facet ("any": all photos), chosen together, kept in the address (with the page's
# own place). Needs $ and an element #filters.
FILTERS_JS = """
function showFilters(facets, chosen) {
  $("filters").innerHTML = Object.entries(facets).map(([f, values]) => `<label>${f} <select data-facet="${f}"><option value="any">any</option>` +
    values.map(([v, n]) => `<option value="${v}">${v} (${n})</option>`).join("") + "</select></label>").join("");
  for (const s of $("filters").querySelectorAll("select")) { s.value = chosen[s.dataset.facet] || "any"; if (!s.value) s.value = "any"; }
}
const chosenFilters = () => Object.fromEntries([...$("filters").querySelectorAll("select")].filter(s => s.value !== "any").map(s => [s.dataset.facet, s.value]));
const filterQuery = () => new URLSearchParams(chosenFilters()).toString();
const fromHash = () => Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
const setHash = more => history.replaceState(null, "", "#" + new URLSearchParams({...chosenFilters(), ...more}).toString());
"""


def dense(pts, closed=True):
    """Points along a polyline, so that it bends with the perspective when projected."""
    ends = np.roll(pts, -1, axis=0) if closed else pts[1:]
    return np.vstack([np.linspace(a, b, 24, endpoint=False) for a, b in zip(pts, ends)] + ([] if closed else [pts[-1:]]))


def render(path, fit, width=800):
    """The photo with the fit drawn on it (or, for a photo not fitted, the crop tried), width px wide, as JPEG bytes."""
    photo = load(path)
    t = max(1, photo.shape[1] // 600)
    if "error" in fit:
        if "crop" in fit:
            x0, y0, x1, y1 = fit["crop"]
            cv2.rectangle(photo, (x0, y0), (x1, y1), (0, 0, 255), t)
    else:
        H = np.array(fit["mm_to_photo"])
        P = lambda pts: project(H, pts).round().astype(np.int32)
        if fit["shell"] == "cgb":
            # The CGB's arrow: its top corners barely rounded, the tip a little more.
            half = CGB_ARROW_WIDTH / 2
            # Seen from the camera camera_of estimates from the fit (the photo's center taken as the view's): the outline,
            # its top and sides 2 mm behind the face (the bevels), its bottom in it; the internal ridges below.
            camera = camera_of(H, (photo.shape[1] / 2, photo.shape[0] / 2))
            cv2.polylines(photo, [P(cgb_outline_seen(camera))], True, (0, 0, 255), t, cv2.LINE_AA)
            arrow = arrow_outline(CGB_ARROW_TOP_RADIUS, CGB_ARROW_TIP_RADIUS, top=CGB_ARROW_TOP, half_width=half, half_angle=np.arctan2(half, CGB_ARROW_HEIGHT))
            cv2.polylines(photo, [P(arrow)], True, (0, 150, 255), t, cv2.LINE_AA)
            # The internal ridges, 1.4 mm behind the face, seen through the clear front wall (refracted).
            cv2.polylines(photo, [P(seen_at(dense(line, False), CGB_RIDGE_DEPTH, camera)) for line in cgb_ridge_lines()], False, (255, 200, 0), max(1, t // 2), cv2.LINE_AA)
            recess = CGB_RECESS
        elif fit["shell"] == "agb":
            # Seen from the camera taken for the AGB (agb_camera): the outline behind the face, the upper crease out of it.
            camera = agb_camera(H, (photo.shape[1] / 2, photo.shape[0] / 2))
            cv2.polylines(photo, [P(seen_straight(*agb_outline_points(), camera))], True, (0, 0, 255), t, cv2.LINE_AA)
            cv2.polylines(photo, [P(seen_straight(points, depths, camera)) for points, depths in agb_creases()], False, (0, 150, 255), max(1, t // 2), cv2.LINE_AA)
            recess = AGB_RECESS
        else:
            cv2.polylines(photo, [P(dense(face_outline()))], True, (0, 0, 255), t, cv2.LINE_AA)
            cv2.polylines(photo, [P(dense(line, False)) for line in bevel_lines()], False, (0, 0, 180), max(1, t // 2), cv2.LINE_AA)
            for shape in (arrow_outline(), pill_outline()):
                cv2.polylines(photo, [P(shape)], True, (0, 150, 255), t, cv2.LINE_AA)
            cv2.polylines(photo, [P(np.array(edge)) for edge in groove_edges()], False, (0, 150, 255), max(1, t // 2), cv2.LINE_AA)
            recess = RECESS
        cv2.polylines(photo, [P(dense(rounded_outline(recess, RECESS_RADIUS)))], True, (0, 220, 0), t, cv2.LINE_AA)
    small = cv2.resize(photo, (width, round(width * photo.shape[0] / photo.shape[1])), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()


def notes(details):
    """What to look for in a fit, from what fit-cartridge found: its flags."""
    if details is None:
        return []
    if "error" in details:
        return [details["error"]]
    found = []
    if details["ambiguous"]:
        # How likely the rival is, as a share of the winner's likelihood (by fit-cartridge's score).
        found.append(f'AMBIGUOUS: a rival {details["rival_strength"]:.0%} as likely lands {details["rival_distance_mm"]:.1f} mm away')
    if details["broken_line"]:
        side = ("top", "right", "bottom", "left")[int(np.argmin(details["line_continuity"]))]
        found.append(f'BROKEN LINE: the {side} side is {min(details["line_continuity"]):.0%} on one line')
    if details["refit_without"]:
        found.append(f'refitted without the {details["refit_without"]} side')
    found.append(f'quality {details["quality"]:.2f}; found by "{details["found_by"]}"')
    return found


class Review:
    """The photos, each with the plastic fit it shows, as the tool starts; verdicts go to fits.json at once."""

    def __init__(self):
        self.paths = {photos.stem(n): os.path.join(photos.ROOT, s, system, n) for s, system, n, _ in photos.all_sources()}
        sha1s = photos.sha1s()
        known = fits.load()
        self.entries, self.shown, self.details = {}, {}, {}
        for name in sorted(self.paths):
            path = os.path.join(DETAILS, name + ".json")
            details = json.load(open(path)) if os.path.exists(path) else None
            e = fits.of(known, name, sha1s[name])
            if details is None and not e["fit"] and not e["rejected"]:
                continue  # never fitted (another shell)
            self.entries[name] = e
            plastic = e["fit"].get("plastic") or (e["rejected"][-1]["plastic"] if e["rejected"] else None)
            self.shown[name] = plastic and plastic["mm_to_photo"]
            # What fit-cartridge found, if it's about the fit shown; files of kept fits may be of an older version of it,
            # without the flags.
            self.details[name] = details if details is not None and details.get("sha1") == sha1s[name] and ("error" in details or "ambiguous" in details) and (
                "error" in details and plastic is None or "error" not in details and plastic is not None and fits.same(details["mm_to_photo"], plastic)) else None
        unreviewed = lambda n: self.shown[n] is not None and self.state(n) is None
        flagged = lambda n: self.details[n] is not None and "error" not in self.details[n] and (self.details[n]["ambiguous"] or self.details[n]["broken_line"])
        quality = lambda n: self.details[n]["quality"] if self.details[n] is not None else 1.0
        # Flagged fits first, then the lowest quality first, then fits already judged; photos not fitted last.
        self.order = sorted(self.entries, key=lambda n: (3, 0) if self.shown[n] is None else (2, 0) if not unreviewed(n) else (not flagged(n), quality(n)))
        self.facets = {"plastic": facet(self.order, lambda n: "not fitted" if self.shown[n] is None else STATE_NAMES[self.state(n)], [*STATE_NAMES.values(), "not fitted"]),
                       "flags": facet(self.order, lambda n: "flagged" if flagged(n) else "unflagged", ["flagged", "unflagged"]),
                       "shell": facet(self.order, lambda n: SHELL_NAMES[shell_of(photos.serial_of(n)).name], SHELL_NAMES.values())}
        self.cache, self.lock = {}, threading.Lock()

    def state(self, name):
        return fits.state(self.entries[name], self.shown[name])

    def view(self, name):
        """The fit shown, as render draws it."""
        if self.shown[name] is None:
            return self.details[name] or {"error": "not fitted"}
        return {"shell": shell_of(photos.serial_of(name)).name, "mm_to_photo": self.shown[name]}

    def image(self, name):
        """The photo as drawn, rendered once (photos are rendered side by side; the last few pages are kept)."""
        with self.lock:
            if name in self.cache:
                return self.cache[name]
        image = render(self.paths[name], self.view(name))
        with self.lock:
            self.cache[name] = image
            while len(self.cache) > 4 * PER_PAGE:
                self.cache.pop(next(iter(self.cache)))
        return image

    def judge(self, names, verdict):
        """Gives the fits shown a verdict (None: takes it back)."""
        sha1s = photos.sha1s()
        with fits.editing() as known:
            for name in names:
                e = fits.entry(known, name, sha1s[name])
                fits.judge_plastic(e, self.shown[name], GIVEN[verdict])
                self.entries[name] = e

    def delete(self, name):
        photos.delete(self.paths.pop(name))
        with fits.editing():
            pass  # the photo's entry is dropped (fits.reconcile)
        self.entries.pop(name)
        self.order.remove(name)
        for values in self.facets.values():
            for names in values.values():
                names.discard(name)
        with self.lock:
            self.cache.pop(name, None)

    def summary(self, filters):
        """How many photos the filters choose, and the verdicts on their fits shown."""
        chosen = matching(self.order, self.facets, filters)
        judged = [SHOWN[self.state(n)] for n in chosen if self.shown[n] is not None]
        return {"photos": len(chosen), **{v: judged.count(v) for v in VERDICTS_GIVEN}}

    def page(self, filters, number):
        chosen = matching(self.order, self.facets, filters)
        names = chosen[number * PER_PAGE:(number + 1) * PER_PAGE]
        items = []
        for name in names:
            e, state = self.entries[name], self.state(name)
            more = [f'{len(e["rejected"])} fit{"s" * (len(e["rejected"]) != 1)} rejected before'] if e["rejected"] else []
            if state == "hand-placed":
                more.insert(0, "placed by hand")
            items.append({"name": name, "path": self.paths[name], "fitted": self.shown[name] is not None and state != "hand-placed",
                          "notes": notes(self.details[name]) + more, "verdict": SHOWN[state]})
        return {"items": items, "pages": max(1, -(-len(chosen) // PER_PAGE)), "summary": self.summary(filters)}


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Review fits</title>
<style>
body{font:14px system-ui;margin:0;background:#f4f4f4;color:#222}
header{position:sticky;top:0;background:#fff;padding:8px 16px;border-bottom:1px solid #ddd;display:flex;gap:12px;align-items:center;flex-wrap:wrap;z-index:1}
#position{display:inline-block;width:12ch;text-align:center;font-variant-numeric:tabular-nums}
#filters{display:flex;gap:12px}
#summary{color:#555;font-variant-numeric:tabular-nums}
main{padding:12px 16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
section{background:#fff;border-radius:6px;padding:8px;display:flex;flex-direction:column;gap:6px;min-width:0}
.top{display:flex;gap:6px;align-items:center}
h2{flex:1;font-size:14px;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.photo{display:block;aspect-ratio:4/3;background:#eee}
.photo img{width:100%;height:100%;object-fit:contain;display:block}
.verdicts{display:flex;gap:6px}.verdicts button{flex:1}
section .verdicts{margin-top:auto}
button{font:inherit;padding:4px 10px;border:none;border-radius:0.3em}
button.on[data-verdict=rejected]{background:#b00;color:#fff}button.on[data-verdict=almost]{background:#c70;color:#fff}button.on[data-verdict=accepted]{background:#070;color:#fff}
.notes{margin:0;font-size:12px;color:#555}.notes b{color:#b00}
button.delete{flex:none;font-size:12px;padding:2px 8px;color:#b00}
</style>
<header>
<span id="filters"></span><span id="summary"></span>
<button id="prev">← prev</button><span id="position"></span><button id="next">next →</button>
<span>Not yet judged on this page:</span><span class="verdicts" id="rest"></span>
</header>
<main id="entries"></main>
<script>
const VERDICTS = %VERDICTS%;
let page = 0, pages = 1;
const $ = id => document.getElementById(id);
const esc = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const BUTTONS = %BUTTONS%;
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
    <div class="top"><h2 title="${esc(item.path)}">${esc(item.name)}</h2><button class="delete">Delete photo</button></div>
    <a class="photo" href="/image/${encodeURIComponent(item.name)}" target="_blank"><img src="/image/${encodeURIComponent(item.name)}" loading="lazy"></a>
    <p class="notes">${item.notes.map(n => /^[A-Z ]+:/.test(n) ? `<b>${esc(n)}</b>` : esc(n)).join("<br>")}</p>
    ${item.fitted ? `<div class="verdicts">${VERDICTS.map(v => `<button data-verdict="${v}" class="${item.verdict === v ? "on" : ""}">${BUTTONS[v]}</button>`).join("")}</div>` : ""}
  </section>`).join("");
  window.scrollTo(0, 0);
}
$("entries").onclick = async e => {
  const remove = e.target.closest("button.delete");
  if (remove) {
    const section = remove.closest("section");
    if (!confirm(`Delete ${section.dataset.name} from photos/?`)) return;
    const response = await fetch("/delete", {method: "POST", body: JSON.stringify({name: section.dataset.name, filters: chosenFilters()})});
    if (!response.ok) return alert("Not deleted: " + response.status);
    section.remove();
    showSummary((await response.json()).summary);
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
            self.send(PAGE.replace("%FILTERS_JS%", FILTERS_JS).replace("%VERDICTS%", json.dumps(VERDICTS_GIVEN)).replace("%BUTTONS%", json.dumps(BUTTONS)).encode(), "text/html; charset=utf-8")
        elif parts == ["list"]:
            self.send({"facets": facet_counts(review.facets)})
        elif len(parts) == 2 and parts[0] == "page" and parts[1].isdigit():
            self.send(review.page(filters_of(self.path), int(parts[1])))
        elif len(parts) == 2 and parts[0] == "image" and parts[1] in review.entries:
            self.send(review.image(parts[1]), "image/jpeg")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ("/verdict", "/delete"):
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/delete":
            if data["name"] not in review.entries:
                return self.send_error(400)
            review.delete(data["name"])
            return self.send({"summary": review.summary(data["filters"])})
        if any(n not in review.entries or review.shown[n] is None or review.state(n) == "hand-placed" for n in data["names"]) or data["verdict"] not in VERDICTS_GIVEN + (None,):
            return self.send_error(400)
        review.judge(data["names"], data["verdict"])
        self.send({"summary": review.summary(data["filters"])})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    review = Review()
    print(f"{len(review.entries)} photos, {len(review.facets['plastic']['not judged'])} fits not judged; review them at http://localhost:{PORT}/ (ctrl-C to stop)")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
