"""add-photos: the photos left in save-new-images-here/ filed into photos/ as <sha1>.<ext>, as they came (never
re-encoded), with where each came from in photo-sources.json.

A subfolder names the photos' source (save-new-images-here/ebay-search/ -> source "ebay-search"); photos straight in
the folder get source "unrecorded". A subfolder's listing.json (file name -> where the photo came from: page_url,
image_url, title_on_page, and whatever else its downloader knew, as written by src/ebay_photos.py) goes into the
photo's record. A photo whose SHA-1 photos/ already has is deleted, its listing added to that photo's record (under
"also") when it differs. Anything that isn't a photo stays, and is listed. Filed photos leave the folder, their entries
leave listing.json, and emptied subfolders are removed.

photo-sources.json: SHA-1 -> {source, file (its name when added), page_url, image_url, title_on_page, ..., also: [...]}.
Output only: publish reads it, no detection step does.

Usage: add_photos.py
"""
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos  # noqa: E402

DROP_OFF = "save-new-images-here"
SOURCES = "photo-sources.json"
KEEP = {"README.md", "listing.json", ".DS_Store", "Thumbs.db", "desktop.ini"}


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def main():
    os.makedirs(photos.ROOT, exist_ok=True)
    os.makedirs(DROP_OFF, exist_ok=True)
    sources = json.load(open(SOURCES, encoding="utf-8")) if os.path.exists(SOURCES) else {}
    have = photos.all_photos()
    added, duplicates, left = 0, 0, []
    folders = [("unrecorded", DROP_OFF)] + [(d, os.path.join(DROP_OFF, d)) for d in sorted(os.listdir(DROP_OFF))
                                             if os.path.isdir(os.path.join(DROP_OFF, d))]
    for source, folder in folders:
        listing_path = os.path.join(folder, "listing.json")
        listing = json.load(open(listing_path, encoding="utf-8")) if os.path.exists(listing_path) else {}
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isdir(path) or name in KEEP:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in photos.EXTENSIONS:
                left.append(path)
                continue
            key = sha1(path)
            entry = {"source": source, "file": name, **listing.get(name, {})}
            if key in have:
                record = sources.setdefault(key, {"source": None})
                same = lambda a, b: {k: v for k, v in a.items() if k != "file"} == {k: v for k, v in b.items() if k != "file"}
                if not same(record, entry) and not any(same(a, entry) for a in record.get("also", [])):
                    record.setdefault("also", []).append(entry)
                os.remove(path)
                duplicates += 1
            else:
                dest = os.path.join(photos.ROOT, key + ext)
                shutil.move(path, dest)
                have[key] = dest
                sources[key] = entry
                added += 1
            listing.pop(name, None)
        if folder != DROP_OFF:
            if listing:
                save(listing_path, listing)
            elif os.path.exists(listing_path):
                os.remove(listing_path)
            rest = [f for f in os.listdir(folder) if f not in KEEP - {"README.md", "listing.json"}]
            if not rest:
                shutil.rmtree(folder)
    save(SOURCES, sources)
    print(f"{added} photos added to photos/, {duplicates} already there (deleted)")
    if left:
        print(f"{len(left)} files left, not photos:", *left, sep="\n  ")


if __name__ == "__main__":
    main()
