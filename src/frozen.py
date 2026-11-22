# Frozen prints (persistent-prints.md stage 2; since 2026-11-22 stored-prints.md): prints the user accepted, now the
# prints in the store (src/stored_prints.py, prints.json) whose "frozen" is true. This module is a view of them in the
# shape the steps read (find, solve, prints, restore, publish, match, select-visually-distinct):
#   load(): {print id: {"datetime" (frozen at), "serial", "shape", "image" (its SHA-1), "crop" (restore's), "paper",
#            "restored_from" (the label photos the image was restored from), "label_photos": {key: its stored pose,
#            plus "found": its stored outline}, "photo_label_photos"}}
#   frozen/<print id>.avif: the restored image, as restore made it (committed).
# Freeze, refreeze and unfreeze change the store through its interface (manual: the user's say). FILE is the store's
# stamp, touched only when the frozen prints change: the steps redo their work when it's newer than their output.
import datetime, json, os, shutil, hashlib
import stored_prints

FILE = stored_prints.STAMP
DIR = "frozen"


def view(p):
    img = p.get("image") or {}
    return {"datetime": p.get("frozen_at"), "serial": p.get("serial"), "shape": p.get("shape"), "image": img.get("sha1"),
            "crop": img.get("crop"), "paper": img.get("paper"), "restored_from": img.get("restored_from"),
            "refrozen": img.get("refrozen"),
            "label_photos": {k: {**(r.get("pose") or {}), "found": r.get("outline")} for k, r in p["label_photos"].items()},
            "photo_label_photos": p.get("photo_label_photos", {})}


def load(path=None):
    return {pid: view(p) for pid, p in stored_prints.load(path)["prints"].items() if p.get("frozen")}


def image_path(pid, folder=None):
    return os.path.join(folder or DIR, pid + ".avif")


def _image(pid, restored_base, folder):
    desc = json.load(open(restored_base + ".json"))
    os.makedirs(folder or DIR, exist_ok=True)
    shutil.copyfile(restored_base + ".avif", image_path(pid, folder) + ".tmp")
    os.replace(image_path(pid, folder) + ".tmp", image_path(pid, folder))
    return {"sha1": hashlib.sha1(open(image_path(pid, folder), "rb").read()).hexdigest(), "crop": desc["crop"],
            "restored_from": desc["keys"], "paper": desc.get("paper")}


def freeze(pid, print_entry, solved, found_outlines, restored_base, path=None, folder=None):
    """Freezes a stored print: its entry from the prints step's prints.json (print_entry), its label photos' records from
    solve.json (solved) and find's outlines (key -> outline) as their stored pose and outline, restore's output
    (restored_base + .avif, .json) as its image."""
    store = stored_prints.Store(path, folder)
    image = _image(pid, restored_base, folder)
    keys = [k for k in print_entry["keys"] if k in solved]
    store.freeze(pid, {k: {"outline": found_outlines.get(k), "pose": solved[k]} for k in keys}, print_entry["shape"], image,
                 # each of its photos' label photos then (match leaves a photo out once all of them are frozen)
                 {photo: sorted(k for k, r in solved.items() if r["photo"] == photo) for photo in {solved[k]["photo"] for k in keys}})
    store.save()


def refreeze(pid, restored_base, path=None, folder=None):
    """A frozen print's image replaced by restore's output (restored with its frozen crop): the rest kept."""
    store = stored_prints.Store(path, folder)
    image = _image(pid, restored_base, folder)
    image.pop("crop")
    store.refreeze(pid, image)
    store.save()


def unfreeze(pid, path=None, folder=None):
    """Unfrozen (its image stays at frozen/<id>.avif, for Undo; freezing again overwrites it)."""
    store = stored_prints.Store(path, folder)
    if pid in store.prints:
        store.unfreeze(pid)
        store.save()


def images(entries=None):
    """image SHA-1 -> (print id, path) of every frozen print's image (match indexes them as if they were photos)."""
    entries = load() if entries is None else entries
    return {e["image"]: (pid, image_path(pid)) for pid, e in entries.items() if os.path.exists(image_path(pid))}


def left_out_of_matching(entries=None):
    """Photos all of whose label photos were in frozen prints when frozen (persistent-prints.md stage 2): match leaves
    them out. A photo's label photos when frozen: each entry's "photo_label_photos"."""
    entries = load() if entries is None else entries
    frozen_keys = {k for e in entries.values() for k in e["label_photos"]}
    had = {}
    for e in entries.values():
        for photo, keys in e.get("photo_label_photos", {}).items():
            had.setdefault(photo, set()).update(keys)
    return {photo for photo, keys in had.items() if keys <= frozen_keys}


def cut_corners(record):
    """A frozen label photo's cut in its photo's pixels (top left, top right, bottom right, bottom left)."""
    import numpy as np, cuts
    return cuts.corners_in_ink(np.float64(record["cut_to_photo"]), record["shape"], record.get("width_mm"), record.get("height_mm"))


def label_photos(entries, present=None):
    """key -> (print id, record) of every frozen label photo, those of photos in present only (if given)."""
    return {k: (pid, r) for pid, e in entries.items() for k, r in e["label_photos"].items()
            if present is None or r["photo"] in present}
