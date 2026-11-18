import json, os, struct
import cv2, numpy as np, pytest
import photos, read_text

TEXT = "DMG-APSJ-JPN"


def text_image():
    """White 600 x 200 with TEXT starting at about (40, 120) (its baseline's left end)."""
    img = np.full((200, 600, 3), 255, np.uint8)
    cv2.putText(img, TEXT, (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
    return img


TURNS = {  # name: (cv2 rotation, where the upright image's point (x, y) goes, size 600 x 200)
    "up": (None, lambda x, y: (x, y)),
    "cw": (cv2.ROTATE_90_CLOCKWISE, lambda x, y: (199 - y, x)),
    "ccw": (cv2.ROTATE_90_COUNTERCLOCKWISE, lambda x, y: (y, 599 - x)),
    "180": (cv2.ROTATE_180, lambda x, y: (599 - x, 199 - y)),
}


def test_reading_order_of_boxes():
    wide = [[0, 0], [100, 0], [100, 20], [0, 20]]
    tall = [[0, 0], [20, 0], [20, 100], [0, 100]]
    assert read_text.reading_order(wide, False)[0] == [0, 0]
    assert read_text.reading_order(wide, True)[0] == [100, 20]
    assert read_text.reading_order(tall, False)[0] == [20, 0]  # reads top down: starts top right
    assert read_text.reading_order(tall, True)[0] == [0, 100]  # reads bottom up: starts bottom left


@pytest.mark.parametrize("turn", TURNS)
def test_read_turned_text_in_reading_order(turn):
    rotation, move = TURNS[turn]
    img = text_image()
    if rotation is not None:
        img = cv2.rotate(img, rotation)
    lines = read_text.read(img)
    assert [l["text"] for l in lines] == [TEXT]
    start, along = np.array(lines[0]["corners"][0]), np.array(lines[0]["corners"][1])
    # the text's top left (upright about (40, 60)) and the reading direction (upright +x)
    assert np.hypot(*(start - move(40, 60))) < 30
    direction = np.subtract(move(1, 0), move(0, 0))
    assert np.dot((along - start) / np.linalg.norm(along - start), direction) > 0.95


def jpeg_with_orientation(img, orientation):
    """A JPEG of img with an EXIF orientation tag (1 = upright, 6 = to be turned 90° clockwise to view)."""
    data = cv2.imencode(".jpg", img)[1].tobytes()
    ifd = struct.pack("<H", 1) + struct.pack("<HHIHH", 0x0112, 3, 1, orientation, 0) + struct.pack("<I", 0)
    tiff = b"II*\x00" + struct.pack("<I", 8) + ifd
    app1 = b"\xff\xe1" + struct.pack(">H", len(tiff) + 8) + b"Exif\x00\x00" + tiff
    return data[:2] + app1 + data[2:]


def test_load_applies_exif_turn(tmp_path):
    p = tmp_path / "turned.jpg"
    p.write_bytes(jpeg_with_orientation(np.zeros((200, 600, 3), np.uint8), 6))
    assert photos.load(str(p)).shape[:2] == (600, 200)


def test_read_photo_writes_size_engine_and_lines(tmp_path):
    p, out = tmp_path / "a.png", tmp_path / "a.json"
    cv2.imwrite(str(p), text_image())
    read_text.read_photo(("a", str(p), str(out)))
    result = json.load(open(out, encoding="utf-8"))
    assert result["size"] == [600, 200]
    assert result["engine"].startswith("rapidocr ")
    assert [l["text"] for l in result["lines"]] == [TEXT]
    assert not os.path.exists(str(out) + ".tmp")


def test_unreadable_photo_gets_an_empty_result(tmp_path):
    p, out = tmp_path / "broken.jpg", tmp_path / "broken.json"
    p.write_bytes(b"not an image")
    read_text.read_photo(("broken", str(p), str(out)))
    assert json.load(open(out, encoding="utf-8")) == {"size": None, "engine": json.load(open(out, encoding="utf-8"))["engine"], "lines": []}
