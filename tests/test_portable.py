# What differs between Windows, macOS and Linux: file locks, image sizes and HEIC, non-ASCII paths, text encoding.
import json, os, subprocess, sys, threading, time
import cv2
import numpy as np
import photos, ebay_photos


def test_lock_excludes_a_second_holder(tmp_path):
    inside, order = [], []

    def worker(name):
        with ebay_photos.locked(str(tmp_path)):
            inside.append(name)
            assert len(inside) == 1
            time.sleep(0.2)
            order.append(name)
            inside.remove(name)

    threads = [threading.Thread(target=worker, args=(n,)) for n in "ab"]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(order) == ["a", "b"]


def test_load_and_size_of_a_photo_in_a_non_ascii_folder(tmp_path):
    folder = tmp_path / "fotos ñ 日本"
    folder.mkdir()
    path = str(folder / "a.png")
    cv2.imencode(".png", np.full((30, 50, 3), 90, np.uint8))[1].tofile(path)
    assert photos.load(path).shape == (30, 50, 3)
    assert ebay_photos.size(path) == [50, 30]


def test_load_reads_heic(tmp_path):
    import pytest
    pillow_heif = pytest.importorskip("pillow_heif")
    from PIL import Image
    path = str(tmp_path / "a.heic")
    pillow_heif.register_heif_opener()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(path)
    img = photos.load(path)
    assert img.shape == (48, 64, 3) and img[0, 0, 2] > 150


def test_load_of_a_non_image_is_none(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"not an image")
    assert photos.load(str(path)) is None


def test_delete_writes_utf8_and_lf(tmp_path):
    (tmp_path / "abc.jpg").write_bytes(b"x")
    (tmp_path / "def.jpg").write_bytes(b"x")
    sources = tmp_path / "photo-sources.json"
    sources.write_text(json.dumps({"abc": "x", "def": "ポケモン é"}), encoding="utf-8")
    photos.delete("abc", root=str(tmp_path), sources_file=str(sources))
    raw = sources.read_bytes()
    assert b"\r" not in raw and "ポケモン é".encode() in raw


def test_no_photos_folder_yet_means_no_photos(tmp_path):
    assert photos.all_photos(str(tmp_path / "photos")) == {}


def test_match_worker_pool_runs_jobs_with_the_index_set_before_it():
    import match
    match._index = ([], [], [], ["a", "b"], "features")
    with match.worker_pool(2) as pool:
        assert pool.map(len, [[1], [1, 2]]) == [1, 2]
    from multiprocessing.pool import ThreadPool
    with ThreadPool(2) as pool:  # what Windows gets
        assert pool.map(lambda _: match._index[3], [0]) == [["a", "b"]]


def test_imread_reads_a_file_with_a_japanese_name(tmp_path):
    path = str(tmp_path / "アタマを.png")
    cv2.imencode(".png", np.full((10, 20, 3), 5, np.uint8))[1].tofile(path)
    assert photos.imread(path).shape == (10, 20, 3)
    assert photos.imread(str(tmp_path / "nothing.png")) is None


def test_avif_round_trip_also_without_an_opencv_avif_writer(tmp_path, monkeypatch):
    img = np.random.default_rng(0).integers(0, 255, (40, 60, 3), dtype=np.uint8)
    path = str(tmp_path / "a.avif")
    photos.write_avif(path, img, 90)
    assert photos.imread(path).shape == (40, 60, 3)
    monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: (_ for _ in ()).throw(cv2.error("no writer")))
    path2 = str(tmp_path / "b.avif")
    photos.write_avif(path2, img, 90)
    assert photos.imread(path2).shape == (40, 60, 3)
