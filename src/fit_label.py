import concurrent.futures, glob, json, os, sys, cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fits, photos
from cartridge import SHELLS, Fitter, corners_of, edges_of, project, shell_of
from fit_cartridge import load

# fit-label: fits the label in the recess of every photo whose plastic is accepted or placed by hand (fits.json,
# src/fits.py; make fit-cartridge, make review-fits, make fit-by-hand), as that fit's label, not yet reviewed. Labels are
# stuck on a little shifted and turned, and cut a few tenths of a mm narrower or wider, so with the plastic's pose fixed,
# the label's is fitted on its own: a shift and a turn in the recess, and its width. Its pose is a homography from mm on
# the label's model (the shell's label: cartridge.LABEL, CGB_LABEL) to the photo's pixels; what this step found on the
# way (the shift in mm, the turn in degrees, the width in mm, the plastic it was fitted on) goes into
# generated/fit-label/<photo>.json. A label accepted or placed by hand isn't fitted; one judged almost is, and a
# different fit takes its place (the almost one goes to the rejected fits); a fit equal to a rejected one isn't made current.
# The label is kept inside the recess as it's fitted (CONTAIN). A photo is fitted again when its file is missing, older than this step's code,
# made on another plastic fit, or from another photo under the same name (the file has the SHA-1 of the photo it was
# made from). Files of photos without a good plastic fit are removed.
# Usage: fit_label.py
OUT = "generated/fit-label"
# Label widths, mm: on the DMG's shell 41.7 to 42.5 mm in 20 hand-placed labels (median about 42.15), on the CGB's 41.40
# to 41.70 in 11 (median 41.45; placed as 42.84 to 43.15 with the recess taken 44.5 wide, scaled to its 43 mm as in
# cartridge.py); with 0.1 mm to spare for the plastic fit's error in scale. Heights vary much less (36.8 to 37.2).
WIDTHS = {"dmg": (41.6, 42.7), "cgb": (41.3, 41.8)}
MAX_SHIFT = 1.5
MEDIAN_WIDTHS = {"dmg": 42.15, "cgb": 41.45}
# The label kept inside the recess while it's fitted (its shift held within the room the recess leaves it), rather than
# fitted freely and rejected when it sticks out: no label placed by hand sticks out (641, 2026-11-04). Against the 285
# labels placed by hand on real photos, within 0.5 / 1 mm: DMG 159 / 200 -> 161 / 204, CGB 55 / 64 -> 57 / 70; of the
# 10 the free fit rejected, about 9 then lie within 1 mm (4 within 0.5); the 166 it rejected all get a label.
CONTAIN = True
MAX_ANGLE = 2.0


def label_pose(dx, dy, angle, width, label):
    """The label's placement in the recess as a mm -> mm transform from its model: its width set (about its center),
    turned by angle (radians) about its center, and shifted by (dx, dy)."""
    cx, cy = (label[0] + label[2]) / 2, (label[1] + label[3]) / 2
    k = width / (label[2] - label[0])
    c, s = np.cos(angle), np.sin(angle)
    A = np.array([[c * k, -s], [s * k, c]])
    t = np.array([cx, cy]) - A @ [cx, cy] + [dx, dy]
    return np.array([[A[0, 0], A[0, 1], t[0]], [A[1, 0], A[1, 1], t[1]], [0, 0, 1]])


def label_samples(label):
    """Points along the label's sides (mm), their middle 70 %, clear of its rounded corners, with outward normals."""
    points, normals = [], []
    for a, b, n in edges_of(label):
        for t in np.linspace(0.15, 0.85, 18):
            points.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            normals.append(n)
    return np.array(points, np.float64), np.array(normals, np.float64)


def room_to_recess(points, normals, recess, margin=0.3):
    """For points (mm, in the recess's frame) with outward normals, how far out each may go and stay margin inside the
    recess's wall: a label's edge can't lie beyond it."""
    x1, y1, x2, y2 = recess
    room = np.full(len(points), np.inf)
    for n, limit in (((1, 0), lambda p: x2 - p[:, 0]), ((-1, 0), lambda p: p[:, 0] - x1), ((0, 1), lambda p: y2 - p[:, 1]), ((0, -1), lambda p: p[:, 1] - y1)):
        along = normals @ np.array(n, float)
        hit = along > 0.5
        room[hit] = np.minimum(room[hit], limit(points[hit]) / along[hit])
    return room - margin


def search(fitter, H, points, normals, band, outward, outside, step=0.04):
    """For each label sample (points and normals in the recess's mm, H to the photo), the offset along its normal (mm)
    with the strongest step within +-band and at most outward out, and its strength. A step is between the mean colors
    0.3 mm to either side, so a thin line (the recess's wall, with plastic on both sides) hardly counts, while the
    label's edge (paper on one side, plastic on the other) does. Steps whose outer side is clearly darker than the
    plastic just outside the recess (outside: Lab, per sample) count less: the wall's shadow is dark, while plastic in
    other light is just shaded."""
    margin = 0.36
    offsets = np.arange(-band - margin, band + margin + step / 2, step)
    grid = points[:, None, :] + normals[:, None, :] * offsets[None, :, None]
    xy = project(H, grid.reshape(-1, 2)).reshape(len(points), len(offsets), 2) * fitter.work
    values = fitter.sample_lab(xy.astype(np.float32))
    w = max(1, int(round(0.3 / step)))
    c = np.concatenate([np.zeros_like(values[:, :1]), np.cumsum(values, axis=1)], axis=1)
    before = (c[:, w:-w] - c[:, :-2 * w]) / w   # mean over [i - w, i)
    after = (c[:, 2 * w:] - c[:, w:-w]) / w      # mean over [i, i + w)
    strength = np.linalg.norm(after - before, axis=2)
    darker = np.asarray(outside, np.float32)[:, None, 0] - after[..., 0]
    strength *= np.exp(-np.maximum(0, darker - 15) / 15)
    at = offsets[w - 1:w - 1 + before.shape[1]] + step / 2
    inside = (xy[..., 0] > 1) & (xy[..., 1] > 1) & (xy[..., 0] < fitter.sw - 2) & (xy[..., 1] < fitter.sh - 2)
    inside = inside[:, w - 1:w - 1 + before.shape[1]] & inside[:, w:w + before.shape[1]]
    within = (np.abs(at)[None, :] <= band + 1e-9) & (at[None, :] <= outward[:, None])
    candidates = np.where(inside & within, strength, 0)
    best = candidates.argmax(axis=1)
    return at[best], candidates[np.arange(len(points)), best]


def fit_label(fitter, H, shell, widths=None, bands=(1.5, 1.0, 0.7, 0.5, 0.4, 0.4), iterations=3):
    """With the plastic's pose fixed (H, mm -> the fitter's photo), the label's: a shift, a turn about its center and its
    width, by point-to-line steps on its edges with robust (Tukey) weights, within MAX_SHIFT mm, MAX_ANGLE degrees and
    the shell's widths (WIDTHS, unless given). Returns (dx, dy, angle in degrees, width, whether it sticks out of the
    recess) and the label's model -> photo homography."""
    label, recess = shell.label, shell.recess
    points, normals = label_samples(label)
    cx, cy = (label[0] + label[2]) / 2, (label[1] + label[3]) / 2
    model_width = label[2] - label[0]
    widths = widths or WIDTHS[shell.name]
    dx = dy = angle = 0.0
    width = float(np.clip(model_width, *widths))
    x, y = points[:, 0] - cx, points[:, 1] - cy
    nx, ny = normals[:, 0], normals[:, 1]
    for band in bands:
        for _ in range(iterations):
            L = label_pose(dx, dy, angle, width, label)
            in_recess = project(L, points)
            turned = normals @ L[:2, :2].T
            turned /= np.linalg.norm(turned, axis=1, keepdims=True)
            # No further out than just inside the recess's wall: the wall and its shadow are the strongest edges near
            # the label's. The plastic's color just outside the recess (0.7 mm past the wall), along each normal.
            beyond = in_recess + turned * (room_to_recess(in_recess, turned, recess, margin=0) + 0.7)[:, None]
            outside = fitter.sample_lab((project(H, beyond) * fitter.work)[None].astype(np.float32))[0]
            found, strength = search(fitter, H, in_recess, turned, band, room_to_recess(in_recess, turned, recess), outside)
            weights = (strength > np.percentile(strength, 30)).astype(float)
            for _ in range(3):
                # Across the edge: n . (t + angle (-y, x) + stretch (x, 0)) = found, for a small update in the label's
                # current frame.
                A = np.stack([nx, ny, nx * -y + ny * x, nx * x], axis=1)
                delta = np.linalg.lstsq(A * np.sqrt(weights)[:, None], found * np.sqrt(weights), rcond=None)[0]
                residual = np.abs(A @ delta - found)
                scale = max(0.05, 1.4826 * np.median(residual[weights > 0]))
                u = residual / (4.685 * scale)
                weights = np.where((weights > 0) & (u < 1), (1 - u * u) ** 2, 0.0)
            c, s = np.cos(angle), np.sin(angle)
            dx = float(np.clip(dx + c * delta[0] - s * delta[1], -MAX_SHIFT, MAX_SHIFT))
            dy = float(np.clip(dy + s * delta[0] + c * delta[1], -MAX_SHIFT, MAX_SHIFT))
            angle = float(np.clip(angle + delta[2], -np.radians(MAX_ANGLE), np.radians(MAX_ANGLE)))
            width = float(np.clip(width * (1 + delta[3]), *widths))
            if CONTAIN:
                extent = np.abs([[np.cos(angle), np.sin(angle)], [np.sin(angle), np.cos(angle)]]) @ [width, label[3] - label[1]]
                half = np.maximum(0.0, (np.array(recess[2:]) - recess[:2] - extent) / 2)
                dx, dy = float(np.clip(dx, -half[0], half[0])), float(np.clip(dy, -half[1], half[1]))
    # The label, a rectangle, must lie within the recess, another: its turned extent, shifted, inside the recess's.
    extent = np.abs([[np.cos(angle), np.sin(angle)], [np.sin(angle), np.cos(angle)]]) @ [width, label[3] - label[1]]
    room = np.array(recess[2:]) - recess[:2] - extent
    protrudes = bool(np.any(np.abs([dx, dy]) > room / 2 + 1e-9))
    return (dx, dy, float(np.degrees(angle)), width, protrudes), H @ label_pose(dx, dy, angle, width, label)


def fit(photo_path, plastic):
    """The label's fit on one photo, its plastic's fit given ({"shell", "mm_to_photo"}), as written to its file."""
    cv2.setNumThreads(1)
    photo = load(photo_path)
    if photo is None:
        return {"error": "the photo can't be read"}
    shell = SHELLS[plastic["shell"]]
    H = np.asarray(plastic["mm_to_photo"], np.float64)
    # Fitted in a crop around the cartridge's body, with a margin of 10 % of its size.
    body = project(H, corners_of((0, 0) + shell.body))
    margin = 0.1 * (body.max(axis=0) - body.min(axis=0))
    x0, y0 = np.maximum(np.floor(body.min(axis=0) - margin).astype(int), 0)
    x1, y1 = np.minimum(np.ceil(body.max(axis=0) + margin).astype(int), [photo.shape[1], photo.shape[0]])
    shift = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], np.float64)
    fitter = Fitter(photo[y0:y1, x0:x1], shell)
    (dx, dy, angle, width, protrudes), L = fit_label(fitter, shift @ H, shell)
    width_at_limit = min(abs(width - w) for w in WIDTHS[shell.name]) < 0.01
    # One stopped at a width limit is fitted again at the median width: against 88 labels placed by hand, 83 then lay
    # within 0.5 mm instead of 77, and none over 1 mm instead of one.
    if width_at_limit:
        median = MEDIAN_WIDTHS[shell.name]
        (dx, dy, angle, width, protrudes), L = fit_label(fitter, shift @ H, shell, widths=(median, median))
    # A label sticking out of the recess can't be right: rejected.
    if protrudes:
        return {"error": "the label's fit sticks out of the recess", "shell": shell.name, "mm_to_photo": plastic["mm_to_photo"],
                "offset_mm": [dx, dy], "angle_degrees": angle, "width_mm": width}
    L = np.linalg.inv(shift) @ L
    return {"shell": shell.name, "label_mm_to_photo": (L / L[2, 2]).tolist(), "mm_to_photo": plastic["mm_to_photo"],
            "offset_mm": [dx, dy], "angle_degrees": angle, "width_mm": width,
            "width_at_limit": bool(width_at_limit)}


def fit_into(stem, photo_path, plastic, sha1):
    out = os.path.join(OUT, stem + ".json")
    try:
        result = fit(photo_path, plastic)
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}", "mm_to_photo": plastic["mm_to_photo"]}
    result["sha1"] = sha1
    json.dump(result, open(out, "w"))
    return stem, result


def take(e, found):
    """Puts a photo's label as this step found it (its file) into its entry in fits.json, unless its label is known to
    be right. Returns whether it's current."""
    plastic, current = e["fit"]["plastic"], e["fit"].get("label")
    if fits.good(current):
        return False
    if "error" in found or fits.was_rejected(e, plastic, found["label_mm_to_photo"]):
        if current is not None and "accepted" not in current:
            del e["fit"]["label"]
        return False
    if current is not None and fits.same(current, found["label_mm_to_photo"]):
        return True
    if current is not None and current.get("accepted") == "almost":
        fits.reject_label(e)
    e["fit"]["label"] = fits.part(found["label_mm_to_photo"])
    return True


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    paths = {photos.stem(n): os.path.join(photos.ROOT, s, system, n) for s, system, n, _ in photos.all_sources()}
    sha1s = photos.sha1s()
    known = fits.load()
    plastics = {stem: fits.of(known, stem, sha1s[stem])["fit"] for stem in paths}
    plastics = {stem: f["plastic"] for stem, f in plastics.items() if fits.good(f.get("plastic"))}
    for path in glob.glob(os.path.join(OUT, "*.json")):
        if photos.stem(os.path.basename(path)) not in plastics:
            os.remove(path)
    code = os.path.getmtime(__file__)
    todo, kept = [], 0
    for stem, plastic in sorted(plastics.items()):
        if fits.good(fits.of(known, stem, sha1s[stem])["fit"].get("label")):
            kept += 1
            continue
        out = os.path.join(OUT, stem + ".json")
        made = json.load(open(out)) if os.path.exists(out) else None
        if made is None or made.get("sha1") != sha1s[stem] or not fits.same(made["mm_to_photo"], plastic) or os.path.getmtime(out) < code:
            todo.append((stem, paths[stem], {"shell": shell_of(photos.serial_of(stem)).name, "mm_to_photo": plastic["mm_to_photo"]}, sha1s[stem]))
    print(f"{len(plastics)} photos with their plastic accepted or placed by hand, {kept} with their label too, kept; {len(todo)} to fit")
    with concurrent.futures.ProcessPoolExecutor() as pool:
        for done, (stem, result) in enumerate(pool.map(fit_into, *zip(*todo)) if todo else (), 1):
            print(f"{done} of {len(todo)}: {stem}: {result.get('error') or 'width %.2f mm' % result['width_mm']}", flush=True)
    # Every photo's label into fits.json, from the files (so that an interrupted run loses nothing).
    with fits.editing() as known:
        current = 0
        for stem in plastics:
            e = fits.entry(known, stem, sha1s[stem])
            out = os.path.join(OUT, stem + ".json")
            found = json.load(open(out)) if os.path.exists(out) else None
            # The plastic may have been judged again meanwhile.
            if found is not None and found.get("sha1") == sha1s[stem] and fits.good(e["fit"].get("plastic")) and fits.same(found["mm_to_photo"], e["fit"]["plastic"]):
                current += take(e, found)
    results = [json.load(open(p)) for p in glob.glob(os.path.join(OUT, "*.json"))]
    print(f"{kept} kept, {current} fitted and not known to be wrong ({sum(r.get('width_at_limit', False) for r in results)} files at the "
          f"median width, as they stopped at a width limit), {sum('error' in r for r in results)} couldn't be fitted or stuck out of the recess")
