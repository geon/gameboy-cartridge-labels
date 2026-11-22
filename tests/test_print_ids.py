import print_ids


def test_split_id():
    assert print_ids.split_id("DMG-APSJ-JPN-lisa") == ("DMG-APSJ-JPN", "lisa")
    assert print_ids.split_id("UNKNOWN-lisa-bob") == ("UNKNOWN", "lisa-bob")


def test_same_label_photo_by_key_or_by_the_old_centre_in_the_outline():
    outlines = {"s@51,50": [[400, 400], [600, 400], [600, 600], [400, 600]]}
    assert print_ids.same_label_photo("s@51,50", ["s@51,50"], outlines, {}) == "s@51,50"
    assert print_ids.same_label_photo("s@48,49", ["s@51,50"], outlines, {"s": [1000, 1000]}) == "s@51,50"
    assert print_ids.same_label_photo("s@10,10", ["s@51,50"], outlines, {"s": [1000, 1000]}) is None
