# match: which photos show something alike, and where: pairs of photos, each with one or more homographies (several
# cartridges or labels in a photo) and their inlier points, into <generated>/match/<sha1>.npz:
#   others (m sha1s), a_to_b (m x 3 x 3: this photo's pixels -> the other's), inliers (k x 4: x, y here, x, y there),
#   starts (m + 1: the rows of inliers of each match).
# Nothing specific to labels: watermarks, backgrounds and embossing match too; find decides what's a label.
# Two stages:
#   candidates: one index of every photo's INDEXED strongest keypoints; each of a photo's keypoints (all of them) looks
#     up its NEIGHBOURS nearest there (of other photos); per photo, Lowe's ratio test (RATIO) among its neighbours in
#     that photo makes a correspondence; the CANDIDATES photos with most correspondences are checked.
#   checking: RANSAC on those correspondences (homography, RANSAC_PX), repeated without each one's inliers (at most
#     MAX_PER_PAIR); one is kept with MIN_INLIERS or more inliers, plausible (not mirrored, scale 1/8 to 8, little shear)
#     and its inliers spread over at least MIN_AREA of the smaller photo.
# Frozen prints (src/frozen.py, persistent-prints.md stage 2): each frozen print's image is in the index as if it were
# a photo (its features from the features step, by the image's SHA-1), before every photo, so a photo matched from now on
# can match it; it has no file of its own. A photo all of whose label photos are frozen (frozen.left_out_of_matching) is
# left out of the index and never matched again; its file stays as written (if the matching changes, its matches are
# gone: the frozen label photos don't need them).
# Each pair is stored once, in one photo's file, and a file never changes once written: in a run, the photos with an
# up-to-date file come first, then the others in SHA-1 order; a photo's file holds its pairs with the photos before
# it. All are done again when the matching changes (VERSION: a fingerprint of the settings and the functions that decide
# the matches, kept in version.json; pairs may move between files); a photo's file missing, it's done. How the index is
# searched (build_index, knn) isn't part of it: the index is split into parts of at most INDEX_ROWS keypoints (OpenCV's
# FLANN takes under 2^31 numbers in one array: 13183 photos' 1500 keypoints of 128 numbers didn't fit, 2026-11-12),
# each part searched and their nearest neighbours merged.
# The page, <generated>/match/index.html: the counts, the photos matching nothing, the weakest matches.
# Usage: match.py [--sample] [--workers N]
import argparse, json, multiprocessing, os, sys
import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, steps, frozen

INDEXED = 1500
NEIGHBOURS = 8
RATIO = 0.8
SELF_EXTRA = 4   # neighbours looked up beyond NEIGHBOURS, as the photo's own come first
CANDIDATES = 20
RANSAC_PX = 0.006  # of the photo's long side
MIN_INLIERS = 15
MAX_PER_PAIR = 4
MIN_AREA = 0.002   # of the smaller photo's area

INDEX_ROWS = 8_000_000  # keypoints per part of the index (see above)

_index = None  # set before the workers start: (index parts, owner, keypoint number, shas, features_dir)


def load_features(features_dir, sha1):
    f = np.load(os.path.join(features_dir, sha1 + ".npz"))
    return {k: f[k] for k in ("points", "responses", "descriptors", "size")}


def worker_pool(workers):
    """Where there is fork, processes that share the index built before them; on Windows (spawn only, and the FLANN
    index can't be pickled to a new process) threads, which share it too: OpenCV and numpy release the GIL."""
    if "fork" in multiprocessing.get_all_start_methods():
        return multiprocessing.get_context("fork").Pool(workers)
    from multiprocessing.pool import ThreadPool
    return ThreadPool(workers)


def build_index(features_dir, shas):
    """FLANN over the INDEXED strongest keypoints of every photo, in parts of at most INDEX_ROWS: ([(matcher, first
    row)], the photo of each row, its keypoint)."""
    parts, chunk, start, rows, owner, which = [], [], 0, 0, [], []

    def close():
        nonlocal chunk, start, rows
        if chunk:
            flann = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 4}, {"checks": 64})
            flann.add([np.ascontiguousarray(np.concatenate(chunk))])
            flann.train()
            parts.append((flann, start))
            start += rows
        chunk, rows = [], 0

    for i, s in enumerate(shas):
        f = load_features(features_dir, s)
        keep = np.argsort(-f["responses"])[:INDEXED]
        if rows + len(keep) > INDEX_ROWS:
            close()
        chunk.append(f["descriptors"][keep].astype(np.float32))
        rows += len(keep)
        owner.append(np.full(len(keep), i, np.int32))
        which.append(keep.astype(np.int32))
    close()
    return parts, np.concatenate(owner) if owner else np.zeros(0, np.int32), np.concatenate(which) if which else np.zeros(0, np.int32)


class Neighbour:
    __slots__ = ("trainIdx", "distance")

    def __init__(self, train_idx, distance):
        self.trainIdx, self.distance = train_idx, distance


def knn(parts, des, k):
    """Each descriptor's k nearest among all parts of the index: [[Neighbour, nearest first]]."""
    found = [[] for _ in range(len(des))]
    for flann, start in parts:
        for q, ms in enumerate(flann.knnMatch(des, k=k)):
            found[q].extend(Neighbour(start + m.trainIdx, m.distance) for m in ms)
    return [sorted(f, key=lambda m: m.distance)[:k] for f in found]


VERSION_FUNCTIONS = ["load_features", "plausible", "homographies", "match_photo"]


def version():
    """A fingerprint of what decides the matches: the settings and the functions in VERSION_FUNCTIONS."""
    import hashlib, inspect
    h = hashlib.sha1(repr((INDEXED, NEIGHBOURS, RATIO, SELF_EXTRA, CANDIDATES, RANSAC_PX, MIN_INLIERS, MAX_PER_PAIR,
                           MIN_AREA)).encode())
    for name in VERSION_FUNCTIONS:
        h.update(inspect.getsource(globals()[name]).encode())
    return h.hexdigest()[:16]


def plausible(H, size_a):
    """Not mirrored, a scale from 1/8 to 8, little shear, and no wild perspective over photo a."""
    if H is None or not np.all(np.isfinite(H)):
        return False
    A = H[:2, :2] / H[2, 2]
    if np.linalg.det(A) <= 0:
        return False
    s = np.linalg.svd(A, compute_uv=False)
    if not (1 / 8 < np.sqrt(s[0] * s[1]) < 8) or s[0] / s[1] > 3:
        return False
    w, h = size_a
    corners = cv2.perspectiveTransform(np.float64([[[0, 0]], [[w, 0]], [[w, h]], [[0, h]]]), H)
    return bool(np.all(np.isfinite(corners)) and np.all(H[2, :2] * [w, h] < 1.5))


def homographies(pa, pb, size_a, size_b):
    """RANSAC homographies a -> b from correspondences, repeated without each one's inliers: [(H, inlier mask)]."""
    found, left = [], np.ones(len(pa), bool)
    thresh = RANSAC_PX * max(max(size_a), max(size_b))
    area = MIN_AREA * min(size_a[0] * size_a[1], size_b[0] * size_b[1])
    for _ in range(MAX_PER_PAIR):
        idx = np.where(left)[0]
        if len(idx) < MIN_INLIERS:
            break
        H, mask = cv2.findHomography(pa[idx], pb[idx], cv2.USAC_MAGSAC, thresh, maxIters=5000, confidence=0.999)
        if H is None:
            break
        inl = np.zeros(len(pa), bool)
        inl[idx[mask.ravel().astype(bool)]] = True
        if inl.sum() < MIN_INLIERS:
            break
        left &= ~inl
        spread = min(cv2.contourArea(cv2.convexHull(pa[inl].astype(np.float32))),
                     cv2.contourArea(cv2.convexHull(pb[inl].astype(np.float32))))
        if plausible(H, size_a) and spread >= area:
            found.append((H, inl))
    return found


def match_photo(job):
    """The matches of photo i with the photos before it in the order."""
    i, out = job
    parts, owner, which, shas, features_dir = _index
    a = load_features(features_dir, shas[i])
    if len(a["descriptors"]) < MIN_INLIERS:
        steps.write_npz(out, others=np.array([], "U40"), a_to_b=np.zeros((0, 3, 3)), inliers=np.zeros((0, 4), np.float32), starts=np.zeros(1, np.int64))
        return i
    # the photo's own keypoints are in the index too (it's every photo's): extra neighbours looked up, its own skipped
    nn = knn(parts, a["descriptors"].astype(np.float32), NEIGHBOURS + SELF_EXTRA)
    # per other photo, Lowe's ratio test among the neighbours in that photo: my keypoint's nearest there must be
    # clearly nearer than its second nearest there (or than the farthest neighbour looked up, if none other is there)
    corr = {}  # other photo -> [(my keypoint, its keypoint)]
    for q, ms in enumerate(nn):
        ms = [m for m in ms if owner[m.trainIdx] != i]
        if not ms:
            continue
        by_photo = {}
        for m in ms[:NEIGHBOURS]:
            by_photo.setdefault(owner[m.trainIdx], []).append(m)
        for j, found in by_photo.items():
            if j >= i:
                continue
            second = found[1].distance if len(found) > 1 else ms[-1].distance
            if found[0].distance < RATIO * second:
                corr.setdefault(j, []).append((q, which[found[0].trainIdx]))
    others, hs, inliers, starts = [], [], [], [0]
    for j in sorted(corr, key=lambda j: -len(corr[j]))[:CANDIDATES]:
        if len(corr[j]) < MIN_INLIERS:
            break
        b = load_features(features_dir, shas[j])
        qa, qb = np.array(corr[j], np.int64).T
        pa, pb = a["points"][qa], b["points"][qb]
        for H, inl in homographies(pa, pb, tuple(a["size"]), tuple(b["size"])):
            others.append(shas[j])
            hs.append(H)
            inliers.append(np.hstack([pa[inl], pb[inl]]).astype(np.float32))
            starts.append(starts[-1] + int(inl.sum()))
    steps.write_npz(out, others=np.array(others, "U40"), a_to_b=np.array(hs).reshape(-1, 3, 3),
                    inliers=np.concatenate(inliers) if inliers else np.zeros((0, 4), np.float32), starts=np.array(starts))
    return i


def read_matches(out_dir, shas, images=()):
    """Every match: [(sha1 a, sha1 b, a_to_b, inliers)], from all the photos' files; a match with a photo not among
    shas (deleted since match ran: remove-photos) is left out, except with one of images (frozen prints' images, by
    their SHA-1: src/frozen.py)."""
    found, wanted = [], set(shas) | set(images)
    for s in shas:
        p = os.path.join(out_dir, s + ".npz")
        if not os.path.exists(p):
            continue
        f = np.load(p)
        for k, other in enumerate(f["others"]):
            if str(other) in wanted:
                found.append((s, str(other), f["a_to_b"][k], f["inliers"][f["starts"][k]:f["starts"][k + 1]]))
    return found


def page(out_dir, chosen):
    shas = list(chosen)
    matches = read_matches(out_dir, shas)
    linked = {}
    for a, b, _, inl in matches:
        linked.setdefault(a, set()).add(b)
        linked.setdefault(b, set()).add(a)
    alone = [s for s in shas if s not in linked]
    n = np.array([len(linked.get(s, ())) for s in shas]) if shas else np.zeros(1)
    rel = os.path.relpath(".", out_dir)
    img = lambda s: f'<a href="{rel}/{chosen[s]}"><img loading="lazy" src="{rel}/{chosen[s]}"></a>'
    weakest = steps.few(sorted(matches, key=lambda m: len(m[3])))
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>match</title>
<style>body{{font:14px system-ui;margin:16px}} img{{max-width:200px;max-height:200px}} td{{vertical-align:top;padding:4px 8px;border-top:1px solid #ccc}}</style>
<h1>match</h1>
<p>{len(shas)} photos, {len(matches)} matches between {len({(a, b) for a, b, _, _ in matches})} pairs. Photos matched with: none {len(alone)}, median {int(np.median(n))}, most {int(n.max())}.</p>
<h2>Matching nothing ({steps.shown(len(alone))})</h2><p>{''.join(img(s) for s in steps.few(alone))}</p>
<h2>Weakest matches ({len(weakest)})</h2><table>{''.join(f'<tr><td>{len(inl)} inliers</td><td>{img(a)}</td><td>{img(b)}</td></tr>' for a, b, _, inl in weakest)}</table>
""")


def main():
    global _index
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    chosen = photos.chosen(args.sample)
    gen = photos.generated(args.sample)
    features_dir, out_dir = os.path.join(gen, "features"), os.path.join(gen, "match")
    os.makedirs(out_dir, exist_ok=True)
    steps.remove_orphans(out_dir, chosen, ".npz")
    missing = [s for s in chosen if not os.path.exists(os.path.join(features_dir, s + ".npz"))]
    if missing:
        sys.exit(f"{len(missing)} photos have no features: run make features first")
    out = lambda s: os.path.join(out_dir, s + ".npz")
    version_file = os.path.join(out_dir, "version.json")
    current = version()
    if not os.path.exists(version_file):
        # the files from before the fingerprint (2026-11-12) were made by this matching: kept
        steps.write_json(version_file, {"version": current})
    if json.load(open(version_file, encoding="utf-8")).get("version") != current:
        for s in chosen:  # the matching changed: pairs may move between files, so all are redone
            if os.path.exists(out(s)):
                os.remove(out(s))
        steps.write_json(version_file, {"version": current})
    # frozen prints (src/frozen.py): their images first in the index, as photos (a new photo of a frozen print matches
    # its image); photos all of whose label photos are frozen left out (their files stay as written)
    images = [s for s in sorted(frozen.images()) if os.path.exists(os.path.join(features_dir, s + ".npz"))]
    left_out = frozen.left_out_of_matching() & set(chosen)
    done = [s for s in chosen if os.path.exists(out(s)) and s not in left_out]
    todo = [s for s in sorted(chosen) if s not in set(done) and s not in left_out]
    shas = images + done + todo
    done = images + done
    if todo:
        print(f"indexing {len(shas)} photos", flush=True)
        parts, owner, which = build_index(features_dir, shas)
        print(f"index: {len(owner)} keypoints in {len(parts)} parts", flush=True)
        _index = (parts, owner, which, shas, features_dir)
        jobs = [(len(done) + k, out(s)) for k, s in enumerate(todo)]
        with worker_pool(args.workers) as pool:
            for n, _ in enumerate(pool.imap_unordered(match_photo, jobs), 1):
                if n % 50 == 0 or n == len(jobs):
                    print(f"matched {n} of {len(jobs)}", flush=True)
    page(out_dir, chosen)
    print(f"page: {os.path.join(out_dir, 'index.html')}")


if __name__ == "__main__":
    main()
