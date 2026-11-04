import json, os, sys, threading, urllib.parse, cv2, numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fits, photos
from cartridge import CGB_ARROW_HEIGHT, CGB_ARROW_TIP_RADIUS, CGB_ARROW_TOP, CGB_ARROW_TOP_RADIUS, CGB_ARROW_WIDTH, RECESS_RADIUS, CGB_REFRACTIVE_INDEX, CGB_RIDGE_DEPTH, CGB_WALL, SHELLS, cgb_outline_points, cgb_ridge_lines, corners_of, groove_edges, shell_of
from fit_cartridge import OUT as DETAILS, load
from find_doubles import rows
from review_fits import FILTERS_JS, SHELL_NAMES, STATE_NAMES, arrow_outline, bevel_lines, dense, face_outline, facet, facet_counts, filters_of, matching, pill_outline, rounded_outline

# fit-by-hand: a local page for placing the plastic and the label by hand, one photo at a time, where the steps' fits
# (fits.json, src/fits.py) are off: the plastic judged almost first (make review-fits), then the labels judged almost
# (make review-labels), the rejected ones and the photos fit-cartridge couldn't fit; also each release's preferred photo
# (preferred.json, make find-doubles); filtered by the plastic's state, the label's, whether preferred (or its
# release's only photo) and the shell, as the tool starts. A photo starts from its current fit
# (else its latest rejected one, else the model in the box fit-cartridge cropped to, else in the middle), with its label
# (else its latest rejected one on that plastic, else the model's). The handles (green squares) sit on the recess's
# corners and are dragged onto the photo's (the photo shown as it is, or straightened: STRAIGHT); the dots in the middle of its sides slide one side through the perspective. Once "Label placed" is
# ticked, the label (cyan) shows: a rectangle in the recess, moving with it: its corners turn it about its center, the
# dots in its sides move one side, the cross moves it. A magnifier shows 6 mm around the handle held. Saving makes the
# placement the photo's current fit, placed by hand (the steps keep it), with the label once it's placed (else the
# current label stays if the plastic wasn't moved, or fit-label fits one); an almost fit it replaces goes to the
# rejected ones. Saved again in the same run, a photo's placement replaces the one saved before. "Save for refit" saves
# the plastic's placement as a rough start instead (fits.json's "start"), leaving the fit as it is: make fit-cartridge
# fits the photo from it alone, and its fit is reviewed as usual (make review-fits). A photo with a start and no current
# fit opens on its start.
# Usage: fit_by_hand.py [port]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8769
# Straightened (a toggle, P; on as a photo with a current plastic fit opens): the photo shown with the perspective of
# its plastic fit (else its latest rejected one) taken out, as if seen straight on, the cartridge's front and
# STRAIGHT_MARGIN mm around it; the placement is still made and saved in the photo's pixels, only the view changes, and
# it stays as the photo opened while the handles move. Its scale: the photo's at the cartridge's middle, within
# STRAIGHT_PX_PER_MM.
STRAIGHT_MARGIN = 10.0
STRAIGHT_PX_PER_MM = (4.0, 40.0)


def homography(src, dst):
    H = cv2.getPerspectiveTransform(np.float32(src), np.float32(dst))
    return H / H[2, 2]


def project(H, pts):
    p = np.c_[pts, np.ones(len(pts))] @ np.asarray(H).T
    return p[:, :2] / p[:, 2:]


def anchor(shell):
    """The rectangle (mm) the handles hold: the recess's (on the CGB its internal ridges' were tried, 2026-11-01)."""
    return corners_of(shell.recess)


def model(shell):
    """A shell's model as the page draws it, in mm: the handles' rectangle's corners (anchor), the label's corners,
    and the lines [points, color, dashed, closed, depths, wall] (as review-fits draws them; depths: each point's depth
    behind the face in mm, or null: in it; the page sees them from the camera it estimates from the placement, as
    cartridge.camera_of does, through the front wall (wall mm thick, or null: none; refractive index n), as
    cartridge.seen_at does)."""
    lines = [[dense(rounded_outline(shell.recess, RECESS_RADIUS)), "#3d3", False, True]]
    if shell.name == "cgb":
        half = CGB_ARROW_WIDTH / 2
        arrow = arrow_outline(CGB_ARROW_TOP_RADIUS, CGB_ARROW_TIP_RADIUS, top=CGB_ARROW_TOP, half_width=half, half_angle=np.arctan2(half, CGB_ARROW_HEIGHT))
        outline, depths = cgb_outline_points()
        lines += [[outline, "#f33", False, True, depths], [arrow, "#f90", False, True], *[[dense(l, False), "#0cf", False, False, np.full(len(dense(l, False)), CGB_RIDGE_DEPTH), CGB_WALL] for l in cgb_ridge_lines()]]
    else:
        lines += [[dense(face_outline()), "#f33", False, True], *[[dense(l, False), "#f33", True, False] for l in bevel_lines()],
                  [arrow_outline(), "#f90", False, True], [pill_outline(), "#f90", False, True], *[[np.array(e), "#f90", False, False] for e in groove_edges()]]
    return {"anchor": anchor(shell).tolist(), "label": corners_of(shell.label).tolist(), "n": CGB_REFRACTIVE_INDEX,
            "lines": [[np.round(l[0], 3).tolist(), *l[1:4], None if len(l) < 5 else np.round(l[4], 3).tolist(), l[5] if len(l) > 5 else None]
                      for l in lines]}


class Hand:
    """The photos to place, with their fits, as the tool starts; placements go to fits.json at once."""

    def __init__(self):
        self.paths = {photos.stem(n): os.path.join(photos.ROOT, s, system, n) for s, system, n, _ in photos.all_sources()}
        self.sha1s = photos.sha1s()
        known = fits.load()
        self.entries, self.details = {}, {}
        for name in sorted(self.paths):
            path = os.path.join(DETAILS, name + ".json")
            details = json.load(open(path)) if os.path.exists(path) else None
            e = fits.of(known, name, self.sha1s[name])
            if details is None and not e["fit"] and not e["rejected"]:
                continue  # never fitted (Game Boy Advance, another shell)
            self.entries[name] = e
            self.details[name] = details if details is not None and details.get("sha1") == self.sha1s[name] else None
        self.order = sorted(self.entries)
        # Each release's preferred photo, and the photo of a release with only one (releases as find-doubles groups them).
        releases = [[(photos.stem(os.path.basename(p["path"])), p["preferred"]) for p in row["photos"]] for row in rows()]
        preferred = {n for photos_of in releases for n, chosen in photos_of if chosen}
        only = {photos_of[0][0] for photos_of in releases if len(photos_of) == 1}
        state = lambda part: STATE_NAMES["hand-placed" if part["source"] == "hand-placed" else part.get("accepted")]

        def plastic(n):
            part = self.entries[n]["fit"].get("plastic")
            return state(part) if part else "rejected" if self.entries[n]["rejected"] else "not fitted"

        def label(n):
            e = self.entries[n]
            if "label" in e["fit"]:
                return state(e["fit"]["label"])
            on = e["fit"].get("plastic")
            return "rejected" if on and any("label" in r and fits.same(r["plastic"], on) for r in e["rejected"]) else "none"

        self.facets = {"plastic": facet(self.order, plastic, [*STATE_NAMES.values(), "not fitted"]),
                       "label": facet(self.order, label, [*STATE_NAMES.values(), "none"]),
                       "preferred": {"preferred": preferred & set(self.order), "preferred or only": (preferred | only) & set(self.order),
                                     "not preferred": set(self.order) - preferred},
                       "shell": facet(self.order, lambda n: SHELL_NAMES[self.shell(n).name], SHELL_NAMES.values())}
        self.cache, self.lock = {}, threading.Lock()

    def shell(self, name):
        return shell_of(photos.serial_of(name))

    def image(self, name):
        """The photo, upright, as JPEG bytes (the last few are kept)."""
        with self.lock:
            if name in self.cache:
                return self.cache[name]
        image = cv2.imencode(".jpg", load(self.paths[name]), [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
        with self.lock:
            self.cache[name] = image
            while len(self.cache) > 8:
                self.cache.pop(next(iter(self.cache)))
        return image

    def straight(self, name):
        """The straightened view of the photo, from its current plastic fit (else its latest rejected one): (view -> photo
        homography, the view's size in px), or None if it has none."""
        e = self.entries[name]
        part = e["fit"].get("plastic") or (e["rejected"][-1]["plastic"] if e["rejected"] else None)
        if part is None:
            return None
        V, (w, h), m = np.asarray(part["mm_to_photo"], np.float64), self.shell(name).body, STRAIGHT_MARGIN
        c = project(V, [[w / 2, h / 2], [w / 2 + 1, h / 2], [w / 2, h / 2 + 1]])
        ppm = float(np.clip((np.hypot(*(c[1] - c[0])) + np.hypot(*(c[2] - c[0]))) / 2, *STRAIGHT_PX_PER_MM))
        to_mm = np.array([[1 / ppm, 0, -m], [0, 1 / ppm, -m], [0, 0, 1]])
        return V @ to_mm, (round((w + 2 * m) * ppm), round((h + 2 * m) * ppm))

    def straight_image(self, name):
        """The straightened photo (straight()), as JPEG bytes, or None."""
        view = self.straight(name)
        if view is None:
            return None
        M, size = view
        key = (name, M.tobytes())
        with self.lock:
            if key in self.cache:
                return self.cache[key]
        warped = cv2.warpPerspective(load(self.paths[name]), M, size, flags=cv2.INTER_AREA | cv2.WARP_INVERSE_MAP, borderValue=(51, 51, 51))
        image = cv2.imencode(".jpg", warped, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
        with self.lock:
            self.cache[key] = image
            while len(self.cache) > 8:
                self.cache.pop(next(iter(self.cache)))
        return image

    def item(self, name):
        """Where a photo starts: the handles' corners (anchor) in the photo's pixels (None: in the middle of the photo), the
        label's corners in mm, if placed, and notes on its fits."""
        shell, e, details = self.shell(name), self.entries[name], self.details[name]
        label = corners_of(shell.label)
        plastic = e["fit"].get("plastic")
        about = lambda part: "placed by hand" if part["source"] == "hand-placed" else {True: "accepted", "almost": "almost", None: "not reviewed"}[part.get("accepted")]
        notes = []
        if plastic is not None:
            H, start = plastic["mm_to_photo"], f"the current fit ({about(plastic)})"
        elif e.get("start"):
            H, start = e["start"]["mm_to_photo"], "the rough fit saved for refit"
        elif e["rejected"]:
            plastic = e["rejected"][-1]["plastic"]
            H, start = plastic["mm_to_photo"], "the latest rejected fit"
        elif details is not None and "crop" in details:
            # The body in the middle of the box fit-cartridge cropped to (the body and 12 % around it).
            x0, y0, x1, y1 = details["crop"]
            s = min((x1 - x0) / shell.body[0], (y1 - y0) / shell.body[1]) / 1.24
            cx, cy = (x0 + x1) / 2 - s * shell.body[0] / 2, (y0 + y1) / 2 - s * shell.body[1] / 2
            H, start = [[s, 0, cx], [0, s, cy], [0, 0, 1]], "the box fit-cartridge cropped to"
            notes.append(f'not fitted: {details["error"]}')
        else:
            H, start = None, "the middle of the photo"
            notes.append(f'not fitted: {details["error"]}' if details is not None else "not fitted")
        notes.insert(0, f"started from {start}")
        label_mm = None
        if plastic is not None:
            on = e["fit"].get("label") if e["fit"].get("plastic") is plastic else None
            rejected = [r["label"] for r in e["rejected"] if "label" in r and fits.same(r["plastic"], plastic)]
            if on is not None or rejected:
                found = on if on is not None else rejected[-1]
                label_mm = project(np.linalg.inv(H), project(found["mm_to_photo"], label)).tolist()
                notes.append(f"label from {'the current fit (' + about(found) + ')' if on is not None else 'the latest rejected label'}")
        if e.get("start"):
            notes.append("saved for refit (make fit-cartridge)")
        if e["rejected"]:
            notes.append(f'{len(e["rejected"])} fit{"s" * (len(e["rejected"]) != 1)} rejected before')
        view = self.straight(name)
        straight = None if view is None else {"view_to_photo": (view[0] / view[0][2, 2]).tolist(),
                                              "photo_to_view": (np.linalg.inv(view[0]) / np.linalg.inv(view[0])[2, 2]).tolist()}
        return {"name": name, "path": self.paths[name], "shell": shell.name, "anchor": None if H is None else project(H, anchor(shell)).tolist(),
                "label": label_mm, "notes": notes, "straight": straight, "fitted": "plastic" in e["fit"]}

    def save(self, name, corners, label_mm):
        """Makes a placement the photo's current fit, placed by hand: the handles' corners (anchor) in the photo's pixels, and the
        label's in mm (or None: the current label stays if the plastic is where it was)."""
        shell = self.shell(name)
        H = homography(anchor(shell), corners)
        with fits.editing() as known:
            e = fits.entry(known, name, self.sha1s[name])
            old = e["fit"]
            new = {"plastic": fits.part(H, "hand-placed", True)}
            moved = "plastic" not in old or not fits.same(old["plastic"], H)
            if label_mm is not None:
                new["label"] = fits.part(homography(corners_of(shell.label), project(H, label_mm)), "hand-placed", True)
            elif not moved and "label" in old:
                new["label"] = old["label"]
            # An almost fit replaced wasn't right.
            if moved and old.get("plastic", {}).get("accepted") == "almost" and not fits.was_rejected(e, old["plastic"]):
                e["rejected"].append({"plastic": fits.bare(old["plastic"])})
            if old.get("label", {}).get("accepted") == "almost" and not ("label" in new and fits.same(new["label"], old["label"])) and not fits.was_rejected(e, old["plastic"], old["label"]):
                e["rejected"].append({"plastic": fits.bare(old["plastic"]), "label": fits.bare(old["label"])})
            fits.unreject(e, H)
            e["fit"] = new
            self.entries[name] = e

    def save_start(self, name, corners):
        """Saves a rough placement of the plastic (the handles' corners in the photo's pixels) as the photo's start for
        fit-cartridge; its fit stays as it is."""
        H = homography(anchor(self.shell(name)), corners)
        with fits.editing() as known:
            e = fits.entry(known, name, self.sha1s[name])
            e["start"] = {"mm_to_photo": np.asarray(H, np.float64).tolist()}
            self.entries[name] = e

    def placed(self, name):
        plastic = self.entries[name]["fit"].get("plastic")
        return plastic is not None and plastic["source"] == "hand-placed"

    def summary(self, filters):
        """How many photos the filters choose, and how many of them have a fit placed by hand."""
        chosen = matching(self.order, self.facets, filters)
        return {"photos": len(chosen), "placed": sum(map(self.placed, chosen))}

    def chosen(self, filters):
        return {"photos": [{"name": n, "placed": self.placed(n)} for n in matching(self.order, self.facets, filters)], "summary": self.summary(filters)}


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fit by hand</title>
<style>
body{font:14px system-ui;margin:0;background:#f4f4f4;color:#222;display:flex;height:100vh}
#side{width:260px;flex:none;display:flex;flex-direction:column;gap:8px;background:#fff;padding:8px;box-sizing:border-box;border-right:1px solid #ddd}
#loupe{display:block;width:240px;height:240px;background:#000}
#filters{display:flex;flex-direction:column;gap:4px}#filters label{display:flex;justify-content:space-between;gap:6px}
#summary{color:#555;font-variant-numeric:tabular-nums}
#list{flex:1;overflow:auto;min-height:0;font-variant-numeric:tabular-nums}
#list a{display:block;color:#222;text-decoration:none;padding:2px 4px;border-radius:0.3em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#list a.cur{background:#dde}#list a::before{content:"\\2713  ";color:transparent}#list a.placed::before{color:#070}
#main{flex:1;display:flex;flex-direction:column;min-width:0}
header{background:#fff;padding:8px 16px;border-bottom:1px solid #ddd;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
#position{display:inline-block;width:12ch;text-align:center;font-variant-numeric:tabular-nums}
h2{font-size:14px;margin:0;width:22ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#notes,#help{flex-basis:100%;margin:0;font-size:12px;color:#555}
#stage{flex:1;position:relative;overflow:hidden;background:#333}
canvas#c{position:absolute;left:0;top:0}
button{font:inherit;padding:4px 10px;border:none;border-radius:0.3em}
button#save{background:#070;color:#fff}button#refit{background:#06c;color:#fff}
#status{display:inline-block;width:10ch;color:#070}
</style>
<div id="side"><div id="filters"></div><span id="summary"></span><canvas id="loupe" width="240" height="240"></canvas><div id="list"></div></div>
<div id="main"><header>
<button id="prev">← prev</button><span id="position"></span><button id="next">next →</button>
<h2 id="title"></h2><button id="reset">Reset (R)</button><label><input type="checkbox" id="labelplaced"> Label placed (L)</label><label><input type="checkbox" id="straighten"> Straightened (P)</label>
<button id="save">Save as great (S)</button><button id="refit">Save for refit (F)</button><span id="status"></span>
<p id="notes"></p>
<p id="help">Drag the green corners (squares) onto the recess's; the dots slide a side. Tick Label placed to show the label (cyan): its corners turn it, the dots move a side, the cross moves it. Tab: next handle; arrow keys: nudge 1 px (Shift: 10 px); wheel: zoom; drag elsewhere: pan; P: straightened or not (the perspective of the plastic fit taken out); S: save and go to the next photo; F: save the plastic as a rough fit for make fit-cartridge to fit from, and go to the next.</p>
</header><div id="stage"><canvas id="c"></canvas></div></div>
<script>
const $ = id => document.getElementById(id);
const c = $("c"), ctx = c.getContext("2d"), lctx = $("loupe").getContext("2d");
let models, list = [], i = 0, item = null, img = new Image(), photo = img, straight = null;
let corners = null, rect = null, sel = 0, drag = -1, grab = null, startCorners = null, startRect = null, pan = null;
let scale = 1, ox = 0, oy = 0;
// The view: the image shown (the photo, or straightened), and the homographies between the photo's pixels, where the
// placement is made, and the image's.
const I3 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
let W = I3, Wi = I3;
const apply = (H, [x, y]) => { const w = H[2][0] * x + H[2][1] * y + H[2][2]; return [(H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w]; };
// The homography taking four points to four others.
function homography(src, dst) {
  const A = [], b = [];
  for (let k = 0; k < 4; k++) {
    const [x, y] = src[k], [u, v] = dst[k];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
  }
  for (let col = 0; col < 8; col++) {
    let p = col;
    for (let r = col + 1; r < 8; r++) if (Math.abs(A[r][col]) > Math.abs(A[p][col])) p = r;
    [A[col], A[p]] = [A[p], A[col]]; [b[col], b[p]] = [b[p], b[col]];
    for (let r = 0; r < 8; r++) if (r !== col) { const f = A[r][col] / A[col][col]; for (let k = col; k < 8; k++) A[r][k] -= f * A[col][k]; b[r] -= f * b[col]; }
  }
  const h = b.map((v, k) => v / A[k][k]);
  return [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1]];
}
const model = () => models[item.shell];
const anchorMm = () => model().anchor;  // the handles' rectangle in mm: the recess
const toPhoto = () => homography(anchorMm(), corners), toMm = () => homography(corners, anchorMm());
// The label: a rectangle in the recess's mm, {c: center, a: turn (radians), w, h}.
const LOCAL = [[-.5, -.5], [.5, -.5], [.5, .5], [-.5, .5]], NORMALS = [[0, -1], [1, 0], [0, 1], [-1, 0]];
const rot = (a, [x, y]) => [Math.cos(a) * x - Math.sin(a) * y, Math.sin(a) * x + Math.cos(a) * y];
const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
const copy = r => ({c: r.c.slice(), a: r.a, w: r.w, h: r.h});
// The label's outline with its corners rounded (1.4 mm, as review-labels draws it), in the recess's mm.
function roundedOutline(r, radius = 1.4, per = 6) {
  const pts = [];
  [[-1, -1, Math.PI], [1, -1, 1.5 * Math.PI], [1, 1, 0], [-1, 1, 0.5 * Math.PI]].forEach(([sx, sy, a0]) => {
    for (let k = 0; k <= per; k++) {
      const t = a0 + k / per * Math.PI / 2;
      const d = rot(r.a, [sx * (r.w / 2 - radius) + radius * Math.cos(t), sy * (r.h / 2 - radius) + radius * Math.sin(t)]);
      pts.push([r.c[0] + d[0], r.c[1] + d[1]]);
    }
  });
  return pts;
}
function rectCorners(r) { return LOCAL.map(([u, v]) => { const d = rot(r.a, [u * r.w, v * r.h]); return [r.c[0] + d[0], r.c[1] + d[1]]; }); }
function rectFrom(q) {
  const t = [q[1][0] - q[0][0] + q[2][0] - q[3][0], q[1][1] - q[0][1] + q[2][1] - q[3][1]], l = [q[3][0] - q[0][0] + q[2][0] - q[1][0], q[3][1] - q[0][1] + q[2][1] - q[1][1]];
  return {c: q.reduce((s, p) => [s[0] + p[0] / 4, s[1] + p[1] / 4], [0, 0]), a: Math.atan2(t[1], t[0]), w: Math.hypot(...t) / 2, h: Math.hypot(...l) / 2};
}
const placed = () => $("labelplaced").checked;
// Handles, in the photo's pixels: 0-3 the anchor's corners (the recess's), 4-7 the middle of its sides (top, right, bottom, left),
// and with the label placed, 8-11 the label's corners, 12-15 the middle of its sides, 16 its center.
function handles() {
  const H = toPhoto(), R = anchorMm(), L = rectCorners(rect);
  const recess = corners.concat([0, 1, 2, 3].map(k => apply(H, mid(R[k], R[(k + 1) % 4]))));
  return placed() ? recess.concat(L.map(q => apply(H, q)), [0, 1, 2, 3].map(k => apply(H, mid(L[k], L[(k + 1) % 4]))), [apply(H, rect.c)]) : recess;
}
// Ticks or unticks Label placed; unticked, the label's handles are gone.
function setPlaced(on) {
  $("labelplaced").checked = on;
  if (!on && sel >= 8) sel = 0;
  draw();
}
// Slides the anchor's side k, from where it was at the start of the drag, to pass through the photo's point q.
function slide(k, q, start) {
  const R = anchorMm(), Hs = homography(R, start), m = apply(homography(start, R), q), n = NORMALS[k], s = mid(R[k], R[(k + 1) % 4]);
  const d = (m[0] - s[0]) * n[0] + (m[1] - s[1]) * n[1];
  corners = start.map(p => p.slice());
  for (const j of [k, (k + 1) % 4]) corners[j] = apply(Hs, [R[j][0] + d * n[0], R[j][1] + d * n[1]]);
}
// Moves the label by handle h (0-8 from its first) to the photo's point q, from where it was at the start.
function moveLabel(h, q, s) {
  const m = apply(toMm(), q);
  rect = copy(s);
  if (h < 4) {
    const corner = rectCorners(s)[h];
    rect.a = s.a + Math.atan2(m[1] - s.c[1], m[0] - s.c[0]) - Math.atan2(corner[1] - s.c[1], corner[0] - s.c[0]);
  } else if (h < 8) {
    const k = h - 4, n = rot(s.a, NORMALS[k]), L = rectCorners(s), e = mid(L[k], L[(k + 1) % 4]);
    const d = (m[0] - e[0]) * n[0] + (m[1] - e[1]) * n[1];
    if (k % 2) rect.w = s.w + d; else rect.h = s.h + d;
    rect.c = [s.c[0] + n[0] * d / 2, s.c[1] + n[1] * d / 2];
  } else rect.c = m;
}
function move(h, q, startC, startR) {
  if (h < 4) corners[h] = q;
  else if (h < 8) slide(h - 4, q, startC);
  else moveLabel(h - 8, q, startR);
  $("status").textContent = "";
}
%FILTERS_JS%
async function start() {
  let facets;
  [models, facets] = await Promise.all([(await fetch("/models")).json(), (await fetch("/facets")).json()]);
  const hash = fromHash();
  showFilters(facets, location.hash.length > 1 ? hash : {plastic: "almost"});
  await showList(hash.photo);
}
const showSummary = s => $("summary").textContent = `${s.photos} photos, ${s.placed} placed`;
async function showList(name) {
  const data = await (await fetch("/list?" + filterQuery())).json();
  list = data.photos;
  showSummary(data.summary);
  i = Math.max(0, list.findIndex(p => p.name === name));
  showNames();
  if (list.length) show(); else { $("title").textContent = "none"; setHash({}); ctx.clearRect(0, 0, c.width, c.height); }
}
function showNames() {
  $("list").innerHTML = list.map((p, k) => `<a href="#" data-k="${k}" class="${k === i ? "cur" : ""} ${p.placed ? "placed" : ""}">${p.name}</a>`).join("");
  $("list").querySelector(".cur")?.scrollIntoView({block: "nearest"});
}
$("list").onclick = e => { const a = e.target.closest("a"); if (a) { e.preventDefault(); go(+a.dataset.k); } };
$("filters").onchange = () => showList();
async function show() {
  const name = list[i].name;
  setHash({photo: name});
  $("position").textContent = `${i + 1} / ${list.length}`;
  $("title").textContent = name;
  $("status").textContent = "";
  showNames();
  item = await (await fetch("/item/" + encodeURIComponent(name))).json();
  $("title").title = item.path;
  $("notes").textContent = item.notes.join(" · ");
  const loaded = src => new Promise(done => { const im = new Image(); im.onload = () => done(im); im.src = src; });
  const [p, s] = await Promise.all([loaded("/image/" + encodeURIComponent(name)), item.straight ? loaded("/straight/" + encodeURIComponent(name)) : null]);
  if (item.name !== name) return;
  photo = p; straight = s;
  $("straighten").disabled = !s;
  $("straighten").checked = !!s && item.fitted;
  setView(); reset();
}
function reset() {
  const w = photo.width, h = photo.height, R = model().anchor;
  corners = item.anchor ? item.anchor.map(q => q.slice()) : R.map(([x, y]) => [w / 2 + (x - 28.5) * w / 120, h / 2 + (y - 37.5) * w / 120]);
  rect = rectFrom(item.label || model().label);
  $("labelplaced").checked = !!item.label;
  sel = 0;
  draw();
}
// The photo fills the stage; the wheel zooms about the pointer.
function frame() {
  const m = $("stage");
  c.width = m.clientWidth; c.height = m.clientHeight;
  scale = Math.min(c.width / img.width, c.height / img.height) * 0.95;
  ox = (c.width - img.width * scale) / 2; oy = (c.height - img.height * scale) / 2;
}
const toView = q => apply(W, q), fromView = p => apply(Wi, p);
const toScreen = q => { const p = toView(q); return [ox + p[0] * scale, oy + p[1] * scale]; }, viewAt = (x, y) => [(x - ox) / scale, (y - oy) / scale];
// Shows the photo straightened (if it can be) or as it is.
function setView() {
  const on = $("straighten").checked && straight;
  img = on ? straight : photo;
  [W, Wi] = on ? [item.straight.photo_to_view, item.straight.view_to_photo] : [I3, I3];
  frame();
}
// The model's lines and, if placed, the label in the photo's pixels: [points, color, dashed, closed].
// The camera, in mm on the front face (x, y, height above it), that sees it as H shows it, the center of its view at
// the photo's center: as cartridge.camera_of.
function cameraOf(H) {
  H = H.map(r => r.map(v => v / H[2][2]));
  const cx = photo.width / 2, cy = photo.height / 2;
    const A = [H[0][0] - cx * H[2][0], H[1][0] - cy * H[2][0]], B = [H[0][1] - cx * H[2][1], H[1][1] - cy * H[2][1]];
  const rows = [[A[0] * B[0] + A[1] * B[1], -H[2][0] * H[2][1]], [A[0] ** 2 + A[1] ** 2 - B[0] ** 2 - B[1] ** 2, H[2][1] ** 2 - H[2][0] ** 2]];
  const num = rows.reduce((t, [a, b]) => t + a * b, 0), den = rows.reduce((t, [a]) => t + a * a, 0), g = den > 0 ? num / den : 0;
  if (!(g > 0)) return [28.5, 32.5, Infinity];  // no perspective: infinitely far, straight in front
  const f = 1 / Math.sqrt(g);
  const col = k => [(H[0][k] - cx * H[2][k]) / f, (H[1][k] - cy * H[2][k]) / f, H[2][k]], norm = v => Math.hypot(...v);
  let [r1, r2, t] = [col(0), col(1), col(2)];
  const k = 2 / (norm(r1) + norm(r2));
  [r1, r2, t] = [r1, r2, t].map(v => v.map(x => x * k * (t[2] < 0 ? -1 : 1)));
  const x = [r1[1] * r2[2] - r1[2] * r2[1], r1[2] * r2[0] - r1[0] * r2[2], r1[0] * r2[1] - r1[1] * r2[0]], n = norm(x), r3 = x.map(v => v / n);
  // C = -[r1 r2 r3]^-1 t, by Cramer's rule.
  const M = [[r1[0], r2[0], r3[0]], [r1[1], r2[1], r3[1]], [r1[2], r2[2], r3[2]]];
  const det = m => m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  const d = det(M), C = [0, 1, 2].map(j => -det(M.map((row, i) => row.map((v, l) => l === j ? t[i] : v))) / d);
  return [C[0], C[1], Math.abs(C[2])];
}
// A point depth mm behind the face, as seen in the face from the camera: the line of sight bent through the front wall
// (wall mm thick, refractive index n) and straight behind it; as cartridge.seen_at.
function seen(cam, [x, y], depth, wall, n) {
  if (!(depth > 0) || !isFinite(cam[2])) return [x, y];
  const h = cam[2], ax = x - cam[0], ay = y - cam[1], target = Math.hypot(ax, ay);
  const glass = Math.min(depth, wall), air = Math.max(0, depth - wall);
  let r = target * h / (h + depth);
  for (let k = 0; k < 8; k++) {
    const tan = r / h, sin = tan / Math.sqrt(1 + tan * tan), sinR = sin / n, cosR = Math.sqrt(1 - sinR * sinR), tanR = sinR / cosR;
    const cos = 1 / Math.sqrt(1 + tan * tan), slope = (glass * cos ** 3 / n / cosR ** 3 + air) / h;
    r -= (r + glass * tanR + air * tan - target) / (1 + slope);
  }
  const k = target > 1e-9 ? r / target : 1;
  return [cam[0] + ax * k, cam[1] + ay * k];
}
function shapes() {
  const H = toPhoto(), cam = model().lines.some(l => l[4]) ? cameraOf(H) : null;
  const lines = model().lines.map(([pts, col, dash, closed, depths, wall]) => [pts.map((q, k) => apply(H, depths && depths[k] ? seen(cam, q, depths[k], wall || 0, model().n) : q)), col, dash, closed]);
  return placed() ? lines.concat([[roundedOutline(rect).map(q => apply(H, q)), "#3cf", false, true]]) : lines;
}
function stroke(g, pts, closed, at) {
  g.beginPath();
  pts.forEach((q, k) => { const [x, y] = at(q); k ? g.lineTo(x, y) : g.moveTo(x, y); });
  if (closed) g.closePath();
  g.stroke();
}
function draw() {
  ctx.clearRect(0, 0, c.width, c.height);
  ctx.drawImage(img, ox, oy, img.width * scale, img.height * scale);
  ctx.lineWidth = 1;
  for (const [pts, col, dash, closed] of shapes()) { ctx.strokeStyle = col; ctx.setLineDash(dash ? [5, 4] : []); stroke(ctx, pts, closed, toScreen); }
  ctx.setLineDash([]);
  handles().forEach((q, k) => {
    const [x, y] = toScreen(q);
    ctx.fillStyle = ctx.strokeStyle = k === sel ? "#ff0" : k >= 8 ? "#3cf" : "#3d3";
    if (k === 16) { ctx.beginPath(); ctx.moveTo(x - 8, y); ctx.lineTo(x + 8, y); ctx.moveTo(x, y - 8); ctx.lineTo(x, y + 8); ctx.stroke(); }
    else if (k % 8 < 4) ctx.fillRect(x - 4, y - 4, 8, 8);
    else { ctx.beginPath(); ctx.arc(x, y, 4, 0, 7); ctx.fill(); }
  });
  loupe(handles()[sel]);
}
// The magnifier: 6 x 6 mm around the handle, at the image's scale along the anchor's top side.
function loupe(q) {
  const R = anchorMm(), [a, b] = [toView(corners[0]), toView(corners[1])], pxPerMm = Math.hypot(b[0] - a[0], b[1] - a[1]) / (R[1][0] - R[0][0]);
  const v = toView(q), r = 3 * pxPerMm, z = 120 / r, at = p => { const u = toView(p); return [120 + (u[0] - v[0]) * z, 120 + (u[1] - v[1]) * z]; };
  lctx.imageSmoothingEnabled = false;
  lctx.fillStyle = "#000"; lctx.fillRect(0, 0, 240, 240);
  lctx.drawImage(img, v[0] - r, v[1] - r, 2 * r, 2 * r, 0, 0, 240, 240);
  for (const [pts, col, dash, closed] of shapes()) { lctx.strokeStyle = col; lctx.setLineDash(dash ? [5, 4] : []); stroke(lctx, pts, closed, at); }
  lctx.setLineDash([]);
  lctx.strokeStyle = "#ff0"; lctx.strokeRect(117, 117, 6, 6);
}
c.onmousedown = e => {
  if (!corners) return;
  let best = -1, bd = 12 ** 2;
  handles().forEach((q, k) => { const [sx, sy] = toScreen(q), d = (sx - e.offsetX) ** 2 + (sy - e.offsetY) ** 2; if (d < bd) { bd = d; best = k; } });
  if (best < 0) { pan = [e.offsetX - ox, e.offsetY - oy]; return; }
  drag = sel = best;
  startCorners = corners.map(q => q.slice()); startRect = copy(rect);
  const h = toView(handles()[best]), m = viewAt(e.offsetX, e.offsetY);
  grab = [h[0] - m[0], h[1] - m[1]];  // in the image's pixels
  draw();
};
c.onmousemove = e => {
  if (pan) { ox = e.offsetX - pan[0]; oy = e.offsetY - pan[1]; return draw(); }
  if (drag < 0) return;
  const m = viewAt(e.offsetX, e.offsetY);
  move(drag, fromView([m[0] + grab[0], m[1] + grab[1]]), startCorners, startRect);
  draw();
};
window.onmouseup = () => { drag = -1; pan = null; };
c.onwheel = e => {
  e.preventDefault();
  const f = Math.exp(-e.deltaY / 500), [x, y] = [e.offsetX, e.offsetY];
  ox = x - (x - ox) * f; oy = y - (y - oy) * f; scale *= f;
  draw();
};
async function save(forRefit) {
  if (!corners) return;
  const body = {name: item.name, anchor: corners, label: placed() && !forRefit ? rectCorners(rect) : null, filters: chosenFilters(), refit: !!forRefit};
  const response = await fetch("/save", {method: "POST", body: JSON.stringify(body)});
  if (!response.ok) return alert("Not saved: " + response.status);
  showSummary(await response.json());
  if (!forRefit) list[i].placed = true;
  if (i + 1 < list.length) go(i + 1); else { showNames(); $("status").textContent = "saved"; }
}
const go = k => { if (k >= 0 && k < list.length) { i = k; show(); } };
$("prev").onclick = () => go(i - 1);
$("next").onclick = () => go(i + 1);
$("reset").onclick = () => reset();
$("save").onclick = () => save(false);
$("refit").onclick = () => save(true);
$("labelplaced").onchange = e => setPlaced(e.target.checked);
$("straighten").onchange = () => { setView(); draw(); };
document.onkeydown = e => {
  if (e.target.tagName === "SELECT" || !corners) return;
  const step = e.shiftKey ? 10 : 1, d = {ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step]}[e.key];
  if (d) {
    const h = toView(handles()[sel]);
    move(sel, fromView([h[0] + d[0], h[1] + d[1]]), corners.map(q => q.slice()), copy(rect));
    draw(); e.preventDefault();
  } else if (e.key === "Tab") {
    // Round each rectangle: a corner, the middle of the side after it, the next corner...; the label's cross last.
    const order = [0, 4, 1, 5, 2, 6, 3, 7, 8, 12, 9, 13, 10, 14, 11, 15, 16].slice(0, handles().length), n = order.length;
    sel = order[(order.indexOf(sel) + (e.shiftKey ? n - 1 : 1)) % n]; draw(); e.preventDefault();
  }
  else if (e.key === "s" || e.key === "S") save(false);
  else if (e.key === "f" || e.key === "F") save(true);
  else if (e.key === "r" || e.key === "R") reset();
  else if (e.key === "l" || e.key === "L") setPlaced(!placed());
  else if ((e.key === "p" || e.key === "P") && straight) { $("straighten").checked = !$("straighten").checked; setView(); draw(); }
};
window.onresize = () => { if (img.width) { frame(); draw(); } };
start();
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
            self.send(PAGE.replace("%FILTERS_JS%", FILTERS_JS).encode(), "text/html; charset=utf-8")
        elif parts == ["models"]:
            self.send({name: model(shell) for name, shell in SHELLS.items()})
        elif parts == ["facets"]:
            self.send(facet_counts(hand.facets))
        elif parts == ["list"]:
            self.send(hand.chosen(filters_of(self.path)))
        elif len(parts) == 2 and parts[0] == "item" and parts[1] in hand.entries:
            self.send(hand.item(parts[1]))
        elif len(parts) == 2 and parts[0] == "image" and parts[1] in hand.entries:
            self.send(hand.image(parts[1]), "image/jpeg")
        elif len(parts) == 2 and parts[0] == "straight" and parts[1] in hand.entries and (image := hand.straight_image(parts[1])) is not None:
            self.send(image, "image/jpeg")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/save":
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if data["name"] not in hand.entries or np.shape(data["anchor"]) != (4, 2) or data["label"] is not None and np.shape(data["label"]) != (4, 2):
            return self.send_error(400)
        if data.get("refit"):
            hand.save_start(data["name"], data["anchor"])
        else:
            hand.save(data["name"], data["anchor"], data["label"])
        self.send(hand.summary(data["filters"]))

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    hand = Hand()
    print(f"{len(hand.entries)} photos, {len(hand.facets['plastic']['almost'])} with their plastic judged almost; place them at http://localhost:{PORT}/ (ctrl-C to stop)")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
