import numpy as np
import find

DATABASE = {"DMG-APSJ-JPN": {"id": "dmg-1"}}
H_SHIFT = np.array([[1.0, 0, 100], [0, 1, 50], [0, 0, 1]])  # a's pixels -> b's


def line(text, x, y, h=20):
    return {"text": text, "confidence": 1.0, "corners": [[x, y], [x + 10 * h, y], [x + 10 * h, y + h], [x, y + h]]}


def points(x0, y0, x1, y1, n=40, seed=0):
    return np.random.default_rng(seed).uniform([x0, y0], [x1, y1], (n, 2))


def inliers(pa, H):
    pb = (np.c_[pa, np.ones(len(pa))] @ H.T)[:, :2]
    return np.hstack([pa, pb]).astype(np.float32)


def run(texts, matches):
    chosen = {s: f"photos/{s}.jpg" for s in texts}
    return find.find(chosen, texts, matches, DATABASE)


def test_group_keeps_one_label_together_and_two_apart():
    s = lambda x, y: {"centre": [x, y], "height": 20.0}
    groups = find.group([s(100, 100), s(150, 120), s(2000, 100)])
    assert sorted(len(g) for g in groups) == [1, 2]


def test_serial_spreads_through_a_match_but_not_through_a_watermark():
    texts = {"a": {"size": [1000, 1000], "lines": [line("DMG-APSJ-JPN", 300, 300)]},
             "b": {"size": [1000, 1000], "lines": []},
             "c": {"size": [1000, 1000], "lines": []}}
    label = points(200, 200, 600, 600)        # inside a's label: within RADIUS line heights of the serial
    watermark = points(0, 0, 1000, 1000)      # spread over the whole photo, mostly outside the label
    watermark = watermark[np.hypot(*(watermark - [400, 310]).T) > 28 * 20 + 50]
    result = run(texts, [("a", "b", H_SHIFT, inliers(label, H_SHIFT)),
                         ("a", "c", np.eye(3), inliers(watermark, np.eye(3)))])
    by_photo = {lp["photo"]: lp for lp in result["label_photos"]}
    assert by_photo["a"]["found_by"] == "serial" and by_photo["a"]["shape"] == "dmg"
    assert by_photo["b"]["found_by"] == "match" and by_photo["b"]["shape"] == "dmg"
    assert "c" not in by_photo
    assert [sorted(s) for s in result["sets"]] == [sorted([by_photo["a"]["key"], by_photo["b"]["key"]])]


def test_unknown_string_needs_a_match_to_a_serial_looking_string():
    texts = {"a": {"size": [1000, 1000], "lines": [line("DMG-ZZZZ-JPN", 300, 300)]},
             "b": {"size": [1000, 1000], "lines": [line("DMG-ZZZ2-JPN", 400, 350)]},
             "c": {"size": [1000, 1000], "lines": [line("DMG-QQQQ-JPN", 300, 300)]}}
    result = run(texts, [("a", "b", H_SHIFT, inliers(points(200, 200, 600, 600), H_SHIFT))])
    found = {lp["photo"]: lp["found_by"] for lp in result["label_photos"]}
    assert found == {"a": "string and match", "b": "string and match"}
    assert [r["photo"] for r in result["rejected"]] == ["c"]


def test_overlapping_label_photos_of_one_photo_are_merged():
    a = {"photo": "p", "centre": np.array([100.0, 100]), "radius": 500, "strings": [{"corners": [[0, 0], [10, 0], [10, 5], [0, 5]], "serial": "DMG-APSJ-JPN", "kind": "exact"}],
         "points": [points(0, 0, 400, 400)], "found_by": "serial", "links": []}
    b = {"photo": "p", "centre": np.array([300.0, 300]), "radius": 500, "strings": [], "points": [points(50, 50, 450, 450, seed=1)],
         "found_by": "match", "links": []}
    far = {"photo": "p", "centre": np.array([2000.0, 300]), "radius": 500, "strings": [], "points": [points(1800, 100, 2200, 500)],
           "found_by": "match", "links": []}
    for lp in (a, b, far):
        lp["outline"] = find.outline(lp)
    merged = find.merge_overlapping([a, b, far])
    assert len(merged) == 2 and merged[0] is a and merged[0]["found_by"] == "serial" and len(a["points"]) == 2


def test_key_is_the_centre_in_percent():
    assert find.key("abc", [512.0, 250.0], [1024, 1000]) == "abc@50,25"


def test_an_area_marked_not_a_label_holds_no_label_photo_and_spreads_none():
    texts = {"a": {"size": [1000, 1000], "lines": [line("DMG-APSJ-JPN", 300, 300)]},
             "b": {"size": [1000, 1000], "lines": []}}
    label = points(200, 200, 600, 600)
    matches = [("a", "b", H_SHIFT, inliers(label, H_SHIFT))]
    chosen = {s: f"photos/{s}.jpg" for s in texts}
    around = {"a": [np.float32([[150, 150], [700, 150], [700, 700], [150, 700]])]}
    result = find.find(chosen, texts, matches, DATABASE, not_labels=around)
    assert result["label_photos"] == []
    assert result["rejected"][0]["why"] == "in an area marked not a label"
    # marked in b only: a's label photo stays, nothing spreads into b
    shifted = {"b": [np.float32([[250, 200], [800, 200], [800, 750], [250, 750]])]}
    result = find.find(chosen, texts, matches, DATABASE, not_labels=shifted)
    assert [lp["photo"] for lp in result["label_photos"]] == ["a"]


def test_a_stored_label_photo_is_taken_as_it_is_and_new_photos_link_to_it():
    texts = {"a": {"size": [1000, 1000], "lines": [line("DMG-APSJ-JPN", 300, 300)]},
             "b": {"size": [1000, 1000], "lines": []}}
    label = points(200, 200, 600, 600)
    chosen = {s: f"photos/{s}.jpg" for s in texts}
    cut = [[180.0, 180.0], [620.0, 180.0], [620.0, 620.0], [180.0, 620.0]]
    for frozen, found_by in ((True, "frozen"), (False, "stored")):
        fz = {"a@12,34": {"photo": "a", "cut": cut, "found": None, "shape": "dmg", "frozen": frozen}}
        result = find.find(chosen, texts, [("a", "b", H_SHIFT, inliers(label, H_SHIFT))], DATABASE, stored_lps=fz)
        by_key = {lp["key"]: lp for lp in result["label_photos"]}
        assert by_key["a@12,34"]["found_by"] == found_by and by_key["a@12,34"]["outline"] == cut
        assert [lp["photo"] for lp in result["label_photos"]].count("a") == 1  # the serial's candidate is taken
        assert any(r["why"] == "in a stored label photo's area" for r in result["rejected"])
    b = [lp for lp in result["label_photos"] if lp["photo"] == "b"]
    assert len(b) == 1 and b[0]["matches"][0]["to"] == "a@12,34"               # spread into b, linked to it


def test_a_match_with_a_frozen_print_image_makes_a_label_photo_tagged_with_it():
    texts = {"b": {"size": [1000, 1000], "lines": []}}
    chosen = {"b": "photos/b.jpg"}
    img_pts = points(50, 50, 700, 600)
    H_img_to_b = np.array([[1.0, 0, 100], [0, 1, 80], [0, 0, 1]])
    inl = inliers(img_pts, H_img_to_b)                      # in the image's file: image -> b
    images = {"img1": {"print": "DMG-APSJ-JPN-zoe", "crop": {"x": 0, "y": 0, "w": 840, "h": 740}, "shape": "dmg"}}
    result = find.find(chosen, texts, [("img1", "b", H_img_to_b, inl)], DATABASE, frozen_images=images)
    (lp,) = result["label_photos"]
    assert lp["photo"] == "b" and lp["found_by"] == "frozen print" and lp["frozen_print"] == "DMG-APSJ-JPN-zoe"
    assert np.allclose(lp["frozen_match"], np.linalg.inv(H_img_to_b)) and lp["shape"] == "dmg"
