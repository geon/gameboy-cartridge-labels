# An experiment (2026-11-10): fitting the recess and the label to a photo with learned edge models, one per shape and
# part (edge-models/<shape>-recess.onnx, <shape>-label.onnx; how they were made: edge-models/training/, results in
# label-detection.md). Not used by a step yet.
#
# A model looks at a strip across an edge: +-10 mm along the edge's normal, from inside (-) to outside (+), 10 samples
# per mm (each the mean of two samples 0.05 mm apart, as in training), RGB 0..1; with the part and side as a one-hot
# condition (recess 0, label 1; top 0, right 1, bottom 2, left 3). It gives a logit per sample: "the edge is here".
# The fit: strips through the current pose, 1 mm apart along each edge and 1.5 mm clear of the corners; each strip's
# edge at its most likely sample (after two rounds: the strong peak nearest the pose's edge, so a strong edge farther
# out can't pull the fit away; a parabola through the peak for the fraction); the pose corrected to put the edges
# there (robust least squares, soft L1 at 0.3 mm; strips under 0.2 confidence left out); repeated until it moves under
# 0.01 mm. The recess: shift, turn and scale for three rounds, then a full homography; the label: shift, turn, and its
# width and height each free (stickers are cut as they are; it's flat on the recess's plane, so no more). A pose maps
# plastic coordinates (mm) to the photo's pixels. fit_params fits any parameters of a pose instead (solve's label).
# A pose that runs away (not finite, or under 0.5 or over 500 px/mm at the part) stops the fit with no confidence.
# Confidence: the median over the strips of the probability within 0.3 mm of the edge found, 0 for a strip whose edge
# is at its window's end (no edge seen; added after the evaluation below, which didn't have it). Below 0.8 every fit
# tried was off by more than 1 mm; above it 1 to 4 % still were, and label fits can run far off with 0.84 (check that
# a label stays in its recess).
import json, os, sys
import cv2, numpy as np, onnxruntime
from scipy.optimize import least_squares

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outlines import corners_of, project

MODELS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edge-models")
SHAPES = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "shape-models.json"), encoding="utf-8"))["shapes"]  # recess, label
HALF, PER_MM = 10.0, 10  # the strip: +-10 mm, 10 samples per mm
FINE = 20  # the photo brought down to at most this many px per mm first, as in training
STEP, END = 1.0, 1.5  # strips 1 mm apart, 1.5 mm clear of the corners
T = np.linspace(-HALF, HALF, int(2 * HALF * PER_MM) + 1)
MIN_CONFIDENCE = 0.2  # a strip less sure than this is left out of the fit
ACCEPT = 0.8  # a fit less sure than this (its median strip) isn't to be used
END_GUARD = 0.5  # mm from the window's ends: no answer
_sessions = {}


def model(shape, part):
    key = (shape, part)
    if key not in _sessions:
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 1  # the steps run one process per core
        _sessions[key] = onnxruntime.InferenceSession(os.path.join(MODELS, f"{shape}-{part}.onnx"), options, providers=["CPUExecutionProvider"])
    return _sessions[key]


def edge_points(rect):
    """Points along the rectangle's sides, their outward normals and their sides (top, right, bottom, left)."""
    x1, y1, x2, y2 = rect
    pts, normals, sides = [], [], []
    for side, (a, b, n) in enumerate((((x1, y1), (x2, y1), (0, -1)), ((x2, y1), (x2, y2), (1, 0)), ((x2, y2), (x1, y2), (0, 1)), ((x1, y2), (x1, y1), (-1, 0)))):
        a, b = np.array(a, float), np.array(b, float)
        length = np.linalg.norm(b - a)
        s = np.arange(END, length - END + 1e-9, STEP)
        pts.append(a + s[:, None] * (b - a) / length)
        normals.append(np.repeat(np.array(n, float)[None], len(s), 0))
        sides += [side] * len(s)
    return np.concatenate(pts), np.concatenate(normals), np.array(sides)


def strips(photo, H, pts, normals):
    """The strips through pose H: (n, 3, samples) floats, RGB 0..1, from a BGR photo."""
    c = pts.mean(0)
    p = project(H, [c, c + [1, 0], c + [0, 1]])
    u, v = p[1] - p[0], p[2] - p[0]
    scale = np.sqrt(abs(u[0] * v[1] - u[1] * v[0]))  # px per mm
    img, Hs = photo, np.asarray(H, np.float64)
    if scale > FINE:  # no aliasing
        f = FINE / scale
        img = cv2.resize(photo, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        Hs = np.diag([f, f, 1]) @ Hs
    out = 0
    for dt in (0.0, -1.0 / FINE):  # the mean of two samples 0.05 mm apart
        grid = pts[:, None, :] + (T + dt)[None, :, None] * normals[:, None, :]
        px = project(Hs, grid.reshape(-1, 2)).reshape(len(pts), len(T), 2).astype(np.float32)
        out = out + cv2.remap(img, px[..., 0], px[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0).astype(np.float32)
    rgb = (out / 2 / 255.0)[..., ::-1]
    return np.ascontiguousarray(rgb.transpose(0, 2, 1))


def peaks(session, st, part_id, sides, nearest):
    """Each strip's edge (mm along it) and confidence."""
    cond = np.zeros((len(st), 6), np.float32)
    cond[:, part_id] = 1
    cond[np.arange(len(st)), 2 + sides] = 1
    logits = session.run(None, {"strips": st.astype(np.float32), "condition": cond})[0].astype(np.float64)
    lp = logits - logits.max(1, keepdims=True)
    lp = lp - np.log(np.exp(lp).sum(1, keepdims=True))
    p = np.exp(lp)
    n = lp.shape[1]
    i = lp.argmax(1)
    if nearest:  # the strong local maximum nearest the strip's middle
        kernel = np.ones(7)
        mass = np.array([np.convolve(row, kernel, "same") for row in p])  # within +-0.3 mm
        padded = np.pad(mass, ((0, 0), (3, 3)), constant_values=-1)
        local_max = np.max(np.stack([padded[:, k:k + n] for k in range(7)]), 0)
        is_max = (mass >= local_max) & (mass >= 0.15)
        dist = np.where(is_max, np.abs(T)[None, :], np.inf)
        i = np.where(is_max.any(1), dist.argmin(1), i)
    i = np.clip(i, 1, n - 2)
    rows = np.arange(len(i))
    a, b, c = lp[rows, i - 1], lp[rows, i], lp[rows, i + 1]
    sub = np.clip(0.5 * (a - c) / np.minimum(a - 2 * b + c, -1e-6), -0.5, 0.5)
    pos = T[i] + sub / PER_MM
    conf = (p * (np.abs(T[None, :] - pos[:, None]) <= 0.3)).sum(1)
    # The edge was always inside the window in training, so a peak at its end means no edge seen: given confidently
    # on a blank photo (0.8 to 0.9), so no answer at all.
    conf[np.abs(pos) >= HALF - END_GUARD] = 0.0
    return pos, conf


def correction(kind, x, center):
    """A correction in plastic coordinates: a homography near the identity; a similarity about center (shift, turn, one
    scale); or a rectangle's (shift, turn, its width and height scaled apart, along its own sides)."""
    if kind == "homography":
        a, b, c, d, e, f, g, h = x
        return np.array([[1 + a, b, c], [d, 1 + e, f], [g / 100, h / 100, 1]])
    if kind == "similarity":
        tx, ty, th, ls = x
        sx = sy = np.exp(ls)
    else:
        tx, ty, th, lsx, lsy = x
        sx, sy = np.exp(lsx), np.exp(lsy)
    M = np.array([[np.cos(th) * sx, -np.sin(th) * sy, 0], [np.sin(th) * sx, np.cos(th) * sy, 0], [0, 0, 1]])
    T1, T2 = np.eye(3), np.eye(3)
    T1[:2, 2] = -np.asarray(center)
    T2[:2, 2] = np.asarray(center) + [tx, ty]
    return T2 @ M @ T1


SANE_PX_PER_MM = (0.5, 500.0)  # a pose outside this at the part has run away: the fit stops, with no confidence


def sane(H, pts):
    """Whether pose H is still plausible at the points: finite, and its scale there within SANE_PX_PER_MM."""
    H = np.asarray(H, np.float64)
    if not np.all(np.isfinite(H)):
        return False
    c = pts.mean(0)
    with np.errstate(all="ignore"):
        p = project(H, [c, c + [1, 0], c + [0, 1]])
    if not np.all(np.isfinite(p)):
        return False
    u, v = p[1] - p[0], p[2] - p[0]
    scale = np.sqrt(abs(u[0] * v[1] - u[1] * v[0]))
    return SANE_PX_PER_MM[0] <= scale <= SANE_PX_PER_MM[1]


def refine(photo, H, shape, part, rounds=8):
    """Pose H (plastic mm -> photo px) refined to the part's edges ("recess" or "label"): (pose, confidence)."""
    rect = SHAPES[shape][part]
    part_id = 0 if part == "recess" else 1
    session = model(shape, part)
    pts, normals, sides = edge_points(rect)
    center = corners_of(rect).mean(0)
    H = np.asarray(H, np.float64)
    conf = np.zeros(len(pts))
    for rnd in range(rounds):
        kind = ("homography" if rnd >= 3 else "similarity") if part == "recess" else "rectangle"
        if not sane(H, pts):
            return H, 0.0
        pos, conf = peaks(session, strips(photo, H, pts, normals), part_id, sides, nearest=rnd >= 2)
        q = pts + pos[:, None] * normals
        w = np.sqrt(np.clip(conf, 0.02, 1)) * (conf >= MIN_CONFIDENCE)

        def residuals(x):
            return w * ((project(correction(kind, x, center), pts) - q) * normals).sum(1)

        r = least_squares(residuals, np.zeros({"homography": 8, "similarity": 4, "rectangle": 5}[kind]), loss="soft_l1", f_scale=0.3, x_scale="jac")
        C = correction(kind, r.x, center)
        H = H @ C
        moved = np.abs(project(C, corners_of(rect)) - corners_of(rect)).max()
        if moved < 0.01 and (part == "label" or rnd >= 3):
            break
    return H, float(np.median(conf)) if sane(H, pts) else 0.0


def fit_params(photo, shape, part, pose_of, x0, rounds=8):
    """The parameters x of a pose (pose_of(x): plastic mm -> photo px, the part's rectangle in plastic mm) fitted to the
    part's edges from x0, as refine does: (x, pose, confidence)."""
    rect = SHAPES[shape][part]
    part_id = 0 if part == "recess" else 1
    session = model(shape, part)
    pts, normals, sides = edge_points(rect)
    x = np.asarray(x0, np.float64)
    conf = np.zeros(len(pts))
    for rnd in range(rounds):
        H = pose_of(x)
        if not sane(H, pts):
            return x, H, 0.0
        pos, conf = peaks(session, strips(photo, H, pts, normals), part_id, sides, nearest=rnd >= 2)
        q = pts + pos[:, None] * normals
        w = np.sqrt(np.clip(conf, 0.02, 1)) * (conf >= MIN_CONFIDENCE)
        back = np.linalg.inv(H)

        def residuals(y):
            return w * ((project(back @ pose_of(y), pts) - q) * normals).sum(1)

        x_new = least_squares(residuals, x, loss="soft_l1", f_scale=0.3, x_scale="jac").x
        moved = np.abs(project(back @ pose_of(x_new), corners_of(rect)) - corners_of(rect)).max()
        x = x_new
        if moved < 0.01:
            break
    return x, pose_of(x), float(np.median(conf)) if sane(pose_of(x), pts) else 0.0


def corner_error(H, H_ref, rect):
    """The largest distance (mm) between where two poses put the rectangle's corners, in H_ref's plastic coordinates."""
    corners = corners_of(rect)
    back = project(np.linalg.inv(np.asarray(H_ref, np.float64)), project(H, corners))
    return float(np.linalg.norm(back - corners, axis=1).max())
