import cv2, numpy as np
import solve, shapes


def drawn_cartridge(H_plastic, shape="dmg", size=(1400, 1400)):
    """A dark background, a mid grey cartridge body, a darker recess and a light label at its nominal place, drawn
    through H_plastic (plastic mm -> photo)."""
    m = solve.MODELS[shape]
    img = np.full((size[1], size[0], 3), 20, np.uint8)
    rect = lambda r: solve.project(H_plastic, [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]).astype(np.int32)
    cv2.fillPoly(img, [rect(m["box"])], (120, 120, 120))
    cv2.fillPoly(img, [rect(m["recess"])], (90, 90, 90))
    cv2.fillPoly(img, [rect(m["label"])], (230, 230, 230))
    return img


def test_nested_fit_finds_the_cartridge_from_a_start_a_few_mm_off():
    import edges
    H_true = solve.similarity_to_H((700, 700), 7.0, 15.0, "dmg") @ np.linalg.inv(solve.label_to_plastic("dmg"))
    segs = edges.segments(drawn_cartridge(H_true))["segments"].astype(np.float64)
    H0 = solve.similarity_to_H((725, 680), 5.0, 15.6, "dmg") @ np.linalg.inv(solve.label_to_plastic("dmg"))  # ~2 mm, 2 deg off
    H, placement, support, error = solve.fit_nested(H0, "dmg", segs)
    # the label and the recess (the drawn body is a plain box, the model's has bevels and steps at the bottom)
    for r in (solve.MODELS["dmg"]["label"], solve.MODELS["dmg"]["recess"]):
        corners = [[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]
        assert np.abs(solve.project(H, corners) - solve.project(H_true, corners)).max() < 6  # px, at 15 px/mm: 0.4 mm
    assert abs(placement[0]) < 0.5 and abs(placement[1]) < 0.5
    assert support["recess"] > 0.5 and support["label"] > 0.5


def test_rigid_fit():
    a = np.random.default_rng(0).uniform(0, 40, (30, 2))
    th = np.radians(2.0)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    theta, t = solve.rigid_fit(a, a @ R.T + [1.0, -0.5])
    assert abs(theta - 2.0) < 1e-6 and np.allclose(t, [1.0, -0.5])


def test_pixel_agreement_finds_the_same_print_shifted_and_not_another():
    from test_match import textured
    print_ = textured(np.random.default_rng(0), 400, 500)
    # two photos of one print: a's cut at the print's origin, b's cut 1 mm right and 0.5 down (b's frame -> a's: +1, +0.5)
    px = 10  # photo px per mm
    cut_a = np.array([[px, 0, 20.0], [0, px, 20.0], [0, 0, 1]])
    cut_b = np.array([[px, 0, 20.0 + px], [0, px, 20.0 + 0.5 * px], [0, 0, 1]])
    va = solve.compare_view(print_, cut_a, "dmg")
    vb = solve.compare_view(print_, cut_b, "dmg")
    share, textured_tiles = solve.pixel_agreement(va, vb, 0.0, np.array([1.0, 0.5]), "dmg")
    assert textured_tiles > 50 and share > 0.7  # tiles textured in either count: the plain border too
    share, _ = solve.pixel_agreement(va, vb, 0.0, np.array([-1.0, -0.5]), "dmg")   # the wrong way round
    assert share < 0.3
    other = solve.compare_view(textured(np.random.default_rng(1), 400, 500), cut_b, "dmg")
    assert solve.pixel_agreement(va, other, 0.0, np.array([1.0, 0.5]), "dmg")[0] < 0.3


def test_the_choice_learns_which_feature_tells_right_from_wrong():
    rng = np.random.default_rng(3)
    n = len(solve.FEATURES)
    right = rng.normal(0, 1, (200, n)); right[:, 7] += 2.0   # the agreeing share higher when right
    wrong = rng.normal(0, 1, (200, n))
    model = solve.train_choice(list(right) + list(wrong), [1] * 200 + [0] * 200)
    assert int(np.argmax(model[2])) == 7
    assert solve.predict(model, right).mean() > solve.predict(model, wrong).mean() + 0.3


def test_confident_needs_two_kinds_of_start_agreeing():
    c = lambda start: {"start": start}
    apart = np.array([[0, 0.2, 0.3], [0.2, 0, 0.1], [0.3, 0.1, 0]])
    assert solve.confident([c("outline (label)"), c("outline (recess)"), c("outline (label)")], apart, 0)
    assert not solve.confident([c("outline (label)"), c("outline (label)"), c("outline (label)")], apart, 0)
    far = np.array([[0, 5.0], [5.0, 0]])
    assert not solve.confident([c("placed by X"), c("outline (body)")], far, 0)


def test_a_degenerate_label_homography_isnt_usable():
    assert solve.usable(solve.similarity_to_H((500, 500), 0, 10, "dmg"), "dmg")
    singular = np.array([[1.0, 2, 3], [2, 4, 6], [0, 0, 1]])
    assert not solve.usable(singular, "dmg")
    assert not solve.usable(np.full((3, 3), np.nan), "dmg")
    tiny = solve.similarity_to_H((500, 500), 0, 0.1, "dmg")          # under 20 px across
    assert not solve.usable(tiny, "dmg")


def test_apart_survives_a_singular_candidate():
    good = {"cut_to_photo": solve.similarity_to_H((500, 500), 0, 10, "dmg")}
    bad = {"cut_to_photo": np.array([[1.0, 2, 3], [2, 4, 6], [0, 0, 1]])}
    assert solve.apart_mm(bad, good, "dmg") == float("inf")


def test_refining_corrects_a_corner_off_by_a_millimetre():
    from test_match import textured
    print_ = textured(np.random.default_rng(5), 600, 700)
    px = 12
    good = np.array([[px, 0, 30.0], [0, px, 30.0], [0, 0, 1]])   # label mm -> photo px
    # a third label photo's fit with one corner 1 mm off: its "label mm" are distorted
    mm = solve.corners_mm("dmg")
    off = mm.copy(); off[3] += [0, 1.0]
    bent = good @ cv2.getPerspectiveTransform(mm.astype(np.float32), off.astype(np.float32)).astype(np.float64)
    views = {"a": solve.compare_view(print_, good, "dmg"), "b": solve.compare_view(print_, good, "dmg"),
             "c": solve.compare_view(print_, bent, "dmg")}
    offsets = {k: np.zeros(3) for k in views}
    corrections, bad = solve.refine_family(list(views), views, offsets, "dmg")
    assert not bad and corrections["a"][1] < 0.2
    # a print point at true mm p lies at D^-1(p) in c's mm (D: mm -> off), so the correction should be D: it takes c's
    # label corners to where the distortion put them
    C = corrections["c"][0]
    assert np.abs(solve.project(C, mm) - off).max() < 0.25


def test_release_groups_are_aligned_to_each_other_on_shared_tiles():
    from test_match import textured
    print_ = cv2.resize(textured(np.random.default_rng(7), 200, 234), None, fx=3, fy=3)  # coarse, as label art
    px = 12
    cut = np.array([[px, 0, 30.0], [0, px, 30.0], [0, 0, 1]])
    shifted = cut @ np.array([[1, 0, 0.8], [0, 1, -0.5], [0, 0, 1.0]])   # group b's fits 0.8, -0.5 mm off
    views = {"a1": solve.compare_view(print_, cut, "dmg"), "a2": solve.compare_view(print_, cut, "dmg"),
             "b1": solve.compare_view(print_, shifted, "dmg")}
    offsets = {k: np.zeros(3) for k in views}
    corrections = {}
    solve.align_groups([["a1", "a2"], ["b1"]], views, offsets, corrections, "dmg")
    C = corrections["b1"][0]
    # a print point at mm p lies at p - (0.8, -0.5) in b1's frame; corrected, it should be back at p
    p = np.array([[10.0, 10.0], [30.0, 25.0]])
    assert np.abs(solve.project(C, p - [0.8, -0.5]) - p).max() < 0.15


def test_fine_refinement_corrects_a_small_offset_at_full_resolution(tmp_path):
    # one textured "photo" at 20 px per mm of ink; three label photos of it, the third's homography 0.3 mm off in x
    rng = np.random.default_rng(3)
    tex = cv2.GaussianBlur(rng.random((1100, 1200)).astype(np.float32), (0, 0), 3)
    img = cv2.cvtColor((np.clip((tex - tex.mean()) / tex.std() * 40 + 128, 0, 255)).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    path = str(tmp_path / "p.png"); cv2.imwrite(path, img)
    photo_to_ink = np.array([[1 / 20, 0, -5.0], [0, 1 / 20, -5.0], [0, 0, 1]])   # photo px -> ink mm
    off = np.array([[1, 0, 0.3], [0, 1, 0], [0, 0, 1.0]]) @ photo_to_ink
    out = solve.fine_group((["a", "b", "c"], [path] * 3, [photo_to_ink, photo_to_ink, off], "dmg", False, solve.MAX_FINE_MM))
    C = out["c"][0]
    assert abs(solve.project(C, [[20.0, 18.0]])[0][0] - 19.7) < 0.03          # the 0.3 mm taken back
    assert out["a"][1] < 0.03


def test_nested_fit_finds_the_label_own_width():
    import edges
    m = solve.MODELS["dmg"]
    H_true = solve.similarity_to_H((700, 700), 3.0, 15.0, "dmg") @ np.linalg.inv(solve.label_to_plastic("dmg"))
    img = drawn_cartridge(H_true)
    x0, y0, x1, y1 = m["recess"]
    cv2.fillPoly(img, [solve.project(H_true, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]).astype(np.int32)], (90, 90, 90))
    lx0, ly0, lx1, ly1 = m["label"]
    c, w = (lx0 + lx1) / 2, 41.8                     # a label cut 0.7 mm narrower than the canonical 42.5
    cv2.fillPoly(img, [solve.project(H_true, [[c - w / 2, ly0], [c + w / 2, ly0], [c + w / 2, ly1], [c - w / 2, ly1]]).astype(np.int32)],
                 (230, 230, 230))
    segs = edges.segments(img)["segments"].astype(np.float64)
    H, placement, support, error = solve.fit_nested(H_true, "dmg", segs)
    assert abs(placement[3] - w) < 0.15


def test_a_family_is_anchored_to_its_frozen_label_photo():
    import numpy as np
    import solve
    T = lambda dx, dy: [[1.0, 0, dx], [0, 1.0, dy], [0, 0, 1.0]]
    out = {"f@1,1": {"shape": "dmg", "family": "f@1,1", "family_size": 2, "photo_to_ink": T(0, 0)},
           "n@1,1": {"shape": "dmg", "family": "f@1,1", "family_size": 2, "photo_to_ink": T(5, 0)}}
    frozen_records = {"f@1,1": {"shape": "dmg", "photo_to_ink": T(0.3, -0.2), "found": [[0, 0]], "frozen": "DMG-X-JPN-bob"}}
    solve.anchor_to_frozen(out, frozen_records)
    assert out["f@1,1"]["photo_to_ink"] == T(0.3, -0.2) and out["f@1,1"]["frozen"] == "DMG-X-JPN-bob"
    assert "found" not in out["f@1,1"] and out["f@1,1"]["family_size"] == 2
    assert np.allclose(out["n@1,1"]["photo_to_ink"], T(5.3, -0.2))


def test_a_refinement_is_cached_by_its_inputs(tmp_path, monkeypatch):
    import numpy as np
    import solve
    monkeypatch.setattr(solve, "_GEN_DIR", str(tmp_path))
    H = np.eye(3)
    f = solve.refine_cache_file("fine", ["v", ["a", "b"], H])
    assert solve.refine_cache_file("fine", ["v", ["a", "b"], H.copy()]) == f
    assert solve.refine_cache_file("fine", ["v", ["a", "b"], H + 1e-12]) != f
    assert solve.refine_cache_file("fine", ["v2", ["a", "b"], H]) != f
    c = {"a": (np.array([[1.0, 0, 0.1234567890123], [0, 1, 0], [0, 0, 1]]), 0.12)}
    solve.save_refined(f, solve.corrections_to_json(c))
    back = solve.corrections_from_json(solve.load_refined(f))
    assert np.array_equal(back["a"][0], c["a"][0]) and back["a"][1] == 0.12
    open(tmp_path / "solve" / "refine-cache" / "fine-old.json", "w").write("{}")
    solve.clean_refine_cache()
    assert sorted(p.name for p in (tmp_path / "solve" / "refine-cache").iterdir()) == [f.rsplit("/", 1)[1]]
