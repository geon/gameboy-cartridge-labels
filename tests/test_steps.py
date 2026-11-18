import json, os, time
import numpy as np
import steps


def test_stale_when_missing_or_older_than_code(tmp_path):
    code, out = tmp_path / "code.py", tmp_path / "out.json"
    code.write_text("")
    assert steps.stale(str(out), str(code))
    out.write_text("{}")
    os.utime(out, (time.time() + 10, time.time() + 10))
    assert not steps.stale(str(out), str(code))
    os.utime(code, (time.time() + 20, time.time() + 20))
    assert steps.stale(str(out), str(code))


def test_writes_leave_no_temporary_files(tmp_path):
    steps.write_json(str(tmp_path / "a.json"), {"x": "ゲーム"})
    steps.write_npz(str(tmp_path / "a.npz"), x=np.arange(3))
    assert sorted(os.listdir(tmp_path)) == ["a.json", "a.npz"]
    assert json.load(open(tmp_path / "a.json", encoding="utf-8")) == {"x": "ゲーム"}
    assert np.load(tmp_path / "a.npz")["x"].tolist() == [0, 1, 2]


def test_remove_orphans_keeps_chosen_and_other_files(tmp_path):
    for f in ("aaa.json", "bbb.json", "index.html"):
        (tmp_path / f).write_text("")
    steps.remove_orphans(str(tmp_path), {"aaa": "photos/aaa.jpg"}, ".json")
    assert sorted(os.listdir(tmp_path)) == ["aaa.json", "index.html"]
