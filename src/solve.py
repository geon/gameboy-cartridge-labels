# solve: every label photo's homography from its photo into ink coordinates (mm on the label's print, one coordinate
# system per shape, anchored by each linked set's median cut), into <generated>/solve/solve.json:
#   {"label_photos": {key: {"photo_to_ink" (3 x 3), "cut_to_photo" (3 x 3: the sticker's cut outline, the canonical
#                            label size about the sticker's centre, -> the photo), "width_mm" and "height_mm" (the
#                            sticker's own size; its cut is cut_to_photo's rectangle that size about its centre), "plastic_to_photo" (3 x 3),
#                            "placement" (dx, dy mm, turn degrees: the label's cut in the recess, from its nominal place),
#                            "offset" (dx, dy mm, turn
#                            degrees: the sticker's cut -> ink), "start" (how it was started), "support" (the share of
#                            the face, recess and label samples along segments), "fallback" (null, or why the pose is weak),
#                            "error_mm" (the fit's leftover), "family" and "family_size" (label photos joined by
#                            counting links, anchored together), "merged" (label photos of the same sticker merged
#                            into it: see merge_fitted)},
#                     ...},
#    "links": the counts of link candidates, judged, pixel-agreeing and counting; poor fits; the largest families,
#    "unsolved": {key: why}}
# Three stages (label-detection.md):
#   1. Each label photo on its own: three nested rectangles of known sizes and places fitted together to the photo's
#      LSD segments (edges): the cartridge's outline, its recess and the label's cut (main's shape models,
#      src/shape-models.json). Unknowns: a homography from the plastic's mm to the photo, the label's shift and turn
#      in the recess (the placement), softly held to about PLACEMENT_MM and PLACEMENT_DEG, and its width (labels are cut
#      a few tenths of a mm narrower or wider: main's fit_label), softly held to WIDTH_SPREAD about main's median and
#      kept within main's range (WIDTHS); the height is the canonical one (main: heights vary much less). Ink
#      coordinates stay true mm: cut_to_photo is the canonical size about the sticker's centre, its width apart. Each model sample point is
#      matched to the nearest segment parallel to its edge (within ANGLE) inside a window shrinking through WINDOWS;
#      the residual is the perpendicular distance in mm, robust (soft L1, ROBUST_MM). Starts, in order: the label
#      placed by a fixed-place logo (find), kept if it passes; else main's outline quadrilaterals (src/outlines.py:
#      each four-sided outline in the photo taken for the label, the recess or the body), all of the photo's, the best
#      supported kept (on the evaluation set: 97 % under 5 mm from the hand fits, 100 % where main's fitter had
#      failed); else the pose search: poses of the model near the evidence scored against direction-binned distance
#      maps of the segments (edge_maps, search_poses), the best few fitted, its turn the direction most of the label's
#      text reads (along the label on 193 of 194 of the sample's). (Carrying a fitted pose through a match was tried:
#      37 % under 5 mm; main's text starts: 42 %; both dropped.) A fit is dropped when less than MIN_SUPPORT of the
#      model's sample points end up along segments
#      (within ON_MM), or less than MIN_FACE of the cartridge's outline (a label placed far off still finds label- and
#      recess-like lines: on the sample, 0.4 kept 69 of 70 fits within 2 mm of main's and dropped 87 of 109 farther off).
#   2. Families: link candidates (one per match homography), counted where the matched points agree within
#      LINK_FIT_MM and the pixels agree (see stage2's comment); poor fits flagged; offsets per family by a robust fit,
#      each family's median cut its anchor; then each family's label photos aligned to its median view by the pixels
#      (refine_family: a homography per label photo, correcting the outline fit's perspective errors), then again at
#      full resolution (refine_fine).
#   Between them, 1b (an experiment): each chosen fit refined by the learned edge models where they're sure
#      (stage1_edges, src/edge_fit.py).
#   Stored label photos of open prints (src/stored_prints.py; stored-prints.md rule 9): not fitted again in stage 1 nor
#      stage 1b: their stored pose is their fit (the stored poses are what stage 1's work is kept in); stages 2 and 3
#      refine them as any, and the prints step writes the result back. Never merged with another stored one.
#   Frozen label photos (src/frozen.py, persistent-prints.md stage 2): not fitted; their records as frozen ("frozen": the
#      print's id), never poor fits, never carried; they take part in stage 2's links (a new photo of a frozen print joins
#      its family), and their family's ink frame is moved onto the frame they were frozen in (anchor_to_frozen), so the
#      family's other label photos line up with them.
#      A label photo find tagged with a match to a frozen print's image and no good pose of its own gets its pose from
#      that match where the pixels agree, and joins that print's family (from_frozen_match).
#   3. An approximate cut alone in its family: its pose carried from a precise label photo it matches, where their
#      pixels then agree; it joins that family (carry_alone; "carried": {from, points, pixels_agree} in its record).
#      So is a precise fit alone in its family, from a precise label photo of a linked family, where also the carried
#      cut lies on it and the two read the same serial (find's).
# Done again when solve.json is older than this file, src/edge_fit.py, the edge models or its inputs, or holds a photo
# since deleted (find's label photos of deleted photos are left out).
# Usage: solve.py [--sample]
import argparse, html, json, os, sys
import cv2, numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, steps, match, shapes, find, outlines, edge_fit, frozen, stored_prints
from multiprocessing import Pool

ANGLE = 8.0           # degrees: a segment counts for a sample point if this parallel to its edge
WINDOWS = (6.0, 3.0, 1.5, 0.8)  # mm: how far a sample point looks for a segment, per round
ROBUST_MM = 0.3       # the soft L1 loss's scale
ON_MM = 0.5           # a sample point is along a segment within this, for the support
PLACEMENT_MM = 1.0    # the label's shift in the recess, softly held to about this
PLACEMENT_DEG = 2.0
# Label widths, mm, from main's fit_label (hand-placed labels: DMG 41.7-42.5, median about 42.15; CGB 41.40-41.70,
# median 41.45; AGB about 43, one measured), with its 0.1 mm to spare for the plastic fit's error in scale.
WIDTHS = {"dmg": (41.6, 42.7), "cgb": (41.3, 41.8), "agb": (42.5, 43.4)}
MEDIAN_WIDTHS = {"dmg": 42.15, "cgb": 41.45, "agb": 43.0}
WIDTH_SPREAD = 0.3    # mm: the width softly held to about this from the median
MIN_SUPPORT = 0.4     # the least share of the model's samples along segments for a fit to count
MIN_FACE = 0.4        # and of the cartridge's outline: a label placed far off still finds label- and recess-like lines
MODELS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "shape-models.json")))["shapes"]
MAX_SHIFT = 4.0       # mm: a link's shift between two stickers' frames that still counts
MAX_TURN = 4.0        # degrees
MIN_LINK_POINTS = 8


def corners_mm(shape):
    w, h = shapes.LABEL_MM[shape]
    return np.float64([[0, 0], [w, 0], [w, h], [0, h]])


def project(H, pts):
    return cv2.perspectiveTransform(np.float64(pts).reshape(-1, 1, 2), np.float64(H)).reshape(-1, 2)


def label_to_plastic(shape):
    """label mm (its top left at 0, 0) -> plastic mm, at its nominal place."""
    x0, y0 = MODELS[shape]["label"][:2]
    return np.array([[1.0, 0, x0], [0, 1, y0], [0, 0, 1]])


def placement_matrix(shape, dx, dy, turn_rad, width=None, height=None):
    """plastic mm -> plastic mm: the label made width mm wide and height mm high (if given) about its nominal centre,
    turned about it and shifted."""
    x0, y0, x1, y1 = MODELS[shape]["label"]
    c = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    R = np.array([[np.cos(turn_rad), -np.sin(turn_rad)], [np.sin(turn_rad), np.cos(turn_rad)]])
    if width is not None or height is not None:
        R = R @ np.diag([(width or x1 - x0) / (x1 - x0), (height or y1 - y0) / (y1 - y0)])
    t = c + [dx, dy] - R @ c
    return np.array([[R[0, 0], R[0, 1], t[0]], [R[1, 0], R[1, 1], t[1]], [0, 0, 1]])


def model_samples(shape):
    m = MODELS[shape]
    pts = np.float64([x["point"] for x in m["samples"]])
    nrm = np.float64([x["normal"] for x in m["samples"]])
    kinds = np.array([x["kind"] for x in m["samples"]])
    return pts, nrm, kinds


def homography_from(params, H0):
    """The plastic -> photo homography: the start H0 times a small change (in mm)."""
    a = params
    D = np.array([[1 + a[0], a[1], a[2]], [a[3], 1 + a[4], a[5]], [a[6] * 1e-3, a[7] * 1e-3, 1]])
    return H0 @ D


def projected(params, H0, shape, pts, nrm, kinds):
    """The model's sample points and their edge directions in the photo, the label's moved by the placement."""
    H = homography_from(params[:8], H0)
    P = placement_matrix(shape, params[8], params[9], np.radians(params[10]), MEDIAN_WIDTHS[shape] + params[11])
    is_label = kinds == "label"
    p = pts.copy()
    p[is_label] = project(P, pts[is_label])
    tangent = np.stack([-nrm[:, 1], nrm[:, 0]], 1)
    q = p + 0.5 * tangent
    pp, qq = project(H, p), project(H, q)
    d = qq - pp
    return pp, d / np.maximum(np.linalg.norm(d, axis=1)[:, None], 1e-12), H


def correspond(pp, dirs, segs, window_px):
    """For each projected sample point, the nearest segment parallel to its edge whose line passes within window_px:
    (index or -1)."""
    sd = segs[:, 2:] - segs[:, :2]
    sl = np.linalg.norm(sd, axis=1)
    su = sd / np.maximum(sl[:, None], 1e-12)
    sn = np.stack([-su[:, 1], su[:, 0]], 1)
    out = np.full(len(pp), -1)
    cos = np.cos(np.radians(ANGLE))
    for i, (p, d) in enumerate(zip(pp, dirs)):
        par = np.abs(su @ d) > cos
        if not par.any():
            continue
        rel = p - segs[par, :2]
        perp = np.abs((rel * sn[par]).sum(1))
        along = (rel * su[par]).sum(1)
        ok = (perp < window_px) & (along > -0.1 * sl[par] - window_px) & (along < 1.1 * sl[par] + window_px)
        if ok.any():
            idx = np.where(par)[0][ok]
            out[i] = idx[np.argmin(perp[ok])]
    return out


def fit_nested(H0_plastic, shape, segs):
    """The three rectangles fitted from a start (plastic mm -> photo): (plastic_to_photo, placement (dx, dy, turn
    degrees, width mm), support {kind: share}, error: the median distance of the samples along segments from them, mm)
    or None."""
    pts, nrm, kinds = model_samples(shape)
    params = np.zeros(12)
    lo, hi = WIDTHS[shape]
    sd = segs[:, 2:] - segs[:, :2]
    su = sd / np.maximum(np.linalg.norm(sd, axis=1)[:, None], 1e-12)
    sn = np.stack([-su[:, 1], su[:, 0]], 1)
    for window in WINDOWS:
        pp, dirs, H = projected(params, H0_plastic, shape, pts, nrm, kinds)
        px_per_mm = local_scale(H, MODELS[shape]["label"])
        corr = correspond(pp, dirs, segs, window * px_per_mm)
        use = corr >= 0
        if use.sum() < 12:
            return None

        def residuals(x):
            pp, _, H = projected(x, H0_plastic, shape, pts, nrm, kinds)
            j = corr[use]
            r = ((pp[use] - segs[j, :2]) * sn[j]).sum(1) / px_per_mm
            prior = [x[8] / PLACEMENT_MM, x[9] / PLACEMENT_MM, x[10] / PLACEMENT_DEG, x[11] / WIDTH_SPREAD]
            return np.concatenate([r, prior])

        params = least_squares(residuals, params, loss="soft_l1", f_scale=ROBUST_MM, max_nfev=200).x
        params[11] = np.clip(MEDIAN_WIDTHS[shape] + params[11], lo, hi) - MEDIAN_WIDTHS[shape]
    pp, dirs, H = projected(params, H0_plastic, shape, pts, nrm, kinds)
    px_per_mm = local_scale(H, MODELS[shape]["label"])
    corr = correspond(pp, dirs, segs, ON_MM * px_per_mm)
    support = {k: round(float((corr[kinds == k] >= 0).mean()), 2) for k in ("face", "recess", "label")}
    j = corr[corr >= 0]
    error = float(np.median(np.abs(((pp[corr >= 0] - segs[j, :2]) * sn[j]).sum(1)) / px_per_mm)) if len(j) else ON_MM
    return (H / H[2, 2], (float(params[8]), float(params[9]), float(params[10]), float(MEDIAN_WIDTHS[shape] + params[11])),
            support, error)


def local_scale(H, rect):
    x0, y0, x1, y1 = rect
    q = project(H, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    return np.sqrt(abs(cv2.contourArea(q.astype(np.float32))) / ((x1 - x0) * (y1 - y0)))


# The pose search: where no good start is known, many poses of the cartridge model near the label photo's evidence
# are scored cheaply against the photo's segments, and the best few refined by fit_nested.
MAP_SIDE = 1000           # the edge maps' long side, px
DIRECTIONS = 8            # edge direction bins over 180 degrees
SEARCH_TURNS = (-10, -5, 0, 5, 10)   # degrees around each quarter turn of the base angle
SEARCH_SCALES = (0.8, 0.87, 0.93, 1.0, 1.07, 1.15, 1.25)
SEARCH_RANGE = 25.0       # mm: the label's centre searched within this of the evidence's centre
SEARCH_STEP = 1.5         # mm
SEARCH_SIGMA = 0.7        # mm: how fast a sample point's score falls with its distance from an edge
SEARCH_REFINE = 6         # the best distinct poses refined


def edge_maps(segs, size):
    """Per edge direction bin, the distance (px of the map) to the nearest segment of about that direction, and the
    map's scale (photo px per map px)."""
    scale = max(1.0, max(size) / MAP_SIDE)
    w, h = int(np.ceil(size[0] / scale)) + 1, int(np.ceil(size[1] / scale)) + 1
    angle = np.degrees(np.arctan2(segs[:, 3] - segs[:, 1], segs[:, 2] - segs[:, 0])) % 180
    b = np.round(angle / (180 / DIRECTIONS)).astype(int) % DIRECTIONS
    maps = []
    for k in range(DIRECTIONS):
        img = np.full((h, w), 255, np.uint8)
        for s_ in segs[(b == k) | (b == (k + 1) % DIRECTIONS) | (b == (k - 1) % DIRECTIONS)] / scale:
            cv2.line(img, (int(round(s_[0])), int(round(s_[1]))), (int(round(s_[2])), int(round(s_[3]))), 0, 1)
        maps.append(cv2.distanceTransform(img, cv2.DIST_L2, 3))
    return np.stack(maps), scale


def base_estimate(lp, lines=()):
    """A label photo's rough turn (degrees; None if unknown) and scale (photo px per mm) from its evidence. The turn:
    the direction most of the text read in its circle runs (weighted by length; RapidOCR's lines read in order): on
    the sample, along the label on 193 of 194 label photos (a detail's turn was a quarter turn off on 17 of 152). The
    scale: the median of its details' and its serial line's (about 2.2 mm tall), else its circle (a label's diagonal)."""
    weight = {}
    for line in lines:
        c = np.float64(line["corners"])
        if np.hypot(*(c.mean(0) - lp["centre"])) > lp["radius"]:
            continue
        v = c[1] - c[0]
        a = np.degrees(np.arctan2(v[1], v[0]))
        q = int(np.round(a / 90)) % 4
        weight.setdefault(q, []).append((np.linalg.norm(v), a))
    turn = None
    if weight:
        q = max(weight, key=lambda k: sum(w for w, _ in weight[k]))
        ws = weight[q]
        turn = float(np.degrees(np.arctan2(sum(w * np.sin(np.radians(a)) for w, a in ws), sum(w * np.cos(np.radians(a)) for w, a in ws))))
    scales = [d["px_per_mm"] for d in lp.get("details", [])]
    for t in lp["strings"][:1]:
        c = np.float64(t["corners"])
        scales.append((np.linalg.norm(c[3] - c[0]) + np.linalg.norm(c[2] - c[1])) / 2 / 2.2)
    scale = float(np.median(scales)) if scales else float(lp["radius"] / find.LABEL_DIAGONAL)
    return turn, scale


def search_poses(lp, shape, maps, map_scale, lines=()):
    """The best distinct poses (plastic mm -> photo, similarities) of the cartridge model near the label photo, by how
    close the model's sample points land to segments of their own direction: [(score, H)]."""
    pts, nrm, kinds = model_samples(shape)
    x0, y0, x1, y1 = MODELS[shape]["label"]
    centre_mm = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    rel = pts - centre_mm
    tangent_angle = np.degrees(np.arctan2(nrm[:, 0], -nrm[:, 1])) % 180  # the edge's direction, perpendicular to its normal
    base_angle, base_scale = base_estimate(lp, lines)
    quarters = (0,) if base_angle is not None else (0, 90, 180, 270)
    base_angle = base_angle or 0.0
    centre = np.float64(lp["outline"]).mean(0) if len(lp["outline"]) >= 3 else np.float64(lp["centre"])
    nd, mh, mw = maps.shape
    results = []
    for quarter in quarters:
        for dt in SEARCH_TURNS:
            th = np.radians(base_angle + quarter + dt)
            R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
            bins = np.round(((tangent_angle + np.degrees(th)) % 180) / (180 / DIRECTIONS)).astype(int) % DIRECTIONS
            for k in SEARCH_SCALES:
                ppm = base_scale * k
                offs = (rel @ R.T) * ppm / map_scale  # sample points around the label's centre, map px
                step = SEARCH_STEP * ppm / map_scale
                n = int(SEARCH_RANGE / SEARCH_STEP)
                grid = np.arange(-n, n + 1) * step
                cx = centre[0] / map_scale + grid
                cy = centre[1] / map_scale + grid
                X = cx[None, :, None] + offs[:, 0][:, None, None]   # samples x positions-x x 1
                Y = cy[None, None, :] + offs[:, 1][:, None, None]   # samples x 1 x positions-y
                xi = np.clip(np.round(X).astype(int), 0, mw - 1)
                yi = np.clip(np.round(Y).astype(int), 0, mh - 1)
                inside = (X >= 0) & (X < mw) & (Y >= 0) & (Y < mh)
                d = maps[bins[:, None, None], yi, xi] * map_scale / ppm  # mm
                score = (np.exp(-(d / SEARCH_SIGMA) ** 2) * inside).mean(0)  # positions-x x positions-y
                i, j = np.unravel_index(np.argmax(score), score.shape)
                for i, j in zip(*np.unravel_index(np.argsort(-score, axis=None)[:3], score.shape)):
                    c = np.array([cx[i], cy[j]]) * map_scale
                    A = ppm * R
                    t = c - A @ centre_mm
                    H = np.array([[A[0, 0], A[0, 1], t[0]], [A[1, 0], A[1, 1], t[1]], [0, 0, 1]])
                    results.append((float(score[i, j]), H, c, base_angle + quarter + dt, ppm))
    results.sort(key=lambda r: -r[0])
    chosen = []
    for r in results:  # distinct: centres over 3 mm apart, or turns over 5 degrees
        if all(np.linalg.norm(r[2] - c[2]) > 3 * r[4] or abs((r[3] - c[3] + 180) % 360 - 180) > 5 for c in chosen):
            chosen.append(r)
        if len(chosen) >= SEARCH_REFINE:
            break
    return [(r[0], r[1]) for r in chosen]


def similarity_to_H(centre, angle_deg, px_per_mm, shape):
    """label mm -> photo: the label's centre at centre, turned by angle, at px_per_mm."""
    w, h = shapes.LABEL_MM[shape]
    a = np.radians(angle_deg)
    R = px_per_mm * np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    t = np.asarray(centre) - R @ [w / 2, h / 2]
    return np.vstack([np.hstack([R, t[:, None]]), [0, 0, 1]])


def link_points(lps, matches):
    """(key a, key b) -> (points in photo a, points in photo b): match inliers lying in both label photos' circles."""
    by_photo = {}
    for lp in lps:
        by_photo.setdefault(lp["photo"], []).append(lp)
    out = {}
    for a, b, H, inl in matches:
        for la in by_photo.get(a, []):
            ina = np.hypot(*(inl[:, :2] - la["centre"]).T) < la["radius"]
            for lb in by_photo.get(b, []):
                ok = ina & (np.hypot(*(inl[:, 2:] - lb["centre"]).T) < lb["radius"])
                if ok.sum() >= MIN_LINK_POINTS:
                    k = (la["key"], lb["key"])
                    pa, pb = out.get(k, (np.zeros((0, 2)), np.zeros((0, 2))))
                    out[k] = (np.vstack([pa, inl[ok, :2]]), np.vstack([pb, inl[ok, 2:]]))
    return out


def rigid_fit(a, b):
    """b ~ R(theta) a + t, least squares: (theta degrees, t)."""
    ca, cb = a.mean(0), b.mean(0)
    A, B = a - ca, b - cb
    theta = np.arctan2((A[:, 0] * B[:, 1] - A[:, 1] * B[:, 0]).sum(), (A * B).sum())
    R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    return np.degrees(theta), cb - R @ ca


def usable(cut, shape):
    """Whether a label's homography is sound: finite, well conditioned, the label a convex quadrilateral at least 20
    px across in the photo (a degenerate fit once got through and couldn't be inverted)."""
    if not np.all(np.isfinite(cut)) or abs(cut[2, 2]) < 1e-12 or np.linalg.cond(cut) > 1e12:
        return False
    q = project(cut / cut[2, 2], corners_mm(shape))
    return bool(np.all(np.isfinite(q)) and cv2.isContourConvex(q.astype(np.float32)) and
                cv2.contourArea(q.astype(np.float32)) > 400)


def candidate(lp, H0_plastic, segs, start):
    """A start (plastic mm -> photo) refined by the nested fit: the fit, or None if it fails the support checks."""
    shape = lp["shape"]
    result = fit_nested(H0_plastic, shape, segs)
    if result is None:
        return None
    H, placement, support, error = result
    if not np.all(np.isfinite(H)) or abs(np.linalg.det(H)) < 1e-12:
        return None
    if np.mean(list(support.values())) < MIN_SUPPORT or support["face"] < MIN_FACE:
        return None
    cut = H @ placement_matrix(shape, placement[0], placement[1], np.radians(placement[2])) @ label_to_plastic(shape)
    if not usable(cut, shape):
        return None
    return {"cut_to_photo": cut / cut[2, 2], "width_mm": placement[3], "plastic_to_photo": H, "placement": placement[:3], "support": support,
            "error_mm": error, "start": start, "px_per_mm": local_scale(H, MODELS[shape]["label"]), "tilt": outlines.tilt(H)}


def fit_label_photo(job):
    """Stage 1's round 1 for one label photo: (key, candidates, why none): every start refined by the nested fit and
    passing the support checks: the logo placement, every outline start, and the pose search if none of those passed;
    each with the scale its evidence suggests (base_estimate) for the choice."""
    lp, edges_dir, text_dir = job
    if not lp["shape"]:
        return lp["key"], [], "no shape"
    shape = lp["shape"]
    e = np.load(os.path.join(edges_dir, lp["photo"] + ".npz"))
    segs, size = e["segments"].astype(np.float64), tuple(int(v) for v in e["size"])
    lines = json.load(open(os.path.join(text_dir, lp["photo"] + ".json")))["lines"]
    found = []
    if lp.get("placed_by") and len(lp["outline"]) == 4:
        mm = corners_mm(shape)
        Hl = cv2.getPerspectiveTransform(mm.astype(np.float32), np.float32(lp["outline"])).astype(np.float64)
        found.append(candidate(lp, Hl @ np.linalg.inv(label_to_plastic(shape)), segs, "placed by " + lp["placed_by"]))
    # every outline start of the photo: keeping only those near the label photo (find's circle) dropped right ones
    # (evaluation set: 94 % under 5 mm against 96 %, 87 against 98 % where main's fitter had failed); with several
    # cartridges in a photo, one may take another's outline
    for H0, i, what in outlines.outline_starts(e["quads"], shape, size):
        found.append(candidate(lp, H0, segs, f"outline ({what})"))
    found = [f for f in found if f is not None]
    if not found:  # the pose search, as a fallback
        maps, map_scale = edge_maps(segs, size)
        found = [f for score, Hp in search_poses(lp, shape, maps, map_scale, lines)
                 if (f := candidate(lp, Hp, segs, f"search ({score:.2f})")) is not None]
    expected = base_estimate(lp, lines)[1]
    for f in found:
        f["expected_px_per_mm"] = expected
    return lp["key"], found, None if found else "no outline found"


# The choice among a label photo's candidates, learned from the first round (label-detection.md: the right
# candidate is among them far more often than the best supported one is right). Round 1 chooses the logo placement if
# it passed, else the best mean support. Confident label photos: candidates from at least two kinds of start agree
# within AGREE_MM with round 1's choice (or the logo placement does). Their candidates are examples: within AGREE_MM of
# it right, over WRONG_MM wrong. A logistic regression on plain features (FEATURES) then chooses for every label photo.
AGREE_MM = 0.5
WRONG_MM = 3.0
KINDS = ["placed", "outline (label)", "outline (recess)", "outline (body)", "search"]
FEATURES = ["face support", "recess support", "label support", "mean support", "placement shift", "placement turn",
            "scale against the evidence", "agreeing share", "agreeing count", "error", "tilt"] + ["start: " + k for k in KINDS]


def kind_of(start):
    return next((k for k in KINDS if start.startswith(k)), "search")


def apart_mm(a, b, shape):
    """The worst corner of b's label cut in a's label mm (infinite if a's can't be inverted)."""
    mm = corners_mm(shape)
    try:
        m = project(np.linalg.inv(a["cut_to_photo"]), project(b["cut_to_photo"], mm))
    except np.linalg.LinAlgError:
        return float("inf")
    d = float(np.max(np.linalg.norm(m - mm, axis=1)))
    return d if np.isfinite(d) else float("inf")


def features(cands, shape):
    """Each candidate's features (FEATURES), and the matrix of their distances apart."""
    n = len(cands)
    apart = np.array([[apart_mm(a, b, shape) if a is not b else 0.0 for b in cands] for a in cands]) if n else np.zeros((0, 0))
    rows = []
    for i, c in enumerate(cands):
        agree = (apart[i] < AGREE_MM).sum() - 1
        s = c["support"]
        row = [s["face"], s["recess"], s["label"], np.mean(list(s.values())), np.hypot(*c["placement"][:2]),
               abs(c["placement"][2]), abs(np.log(c["px_per_mm"] / max(c["expected_px_per_mm"], 1e-9))),
               agree / max(n - 1, 1), min(agree, 10) / 10, c["error_mm"], abs(c["tilt"]) / 50]
        row += [float(kind_of(c["start"]) == k) for k in KINDS]
        rows.append(row)
    return np.array(rows, np.float64).reshape(n, len(FEATURES)), apart


def round1(cands):
    placed = [i for i, c in enumerate(cands) if c["start"].startswith("placed")]
    if placed:
        return placed[0]
    return int(np.argmax([np.mean(list(c["support"].values())) for c in cands]))


def confident(cands, apart, chosen):
    """Whether round 1's choice is confirmed: candidates from at least two kinds of start agree with it within
    AGREE_MM, or it's the logo placement and another candidate agrees."""
    agreeing = [i for i in range(len(cands)) if apart[chosen, i] < AGREE_MM]
    kinds = {kind_of(cands[i]["start"]).split(" ")[0] if not cands[i]["start"].startswith("outline") else kind_of(cands[i]["start"]) for i in agreeing}
    return len(kinds) >= 2


def train_choice(examples, labels, steps=3000, rate=0.1, l2=1e-3):
    """A logistic regression (standardized features, L2): (mean, scale, weights, bias)."""
    X = np.array(examples); y = np.array(labels, np.float64)
    mean, scale = X.mean(0), X.std(0) + 1e-9
    Z = (X - mean) / scale
    w, b = np.zeros(Z.shape[1]), 0.0
    for _ in range(steps):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = p - y
        w -= rate * (Z.T @ g / len(y) + l2 * w)
        b -= rate * g.mean()
    return mean, scale, w, b


def predict(model, X):
    mean, scale, w, b = model
    return 1 / (1 + np.exp(-(((X - mean) / scale) @ w + b)))


# Stage 1's candidates are cached per label photo in <generated>/solve/candidates/, stamped with a fingerprint of the
# fitting code (the source of the functions stage 1 runs, and the models), so a change elsewhere in this file (stage
# 2, the choice, the page) or a crash after stage 1 doesn't redo the fitting.
FITTING = ["usable", "candidate", "fit_label_photo", "fit_nested", "correspond", "projected", "homography_from",
           "model_samples", "placement_matrix", "label_to_plastic", "local_scale", "edge_maps", "base_estimate",
           "search_poses", "corners_mm", "project"]


def fitting_version():
    import hashlib, inspect
    h = hashlib.sha1()
    for name in FITTING:
        h.update(inspect.getsource(globals()[name]).encode())
    for k in ("ANGLE", "WINDOWS", "ROBUST_MM", "ON_MM", "PLACEMENT_MM", "PLACEMENT_DEG", "WIDTHS", "MEDIAN_WIDTHS", "WIDTH_SPREAD", "MIN_SUPPORT", "MIN_FACE",
              "MAP_SIDE", "DIRECTIONS", "SEARCH_TURNS", "SEARCH_SCALES", "SEARCH_RANGE", "SEARCH_STEP", "SEARCH_SIGMA", "SEARCH_REFINE"):
        h.update(repr(globals()[k]).encode())
    h.update(inspect.getsource(outlines).encode())
    h.update(json.dumps(MODELS, sort_keys=True).encode())
    return h.hexdigest()[:16]


def cache_file(cache_dir, key):
    return os.path.join(cache_dir, key.replace("@", "_").replace(",", "_") + ".json")


def fitting_inputs(lp, edges_dir):
    """What a label photo's fit depends on besides the code: find's shape, logo placement, outline, centre and radius
    for it, and its photo's edges file (its time)."""
    e = os.path.join(edges_dir, lp["photo"] + ".npz")
    plain = lambda v: v.tolist() if isinstance(v, np.ndarray) else v
    return {k: plain(lp.get(k)) for k in ("shape", "placed_by", "outline", "centre", "radius")} | {
        "edges": os.path.getmtime(e) if os.path.exists(e) else None}


def save_candidates(cache_dir, lp, cands, why, version, edges_dir):
    plain = [{k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in c.items()} for c in cands]
    steps.write_json(cache_file(cache_dir, lp["key"]), {"version": version, "inputs": fitting_inputs(lp, edges_dir),
                                                        "candidates": plain, "why": why})


def load_candidates(cache_dir, lp, version, edges_dir):
    """(candidates, why) if cached for this fitting code and the same inputs (fitting_inputs: a label photo whose find
    result or edges changed under the same key is fitted again), else None."""
    p = cache_file(cache_dir, lp["key"])
    if not os.path.exists(p):
        return None
    d = json.load(open(p))
    if d.get("version") != version or d.get("inputs") != json.loads(json.dumps(fitting_inputs(lp, edges_dir))):
        return None
    cands = [{k: (np.array(v) if k in ("cut_to_photo", "plastic_to_photo") else v) for k, v in c.items()} for c in d["candidates"]]
    return cands, d["why"]


def own_candidates(all_cands, lps):
    """In a photo with several label photos, each keeps only the candidates whose label centre is nearer its own centre
    (find's) than any other label photo's of the photo: every label photo gets all the photo's outline starts (see
    fit_label_photo), and without this the best supported cartridge won for all of them (2026-11-11: 273 of 609 label
    photos in such photos fitted over a radius from their own centre, against 147 of 10534 alone in theirs).
    -> (key -> candidates, the keys left with none)."""
    by_photo = {}
    for lp in lps:
        by_photo.setdefault(lp["photo"], []).append(lp)
    out, emptied = dict(all_cands), []
    for group in by_photo.values():
        bases = list(dict.fromkeys(lp.get("base", lp["key"]) for lp in group))  # a label photo fitted with several shapes: one
        if len(bases) < 2:
            continue
        centres = np.array([next(lp["centre"] for lp in group if lp.get("base", lp["key"]) == b) for b in bases], np.float64)
        for lp in group:
            i = bases.index(lp.get("base", lp["key"]))
            cands = all_cands.get(lp["key"])
            if not cands:
                continue
            mm = corners_mm(lp["shape"]).mean(0)
            mine = []
            for c in cands:
                at = project(np.array(c["cut_to_photo"]), [mm])[0]
                if np.all(np.isfinite(at)) and int(np.argmin(np.linalg.norm(centres - at, axis=1))) == i:
                    mine.append(c)
            if mine:
                out[lp["key"]] = mine
            else:
                del out[lp["key"]]
                emptied.append(lp["key"])
    return out, emptied


def stage1(lps, edges_dir, pairs, workers=8):
    """The fits: round 1 (every candidate, in parallel), then the choice learned from its confident label photos:
    key -> fit; key -> why for those that failed; the choice model's description."""
    text_dir = os.path.join(os.path.dirname(edges_dir), "read-text")
    cache_dir = os.path.join(os.path.dirname(edges_dir), "solve", "candidates")
    os.makedirs(cache_dir, exist_ok=True)
    shape_of = {lp["key"]: lp["shape"] for lp in lps}
    all_cands, failed = {}, {}
    version = fitting_version()
    by_key = {lp["key"]: lp for lp in lps}
    todo = []
    for lp in lps:
        cached = load_candidates(cache_dir, lp, version, edges_dir)
        if cached is None:
            todo.append(lp)
        elif cached[0]:
            all_cands[lp["key"]] = cached[0]
        else:
            failed[lp["key"]] = cached[1]
    print(f"stage 1: {len(lps) - len(todo)} label photos' candidates cached, {len(todo)} to fit", flush=True)
    with Pool(workers) as pool:
        for n, (key, cands, why) in enumerate(pool.imap_unordered(fit_label_photo, [(lp, edges_dir, text_dir) for lp in todo]), 1):
            save_candidates(cache_dir, by_key[key], cands, why, version, edges_dir)
            if cands:
                all_cands[key] = cands
            else:
                failed[key] = why
            if n % 100 == 0 or n == len(todo):
                print(f"stage 1: fitted {n} of {len(todo)}", flush=True)
    all_cands, taken = own_candidates(all_cands, lps)
    for key in taken:
        failed[key] = "no candidate on this label: the photo's other label photos are nearer every one"
    feats, examples, labels, first, sure = {}, [], [], {}, 0
    for key, cands in all_cands.items():
        X, apart = features(cands, shape_of[key])
        feats[key] = X
        first[key] = round1(cands)
        if confident(cands, apart, first[key]):
            sure += 1
            for i in range(len(cands)):
                if apart[first[key], i] < AGREE_MM:
                    examples.append(X[i]); labels.append(1)
                elif apart[first[key], i] > WRONG_MM:
                    examples.append(X[i]); labels.append(0)
    model = train_choice(examples, labels) if len(set(labels)) == 2 else None
    fits = {}
    for key, cands in all_cands.items():
        if model is None:
            k, p = first[key], None
        else:
            probs = predict(model, feats[key])
            k, p = int(np.argmax(probs)), float(probs.max())
        fits[key] = dict(cands[k], candidates=len(cands), probability=p, round1_same=bool(k == first[key]))
    description = None if model is None else {
        "confident label photos": sure, "examples": len(labels), "right": int(sum(labels)),
        "weights": {f: round(float(w), 3) for f, w in zip(FEATURES, model[2])}}
    return fits, failed, description


# Shapes (the user, 2026-11-22): find gives a label photo the shape its serials name, but its strings are those near
# it, before anyone knows the label's edges: a second cartridge's serial in the photo can land in it (9817412e@48,54:
# CGB-BYTP-EUR on its label, AGB-AXVP-EUR of another cartridge 450 px off), and with a 1-1 tie find's vote once came out
# at random. So a label photo whose exact or near serials name two shapes or more is fitted once with each
# (shape_variants: key "<key>#<shape>"), and the fit kept (choose_shapes) is one whose fitted label holds a serial of
# its own shape (the string's centre on the label), the best mean support among those, else among all. Then every
# label photo keeps only its strings whose centre is on its fitted label (drop_strings_off_label; read-serials does
# the same with the final fit).
def platforms_named(lp):
    """The shapes a label photo's exact and near serials name, sorted."""
    return sorted({find.shape_of(t["serial"]) for t in lp.get("strings") or [] if t["kind"] != "unknown"} - {None})


def strings_on_label(strings, photo_to_label, shape):
    """The strings whose centre lies on the label: photo_to_label maps the photo's pixels to label mm (its top left at
    0, 0: the inverse of a cut_to_photo, or a photo_to_ink), the label its shape's canonical size."""
    w, h = shapes.LABEL_MM[shape]
    on = []
    for t in strings:
        if not t.get("corners"):
            continue
        c = project(photo_to_label, [np.mean(np.float64(t["corners"]), 0)])[0]
        if np.all(np.isfinite(c)) and 0 <= c[0] <= w and 0 <= c[1] <= h:
            on.append(t)
    return on


def shape_variants(lps):
    """The label photos to fit: each once, those whose serials name several shapes once per shape (key
    "<key>#<shape>", "base": its key)."""
    out = []
    for lp in lps:
        named = platforms_named(lp)
        if len(named) < 2:
            out.append(lp)
        else:
            out += [dict(lp, key=f"{lp['key']}#{s}", shape=s, base=lp["key"]) for s in named]
    return out


def choose_shapes(lps, fits, failed):
    """For each label photo fitted with several shapes (shape_variants), in place: its shape and fit the chosen one's
    (above), its variants' fits and failures removed; one with no fit at all fails (shape None). -> {shape chosen,
    shapes named: count}."""
    chosen = {}
    for lp in lps:
        named = platforms_named(lp)
        if len(named) < 2:
            continue
        tried, why = [], []
        for s in named:
            v = f"{lp['key']}#{s}"
            f = fits.pop(v, None)
            if v in failed:
                why.append(f"{s}: {failed.pop(v)}")
            if f is None:
                continue
            on = strings_on_label(lp["strings"], np.linalg.inv(f["cut_to_photo"]), s)
            own = any(t["kind"] != "unknown" and find.shape_of(t["serial"]) == s for t in on)
            tried.append((own, float(np.mean(list(f["support"].values()))), s, f))
        if not tried:
            lp["shape"] = None
            failed[lp["key"]] = "no fit with any shape its serials name: " + "; ".join(why)
            continue
        own, _, s, f = max(tried, key=lambda t: (t[0], t[1]))
        lp["shape"] = s
        fits[lp["key"]] = f
        label = f"{s} of {', '.join(named)}" + ("" if own else ", none holding its serial")
        chosen[label] = chosen.get(label, 0) + 1
    return dict(sorted(chosen.items()))


def drop_strings_off_label(lps, fits):
    """Each fitted label photo's strings: only those on its fitted label (in place). -> how many dropped."""
    dropped = 0
    for lp in lps:
        if lp["key"] in fits and lp.get("strings"):
            on = strings_on_label(lp["strings"], np.linalg.inv(fits[lp["key"]]["cut_to_photo"]), lp["shape"])
            dropped += len(lp["strings"]) - len(on)
            lp["strings"] = on
    return dropped


# Stage 1b, an experiment (label-detection.md: edge models): each chosen fit refined by the learned edge models
# (src/edge_fit.py), on the photo's pixels instead of its segments: the recess (the plastic's pose), then on it the
# label's cut: its shift and turn in the recess, its width and its height, each free (stickers are cut as they are),
# started from the nested fit's (the height from the canonical one). Each part's refinement is used only if its
# confidence is at least edge_fit.ACCEPT, and the label's only if it's plausible: its corners within the recess (with
# EDGE_RECESS_SLACK mm for the fit's error) and its width and height each within EDGE_SIZE_TOLERANCE mm of the
# canonical ones (the sample's widest departure 1.5 mm, 2026-11-10); else the
# nested fit's is kept (a label not used keeps its place in the photo), marked an approximate cut (its fallback): the
# nested fit's label is no better where the edge models found none, but the label photo's pixels are still aligned to
# its family's by stage 2 and the refinements (their corrections as small as the confirmed fits', 2026-11-12), so
# restore uses it with its cut moved further inward (restore.APPROXIMATE_INSET). Cached per label photo in
# <generated>/solve/edge/, for its chosen fit and this code.
EDGE_RECESS_SLACK = 0.5
EDGE_SIZE_TOLERANCE = 2.0


def approximate_cut(r):
    """Whether a label photo's record in solve.json has an approximate cut: the label edges could not be precisely located."""
    return bool(r.get("edge")) and not r["edge"].get("label_used", True)


def poor_fit(r):
    """Whether a label photo's record in solve.json is a poor fit (its links disagree, or its correction was too large):
    not aligned to its family, so not used. (Approximate cuts were once called poor fits too: older solve.json.)"""
    return (r.get("fallback") or "").startswith("a poor") and not approximate_cut(r)


def edge_version():
    import hashlib, inspect
    h = hashlib.sha1(inspect.getsource(edge_fit).encode())
    for name in ("edge_refine", "refine_one", "placement_matrix", "label_to_plastic", "corners_mm"):
        h.update(inspect.getsource(globals()[name]).encode())
    h.update(repr((EDGE_RECESS_SLACK, EDGE_SIZE_TOLERANCE)).encode())
    for f in sorted(os.listdir(edge_fit.MODELS)):
        if f.endswith(".onnx"):
            h.update(open(os.path.join(edge_fit.MODELS, f), "rb").read())
    return h.hexdigest()[:16]


def edge_refine(job):
    """(key, what the edge models made of one chosen fit: the poses to use and the measures), None if the photo can't be
    read. A refinement that fails is neither part used (the label photo then a poor fit), with the error."""
    try:
        return refine_one(job)
    except Exception as e:  # one label photo's failure mustn't end the run
        key, shape, path, H, placement, width = job
        H = np.asarray(H, np.float64)
        cut = H @ placement_matrix(shape, *placement[:2], np.radians(placement[2])) @ label_to_plastic(shape)
        return key, {"plastic_to_photo": H.tolist(), "cut_to_photo": (cut / cut[2, 2]).tolist(), "placement": list(placement),
                     "width_mm": float(width), "height_mm": float(shapes.LABEL_MM[shape][1]),
                     "recess_confidence": 0.0, "recess_used": False, "recess_moved_mm": 0.0,
                     "label_confidence": 0.0, "label_used": False, "label_moved_mm": 0.0, "error": f"{type(e).__name__}: {e}"[:200]}


def refine_one(job):
    key, shape, path, H, placement, width = job
    photo = photos.load(path)
    if photo is None:
        return key, None
    H = np.asarray(H, np.float64)
    recess = MODELS[shape]["recess"]
    Hr, recess_conf = edge_fit.refine(photo, H, shape, "recess")
    recess_used = recess_conf >= edge_fit.ACCEPT
    base = Hr if recess_used else H
    pose_of = lambda x: base @ placement_matrix(shape, x[0], x[1], np.radians(x[2]), x[3], x[4])
    lw, lh = shapes.LABEL_MM[shape]
    x, Hl, label_conf = edge_fit.fit_params(photo, shape, "label", pose_of, [*placement, width, lh])
    x1, y1, x2, y2 = MODELS[shape]["label"]
    placed = project(placement_matrix(shape, x[0], x[1], np.radians(x[2]), x[3], x[4]), [[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
    rx1, ry1, rx2, ry2 = recess
    inside = bool(np.all((placed[:, 0] >= rx1 - EDGE_RECESS_SLACK) & (placed[:, 0] <= rx2 + EDGE_RECESS_SLACK)
                         & (placed[:, 1] >= ry1 - EDGE_RECESS_SLACK) & (placed[:, 1] <= ry2 + EDGE_RECESS_SLACK)))
    label_used = bool(label_conf >= edge_fit.ACCEPT and inside and abs(x[3] - lw) <= EDGE_SIZE_TOLERANCE and abs(x[4] - lh) <= EDGE_SIZE_TOLERANCE)
    old_cut = H @ placement_matrix(shape, *placement[:2], np.radians(placement[2])) @ label_to_plastic(shape)
    new_cut = base @ placement_matrix(shape, x[0], x[1], np.radians(x[2])) @ label_to_plastic(shape)
    mm = corners_mm(shape)
    label_moved = float(np.max(np.linalg.norm(project(np.linalg.inv(old_cut), project(new_cut, mm)) - mm, axis=1)))
    return key, {"plastic_to_photo": (Hr if recess_used else H).tolist(),
                 "cut_to_photo": ((new_cut if label_used else old_cut) / (new_cut if label_used else old_cut)[2, 2]).tolist(),
                 "placement": [float(v) for v in (x[:3] if label_used else placement)], "width_mm": float(x[3] if label_used else width),
                 "height_mm": float(x[4] if label_used else lh),
                 "recess_confidence": round(recess_conf, 3), "recess_used": bool(recess_used),
                 "recess_moved_mm": round(edge_fit.corner_error(Hr, H, recess), 3),
                 "label_confidence": round(label_conf, 3), "label_used": label_used, "label_moved_mm": round(label_moved, 3)}


def stage1_edges(lps, fits, photo_paths, workers=8):
    """The chosen fits, each refined by the edge models where they're sure (stage 1b, above)."""
    cache_dir = os.path.join(_GEN_DIR, "solve", "edge")
    os.makedirs(cache_dir, exist_ok=True)
    version = edge_version()
    by_key = {lp["key"]: lp for lp in lps}
    done, todo = {}, []
    for key, f in fits.items():
        lp = by_key[key]
        job = (key, lp["shape"], photo_paths.get(lp["photo"]), np.asarray(f["plastic_to_photo"]).tolist(),
               [float(v) for v in f["placement"]], float(f.get("width_mm", MEDIAN_WIDTHS[lp["shape"]])))
        if job[2] is None:
            continue
        p = cache_file(cache_dir, key)
        if os.path.exists(p):
            d = json.load(open(p))
            if d.get("version") == version and d.get("job") == list(job[3:]):
                done[key] = d["edge"]
                continue
        todo.append(job)
    print(f"stage 1b: {len(done)} label photos' edge refinements cached, {len(todo)} to do", flush=True)
    jobs = {j[0]: j for j in todo}
    with Pool(workers) as pool:
        for n, (key, e) in enumerate(pool.imap_unordered(edge_refine, todo, chunksize=4), 1):
            steps.write_json(cache_file(cache_dir, key), {"version": version, "job": list(jobs[key][3:]), "edge": e})
            done[key] = e
            if n % 200 == 0 or n == len(todo):
                print(f"stage 1b: refined {n} of {len(todo)}", flush=True)
    out = {}
    for key, f in fits.items():
        e = done.get(key)
        if e is None:
            out[key] = dict(f, edge=None)
            continue
        out[key] = dict(f, plastic_to_photo=np.asarray(e["plastic_to_photo"]), cut_to_photo=np.asarray(e["cut_to_photo"]),
                        placement=e["placement"], width_mm=e["width_mm"], height_mm=e["height_mm"],
                        edge={k: v for k, v in e.items() if k not in ("plastic_to_photo", "cut_to_photo", "placement", "width_mm", "height_mm")})
    used = lambda part: sum(1 for f in out.values() if f["edge"] and f["edge"][part + "_used"])
    print(f"stage 1b: the edge models' recess used on {used('recess')}, label on {used('label')} of {len(out)}", flush=True)
    return out


# One sticker, one label photo: find tells label photos of one photo apart by rough outlines (find.MERGE_OVERLAP), and a
# label photo spread there through a match could sit beside one found by its serial, both then fitted to the same
# sticker (the full set, 2026-11-12: 327 of 381 pairs of label photos in one photo had fits overlapping, 315 by over 90 %
# of the smaller; none between 0 and 10 %). Stickers can't overlap, so after the fits are final in the photo (stage 1b),
# label photos of one photo whose fitted cuts share over FIT_OVERLAP of the smaller are merged (the user: 25 %): the one
# kept is the precise fit over an approximate cut, then the one found by the strongest means (find.FOUND_BY), then the
# first key; it takes the others' strings and their link candidates (per match, the one with the most points between
# two label photos), and lists them in solve.json ("merged").
FIT_OVERLAP = 0.25


def fit_quad(f, shape):
    """A fit's cut (its width and height) in the photo: 4 x 2 float32."""
    lw, lh = shapes.LABEL_MM[shape]
    w, h = f.get("width_mm") or lw, f.get("height_mm") or lh
    a, b = (lw - w) / 2, (lh - h) / 2
    return project(np.asarray(f["cut_to_photo"], np.float64), np.float64([[a, b], [lw - a, b], [lw - a, lh - b], [a, lh - b]])).astype(np.float32)


def merge_fitted(lps, fits):
    """{dropped key: kept key} for label photos of one photo whose fits overlap (see above); the kept ones' strings
    combined."""
    by_photo = {}
    for lp in lps:
        if lp["key"] in fits:
            by_photo.setdefault(lp["photo"], []).append(lp)
    merged = {}
    for group in by_photo.values():
        if len(group) < 2:
            continue
        quads = [fit_quad(fits[lp["key"]], lp["shape"]) for lp in group]
        parent = list(range(len(group)))
        fixed_in = [lp["found_by"] in ("frozen", "stored") for lp in group]  # per root: its set holds a stored one
        def root(i):
            while parent[i] != i:
                i = parent[i]
            return i
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                try:
                    shared = cv2.intersectConvexConvex(quads[i], quads[j])[0]
                except cv2.error:
                    shared = 0.0
                smaller = min(abs(cv2.contourArea(quads[i])), abs(cv2.contourArea(quads[j])))
                # two stored label photos: never one, not through a third either (union-find joins transitively:
                # 2026-11-22, 19 stored label photos merged into another stored one through unstored ones between)
                ri, rj = root(i), root(j)
                fixed = ri != rj and fixed_in[ri] and fixed_in[rj]
                if smaller > 0 and shared / smaller > FIT_OVERLAP and not fixed:
                    parent[rj] = ri
                    fixed_in[ri] = fixed_in[ri] or fixed_in[rj]
        sets = {}
        for i, lp in enumerate(group):
            sets.setdefault(root(i), []).append(lp)
        for members in sets.values():
            if len(members) < 2:
                continue
            rank = lambda lp: (lp["found_by"] not in ("frozen", "stored"), approximate_cut(fits[lp["key"]]), find.FOUND_BY.index(lp["found_by"]), lp["key"])
            members.sort(key=rank)
            keep = members[0]
            for lp in members[1:]:
                merged[lp["key"]] = keep["key"]
                keep["strings"] = keep["strings"] + lp["strings"]
    print(f"one sticker, one label photo: {len(merged)} label photos merged into another of their photo", flush=True)
    return merged


# Stage 2: each link candidate is one match homography between two label photos (not pooled: a match between prints
# with offset art finds one alignment for the text and another for the art). A link counts where
#   - its matched points, mapped into each sticker's frame, agree within LINK_FIT_MM after the best shift and turn
#     (in good matches the halftone dots line up; 0.5 mm means a fit is off), and
#   - the two label photos' pixels agree there: both drawn into the label's mm at COMPARE_PX_PER_MM, lighting evened
#     (minus the local mean, over the local spread), compared in COMPARE_TILE_MM tiles by correlation; at least
#     AGREE_SHARE of the tiles textured in either above TILE_CORRELATION in both (a shared template or offset art
#     agrees only in part; art in one and plain in the other disagrees), over at least MIN_COVERAGE of the label's
#     tiles, its shift and turn within MAX_SHIFT and MAX_TURN (a template matched at another place on another layout
#     overlaps the two labels only in part: those links had chained five CGB games into one family).
# A label photo most of whose pixel-agreeing links fail the fit test is a poor fit: flagged, no links, its own family.
# Offsets fitted per family (label photos joined by counting links) by least squares with Tukey reweighting; each
# family's median offset is none (its median cut anchors its ink coordinates).
LINK_FIT_MM = 0.25
COMPARE_PX_PER_MM = 5
COMPARE_MARGIN = 2.0
COMPARE_TILE_MM = 2.0
TILE_CORRELATION = 0.5
AGREE_SHARE = 0.45  # sample, links fitting within LINK_FIT_MM, tiles textured in either: same old name 10/50/90 % at 0.46/0.70/0.85, different 0.03/0.12/0.21; the MINUET against plain DMG-TRA 0.36-0.43 (its offset art)
MIN_COVERAGE = 0.5  # of the label's tiles: a link comparing fewer (two labels overlapping in part) doesn't count
MIN_TEXTURED_TILES = 20
TUKEY_MM = 0.5


def link_candidates(lps, matches, merged=None):
    """One link candidate per match homography: [(key a, key b, points in a, points in b)], the points those in both
    label photos' circles. A merged label photo's (merged: {dropped: kept}) count as the kept one's: per match, the
    one with the most points between two label photos; none within one."""
    merged = merged or {}
    by_photo = {}
    for lp in lps:
        by_photo.setdefault(lp["photo"], []).append(lp)
    out = []
    for a, b, H, inl in matches:
        best = {}
        for la in by_photo.get(a, []):
            ina = np.hypot(*(inl[:, :2] - la["centre"]).T) < la["radius"]
            for lb in by_photo.get(b, []):
                ok = ina & (np.hypot(*(inl[:, 2:] - lb["centre"]).T) < lb["radius"])
                if ok.sum() >= MIN_LINK_POINTS:
                    ka, kb = merged.get(la["key"], la["key"]), merged.get(lb["key"], lb["key"])
                    if ka != kb and ((ka, kb) not in best or ok.sum() > len(best[(ka, kb)][2])):
                        best[(ka, kb)] = (ka, kb, inl[ok, :2], inl[ok, 2:])
        out += best.values()
    return out


def compare_view(photo, cut_to_photo, shape):
    """A label photo drawn into its sticker's frame (label mm, COMPARE_MARGIN around), gray, lighting evened."""
    w, h = shapes.LABEL_MM[shape]
    W, Hh = int((w + 2 * COMPARE_MARGIN) * COMPARE_PX_PER_MM), int((h + 2 * COMPARE_MARGIN) * COMPARE_PX_PER_MM)
    s = 1 / COMPARE_PX_PER_MM
    px_to_mm = np.array([[s, 0, -COMPARE_MARGIN], [0, s, -COMPARE_MARGIN], [0, 0, 1.0]])
    g = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY).astype(np.float32)
    v = cv2.warpPerspective(g, np.float64(cut_to_photo) @ px_to_mm, (W, Hh), flags=cv2.INTER_AREA | cv2.WARP_INVERSE_MAP)
    mean = cv2.GaussianBlur(v, (0, 0), COMPARE_PX_PER_MM)
    spread = np.sqrt(cv2.GaussianBlur((v - mean) ** 2, (0, 0), COMPARE_PX_PER_MM)) + 2.0
    return (v - mean) / spread


def pixel_agreement(va, vb, theta_deg, t_mm, shape):
    """The share of tiles textured in either label photo where b, carried into a's frame (b's mm -> a's mm: turn theta,
    shift t), agrees with a (both textured and correlating); and the count of those tiles."""
    th = np.radians(theta_deg)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    s, m = COMPARE_PX_PER_MM, COMPARE_MARGIN
    # a's px -> a's mm -> b's mm -> b's px
    A = np.array([[1 / s, 0, -m], [0, 1 / s, -m], [0, 0, 1.0]])
    B = np.array([[R[0, 0], R[0, 1], t_mm[0]], [R[1, 0], R[1, 1], t_mm[1]], [0, 0, 1.0]])
    Binv = np.linalg.inv(B)
    C = np.array([[s, 0, m * s], [0, s, m * s], [0, 0, 1.0]])
    M = C @ Binv @ A
    wb = cv2.warpPerspective(vb, M, (va.shape[1], va.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=np.nan)  # M: a's px -> b's px
    t = int(COMPARE_TILE_MM * s)
    w, h = shapes.LABEL_MM[shape]
    x0, y0 = int(m * s), int(m * s)
    agree = textured = 0
    for y in range(y0, y0 + int(h * s) - t + 1, t):
        for x in range(x0, x0 + int(w * s) - t + 1, t):
            pa, pb = va[y:y + t, x:x + t].ravel(), wb[y:y + t, x:x + t].ravel()
            if np.isnan(pb).any():
                continue
            ta, tb = pa.std() >= 0.5, pb.std() >= 0.5
            if not (ta or tb):
                continue
            textured += 1  # textured in either: art in one and plain in the other disagrees (a shared layout's strip
            # agrees, the games' art doesn't: counting only tiles textured in both let different games link)
            agree += bool(ta and tb and float(np.corrcoef(pa, pb)[0, 1]) > TILE_CORRELATION)
    return (agree / textured if textured else 0.0), textured


# Stage 2's drawn views are cached in <generated>/solve/view-cache/, one file per label photo, named by what the view
# depends on (view_name): a label photo is drawn again only when its photo, fit or shape or the drawing changes. A
# photo that can't be loaded gets no file (drawn again next run). Files of views no longer wanted are removed after
# each run. The link workers load the views from these files, each keeping the latest in memory: forking workers that
# share them deadlocked on the full set (macOS: a fork after other pools and OpenCV's threads can leave the children
# waiting on a lock forever).
_VIEW_FILES = {}  # key -> its view's file (the link workers')
_VIEWS = {}


def view_version():
    """A fingerprint of the drawing (compare_view and its settings)."""
    import hashlib, inspect
    h = hashlib.sha1(inspect.getsource(compare_view).encode())
    h.update(repr((COMPARE_PX_PER_MM, COMPARE_MARGIN, shapes.LABEL_MM)).encode())
    return h.hexdigest()[:16]


def view_name(key, path, cut_to_photo, shape, version):
    """A view's cache file name: its key (readable) and a hash of its photo file (size, time), fit, shape and version."""
    import hashlib
    st = os.stat(path) if path and os.path.exists(path) else None
    h = hashlib.sha1(repr((key, path, (st.st_size, st.st_mtime_ns) if st else None, shape, version)).encode())
    h.update(np.ascontiguousarray(cut_to_photo, dtype=np.float64).tobytes())
    return key.replace("@", "_").replace(",", "_").replace("/", "_") + "-" + h.hexdigest()[:16] + ".npy"


def view_job(job):
    """Draws one label photo's view into its cache file (written whole, then renamed: a stopped run leaves no half
    file). True if drawn."""
    k, path, cut, shape, file = job
    img = photos.load(path) if path else None
    if img is None:
        return k, False
    tmp = file[:-4] + f".{os.getpid()}.tmp.npy"
    np.save(tmp, compare_view(img, cut, shape))
    os.replace(tmp, file)
    return k, True


def init_link_worker(view_files):
    global _VIEW_FILES
    _VIEW_FILES = view_files


def load_view(file):
    return np.load(file) if file and os.path.exists(file) else None


def get_view(key):
    if key not in _VIEWS:
        if len(_VIEWS) > 3000:
            _VIEWS.clear()
        _VIEWS[key] = load_view(_VIEW_FILES.get(key))
    return _VIEWS[key]


class CachedViews:
    """The views by key, loaded from their cache files when asked for (all of them in memory would be gigabytes)."""
    def __init__(self, files):
        self.files = files
        self.recent = {}  # the latest loaded (a family's members are asked for several times in a row)

    def get(self, key, default=None):
        if key not in self.recent:
            if len(self.recent) > 500:
                self.recent.clear()
            self.recent[key] = load_view(self.files.get(key))
        v = self.recent[key]
        return default if v is None else v

    def __getitem__(self, key):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __contains__(self, key):
        return self.get(key) is not None


def judge_link(job):
    """(index, fit leftover mm, turn, shift, pixel share, textured tiles) of one link candidate."""
    i, a, b, ma, mb, shape = job
    va, vb = get_view(a), get_view(b)
    theta, t = rigid_fit(mb, ma)  # b's frame -> a's
    th = np.radians(theta)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    leftover = float(np.median(np.linalg.norm(mb @ R.T + t - ma, axis=1)))
    share, textured = pixel_agreement(va, vb, theta, t, shape) if va is not None and vb is not None else (0.0, 0)
    return i, leftover, theta, t, share, textured


_GEN_DIR = None  # set by solve(): where stage 2 keeps its drawn views


def stage2(lps, fits, candidates, photo_paths, workers=8):
    """Offsets (sticker's cut -> ink) per family; families; poor fits; the links judged."""
    shape_of = {lp["key"]: lp["shape"] for lp in lps}
    photo_of = {lp["key"]: lp["photo"] for lp in lps}
    cache_dir = os.path.join(_GEN_DIR or "generated", "solve", "view-cache")
    os.makedirs(cache_dir, exist_ok=True)
    version = view_version()
    view_files = {k: os.path.join(cache_dir, view_name(k, photo_paths.get(photo_of[k]), f["cut_to_photo"], shape_of[k], version))
                  for k, f in fits.items()}
    jobs_v = [(k, photo_paths.get(photo_of[k]), f["cut_to_photo"], shape_of[k], view_files[k])
              for k, f in fits.items() if not os.path.exists(view_files[k])]
    print(f"stage 2: {len(fits) - len(jobs_v)} of {len(fits)} label photos' views cached", flush=True)
    with Pool(workers) as pool:
        for n, _ in enumerate(pool.imap_unordered(view_job, jobs_v, chunksize=4), 1):
            if n % 200 == 0 or n == len(jobs_v):
                print(f"stage 2: drew {n} of {len(jobs_v)} label photos for the pixel comparison", flush=True)
    wanted = {os.path.basename(f) for f in view_files.values()}
    for f in os.listdir(cache_dir):  # views of fits, photos or drawings no longer wanted; half files of a stopped run
        if f not in wanted:
            os.remove(os.path.join(cache_dir, f))
    views = CachedViews(view_files)
    jobs = []
    for i, (a, b, pa, pb) in enumerate(candidates):
        if a in fits and b in fits and shape_of[a] == shape_of[b]:
            ma = project(np.linalg.inv(fits[a]["cut_to_photo"]), pa)
            mb = project(np.linalg.inv(fits[b]["cut_to_photo"]), pb)
            jobs.append((i, a, b, ma, mb, shape_of[a]))
    judged = {}
    with Pool(workers, initializer=init_link_worker, initargs=(view_files,)) as pool:
        for n, (i, leftover, theta, t, share, textured) in enumerate(pool.imap_unordered(judge_link, jobs, chunksize=8), 1):
            judged[i] = (leftover, theta, t, share, textured)
            if n % 2000 == 0 or n == len(jobs):
                print(f"stage 2: compared {n} of {len(jobs)} link candidates", flush=True)
    label_tiles = {sh: int(w // COMPARE_TILE_MM) * int(h // COMPARE_TILE_MM) for sh, (w, h) in shapes.LABEL_MM.items()}
    shape_of_link = {i: shape_of[candidates[i][0]] for i in judged}
    pixel_ok = lambda i, j: (j[3] >= AGREE_SHARE and j[4] >= max(MIN_TEXTURED_TILES, MIN_COVERAGE * label_tiles[shape_of_link[i]])
                             and abs(j[1]) <= MAX_TURN and np.hypot(*j[2]) <= MAX_SHIFT)
    # poor fits: most of a label photo's pixel-agreeing links fail the fit test
    tally = {}
    for i, j in judged.items():
        if pixel_ok(i, j):
            a, b = candidates[i][0], candidates[i][1]
            for k in (a, b):
                tally.setdefault(k, [0, 0])[0 if j[0] <= LINK_FIT_MM else 1] += 1
    poor = {k for k, (good, bad) in tally.items() if bad >= 2 and bad > good}
    links = [(candidates[i][0], candidates[i][1], j) for i, j in judged.items()
             if pixel_ok(i, j) and j[0] <= LINK_FIT_MM and candidates[i][0] not in poor and candidates[i][1] not in poor]
    # families
    parent = {k: k for k in fits}
    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b, _ in links:
        parent[root(a)] = root(b)
    families = {}
    for k in fits:
        families.setdefault(root(k), []).append(k)
    print(f"stage 2: {len(links)} links count, {len(poor)} poor fits; fitting the offsets of {len(families)} families", flush=True)
    offsets, residual = {}, {}
    for members in families.values():
        idx = {k: n for n, k in enumerate(members)}
        fam_links = [(idx[a], idx[b], j) for a, b, j in links if a in idx]
        x = np.zeros((len(members), 3))
        if fam_links:
            weights = np.ones(len(fam_links))
            for _ in range(6):  # least squares, Tukey reweighting: o_b - o_a = the link's (turn, shift)
                rows, rhs, ws = [], [], []
                for (ia, ib, j), w in zip(fam_links, weights):
                    theta, t = np.radians(j[1]), j[2]
                    for c, v in ((0, theta), (1, t[0]), (2, t[1])):
                        r = np.zeros(3 * len(members)); r[3 * ib + c] = 1; r[3 * ia + c] = -1
                        rows.append(r * np.sqrt(w)); rhs.append(v * np.sqrt(w))
                for n in range(len(members)):  # the gauge, weakly
                    for c in range(3):
                        r = np.zeros(3 * len(members)); r[3 * n + c] = 1e-3
                        rows.append(r); rhs.append(0.0)
                x = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)[0].reshape(-1, 3)
                res = np.array([np.hypot(*(x[ib, 1:] - x[ia, 1:] - j[2])) + 20 * abs(x[ib, 0] - x[ia, 0] - np.radians(j[1]))
                                for ia, ib, j in fam_links])  # mm; a turn's effect across about 20 mm
                u = res / TUKEY_MM
                weights = np.where(u < 1, (1 - u ** 2) ** 2, 0.0) + 1e-6
            x -= np.median(x, 0)
            for (ia, ib, j), w in zip(fam_links, weights):
                pass
        for k, n in idx.items():
            offsets[k] = x[n]
    fam_of = {k: (min(m), len(m)) for m in families.values() for k in m}
    corrections = {}
    release_of = {lp["key"]: next((t["release"] for t in lp["strings"] if t.get("release")), None) for lp in lps}
    all_groups = []
    to_refine = sum(1 for m in families.values() if len(m) >= 2)
    print(f"stage 2: refining the label photos of {to_refine} families by their pixels", flush=True)
    for n_fam, members in enumerate((m for m in families.values() if len(m) >= 2), 1):
        if n_fam % 100 == 0 or n_fam == to_refine:
            print(f"stage 2: refining family {n_fam} of {to_refine}", flush=True)
        # refined per release within the family (a family can hold a series' games sharing a layout: aligning them to
        # one median pulls them apart); label photos without a serial with the family's largest release group
        by_release = {}
        for k in members:
            if release_of.get(k):
                by_release.setdefault(release_of[k], []).append(k)
        largest = max(by_release.values(), key=len) if by_release else members
        for k in members:
            if not release_of.get(k) and largest is not members:
                largest.append(k)
        groups = [g for g in (by_release.values() if by_release else [members])]
        all_groups += groups
        for group in groups:
            if len(group) >= 2:
                c, bad = refine_family(group, views, offsets, shape_of[group[0]])
                corrections.update(c)
                poor |= bad
        if len(groups) > 1:  # the release groups aligned to each other on the tiles they share
            align_groups(groups, views, offsets, corrections, shape_of[members[0]])
    info = {"link candidates": len(candidates), "judged": len(judged),
            "pixels agree": int(sum(pixel_ok(i, j) for i, j in judged.items())),
            "counting links": len(links), "poor fits": len(poor),
            "families": sorted((len(m) for m in families.values()), reverse=True)[:10],
            "refined": len(corrections),
            "correction_mm": {"median": round(float(np.median([v[1] for v in corrections.values()])), 3) if corrections else None,
                              "90 %": round(float(np.percentile([v[1] for v in corrections.values()], 90)), 3) if corrections else None}}
    return offsets, fam_of, poor, info, corrections, all_groups


# Refinement by pixels: within a family (per release: a series' games share a family), each label photo's view (stage 2's, carried into ink coordinates by its
# offset) is aligned to the family's median view by a homography (ECC), twice, the reference rebuilt in between: it
# corrects what the outline fit got wrong in perspective (DMG-A7CJ-JPN (3): a corner about 1 mm off split its family).
# A correction moving the label's corners over MAX_CORRECTION_MM isn't applied: that label photo is a poor fit.
MAX_CORRECTION_MM = 2.0
REFINE_ROUNDS = 2


def mm_to_view_px():
    s, m = COMPARE_PX_PER_MM, COMPARE_MARGIN
    return np.array([[s, 0, m * s], [0, s, m * s], [0, 0, 1.0]])


def ink_view(view, offset):
    """A sticker-frame view (compare_view) carried into ink coordinates by the label photo's offset."""
    S = mm_to_view_px()
    M = S @ offset_matrix(offset) @ np.linalg.inv(S)  # sticker px -> ink px
    return cv2.warpPerspective(view, M, (view.shape[1], view.shape[0]), flags=cv2.INTER_LINEAR, borderValue=np.nan)


def corrected_view(k, views, offsets, corrections):
    """A label photo's view in its corrected ink coordinates (NaN outside)."""
    S = mm_to_view_px()
    v = ink_view(views[k], offsets[k])
    C = corrections.get(k, (np.eye(3), 0))[0]
    M = S @ C @ np.linalg.inv(S)  # ink px -> corrected ink px
    return cv2.warpPerspective(v, M, (v.shape[1], v.shape[0]), flags=cv2.INTER_LINEAR, borderValue=np.nan)


def align_groups(groups, views, offsets, corrections, shape):
    """Aligns a family's release groups to its largest by the pixels of the tiles they share (their median views
    correlating over TILE_CORRELATION in COMPARE_TILE_MM tiles): nearly-same prints of different releases (Fire Red,
    Leaf Green) refined per release were never aligned to each other. The alignment is composed onto the members'
    corrections."""
    S = mm_to_view_px()
    corners = corners_mm(shape)
    import warnings
    medians = []
    for g in groups:
        vs = [corrected_view(k, views, offsets, corrections) for k in g if views.get(k) is not None]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            medians.append(np.nanmedian(np.stack(vs), 0) if vs else None)
    main = max(range(len(groups)), key=lambda i: len(groups[i]))
    ref = medians[main]
    t = int(COMPARE_TILE_MM * COMPARE_PX_PER_MM)
    blur = lambda v: cv2.GaussianBlur(np.nan_to_num(v).astype(np.float32), (0, 0), COMPARE_PX_PER_MM * 0.4)
    for i, (g, med) in enumerate(zip(groups, medians)):
        if i == main or med is None or ref is None:
            continue
        # a coarse shift first (phase correlation), then the shared tiles found on blurred views, aligned on sharp ones
        (sx, sy), _ = cv2.phaseCorrelate(np.nan_to_num(ref).astype(np.float64), np.nan_to_num(med).astype(np.float64))
        if np.hypot(sx, sy) > MAX_CORRECTION_MM * COMPARE_PX_PER_MM:
            sx = sy = 0.0
        T = np.array([[1, 0, sx], [0, 1, sy], [0, 0, 1]], np.float32)  # ref px -> med px
        med_on_ref = cv2.warpPerspective(med, T, (med.shape[1], med.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=np.nan)
        rb, mb = blur(ref), blur(med_on_ref)
        mask = np.zeros(ref.shape, np.uint8)
        for y in range(0, ref.shape[0] - t + 1, t):
            for x in range(0, ref.shape[1] - t + 1, t):
                if not (np.isfinite(ref[y:y + t, x:x + t]).all() and np.isfinite(med_on_ref[y:y + t, x:x + t]).all()):
                    continue
                a, b = rb[y:y + t, x:x + t].ravel(), mb[y:y + t, x:x + t].ravel()
                if a.std() >= 0.2 and b.std() >= 0.2 and np.corrcoef(a, b)[0, 1] > TILE_CORRELATION:
                    mask[y:y + t, x:x + t] = 1
        if mask.mean() < 0.05:
            continue
        W = T.copy()
        try:
            _, W = cv2.findTransformECC(np.nan_to_num(ref).astype(np.float32), np.nan_to_num(med).astype(np.float32), W,
                                        cv2.MOTION_HOMOGRAPHY, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5), mask, 3)
        except cv2.error:
            continue
        G = np.linalg.inv(np.linalg.inv(S) @ W.astype(np.float64) @ S)  # the group's corrected mm -> the main group's
        if np.max(np.linalg.norm(project(G, corners) - corners, axis=1)) > MAX_CORRECTION_MM:
            continue
        for k in g:
            C, _ = corrections.get(k, (np.eye(3), 0))
            C2 = G @ C
            moved = float(np.max(np.linalg.norm(project(C2, corners) - corners, axis=1)))
            corrections[k] = (C2 / C2[2, 2], moved)


def refine_family(members, views, offsets, shape):
    """{key: (correction: ink mm -> corrected ink mm, how far it moves the label's corners, mm)} for a family's label
    photos, and those whose correction would be too large."""
    S = mm_to_view_px()
    corners = corners_mm(shape)
    inks = {k: ink_view(views[k], offsets[k]) for k in members if views.get(k) is not None}
    W = {k: np.eye(3, dtype=np.float32) for k in inks}  # ref px -> member px
    for _ in range(REFINE_ROUNDS):
        warped = []
        for k, v in inks.items():
            warped.append(cv2.warpPerspective(v, W[k], (v.shape[1], v.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=np.nan))
        with np.errstate(all="ignore"):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)  # the margin is outside every view
                ref = np.nanmedian(np.stack(warped), 0)
        mask = np.isfinite(ref).astype(np.uint8)
        ref = np.nan_to_num(ref).astype(np.float32)
        for k, v in inks.items():
            try:
                _, W[k] = cv2.findTransformECC(ref, np.nan_to_num(v).astype(np.float32), W[k], cv2.MOTION_HOMOGRAPHY,
                                               (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5), mask, 3)
            except cv2.error:
                pass
    out, bad = {}, set()
    for k in inks:
        Wmm = np.linalg.inv(S) @ W[k].astype(np.float64) @ S  # ref mm -> member mm
        C = np.linalg.inv(Wmm)                               # member ink mm -> corrected (the reference's)
        moved = float(np.max(np.linalg.norm(project(C, corners) - corners, axis=1)))
        if moved > MAX_CORRECTION_MM:
            bad.add(k)
        else:
            out[k] = (C / C[2, 2], moved)
    return out, bad


# Fine refinement, at full resolution: refine_family aligns at COMPARE_PX_PER_MM (5 px/mm, chosen for the link tests'
# speed), which left label photos of one print up to about 0.3 mm apart in places (1e37930852 against 837abc2b9c: the
# bottom left 0.27 mm off), enough for prints' comparison to see differences that aren't there or miss ones that are.
# Each refinement group (as refine_family's) is drawn at straighten's resolution (FINE_PX_PER_MM) in its current ink
# coordinates, lighting evened (minus the local mean over the local spread, 0.5 mm), and each label photo aligned to
# the group's median by a homography (ECC), FINE_ROUNDS times. A fine correction moving the label's corners over
# MAX_FINE_MM isn't applied (the coarse one stands).
FINE_PX_PER_MM = 20
FINE_MARGIN = 2.0
FINE_ROUNDS = 2
MAX_FINE_MM = 1.0


def fine_view(photo, photo_to_ink, shape):
    """The label photo in ink coordinates at FINE_PX_PER_MM (FINE_MARGIN around), gray, lighting evened, NaN outside."""
    w, h = shapes.LABEL_MM[shape]
    P, m = FINE_PX_PER_MM, FINE_MARGIN
    W, Hh = int((w + 2 * m) * P), int((h + 2 * m) * P)
    px_to_mm = np.array([[1 / P, 0, -m], [0, 1 / P, -m], [0, 0, 1.0]])
    g = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY).astype(np.float32)
    M = np.linalg.inv(np.float64(photo_to_ink)) @ px_to_mm
    v = cv2.warpPerspective(g, M, (W, Hh), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=-1)
    valid = cv2.warpPerspective(np.ones_like(g), M, (W, Hh), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0) > 0
    mean = cv2.GaussianBlur(v, (0, 0), P / 2)
    spread = np.sqrt(cv2.GaussianBlur((v - mean) ** 2, (0, 0), P / 2)) + 2.0
    return np.where(valid, (v - mean) / spread, np.nan).astype(np.float32)


def fine_group(job):
    """{key: (correction: ink mm -> corrected ink mm, how far it moves the label's corners)} for one group, aligned at
    full resolution (keys whose correction is too large left out)."""
    import warnings
    keys, paths, to_inks, shape = job
    views = {}
    for k, path, H in zip(keys, paths, to_inks):
        img = photos.load(path) if path else None
        if img is not None:
            views[k] = fine_view(img, H, shape)
    if len(views) < 2:
        return {}
    P, m = FINE_PX_PER_MM, FINE_MARGIN
    S = np.array([[P, 0, m * P], [0, P, m * P], [0, 0, 1.0]])  # ink mm -> view px
    corners = corners_mm(shape)
    W = {k: np.eye(3, dtype=np.float32) for k in views}  # ref px -> member px
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5)
    for _ in range(FINE_ROUNDS):
        warped = [cv2.warpPerspective(v, W[k], (v.shape[1], v.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=np.nan)
                  for k, v in views.items()]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ref = np.nanmedian(np.stack(warped), 0)
        mask = np.isfinite(ref).astype(np.uint8)
        ref = np.nan_to_num(ref).astype(np.float32)
        for k, v in views.items():
            try:
                _, W[k] = cv2.findTransformECC(ref, np.nan_to_num(v).astype(np.float32), W[k], cv2.MOTION_HOMOGRAPHY, crit, mask, 5)
            except cv2.error:
                pass
    out = {}
    for k in views:
        C = np.linalg.inv(np.linalg.inv(S) @ W[k].astype(np.float64) @ S)  # member ink mm -> the reference's
        moved = float(np.max(np.linalg.norm(project(C, corners) - corners, axis=1)))
        if moved <= MAX_FINE_MM:
            out[k] = (C / C[2, 2], moved)
    return out


def refine_fine(groups, photo_to_ink, paths, shape_of, workers=8):
    """Fine corrections for every refinement group of two or more label photos (fine_group), in parallel."""
    jobs = [(g, [paths.get(k) for k in g], [photo_to_ink[k] for k in g], shape_of[g[0]]) for g in groups if len(g) >= 2]
    out = {}
    with Pool(workers) as pool:
        for n, c in enumerate(pool.imap_unordered(fine_group, jobs), 1):
            out.update(c)
            if n % 100 == 0 or n == len(jobs):
                print(f"fine refinement: {n} of {len(jobs)} groups", flush=True)
    return out


def apply_offset(o, pts):
    th, dx, dy = o
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    return pts @ R.T + [dx, dy]


def offset_matrix(o):
    th, dx, dy = o
    return np.array([[np.cos(th), -np.sin(th), dx], [np.sin(th), np.cos(th), dy], [0, 0, 1]])


def frozen_fit(r):
    """A frozen or stored label photo's record in solve.json as stage 1's fit."""
    return {"cut_to_photo": np.float64(r["cut_to_photo"]), "plastic_to_photo": np.float64(r["plastic_to_photo"]),
            "width_mm": r.get("width_mm"), "height_mm": r.get("height_mm"), "placement": r["placement"],
            "start": r["start"], "support": r["support"], "error_mm": r["error_mm"], "candidates": r["candidates"],
            "probability": r["probability"], "round1_same": not r.get("changed_by_choice"), "edge": r.get("edge")}


def anchor_to_frozen(out, frozen_records):
    """Each family holding frozen label photos: its ink frame moved onto theirs (the frozen poses are in the frame their
    family had when frozen), the others' photo_to_ink with it; the frozen ones' records as frozen."""
    by_family = {}
    for k, r in out.items():
        by_family.setdefault(r["family"], []).append(k)
    for members in by_family.values():
        fz = [k for k in members if k in frozen_records]
        if not fz:
            continue
        shape = out[fz[0]]["shape"]
        c = corners_mm(shape)
        # where the frozen poses put the family's ink corners: each frozen one's (frozen ink <- this run's ink), averaged
        moved = np.mean([project(np.float64(frozen_records[k]["photo_to_ink"]) @ np.linalg.inv(np.float64(out[k]["photo_to_ink"])), c)
                         for k in fz], 0)
        M = cv2.getPerspectiveTransform(np.float32(c), np.float32(moved)).astype(np.float64)
        for k in members:
            if k in frozen_records:
                continue
            H = M @ np.float64(out[k]["photo_to_ink"])
            out[k]["photo_to_ink"] = (H / H[2, 2]).tolist()
        for k in fz:
            fam, size = out[k]["family"], out[k]["family_size"]
            out[k] = {**{f: v for f, v in frozen_records[k].items() if f != "found"}, "family": fam, "family_size": size,
                      "frozen": frozen_records[k]["frozen"]}


def from_frozen_match(out, lps, failed, photo_paths, frozen_entries):
    """A label photo find tagged with a match to a frozen print's image ("frozen_match": its photo's pixels -> the
    image's) and with no good pose of its own (unsolved, or an approximate cut alone in its family): its pose from that
    match (the image is in the frozen ink frame: straighten's pixels, cropped), where its pixels then agree with the
    image's as stage 2 requires of a link; it joins the family of the print's frozen label photos, as an approximate
    cut (its own cut is found by straighten)."""
    import straighten
    done = 0
    for lp in lps:
        k, P = lp["key"], lp.get("frozen_print")
        if P is None or P not in frozen_entries or (k in out and (out[k].get("frozen") or not (
                approximate_cut(out[k]) and out[k]["family_size"] <= 1))):
            continue
        e, shape = frozen_entries[P], lp["shape"] or frozen_entries[P]["shape"]
        img_to_ink = straighten.canvas(shape)[1] @ np.array([[1.0, 0, e["crop"]["x"]], [0, 1.0, e["crop"]["y"]], [0, 0, 1.0]])
        ink = img_to_ink @ np.float64(lp["frozen_match"])
        cut = np.linalg.inv(ink)
        cut /= cut[2, 2]
        path, image = photo_paths.get(lp["photo"]), cv2.imread(frozen.image_path(P))
        photo = photos.load(path) if path else None
        if photo is None or image is None or not usable(cut, shape):
            continue
        img_cut = np.linalg.inv(img_to_ink)
        w, h = shapes.LABEL_MM[shape]
        need = max(MIN_TEXTURED_TILES, MIN_COVERAGE * int(w // COMPARE_TILE_MM) * int(h // COMPARE_TILE_MM))
        share, textured = pixel_agreement(compare_view(photo, cut, shape), compare_view(image, img_cut, shape), 0.0, np.zeros(2), shape)
        if share < AGREE_SHARE or textured < need:
            continue
        mates = [m for m, r in out.items() if r.get("frozen") == P]
        fam = out[mates[0]]["family"] if mates else k
        mate = out[mates[0]] if mates else next(iter(e["label_photos"].values()))
        plastic = cut @ np.float64(mate["photo_to_ink"]) @ np.float64(mate["plastic_to_photo"])
        base = out.get(k) or {"photo": lp["photo"], "shape": shape, "start": "frozen print match", "support": {},
                              "error_mm": 0.0, "candidates": 0, "probability": None, "changed_by_choice": False,
                              "correction_mm": None, "fine_correction_mm": None, "merged": []}
        out[k] = {**base, "photo_to_ink": (ink / ink[2, 2]).tolist(), "cut_to_photo": cut.tolist(),
                  "plastic_to_photo": (plastic / plastic[2, 2]).tolist(), "width_mm": mate.get("width_mm"),
                  "height_mm": mate.get("height_mm"), "offset": [0.0, 0.0, 0.0], "placement": mate["placement"],
                  "family": fam, "edge": {"label_used": False, "recess_used": False},
                  "fallback": f"approximate cut: pose from a match to frozen print {P}",
                  "frozen_match": {"print": P, "pixels_agree": round(share, 3)}}
        failed.pop(k, None)
        done += 1
    sizes = {}
    for r in out.values():
        sizes[r["family"]] = sizes.get(r["family"], 0) + 1
    for r in out.values():
        r["family_size"] = sizes[r["family"]]
    print(f"frozen prints: {done} label photos posed from a match to a frozen print's image", flush=True)
    return done


def solve(found, matches, edges_dir, photo_paths=None, frozen_records=None, frozen_entries=None, stored_records=None):
    lps = found["label_photos"]
    keys = [lp["key"] for lp in lps]
    if len(set(keys)) < len(keys):  # find makes keys unique (find.unique_keys); two alike would both be merged away
        seen = set()
        twice = sorted({k for k in keys if k in seen or seen.add(k)})
        sys.exit(f"{len(twice)} keys found twice in find's output (like {twice[0]}): run make find again")
    for lp in lps:
        lp["centre"] = np.float64(lp["centre"])
    global _GEN_DIR
    _GEN_DIR = os.path.dirname(edges_dir)
    present = {lp["key"] for lp in lps}
    frozen_records = {k: r for k, r in (frozen_records or {}).items() if k in present}
    stored_records = {k: r for k, r in (stored_records or {}).items() if k in present and k not in frozen_records}
    fitting = [lp for lp in lps if lp["key"] not in frozen_records and lp["key"] not in stored_records]
    print(f"stage 1: {len(stored_records)} label photos start from their stored poses, {len(frozen_records)} frozen", flush=True)
    fits, failed, choice = stage1(shape_variants(fitting), edges_dir, None)
    shapes_chosen = choose_shapes(fitting, fits, failed)
    strings_off = drop_strings_off_label(fitting, fits)
    fits = stage1_edges(fitting, fits, photo_paths or {})
    fits.update({k: frozen_fit(r) for k, r in stored_records.items()})
    strings_off += drop_strings_off_label([lp for lp in lps if lp["key"] in stored_records], fits)
    fits.update({k: frozen_fit(r) for k, r in frozen_records.items()})
    merged = merge_fitted(lps, fits)
    candidates = link_candidates(lps, matches, merged)
    lps = [lp for lp in lps if lp["key"] not in merged]
    fits = {k: f for k, f in fits.items() if k not in merged}
    merged_into = {}
    for d, k in merged.items():
        merged_into.setdefault(k, []).append(d)
    offsets, family_of, poor, links_info, corrections, groups = stage2(lps, fits, candidates, photo_paths or {})
    poor -= set(frozen_records)  # a frozen label photo is never a poor fit
    links_info["shapes chosen by the fit"] = shapes_chosen
    links_info["strings off the label, dropped"] = strings_off
    coarse = {}
    for k, f in fits.items():
        C, _ = corrections.get(k, (np.eye(3), None))
        coarse[k] = C @ offset_matrix(offsets.get(k, np.zeros(3))) @ np.linalg.inv(f["cut_to_photo"])
    photo_of = {lp["key"]: lp["photo"] for lp in lps}
    paths = {k: (photo_paths or {}).get(photo_of[k]) for k in fits}
    shape_of = {lp["key"]: lp["shape"] for lp in lps}
    fine = refine_fine([[k for k in g if k not in poor and k in fits] for g in groups], coarse, paths, shape_of)
    if fine:
        links_info["fine refined"] = len(fine)
        links_info["fine correction_mm"] = {"median": round(float(np.median([v[1] for v in fine.values()])), 3),
                                            "90 %": round(float(np.percentile([v[1] for v in fine.values()], 90)), 3)}
    out = {}
    for lp in lps:
        k = lp["key"]
        if k not in fits:
            continue
        f = fits[k]
        o = offsets.get(k, np.zeros(3))
        C, moved = corrections.get(k, (np.eye(3), None))
        Cf, fine_moved = fine.get(k, (np.eye(3), None))
        photo_to_ink = Cf @ C @ offset_matrix(o) @ np.linalg.inv(f["cut_to_photo"])
        out[k] = {"photo": lp["photo"], "shape": lp["shape"], "photo_to_ink": (photo_to_ink / photo_to_ink[2, 2]).tolist(),
                  "cut_to_photo": (f["cut_to_photo"] / f["cut_to_photo"][2, 2]).tolist(),
                  "width_mm": round(float(f.get("width_mm", shapes.LABEL_MM[lp["shape"]][0])), 3),
                  "height_mm": round(float(f.get("height_mm", shapes.LABEL_MM[lp["shape"]][1])), 3),
                  "offset": [round(float(o[1]), 3), round(float(o[2]), 3), round(float(np.degrees(o[0])), 3)],
                  "plastic_to_photo": f["plastic_to_photo"].tolist(),
                  "placement": [round(v, 3) for v in f["placement"]],
                  "start": f["start"], "support": f["support"], "error_mm": round(f["error_mm"], 3),
                  "candidates": f["candidates"], "probability": f["probability"] and round(f["probability"], 3),
                  "changed_by_choice": not f["round1_same"],
                  "fallback": "a poor fit: its links disagree" if k in poor else
                              "approximate cut: the label edges could not be precisely located" if f.get("edge") and not f["edge"]["label_used"] else
                              ("found by the pose search" if f["start"].startswith("search") else None),
                  "family": family_of[k][0], "family_size": family_of[k][1],
                  "correction_mm": None if moved is None else round(moved, 3),
                  "fine_correction_mm": None if fine_moved is None else round(fine_moved, 3),
                  "edge": f.get("edge"), "merged": sorted(merged_into.get(k, []))}
    anchor_to_frozen(out, frozen_records)
    links_info["from frozen print matches"] = from_frozen_match(out, lps, failed, photo_paths or {}, frozen_entries or {})
    carry_alone(out, lps, matches, photo_paths or {}, links_info)
    print("writing solve.json and the page", flush=True)
    return {"label_photos": out, "links": links_info, "unsolved": failed, "choice": choice}


# Stage 3: an approximate cut alone in its family (its pose off, so its links failed the fit test: on the full set,
# 2026-11-13, the edge model had moved their recess a median 9.9 mm, 0.5 mm on precise fits) gets its pose carried from
# a precise label photo it matches: the match's inliers in both label photos' circles (MIN_LINK_POINTS or more), a
# homography refitted to them (RANSAC, CARRY_RANSAC_PX), the precise one's cut, recess and ink carried through it. Kept
# where the two label photos' pixels then agree as stage 2 requires of a link (AGREE_SHARE, MIN_COVERAGE); tried with
# the CARRY_MAX best-matched precise label photos, the first agreeing taken. It joins that one's family; it stays an
# approximate cut (its own cut is found by straighten; restore insets it). Measured before building (2026-11-13): of
# 1297 alone approximate cuts, 789 matched a precise label photo and 312 agreed (175 of the user's 289 OK-ed ones);
# where two or more precise label photos agreed, their carried poses' largest corner apart was a median 0.82 mm, 90 %
# 1.67 mm (the print's place on the sticker varies about 1 mm); the approximate cut had been a median 3.8 mm off.
# A precise fit alone in its family (the user, 2026-11-15: 77261d83's own fit 5.5 mm off, its only link failing the fit
# test because of it, and a hand-joined print restored with it) is carried the same way, from a precise label photo of
# a family of two or more, with two checks more, as its own fit is often right:
#   - the carried cut lies on it: find's centre of it inside the carried cut, or the carried cut overlapping its own by
#     ON_LABEL_OVERLAP of the smaller (a label photo found by its serial has its centre on the serial, near an edge);
#     a carry onto another label of the photo (the same print on another cartridge) fails both;
#   - the two read the same serial: a serial in both label photos' find strings (a nearly-same print, a region
#     variant, agrees in its pixels as stage 2 requires).
# Measured before building (2026-11-15, full set): of 2013 precise fits alone, 1507 matched a precise label photo of a
# linked family, 294 agreed in their pixels; 84 of those were carried over 2 mm, 61 passing both checks (60 by find's
# serials). The user judged samples: mostly right where both checks pass, refused ones mostly right to refuse. Tried
# and dropped: the precise fit refitted to its own edges from the carried pose (the refit was wrong in 7 of 9), and
# prints' tile comparison as the same-print check (it refused three same prints, at 4 to 24 differing tiles).
ON_LABEL_OVERLAP = 0.5
CARRY_MAX = 5
CARRY_RANSAC_PX = 3.0


def on_label(cut, shape, centre, own_cut):
    """Whether a carried cut lies on the label photo: find's centre inside it, or it overlapping the label photo's own
    cut by ON_LABEL_OVERLAP of the smaller."""
    q = project(cut, corners_mm(shape)).astype(np.float32)
    if cv2.pointPolygonTest(q, (float(centre[0]), float(centre[1])), False) >= 0:
        return True
    o = project(np.float64(own_cut), corners_mm(shape)).astype(np.float32)
    smaller = min(cv2.contourArea(q), cv2.contourArea(o))
    return smaller > 0 and cv2.intersectConvexConvex(q, o)[0] >= ON_LABEL_OVERLAP * smaller


def carry_job(job):
    """(key, carrier key, carried cut_to_photo, H a -> b, points, pixel share) for the first agreeing carrier, or (key, None, ...).
    With a precise fit's own cut and find's centre (job's 5th and 6th), the carried cut must lie on it (on_label)."""
    k, path, shape, tries = job[:4]
    own = job[4:] if len(job) > 4 else None
    img = photos.load(path) if path else None
    if img is None:
        return k, None, None, None, 0, 0.0
    w, h = shapes.LABEL_MM[shape]
    need = max(MIN_TEXTURED_TILES, MIN_COVERAGE * int(w // COMPARE_TILE_MM) * int(h // COMPARE_TILE_MM))
    for kb, path_b, cut_b, pa, pb in tries:
        H, mask = cv2.findHomography(np.float32(pa), np.float32(pb), cv2.RANSAC, CARRY_RANSAC_PX)
        if H is None or mask.sum() < MIN_LINK_POINTS:
            continue
        cut = np.linalg.inv(H) @ np.float64(cut_b)
        cut /= cut[2, 2]
        img_b = photos.load(path_b) if path_b else None
        if not usable(cut, shape) or img_b is None or (own and not on_label(cut, shape, own[1], own[0])):
            continue
        share, textured = pixel_agreement(compare_view(img, cut, shape), compare_view(img_b, cut_b, shape), 0.0, np.zeros(2), shape)
        if share >= AGREE_SHARE and textured >= need:
            return k, kb, cut, H, int(mask.sum()), share
    return k, None, None, None, 0, 0.0


def carry_alone(out, lps, matches, photo_paths, info, workers=8):
    """Stage 3 (above), in place on solve's records; family sizes recounted."""
    alone = {k for k, r in out.items() if approximate_cut(r) and r["family_size"] <= 1 and not poor_fit(r) and not r.get("frozen")}
    precise = {k for k, r in out.items() if not approximate_cut(r) and not poor_fit(r)}
    precise_alone = {k for k in precise if out[k]["family_size"] <= 1 and not out[k].get("frozen")}
    linked = {k for k in precise if out[k]["family_size"] >= 2}
    alone |= precise_alone
    lp_of = {lp["key"]: lp for lp in lps}
    serials_of = lambda k: {s["serial"] for s in lp_of.get(k, {}).get("strings") or [] if s.get("serial")}
    by_photo = {}
    for k in alone | precise:
        by_photo.setdefault(out[k]["photo"], []).append(k)
    inside = lambda pts, lp: np.hypot(*(pts - lp["centre"]).T) < lp["radius"]
    tries = {}
    for a, b, _, inl in matches:
        for pa_all, pb_all, x, y in ((inl[:, :2], inl[:, 2:], a, b), (inl[:, 2:], inl[:, :2], b, a)):
            for ka in by_photo.get(x, []):
                if ka not in alone:
                    continue
                ia = inside(pa_all, lp_of[ka])
                for kb in by_photo.get(y, []):
                    if kb in precise and out[kb]["shape"] == out[ka]["shape"] and (
                            ka not in precise_alone or (kb in linked and serials_of(ka) & serials_of(kb))):
                        m = ia & inside(pb_all, lp_of[kb])
                        if m.sum() >= MIN_LINK_POINTS:
                            tries.setdefault(ka, []).append((int(m.sum()), kb, pa_all[m], pb_all[m]))
    jobs = [(k, photo_paths.get(out[k]["photo"]), out[k]["shape"],
             [(kb, photo_paths.get(out[kb]["photo"]), np.float64(out[kb]["cut_to_photo"]), pa, pb)
              for _, kb, pa, pb in sorted(t, key=lambda c: -c[0])[:CARRY_MAX]])
            + ((np.float64(out[k]["cut_to_photo"]), np.float64(lp_of[k]["centre"])) if k in precise_alone else ())
            for k, t in tries.items()]
    n_precise = sum(1 for j in jobs if j[0] in precise_alone)
    print(f"stage 3: {len(alone) - len(precise_alone)} approximate cuts and {len(precise_alone)} precise fits alone, "
          f"{len(jobs) - n_precise} and {n_precise} matching a precise label photo; carrying", flush=True)
    carried = carried_precise = 0
    with Pool(workers) as pool:
        for n, (k, kb, cut, H, points, share) in enumerate(pool.imap_unordered(carry_job, jobs, chunksize=2), 1):
            if n % 200 == 0 or n == len(jobs):
                print(f"stage 3: tried {n} of {len(jobs)}", flush=True)
            if kb is None:
                continue
            r, rb = out[k], out[kb]
            Hinv = np.linalg.inv(H)
            ink = np.float64(rb["photo_to_ink"]) @ H
            plastic = Hinv @ np.float64(rb["plastic_to_photo"])
            r.update({"photo_to_ink": (ink / ink[2, 2]).tolist(), "cut_to_photo": cut.tolist(),
                      "plastic_to_photo": (plastic / plastic[2, 2]).tolist(),
                      "width_mm": rb["width_mm"], "height_mm": rb["height_mm"], "offset": rb["offset"], "placement": rb["placement"],
                      "family": rb["family"], "carried": {"from": kb, "points": points, "pixels_agree": round(share, 3)},
                      "fallback": (f"precise fit alone: pose carried from {kb} through a match" if k in precise_alone else
                                   f"approximate cut: pose carried from {kb} through a match")})
            carried += 1
            carried_precise += k in precise_alone
    sizes = {}
    for r in out.values():
        sizes[r["family"]] = sizes.get(r["family"], 0) + 1
    for r in out.values():
        r["family_size"] = sizes[r["family"]]
    info["carried"] = {"alone approximate cuts": len(alone) - len(precise_alone), "alone precise fits": len(precise_alone),
                       "matching a precise one": len(jobs) - n_precise, "precise matching a linked one, same serial": n_precise,
                       "carried": carried - carried_precise, "precise carried": carried_precise}
    print(f"stage 3: {carried} carried into a precise label photo's family ({carried_precise} of them precise fits)", flush=True)


def edge_caption(e):
    if not e:
        return ""
    def part(p):  # a pose from a frozen print match has no edge fit: only "not used"
        if p + "_confidence" not in e:
            return f'{p} not fitted'
        return f'{p} {e[p + "_confidence"]:.2f} {"used" if e[p + "_used"] else "not used"}, moved {e[p + "_moved_mm"]} mm'
    return f'<br>edge models: {part("recess")}; {part("label")}'


def page(out_dir, chosen, result, sizes):
    lps = result["label_photos"]
    edges = [r["edge"] for r in lps.values() if r.get("edge")]
    edge_used = {p: sum(1 for e in edges if e[p + "_used"]) for p in ("recess", "label")}
    rel = os.path.relpath(".", out_dir)
    kinds = ["placed", "outline", "search"]
    group = lambda r: next((k for k in kinds if r["start"].startswith(k)), "search")
    by_kind = {k: sorted([(key, r) for key, r in lps.items() if group(r) == k], key=lambda kv: -kv[1]["support"].get("face", 0)) for k in kinds}

    def figure(key, r):
        s = r["photo"]; w, h = sizes[s]
        quad = project(r["cut_to_photo"], corners_mm(r["shape"]))
        pts = " ".join(f"{x:.0f},{y:.0f}" for x, y in quad)
        m = MODELS[r["shape"]]
        box = project(r["plastic_to_photo"], [[m["box"][0], m["box"][1]], [m["box"][2], m["box"][1]], [m["box"][2], m["box"][3]], [m["box"][0], m["box"][3]]])
        rec = project(r["plastic_to_photo"], [[m["recess"][0], m["recess"][1]], [m["recess"][2], m["recess"][1]], [m["recess"][2], m["recess"][3]], [m["recess"][0], m["recess"][3]]])
        extra = "".join(f'<polygon points="{" ".join(f"{x:.0f},{y:.0f}" for x, y in q)}" fill="none" stroke="{c}" stroke-width="{max(w, h) / 400:.1f}"/>' for q, c in ((box, "#08f"), (rec, "#fa0")))
        return (f'<figure><div class="ph"><img loading="lazy" src="{rel}/{chosen[s]}"><svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
                f'{extra}<polygon points="{pts}" fill="none" stroke="#0c0" stroke-width="{max(w, h) / 250:.1f}"/>'
                f'<circle cx="{quad[0][0]:.0f}" cy="{quad[0][1]:.0f}" r="{max(w, h) / 80:.0f}" fill="#f00"/></svg></div>'
                f'<figcaption><code>{html.escape(key[:14])}</code> {html.escape(r["start"][:30])}<br>support {r["support"]}, placement {r["placement"]}, size {r["width_mm"]} x {r.get("height_mm", "?")} mm, error {r["error_mm"]} mm, family of {r["family_size"]}{", " + r["fallback"] if r["fallback"] else ""}{edge_caption(r.get("edge"))}</figcaption></figure>')

    unsolved = "".join(f"<li><code>{html.escape(k[:16])}</code>: {html.escape(v)}</li>" for k, v in result["unsolved"].items())
    starts = {}
    for r in lps.values():
        kind = r["start"].split(" ")[0]
        starts[kind] = starts.get(kind, 0) + 1
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>solve</title>
<style>body{{font:14px system-ui;margin:16px}} figure{{display:inline-block;margin:6px;vertical-align:top;width:280px}}
.ph{{position:relative;display:inline-block}} .ph img{{max-width:280px;max-height:280px;display:block}} .ph svg{{position:absolute;inset:0;width:100%;height:100%}} figcaption{{font-size:11px}}</style>
<h1>solve</h1>
<p>{len(lps)} label photos solved (started: {", ".join(f"{k} {v}" for k, v in starts.items())}), {len(result["unsolved"])} not. Links: {html.escape(str(result["links"]))}.</p>
{steps.legend([("#08f", "the cartridge's outline"), ("#fa0", "the recess"), ("#0c0", "the label's cut (canonical size)"), ("#f00", "the label's top left")])}
<p>The edge models (an experiment) refined {len(edges)}: their recess used on {edge_used["recess"]}, their label on {edge_used["label"]} (confidence at least {edge_fit.ACCEPT}, the label within the fit's limits); the drawing shows the poses used.</p>
<p>Grouped by how the fit was started; within a group, most outline support first.</p>
<h2>Not solved ({len(result["unsolved"])})</h2><ul>{unsolved}</ul>
{"".join(f'<h2>Started from: {k} ({steps.shown(len(by_kind[k]))})</h2>' + "".join(figure(key, r) for key, r in steps.few(by_kind[k])) for k in kinds)}
""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()
    chosen = photos.chosen(args.sample)
    gen = photos.generated(args.sample)
    out_dir = os.path.join(gen, "solve")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "solve.json")
    found_file = os.path.join(gen, "find", "label-photos.json")
    inputs = [found_file] + [os.path.join(gen, d, s + e) for s in chosen for d, e in (("edges", ".npz"), ("match", ".npz"))]
    inputs += [frozen.FILE] if os.path.exists(frozen.FILE) else []
    missing = [p for p in inputs if not os.path.exists(p)]
    if missing:
        sys.exit(f"{len(missing)} inputs missing: run make find and make edges first")
    code = [__file__, edge_fit.__file__] + [os.path.join(edge_fit.MODELS, f) for f in os.listdir(edge_fit.MODELS) if f.endswith(".onnx")]
    # done again for a deleted photo too (remove-photos): a deletion makes no input newer, and find isn't redone for it
    deleted = os.path.exists(out) and any(r["photo"] not in chosen for r in json.load(open(out))["label_photos"].values())
    if deleted or any(steps.stale(out, c) for c in code) or os.path.getmtime(out) < max(os.path.getmtime(p) for p in inputs):
        found = json.load(open(found_file))
        found["label_photos"] = [lp for lp in found["label_photos"] if lp["photo"] in chosen]  # deleted since find ran: left out
        entries = frozen.load()
        fz = {k: {**r, "frozen": pid} for k, (pid, r) in frozen.label_photos(entries, set(chosen)).items()}
        store = stored_prints.load(None if not args.sample else os.path.join(gen, "prints", stored_prints.FILE))
        stored = {k: r["pose"] for p in store["prints"].values() if not p.get("frozen") for k, r in p["label_photos"].items()
                  if (r.get("pose") or {}).get("plastic_to_photo") is not None}
        result = solve(found, match.read_matches(os.path.join(gen, "match"), list(chosen)), os.path.join(gen, "edges"), chosen, fz, entries, stored)
        steps.write_json(out, result)
    result = json.load(open(out))
    sizes = {s: json.load(open(os.path.join(gen, "read-text", s + ".json")))["size"] or [1, 1] for s in chosen}
    page(out_dir, chosen, result, sizes)
    print(f"{len(result['label_photos'])} solved, {len(result['unsolved'])} not; page: {os.path.join(out_dir, 'index.html')}")


if __name__ == "__main__":
    main()
