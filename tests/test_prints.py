import numpy as np
import prints


def differ_matrix(n, tiles, differ=()):
    """Different nowhere, except: for (members, tile range) in differ, those members different from the rest there."""
    D = np.zeros((n, n, tiles), bool)
    for members, ts in differ:
        for i in range(n):
            for j in range(n):
                if (i in members) != (j in members):
                    D[i, j, ts] = True
    return D


def test_different_text_on_a_few_tiles_splits_the_family():
    D = differ_matrix(4, 50, [({2, 3}, slice(10, 13))])            # a region code: three tiles
    groups, differs = prints.split_family(D)
    assert sorted(sorted(g) for g in groups) == [[0, 1], [2, 3]]
    assert differs[10:13].all() and not differs[:10].any()


def test_a_single_label_photo_with_other_text_is_a_print_of_its_own():
    D = differ_matrix(3, 50, [({2}, slice(10, 13))])
    assert sorted(sorted(g) for g in prints.split_family(D)[0]) == [[0, 1], [2]]


def test_a_speck_on_one_or_two_tiles_doesnt_split():
    D = differ_matrix(3, 50, [({2}, slice(10, 12))])
    assert len(prints.split_family(D)[0]) == 1


def test_one_dirty_label_photo_doesnt_split_a_print_whose_others_agree():
    # 0-3 one print; 3 differs from 1 only (a smudge on one of them): most cross pairs agree, one print
    D = differ_matrix(4, 50)
    D[1, 3, 10:14] = D[3, 1, 10:14] = True
    assert len(prints.split_family(D)[0]) == 1


def test_pair_cache_round_trip(tmp_path):
    a = np.zeros((18, 21), bool); a[3, 4] = a[17, 20] = True
    b = np.ones((10, 21), bool)
    path = str(tmp_path / "pairs.npz")
    prints.save_pairs(path, "v1", {"x@1,1|y@1,1|1:2|3:4": a, "x@1,1|z@1,1|1:2|5:6": b})
    back = prints.load_pairs(path, "v1")
    assert np.array_equal(back["x@1,1|y@1,1|1:2|3:4"], a) and np.array_equal(back["x@1,1|z@1,1|1:2|5:6"], b)
    assert prints.load_pairs(path, "v2") == {}


def test_a_frozen_group_stays_one_print_others_may_join_two_frozen_never_merge():
    D = differ_matrix(5, 50)                                       # all alike
    groups, _ = prints.split_family(D, [[0, 1], [2, 3]])
    assert sorted(sorted(g) for g in groups) in ([[0, 1, 4], [2, 3]], [[0, 1], [2, 3, 4]])
    D = differ_matrix(3, 50, [({1}, slice(10, 13))])               # 1 differs from 0 and 2
    groups, _ = prints.split_family(D, [[0, 1]])                   # frozen together anyway
    assert sorted(sorted(g) for g in groups) == [[0, 1, 2]] or sorted(sorted(g) for g in groups) == [[0, 1], [2]]
    assert any(sorted(g)[:2] == [0, 1] for g in groups)


def test_a_prints_release_only_of_its_serials_game():
    stray = {"serial": "AGB-AW2E-USA", "release": "AGB-AW2E"}
    assert prints.print_release("AGB-BSPE-USA", [{"serial": "AGB-BSPE-USA", "release": None}] * 7 + [stray]) is None
    assert prints.print_release("AGB-AC6D-NOE", [{"serial": None, "release": "AGB-AC6P"}]) == "AGB-AC6P"  # another language
    assert prints.print_release("DMG-A05J-JPN", [{"serial": "DMG-AO5J-JPN", "release": "DMG-AO5J"}]) == "DMG-AO5J"  # look-alike
    assert prints.print_release("DMG-NR", [{"serial": "DMG-NRJ", "release": "DMG-NRJ"}]) == "DMG-NRJ"
    assert prints.print_release("AGB-AIGP-EUR-2", [{"serial": "AGB-AIGP", "release": "AGB-AIGP"}]) == "AGB-AIGP"
    reads = [{"serial": "DMG-ZL-USA", "release": "DMG-ZL"}] * 2 + [{"serial": "DMG-ZLJ-JPN", "release": "DMG-ZLJ"}]
    assert prints.print_release("DMG-ZL-USA", reads) == "DMG-ZL"
    assert prints.print_release(None, [stray]) == "AGB-AW2E"  # no serial: all its label photos
