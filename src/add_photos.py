import glob, hashlib, os, shutil, sys, cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, serials, text
from fit_cartridge import load

# add-photos: files the photos left in save-new-images-here/ into photos/ (src/photos.py). A subfolder names their
# source (save-new-images-here/ebay-elrocinante/ -> photos/ebay-elrocinante/); photos straight in the folder go to
# photos/unrecorded/. Each photo is stored as it came (never re-encoded) under the serial read on its label
# (src/serials.py: exact, or one character off); without one, as UNKNOWN. A photo already in photos/ (the same file,
# by SHA-1) is deleted; one that is the same picture as a photo in photos/, saved another way (re-encoded, another
# format: see same_picture), stays in the folder, and is listed with that photo, for you to delete or keep; anything not
# a photo stays too, and is listed. Otherwise the folder is left empty: filed photos and emptied subfolders are removed.
# Usage: add_photos.py
DROP_OFF = "save-new-images-here"
WORK = "generated/add-photos"
PHOTO = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".heif")
# Each photo's look, by SHA-1, kept between runs (photos/ is read once).
LOOKS = "generated/photo-looks.npz"
# The same picture saved twice differed by at most 0.4 (of 255) in the 2371 photos of 2026-10-30; two different photos,
# even of one cartridge cropped alike, by 5.9 or more.
SAME_PICTURE = 2.0


def look(path):
    """A photo, small and grey (64 x 64), with its width over its height; None if it can't be read."""
    photo = load(path)
    if photo is None:
        return None
    return photo.shape[1] / photo.shape[0], cv2.resize(cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY), (64, 64), interpolation=cv2.INTER_AREA)


def same_picture(a, b):
    """Whether two looks are of the same picture: as wide for their height (within 1 %), and on average within
    SAME_PICTURE of each other."""
    return abs(a[0] / b[0] - 1) < 0.01 and np.abs(a[1].astype(np.float32) - b[1]).mean() < SAME_PICTURE


def looks_of_photos():
    """The look of every photo in photos/: path -> look; read once per photo, kept in LOOKS by SHA-1."""
    kept = dict(np.load(LOOKS, allow_pickle=True)["looks"].item()) if os.path.exists(LOOKS) else {}
    looks = {}
    for source, system, name, entry in photos.all_sources():
        path = os.path.join(photos.ROOT, source, system, name)
        if entry.get("sha1") not in kept:
            kept[entry["sha1"]] = look(path)
        if kept[entry["sha1"]] is not None:
            looks[path] = kept[entry["sha1"]]
    os.makedirs(os.path.dirname(LOOKS), exist_ok=True)
    np.savez(LOOKS, looks=np.array(kept, dtype=object))
    return looks

photos.reconcile()
known = {e[k] for _, _, _, e in photos.all_sources() for k in ("sha1", "original_sha1") if e.get(k)}

# The photos to file: (source, path, SHA-1).
os.makedirs(DROP_OFF, exist_ok=True)
incoming, left, duplicates = [], [], 0
for folder in [DROP_OFF] + sorted(d for d in glob.glob(os.path.join(DROP_OFF, "*")) if os.path.isdir(d)):
    source = "unrecorded" if folder == DROP_OFF else photos.tidy(os.path.basename(folder)).lower()
    for path in sorted(glob.glob(os.path.join(folder, "*"))):
        name = os.path.basename(path)
        if os.path.isdir(path) or name == "README.md":
            continue
        if os.path.splitext(name)[1].lower() not in PHOTO:
            left.append(path)
            continue
        sha1 = hashlib.sha1(open(path, "rb").read()).hexdigest()
        if sha1 in known:
            os.remove(path)
            duplicates += 1
            continue
        known.add(sha1)
        incoming.append((source, path, sha1))

# Pictures already in photos/ (or earlier in this run), saved another way: left in the folder.
if incoming:
    looks, same = looks_of_photos(), []
    for source, path, sha1 in incoming:
        mine = look(path)
        match = next((p for p, other in looks.items() if same_picture(mine, other)), None) if mine is not None else None
        if match:
            same.append((path, match))
        elif mine is not None:
            looks[path] = mine
    incoming = [i for i in incoming if i[1] not in {p for p, _ in same}]
else:
    same = []

# The serial on each label, read from links to the photos (src/ocr reads every format here, HEIC and AVIF too).
reads = {}
if incoming:
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(os.path.join(WORK, "photos"))
    links = []
    for k, (_, path, _) in enumerate(incoming):
        links.append(os.path.join(WORK, "photos", f"p{k}{os.path.splitext(path)[1].lower()}"))
        os.symlink(os.path.abspath(path), links[-1])
    text.read(links, os.path.join(WORK, "ocr"))
    reads = {row[0]: (row[1], row[2]) for row in serials.serials(os.path.join(WORK, "ocr"))}
    shutil.rmtree(WORK)

filed = {}
for k, (source, path, sha1) in enumerate(incoming):
    status, serial = reads.get(f"p{k}", ("none", ""))
    original = os.path.basename(path)
    if status in ("exact", "near") and serial:
        name_by, how = serial, f"the serial read on it ({status})"
    else:
        name_by, how = "UNKNOWN", "nothing: no serial read"
    entry = dict(original_name=original, serial_on_label=serial or None, note=f"named by {how}")
    name = photos.add(name_by, open(path, "rb").read(), os.path.splitext(original)[1], {key: value for key, value in entry.items() if value is not None}, source)
    os.remove(path)
    filed.setdefault(source, []).append(name)
    print(f"{source}/{original}\t-> {name}\t({how})")

# The emptied subfolders.
for folder in sorted(d for d in glob.glob(os.path.join(DROP_OFF, "*")) if os.path.isdir(d)):
    if not [n for n in os.listdir(folder) if n != ".DS_Store"]:
        shutil.rmtree(folder)
for source, names in sorted(filed.items()):
    print(f"{source}: {len(names)} filed, {sum(n.startswith('UNKNOWN') for n in names)} of them as UNKNOWN")
if duplicates:
    print(f"{duplicates} already in photos/, deleted")
for path, match in same:
    print(f"left, the same picture as {match}: {path}")
for path in left:
    print(f"left, not a photo: {path}")
if not (incoming or duplicates or same or left):
    print(f"nothing to file in {DROP_OFF}/")
