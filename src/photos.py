# photos/: every photo, named by its SHA-1 (<sha1>.<ext>), never re-encoded. Which photos a run works on (all of
# photos/, or the sample in sample.txt) and where its output goes (generated/ or generated-sample/), and loading a photo
# the way every step sees it: upright (its EXIF turn applied), as BGR pixels.
import os
import cv2
import numpy as np

ROOT = "photos"
SAMPLE = "sample.txt"
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".heif")


def all_photos(root=ROOT):
    """SHA-1 -> path, for every photo in root (none if there is no such folder yet)."""
    if not os.path.isdir(root):
        return {}
    return {os.path.splitext(f)[0]: os.path.join(root, f) for f in sorted(os.listdir(root))
            if f.lower().endswith(EXTENSIONS)}


def chosen(sample=False, root=ROOT, sample_file=SAMPLE):
    """SHA-1 -> path of the photos a run works on: all of them, or with sample those listed in sample_file."""
    photos = all_photos(root)
    if not sample:
        return photos
    return {s: photos[s] for s in open(sample_file, encoding="utf-8").read().split() if s in photos}


def generated(sample=False):
    """The folder a run's output goes in."""
    return "generated-sample" if sample else "generated"


def pil_open(path):
    """A PIL image of the file, with HEIC/HEIF support if pillow-heif is installed."""
    from PIL import Image
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    return Image.open(path)


def imread(path):
    """cv2.imread, from the file's bytes: OpenCV can't open a path with non-ASCII characters on Windows. A format
    OpenCV's build can't decode (AVIF in the Windows wheel) through Pillow. None if the file can't be read."""
    try:
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return None
    if img is None and path.lower().endswith((".avif", ".webp")):
        try:
            from PIL import ImageOps
            with pil_open(path) as pil:
                img = cv2.cvtColor(np.asarray(ImageOps.exif_transpose(pil).convert("RGB")), cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    return img


def write_avif(path, img, quality):
    """An 8-bit BGR image as an AVIF file: with OpenCV, or with Pillow where OpenCV's build has no AVIF writer (the
    Windows wheel). path must end in .avif."""
    try:
        if cv2.imwrite(path, img, [cv2.IMWRITE_AVIF_QUALITY, quality]):
            return
    except cv2.error:
        pass
    from PIL import Image
    Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).save(path, format="AVIF", quality=quality)


def load(path):
    """The photo, upright (OpenCV applies the EXIF orientation), as BGR pixels; formats OpenCV can't read (HEIC) through
    Pillow + pillow-heif. Read from bytes, as cv2.imread can't open paths with non-ASCII characters on Windows. None if
    it can't be read."""
    photo = imread(path)
    if photo is None:
        try:
            from PIL import ImageOps
            with pil_open(path) as img:
                rgb = np.asarray(ImageOps.exif_transpose(img).convert("RGB"))
            photo = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except Exception:
            return None
    return photo


def delete(sha1, root=ROOT, sources_file="photo-sources.json"):
    """Deletes a photo from photos/: its file and its record in photo-sources.json."""
    os.remove(all_photos(root)[sha1])
    import json, time
    if os.path.exists(sources_file):
        with open(sources_file, encoding="utf-8") as f:
            sources = json.load(f)
        if sources.pop(sha1, None) is not None:
            tmp = sources_file + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump(sources, f, indent=1, ensure_ascii=False, sort_keys=True)
                f.write("\n")
            for attempt in range(10):  # Windows refuses to replace a file another program has open; retry briefly
                try:
                    os.replace(tmp, sources_file)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.2)
