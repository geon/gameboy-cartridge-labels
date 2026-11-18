# Outline quadrilaterals and the starts they give, ported from main's src/cartridge.py (outline_quads, outline_starts,
# tilt): on the evaluation set (label-detection.md), these starts alone, refined by solve's nested fit and chosen by
# support, had 97 % of fits under 5 mm from the hand fits, 100 % on photos main's fitter had failed on; main's text
# starts alone 42 %.
import json, os
import cv2, numpy as np

MODELS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "shape-models.json"), encoding="utf-8"))["shapes"]
MAX_TILT = 50.0  # main: of 2,326 fits accepted or placed by hand, all but 4 within 45 degrees of upright


def corners_of(rect):
    x1, y1, x2, y2 = rect
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], np.float64)


def project(H, pts):
    return cv2.perspectiveTransform(np.float64(pts).reshape(-1, 1, 2), np.float64(H)).reshape(-1, 2)


def tilt(H):
    """How far a fit turns the cartridge's up from the photo's up, in degrees."""
    a, b = project(H, [[28.5, 10.0], [28.5, 55.0]])
    d = b - a
    return float(np.degrees(np.arctan2(-d[0], d[1])))


def outline_quads(photo, max_side=1000):
    """Four-sided outlines in the photo (in its pixels, clockwise from the top left one): the convex hulls of the
    contours of edges (Canny at three thresholds) and of light/dark, red/green, yellow/blue and saturated/grey regions
    (Otsu), each as a quadrilateral where one simplifies to four corners, and as its least rotated rectangle; those
    covering under 1 % of the photo left out, near-duplicates (corners within 1.5 % of its size) once. The label, the
    recess and the body each turn up among them on most photos."""
    h, w = photo.shape[:2]
    s = min(1.0, max_side / max(h, w))
    small = cv2.resize(photo, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (0, 0), 1.2)
    lab, hsv = cv2.cvtColor(small, cv2.COLOR_BGR2LAB), cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    maps = [cv2.dilate(cv2.Canny(gray, lo, hi), np.ones((3, 3), np.uint8)) for lo, hi in ((20, 60), (40, 120), (80, 200))]
    for channel in (lab[..., 0], lab[..., 1], lab[..., 2], hsv[..., 1]):
        _, m = cv2.threshold(cv2.GaussianBlur(channel, (0, 0), 2), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        maps += [m, 255 - m]
    found = []
    for m in maps:
        for c in cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]:
            hull = cv2.convexHull(c)
            if not 0.01 * sh * sw <= cv2.contourArea(hull) <= 0.98 * sh * sw:
                continue
            perimeter = cv2.arcLength(hull, True)
            for eps in (0.015, 0.03):
                simple = cv2.approxPolyDP(hull, eps * perimeter, True)
                if len(simple) == 4:
                    found.append(simple.reshape(4, 2).astype(np.float64))
                    break
            found.append(cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float64))
    quads = []
    for q in found:
        c = q.mean(axis=0)
        q = q[np.argsort(np.arctan2(q[:, 1] - c[1], q[:, 0] - c[0]))]
        q = np.roll(q, -int(np.argmin(q.sum(axis=1))), axis=0)
        if not any(np.abs(q - o).max() < 0.015 * max(sh, sw) for o in quads):
            quads.append(q)
    return [q / s for q in quads]


def outline_starts(quads, shape, size, tolerance=0.15):
    """Starts (plastic mm -> photo) from outline_quads: each quadrilateral taken for the label, the recess or the body
    (its box), in each of its four turns whose proportions are within tolerance (log of the ratio) of that rectangle's
    and that keep the cartridge within MAX_TILT of upright; a start putting the body partly outside the photo (by over
    10 % of its size) or covering under 3 % of it left out. As [(homography, quad index, what)]."""
    w, h = size
    m = MODELS[shape]
    sides = lambda q: np.linalg.norm(np.roll(q, -1, axis=0) - q, axis=1)
    body = corners_of(m["box"])
    starts = []
    for i, q in enumerate(quads):
        for what, rect in (("label", m["label"]), ("recess", m["recess"]), ("body", m["box"])):
            mm = corners_of(rect)
            ms = sides(mm)
            for k in range(4):
                qk = np.roll(np.float64(q), -k, axis=0)
                qs = sides(qk)
                if abs(np.log((qs[0] + qs[2]) / (qs[1] + qs[3]) / ((ms[0] + ms[2]) / (ms[1] + ms[3])))) > tolerance:
                    continue
                H = cv2.getPerspectiveTransform(mm.astype(np.float32), qk.astype(np.float32)).astype(np.float64)
                H /= H[2, 2]
                b = project(H, body)
                if abs(tilt(H)) > MAX_TILT or (b < [-0.1 * w, -0.1 * h]).any() or (b > [1.1 * w, 1.1 * h]).any() \
                        or cv2.contourArea(b.astype(np.float32)) < 0.03 * w * h:
                    continue
                starts.append((H, i, what))
    return starts
