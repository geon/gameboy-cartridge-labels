# Details in photos: where each image of details/ (common details of the labels, 20 px/mm, named by hand) is found
# in a photo, for find. Each photo's detections are cached in <generated>/details/<sha1>.json:
#   [{"detail" (its file name), "size" (its image's), "corners" (the image's corners in the photo), "centre",
#     "px_per_mm", "inliers"}]
# A detail is matched against the photo's SIFT keypoints (features), each neighbour clearly nearer than the
# (MAX_PER_PHOTO + 1)-th kept (the plain ratio test would reject a detail found twice), then a RANSAC homography:
# kept with MIN_INLIERS or more, plausible, at 2 to 60 photo pixels per mm; repeated without its inliers (a detail on
# several cartridges). A photo's cache is redone when it's missing, or older than this file or any detail image.
# Seals and the CE have too few keypoints for this (18); they're found later, in straightened label photos.
import json, os
import cv2, numpy as np
import photos

import steps, match

DETAILS = "details"
DETAIL_PX_PER_MM = 20
MIN_INLIERS = 12
RATIO = 0.8
MAX_PER_PHOTO = 4
PX_PER_MM = (2, 60)

_details = None


def load_details(folder=DETAILS):
    """The detail images' SIFT keypoints: [(name, (w, h), points, descriptors)]."""
    global _details
    if _details is None:
        sift = cv2.SIFT_create()
        _details = []
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".png"):
                continue
            img = photos.imread(os.path.join(folder, name))
            kp, des = sift.detectAndCompute(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), None)
            if des is not None and len(kp) >= MIN_INLIERS:
                _details.append((name, (img.shape[1], img.shape[0]), np.float32([k.pt for k in kp]), des.astype(np.float32)))
    return _details


def detect(features, details):
    """Where the details are in a photo (its features: points, descriptors, size)."""
    found = []
    des = features["descriptors"].astype(np.float32)
    if len(des) < 2:
        return found
    bf = cv2.BFMatcher()
    for name, (w, h), dpts, ddes in details:
        # a detail may be in a photo several times (cartridges of one layout), so the plain ratio test (nearest against
        # second nearest) would reject every copy: each neighbour clearly nearer than the k-th is kept
        k = MAX_PER_PHOTO + 1
        ms = [m for ns in bf.knnMatch(ddes, des, k=k) if len(ns) == k for m in ns[:-1] if m.distance < RATIO * ns[-1].distance]
        if len(ms) < MIN_INLIERS:
            continue
        pa = np.float32([dpts[m.queryIdx] for m in ms])
        pb = np.float32([features["points"][m.trainIdx] for m in ms])
        left = np.ones(len(ms), bool)
        for _ in range(MAX_PER_PHOTO):
            idx = np.where(left)[0]
            if len(idx) < MIN_INLIERS:
                break
            H, mask = cv2.findHomography(pa[idx], pb[idx], cv2.USAC_MAGSAC, 3.0 * max(1.0, float(features["scale"])))
            if H is None:
                break
            inl = np.zeros(len(ms), bool)
            inl[idx[mask.ravel().astype(bool)]] = True
            left &= ~inl
            if inl.sum() < MIN_INLIERS or not match.plausible(H, (w, h)):
                continue
            corners = cv2.perspectiveTransform(np.float64([[[0, 0]], [[w, 0]], [[w, h]], [[0, h]]]), H).reshape(-1, 2)
            px_per_mm = np.sqrt(abs(cv2.contourArea(corners.astype(np.float32))) / (w * h)) * DETAIL_PX_PER_MM
            if PX_PER_MM[0] <= px_per_mm <= PX_PER_MM[1]:
                found.append({"detail": name, "size": [w, h], "corners": corners.round(1).tolist(), "centre": corners.mean(0).round(1).tolist(),
                              "px_per_mm": round(float(px_per_mm), 3), "inliers": int(inl.sum())})
    return found


def detect_photo(job):
    sha1, features_path, out = job
    f = np.load(features_path)
    steps.write_json(out, detect({k: f[k] for k in ("points", "descriptors", "scale")}, load_details()))
    return sha1


def detections(gen, chosen, workers=8, folder=DETAILS):
    """sha1 -> the photo's detections, made where the cache is stale."""
    out_dir = os.path.join(gen, "details")
    os.makedirs(out_dir, exist_ok=True)
    steps.remove_orphans(out_dir, chosen, ".json")
    newest = max([os.path.getmtime(__file__)] + [os.path.getmtime(os.path.join(folder, n)) for n in os.listdir(folder)])
    out = lambda s: os.path.join(out_dir, s + ".json")
    jobs = [(s, os.path.join(gen, "features", s + ".npz"), out(s)) for s in chosen
            if not os.path.exists(out(s)) or os.path.getmtime(out(s)) < newest]
    steps.run(detect_photo, jobs, workers, what="details searched in")
    return {s: json.load(open(out(s), encoding="utf-8")) for s in chosen}


# Details at one place on every label of their shape (details/places.json): such a detail, found, places the whole label.
PLACES = "places.json"


def load_places(folder=DETAILS):
    """Detail name -> {"shape", "centre_mm"}."""
    path = os.path.join(folder, PLACES)
    return json.load(open(path, encoding="utf-8"))["places"] if os.path.exists(path) else {}


def label_mm_to_detail_px(centre_mm, detail_size):
    """mm on the label -> the detail image's pixels (20 px/mm, no turn), the detail's centre at centre_mm."""
    w, h = detail_size
    ox, oy = centre_mm[0] - w / 2 / DETAIL_PX_PER_MM, centre_mm[1] - h / 2 / DETAIL_PX_PER_MM
    return np.array([[DETAIL_PX_PER_MM, 0, -DETAIL_PX_PER_MM * ox], [0, DETAIL_PX_PER_MM, -DETAIL_PX_PER_MM * oy], [0, 0, 1.0]])


def placed_label(detection, places, detail_size, label_mm):
    """The label's corners in the photo (top left, top right, bottom right, bottom left), placed by a fixed-place
    detection (label_mm: shape -> label size); None if the detail has no place. Through an affine fit to the detail's
    corners, not its homography: a small detail's perspective, carried across a whole label, magnifies its error (3 to
    6 mm for KONAMI); the label's perspective is solve's."""
    place = places.get(detection["detail"])
    if place is None:
        return None
    w, h = detail_size
    src = np.float64([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1]])
    A = np.linalg.lstsq(src, np.float64(detection["corners"]), rcond=None)[0].T  # 2 x 3, least squares
    H = np.vstack([A, [0, 0, 1]])
    lw, lh = label_mm[place["shape"]]
    M = H @ label_mm_to_detail_px(place["centre_mm"], detail_size)
    return cv2.perspectiveTransform(np.float64([[[0, 0]], [[lw, 0]], [[lw, lh]], [[0, lh]]]), M).reshape(-1, 2)
