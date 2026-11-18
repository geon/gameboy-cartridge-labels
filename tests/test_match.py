import os
import cv2, numpy as np
import features, match, steps


def warp_points(H, pts):
    return cv2.perspectiveTransform(np.float64(pts).reshape(-1, 1, 2), H).reshape(-1, 2)


def test_plausible():
    size = (1000, 800)
    assert match.plausible(np.eye(3), size)
    assert not match.plausible(np.diag([-1.0, 1, 1]), size)            # mirrored
    assert not match.plausible(np.diag([20.0, 20, 1]), size)           # scale beyond 8
    assert not match.plausible(np.array([[1, 5, 0], [0, 1, 0], [0, 0, 1.0]]), size)  # sheared
    assert match.plausible(np.diag([3.0, 3, 1]), size)


def test_homographies_finds_two_planes_among_noise():
    rng = np.random.default_rng(0)
    H1 = np.array([[1.1, 0.05, 30], [-0.04, 1.05, 10], [1e-5, 0, 1]])
    H2 = np.array([[0.7, 0, 600], [0, 0.7, 300], [0, 0, 1.0]])
    a1 = rng.uniform([0, 0], [400, 400], (60, 2))
    a2 = rng.uniform([500, 400], [900, 750], (40, 2))
    noise_a, noise_b = rng.uniform(0, 1000, (80, 2)), rng.uniform(0, 1000, (80, 2))
    pa = np.vstack([a1, a2, noise_a]).astype(np.float32)
    pb = np.vstack([warp_points(H1, a1), warp_points(H2, a2), noise_b]).astype(np.float32)
    found = match.homographies(pa, pb, (1000, 800), (1000, 800))
    assert len(found) == 2
    for H, inl in found:
        assert inl.sum() >= 35
        true = H1 if inl[:60].sum() > inl[60:100].sum() else H2
        test = np.float64([[100, 100], [300, 200]]) if true is H1 else np.float64([[600, 500], [800, 700]])
        assert np.abs(warp_points(H, test) - warp_points(true, test)).max() < 2


def textured(rng, h, w):
    """Random triangles and words: distinct SIFT keypoints, like print."""
    img = np.full((h, w, 3), 128, np.uint8)
    for _ in range(h * w // 4000):
        pts = (rng.integers(0, [w, h], 2) + rng.integers(-25, 25, (3, 2))).astype(np.int32)
        cv2.fillPoly(img, [pts], tuple(int(v) for v in rng.integers(0, 256, 3)))
    for _ in range(h * w // 40000):
        word = "".join(chr(int(c)) for c in rng.integers(65, 91, 5))
        cv2.putText(img, word, (int(rng.integers(0, w - 100)), int(rng.integers(20, h))), cv2.FONT_HERSHEY_SIMPLEX,
                    float(rng.uniform(0.6, 1.2)), tuple(int(v) for v in rng.integers(0, 256, 3)), 2)
    return img


def test_matches_a_pasted_patch_and_not_another_photo(tmp_path):
    rng = np.random.default_rng(1)
    patch = textured(rng, 300, 400)
    # photo a: the patch at (100, 80); photo b: the patch scaled 1.5 at (300, 200); photo c: something else
    a = textured(rng, 600, 800); a[80:380, 100:500] = patch
    b = textured(rng, 900, 1200); b[200:650, 300:900] = cv2.resize(patch, (600, 450))
    c = textured(rng, 600, 800)
    feats, out = tmp_path / "features", tmp_path / "match"
    feats.mkdir(); out.mkdir()
    for name, img in (("a", a), ("b", b), ("c", c)):
        steps.write_npz(str(feats / f"{name}.npz"), **features.features(img))
    shas = ["a", "b", "c"]
    neighbours = match.NeighbourFiles(str(tmp_path / "neighbours"))
    os.makedirs(neighbours.folder)
    _, owner, which = match.search(str(feats), shas, shas, neighbours, 0)
    match._index = (neighbours, owner, which, shas, str(feats))
    for i, s in enumerate(shas):
        match.match_job((i, str(out / f"{s}.npz")))
    found = match.read_matches(str(out), shas)
    pairs = {(x, y) for x, y, _, _ in found}
    assert ("b", "a") in pairs                   # stored once, in the later photo's file
    assert not any("c" in p for p in pairs)
    H = next(H for x, y, H, _ in found if (x, y) == ("b", "a"))
    # b's patch corner (300, 200) is a's (100, 80); b's (900, 650) is a's (500, 380)
    assert np.abs(warp_points(H, [[300, 200], [900, 650]]) - [[100, 80], [500, 380]]).max() < 3


def test_an_index_in_parts_finds_the_nearest_neighbours(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    shas = [f"{i:040x}" for i in range(6)]
    for s in shas:
        d = rng.normal(0, 1, (300, 128)).astype(np.float32)
        np.savez(tmp_path / (s + ".npz"), points=np.zeros((300, 2)), responses=rng.random(300), descriptors=d, size=np.array([100, 100]))
    monkeypatch.setattr(match, "INDEX_ROWS", 650)   # 2 photos per part: 3 parts
    whole = np.concatenate([match.load_features(str(tmp_path), s)["descriptors"][np.argsort(-match.load_features(str(tmp_path), s)["responses"])] for s in shas])
    q = whole[::37] + rng.normal(0, 0.05, whole[::37].shape).astype(np.float32)
    query = "f" * 40  # a photo searched for, not in the index
    np.savez(tmp_path / (query + ".npz"), points=np.zeros((len(q), 2)), responses=np.zeros(len(q)), descriptors=q, size=np.array([100, 100]))
    neighbours = match.NeighbourFiles(str(tmp_path / "neighbours"))
    os.makedirs(neighbours.folder)
    parts, owner, which = match.search(str(tmp_path), shas, [query], neighbours, 0)
    assert len(parts) == 3 and len(owner) == 1800
    monkeypatch.setattr(match, "_query", neighbours.path(query))
    found = match.knn(neighbours, q, 3)
    exact = cv2.BFMatcher(cv2.NORM_L2).knnMatch(q, whole, k=3)
    same = np.mean([f[0].trainIdx == e[0].trainIdx for f, e in zip(found, exact)])
    assert same > 0.95
    assert all(f[0].distance <= f[1].distance <= f[2].distance for f in found)
