import json, os
import photos


def test_delete_removes_the_file_and_its_record(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    (root / "aa.jpg").write_bytes(b"x")
    (root / "bb.png").write_bytes(b"y")
    sources = tmp_path / "photo-sources.json"
    sources.write_text(json.dumps({"aa": {"source": "s"}, "bb": {"source": "t"}}))
    photos.delete("aa", root=str(root), sources_file=str(sources))
    assert sorted(os.listdir(root)) == ["bb.png"]
    assert json.loads(sources.read_text()) == {"bb": {"source": "t"}}

