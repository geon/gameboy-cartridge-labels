from collections import Counter
import read_serials

DATABASE = {"DMG-BQ": {"id": "dmg-bq"}, "DMG-BQIJ-JPN": {"id": "dmg-bqij"}, "DMG-APSJ-JPN": {"id": "dmg-apsj"},
            "DMG-APBJ-JPN": {"id": "dmg-apbj"}}


def r(serial, kind="exact"):
    return {"text": serial, "serial": serial, "kind": kind, "from": "straightened"}


def test_own_read_wins():
    assert read_serials.decide([r("DMG-APSJ-JPN")], Counter({"dmg-apbj": 5}), DATABASE, 5)[1:] == ("dmg-apsj", "own")


def test_several_own_releases_settled_by_the_family():
    serial, release, how = read_serials.decide([r("DMG-APSJ-JPN"), r("DMG-APBJ-JPN")], Counter({"dmg-apbj": 3}), DATABASE, 3)
    assert (release, how) == ("dmg-apbj", "own, with its title or family")


def test_family_passes_a_serial_on_only_with_a_majority():
    reads = [r("DMG-BON", "unknown")]
    assert read_serials.decide(reads, Counter({"dmg-bq": 1}), DATABASE, 4)[2] == "unknown"   # 1 of 4 read DMG-BQ
    assert read_serials.decide(reads, Counter({"dmg-bqij": 3}), DATABASE, 4)[1:] == ("dmg-bqij", "family")
    assert read_serials.decide([], Counter({"dmg-bqij": 1}), DATABASE, 1)[1:] == ("dmg-bqij", "family")


def test_the_title_settles_several_own_reads():
    title = lambda rid: {"dmg-apsj": 0.9, "dmg-apbj": 0.1}.get(rid, 0)
    serial, release, how = read_serials.decide([r("DMG-APSJ-JPN"), r("DMG-APBJ-JPN")], Counter({"dmg-apbj": 3}), DATABASE, 3, title)
    assert release == "dmg-apsj"


def test_a_cut_off_read_gives_way_to_the_whole_one():
    db = {"DMG-VF": {"id": "dmg-vf"}, "DMG-VFJ": {"id": "dmg-vfj"}}
    assert read_serials.decide([r("DMG-VF"), r("DMG-VFJ")], Counter({"dmg-vf": 2}), db, 2)[1] == "dmg-vfj"


def test_straightened_serial_is_the_straightened_images_own_exact_read_only():
    s = lambda serial, kind="exact", where="straightened": {"text": serial, "serial": serial, "kind": kind, "from": where}
    assert read_serials.straightened_serial([s("DMG-APSJ-JPN"), s("DMG-APSJ-JPN")]) == "DMG-APSJ-JPN"
    assert read_serials.straightened_serial([s("DMG-APSJ-JPN", where="photo")]) is None
    assert read_serials.straightened_serial([s("DMG-APSJ-JPN", kind="near")]) is None
    assert read_serials.straightened_serial([s("DMG-APSJ-JPN"), s("DMG-APBJ-JPN")]) is None
