"""Cartridge photos from Golisto (golisto.com), from whole categories, not searches.

The category pages (https://golisto.com/explore/video-games-and-consoles/nintendo/<platform>/games?page=<n>, platforms
game-boy, game-boy-color and gba, 40 listings a page) load with plain curl. Their data is Next.js flight data (the
strings of the page's self.__next_f.push([1, "..."]) calls, each decoded as JSON): a GraphQL result whose
"edges":[{"__typename":"SearchResultCardEdge", ...}] hold each listing's goodId, title and imageUrl, the listing's first
photo at full size (https://golisto.fra1.cdn.digitaloceanspaces.com/img/<base64 JSON>.webp; the JSON holds its width and
height: 3000x3000 seen). The listing pages' URLs are in the page's JSON-LD ItemList. Crawled 2026-11-18, one page every
3 to 5 s; the listings, one record each, are in downloaded-photos/golisto-listings.json.

Manuals are left out (the user, 2026-11-18): titles naming a manual and no cartridge (MANUAL_ONLY). Complete-in-box
listings come last. A photo under MIN_SIDE on its long side (read from the URL, before downloading) is not downloaded.

    python3 src/golisto_photos.py download downloaded-photos/golisto-listings.json

Photos go to downloaded-photos/golisto-category/ as golisto-<goodId>.webp (the goodId's base64 decoded: Good:<n>) with a
listing.json there, moved to save-new-images-here/ by make move-downloads for make add-photos. Records:
downloaded-photos/golisto-sources.json (every listing whose photo was downloaded or found too small, also those deleted
by hand afterwards: never downloaded again).
"""
import base64
import datetime
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import ebay_photos  # noqa: E402
from ebay_photos import load, locked, save, size  # noqa: E402

OUT = os.environ.get("GOLISTO_OUT", ebay_photos.DOWNLOADED)
DROP = os.environ.get("GOLISTO_DROP", os.path.join(ebay_photos.DOWNLOADED, "golisto-category"))
LISTING = os.path.join(DROP, "listing.json")
SOURCES = os.path.join(OUT, "golisto-sources.json")
MIN_SIDE = 1200
MANUAL = re.compile(r"manual|manuel|anleitung|handbok|instruction|booklet|häfte", re.I)
# A cartridge besides the manual: complete, boxed, "game + manual", "with manual" and the like.
WITH_CARTRIDGE = re.compile(r"\bcib\b|complete|komplet|boxed|\bbox\b|(\b(with|w/|med|inkl\w*|incl\w*|and|og)|\+|&)\s*(\w+\s+)?manual|"
                            r"\b(cart|cartridge|modul|kassett|game and)\b", re.I)
CIB = re.compile(r"\bcib\b|complete|komplet|boxed|\bbox\b|\bin box\b|\bovp\b|\bæske", re.I)


def is_manual(title):
    return bool(MANUAL.search(title or "")) and not WITH_CARTRIDGE.search(title or "")


def is_cib(title):
    return bool(CIB.search(title or ""))


def item_id(good_id):
    """'R29vZDoxOTEzMzU=' (base64 of 'Good:191335') -> '191335'."""
    return base64.b64decode(good_id).decode().split(":")[-1]


def url_size(image_url):
    """[width, height] from the image URL's base64 JSON, or None."""
    try:
        d = json.loads(base64.b64decode(image_url.rsplit("/", 1)[1].split(".")[0]))["dimensions"]
        return [d["width"], d["height"]]
    except Exception:
        return None


def download(listings_file):
    listings = [v for v in json.load(open(listings_file)) if not is_manual(v["title"])]
    listings.sort(key=lambda v: is_cib(v["title"]))  # stable: page order otherwise
    sources = load(SOURCES)
    today = datetime.date.today().isoformat()
    done = kept = small = 0
    for v in listings:
        item = item_id(v["goodId"])
        ext = os.path.splitext(v["imageUrl"])[1] or ".webp"
        name = f"golisto-{item}{ext}"
        if name in sources or not v.get("imageUrl"):
            continue
        record = {"item": item, "platform": v["platform"], "listing": v["url"], "listing_title": v["title"],
                  "image": v["imageUrl"], "cib": is_cib(v["title"]), "fetched": today}
        wh = url_size(v["imageUrl"])
        if wh and max(wh) < MIN_SIDE:
            sources[name] = {**record, "size": wh, "too_small": True}
            small += 1
            save(SOURCES, sources)
            continue
        os.makedirs(DROP, exist_ok=True)
        path = os.path.join(DROP, name)
        ok = subprocess.run(["curl", "-sSf", "-A", "Mozilla/5.0", "-o", path, v["imageUrl"]],
                            stderr=subprocess.DEVNULL).returncode == 0
        time.sleep(1)
        if not ok:
            if os.path.exists(path):
                os.remove(path)
            print("failed", item, v["imageUrl"], flush=True)
            continue
        wh = size(path)
        if max(wh) < MIN_SIDE:
            os.remove(path)
            sources[name] = {**record, "size": wh, "too_small": True}
            small += 1
        else:
            sources[name] = {**record, "size": wh}
            with locked(DROP):
                listing = load(LISTING)
                listing[name] = {"page_url": v["url"], "image_url": v["imageUrl"], "title_on_page": v["title"],
                                 "platform": v["platform"], "fetched": today}
                save(LISTING, listing)
            kept += 1
        save(SOURCES, sources)
        done += 1
        if done % 50 == 0:
            print(done, "done,", kept, "kept,", small, "too small", flush=True)
    print(done, "done,", kept, "kept,", small, "too small", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "download":  # download <listings.json>
        download(sys.argv[2])
