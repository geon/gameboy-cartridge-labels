import os, pytest
import stored_prints as sp


def lp(k):
    return {k: {"outline": [[0, 0], [1, 0], [1, 1]], "pose": {"photo": k.split("@")[0]}}}


@pytest.fixture
def store(tmp_path):
    s = sp.Store(str(tmp_path / "prints.json"), folder=str(tmp_path / "frozen"))
    return s


def test_make_add_split_join_and_save_round_trip(store):
    a = store.make({**lp("a@1,1"), **lp("b@1,1")}, "DMG-APSJ-JPN", manual=False)
    assert a.startswith("DMG-APSJ-JPN-")
    store.add(a, lp("c@1,1"), manual=False)
    b = store.split(a, ["c@1,1"], manual=True)
    assert sorted(store.prints[b]["label_photos"]) == ["c@1,1"] and store.prints[b]["split_from"] == a
    into = store.join([a, b], manual=True)
    assert into == a and b in store.data["gone"] and store.data["gone"][b]["into"] == a
    store.save()
    again = sp.load(store.path)
    assert again["prints"] == store.data["prints"] and again["gone"] == store.data["gone"]


def test_an_automatic_change_to_a_frozen_print_raises_and_changes_nothing(store):
    a = store.make(lp("a@1,1"), "DMG-APSJ-JPN", manual=False)
    store.freeze(a, {}, "DMG", {"sha1": "x"}, {})
    before = sp._dump(store.data["prints"])
    for change in (lambda: store.add(a, lp("b@1,1"), manual=False), lambda: store.remove(a, ["a@1,1"], manual=False),
                   lambda: store.split(a, ["a@1,1"], manual=False), lambda: store.set_serial(a, "DMG-APBJ-JPN", manual=False),
                   lambda: store.write_back(a, lp("a@1,1"))):
        with pytest.raises(sp.FrozenError):
            change()
    assert sp._dump(store.data["prints"]) == before


def test_a_manual_change_unfreezes_but_its_own_serial_doesnt(store):
    a = store.make(lp("a@1,1"), "DMG-APSJ-JPN", manual=False)
    store.freeze(a, {}, "DMG", {"sha1": "x"}, {})
    assert store.set_serial(a, "DMG-APSJ-JPN", manual=True) == a and store.prints[a]["frozen"]
    store.add(a, lp("b@1,1"), manual=True)
    assert not store.prints[a]["frozen"]


def test_set_serial_renames_keeping_the_name(store):
    a = store.make(lp("a@1,1"), "DMG-APSJ-JPN", manual=False)
    name = a.split("-")[-1]
    b = store.set_serial(a, "DMG-APBJ-JPN", manual=True)
    assert b == "DMG-APBJ-JPN-" + name and store.data["gone"][a]["why"] == "renamed"


def test_undo_restores_a_join_with_its_frozen_print(store, tmp_path):
    a = store.make(lp("a@1,1"), "DMG-APSJ-JPN", manual=False)
    b = store.make(lp("b@1,1"), "DMG-APSJ-JPN", manual=False)
    store.freeze(a, {}, "DMG", {"sha1": "x"}, {})
    os.makedirs(store.folder)
    open(os.path.join(store.folder, a + ".avif"), "w").write("image")
    store.join([a, b], manual=True, into=a)
    assert not store.prints[a]["frozen"]
    assert store.undo() is None
    assert store.prints[a]["frozen"] and store.prints[a]["image"] == {"sha1": "x"}
    assert sorted(store.prints[b]["label_photos"]) == ["b@1,1"] and b not in store.data["gone"]


def test_undo_restores_removed_label_photos(store):
    a = store.make({**lp("a@1,1"), **lp("b@1,1")}, "DMG-APSJ-JPN", manual=False)
    store.remove(a, ["b@1,1"], manual=True)
    assert store.undo() is None
    assert sorted(store.prints[a]["label_photos"]) == ["a@1,1", "b@1,1"]


def test_the_stamp_changes_only_with_the_frozen_prints(store):
    a = store.make(lp("a@1,1"), "DMG-APSJ-JPN", manual=False)
    store.save()
    stamp = store.path + ".frozen-changed"
    first = open(stamp).read()
    store.add(a, lp("b@1,1"), manual=False)
    store.save()
    assert open(stamp).read() == first
    store.freeze(a, {}, "DMG", {"sha1": "x"}, {})
    store.save()
    assert open(stamp).read() != first
