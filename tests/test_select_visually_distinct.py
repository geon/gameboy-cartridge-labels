import numpy as np
import select_visually_distinct as svd


def pairs(d):
    out = {}
    for (a, b), s in d.items():
        out[a, b] = out[b, a] = s
    return out


def test_alike_prints_of_a_game_shown_once_the_most_used_kept():
    games = {"a": "G", "b": "G", "c": "G", "x": None, "y": None}
    used = {"a": 3, "b": 7, "c": 5, "x": 3, "y": 3}
    differ = pairs({("a", "b"): 0.1, ("a", "c"): 0.9, ("b", "c"): 0.8})
    kept, left_out = svd.select(list(games), games, used, differ)
    assert kept == ["b", "c", "x", "y"]          # b first (most used); c differs enough; unknown games all kept
    assert left_out == {"a": "b"}


def test_left_out_only_when_alike_a_kept_one():
    # b and c both alike a, but not alike each other: a kept (most used), b and c left out, each by a
    games = dict.fromkeys("abc", "G")
    differ = pairs({("a", "b"): 0.3, ("a", "c"): 0.2, ("b", "c"): 0.9})
    kept, left_out = svd.select(list(games), games, {"a": 9, "b": 5, "c": 4}, differ)
    assert kept == ["a"] and left_out == {"b": "a", "c": "a"}


def test_the_cutoff_and_a_missing_pair():
    games = dict.fromkeys("abc", "G")
    differ = pairs({("a", "b"): svd.DISTINCT})  # at the cutoff: different enough; a, c not compared (shapes): kept
    kept, _ = svd.select(list(games), games, dict.fromkeys("abc", 1), differ)
    assert kept == ["a", "b", "c"]


def test_identical_prints_differ_nowhere_and_a_recoloured_one_everywhere():
    rng = np.random.default_rng(0)
    A = np.full((40 * svd.PX, 50 * svd.PX, 3), 0.8, np.float32)
    for _ in range(40):  # some art: blocks of colour
        x, y = rng.integers(0, 45 * svd.PX), rng.integers(0, 35 * svd.PX)
        A[y:y + 4 * svd.PX, x:x + 4 * svd.PX] = rng.random(3)
    assert svd.compare(A, A.copy())[0] == 0
    B = A.copy()
    B[..., [0, 2]] = A[..., [2, 0]]  # blue and red swapped
    B = 1 - B                        # and inverted
    assert svd.compare(A, B)[0] > svd.DISTINCT
