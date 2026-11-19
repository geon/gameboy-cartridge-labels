import wanted

CUT = [[10, 0, 0], [0, 10, 0], [0, 0, 1]]  # 10 photo px per mm


def rec(**kw):
    return {"shape": "dmg", "cut_to_photo": CUT, **kw}


def test_wanted_skips_a_game_with_an_image_in_its_region_group_and_ranks_agreeing_first():
    releases = {"DMG-A": {"id": "DMG-A", "title": "Game A", "system": "dmg", "cartridgeSerials": [{"serial": "DMG-A-USA"}, {"serial": "DMG-A-NOE"}]},
                "DMG-B": {"id": "DMG-B", "title": "Game B", "system": "dmg", "cartridgeSerials": [{"serial": "DMG-B-JPN"}]},
                "DMG-C": {"id": "DMG-C", "title": "Game C", "system": "dmg", "cartridgeSerials": [{"serial": "DMG-C-USA"}]}}
    prints = [{"id": "a-usa", "keys": ["1@1,1", "2@1,1", "3@1,1"], "release": "DMG-A", "serial": "DMG-A-USA"},
              {"id": "a-noe", "keys": ["4@1,1", "5@1,1"], "release": "DMG-A", "serial": "DMG-A-NOE"},  # USA has an image
              {"id": "b", "keys": ["6@1,1", "7@1,1"], "release": "DMG-B", "serial": "DMG-B-JPN"},
              {"id": "c", "keys": ["8@1,1", "9@1,1"], "release": "DMG-C", "serial": "DMG-C-USA"},
              {"id": "c1", "keys": ["10@1,1"], "release": "DMG-C", "serial": "DMG-C-USA"}]
    solved = {f"{i}@1,1": rec() for i in range(1, 11)}
    serials = {"6@1,1": {"serial": "DMG-B-JPN"}, "7@1,1": {"serial": "DMG-B-JPN"},
               "8@1,1": {"serial": "DMG-C-USA"}, "9@1,1": {"serial": "DMG-C-USA"}}
    differences = {("6@1,1", "7@1,1"): 2, ("8@1,1", "9@1,1"): 0}
    out = wanted.entries(prints, {"a-usa"}, solved, serials, releases, {}, differences)
    assert [(e["print"], e["needed"], e["agree"]) for e in out] == [("c", 1, True), ("b", 1, False), ("c1", 2, None)]
    assert out[0]["px_per_mm"] == 10


def test_poor_fits_and_approximate_cuts_count_as_missing():
    solved = {"a": rec(), "b": rec(fallback="a poor fit"), "c": rec(edge={"label_used": False})}
    assert wanted.needed(["a", "b", "c"], solved) == 1
    assert wanted.needed(["a", "c"], {"a": rec(edge={"label_used": False}), "c": rec(edge={"label_used": False})}) == 2
