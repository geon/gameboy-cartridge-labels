"""Cartridge photos from Tradera (www.tradera.com), from whole categories, not searches.

The category pages (https://www.tradera.com/category/<id>?paging=<n>, 80 listings a page) load with plain curl; each
page's embedded data has every listing's itemId, shortDescription (the title), itemUrl and imageUrlTemplate
(https://img.tradera.net/{format}/...). Crawled 2026-11-17: Game Boy games (300201, 2314 listings, 29 pages) and
Game Boy Advance (300306, 1923 listings, 25 pages), one page every 3 to 5 s, never blocked. The listings, one record
each, are in downloaded-photos/tradera-listings.json.
Sold listings too (the same pages with itemStatus=Sold, 2026-11-17): 2008 Game Boy, 1904 GBA, ended 2026-04-05 to
2026-11-17 (as far back as Tradera shows), in downloaded-photos/tradera-sold-listings.json. Their photos still load at
full size. The page's data is Next.js flight data: the strings of its self.__next_f.push([1, "..."]) calls, each to be
decoded as JSON (a plain replace of \\" breaks on titles with quotes), then the "items":[{"itemId"... array.

The format "images" is the stored photo at full size (as the link on the listing page; 1536x2048 seen); the page's own
formats (250-square, 500-square, 750-square) are crops. Only each listing's first photo is downloaded, one a second.
Listings whose title says they are complete in box (CIB, komplett, kartong, ...) come last (the user, 2026-11-17).
A photo under MIN_SIDE on its long side is not kept.

    python3 src/tradera_photos.py download downloaded-photos/tradera-listings.json

Photos go to downloaded-photos/tradera-category/ as tradera-<itemId>.jpg with a listing.json there, moved to
save-new-images-here/ by make move-downloads for make add-photos. Records: downloaded-photos/tradera-sources.json
(every listing whose photo was downloaded or found too small, also those deleted by hand afterwards: never downloaded
again).
"""
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

OUT = os.environ.get("TRADERA_OUT", ebay_photos.DOWNLOADED)
DROP = os.environ.get("TRADERA_DROP", os.path.join(ebay_photos.DOWNLOADED, "tradera-category"))
LISTING = os.path.join(DROP, "listing.json")
SOURCES = os.path.join(OUT, "tradera-sources.json")
MIN_SIDE = 1000
# Complete in box. "Skyddsbox" / "skyddsfodral" is a protective case for the loose cartridge: not this.
CIB = re.compile(r"\bCIB\b|komplett|complete|\bkartong|\bboxed\b|\bi box\b|\bmed box\b|\boriginalbox|\bOVP\b", re.I)


def is_cib(title):
    return bool(CIB.search(title or ""))


def download(listings_file):
    listings = json.load(open(listings_file))
    listings.sort(key=lambda v: is_cib(v["shortDescription"]))  # stable: page order otherwise
    sources = load(SOURCES)
    today = datetime.date.today().isoformat()
    done = kept = small = 0
    for v in listings:
        name = f"tradera-{v['itemId']}.jpg"
        if name in sources or not v.get("imageUrlTemplate"):
            continue
        image_url = v["imageUrlTemplate"].replace("{format}", "images")
        os.makedirs(DROP, exist_ok=True)
        path = os.path.join(DROP, name)
        ok = subprocess.run(["curl", "-sSf", "-A", "Mozilla/5.0", "-o", path, image_url],
                            stderr=subprocess.DEVNULL).returncode == 0
        time.sleep(1)
        if not ok:
            if os.path.exists(path):
                os.remove(path)
            print("failed", v["itemId"], image_url, flush=True)
            continue
        wh = size(path)
        record = {"item": v["itemId"], "category": v["categoryId"], "listing": v["itemUrl"],
                  "listing_title": v["shortDescription"], "image": image_url, "size": wh,
                  "cib": is_cib(v["shortDescription"]), "fetched": today}
        if max(wh) < MIN_SIDE:
            os.remove(path)
            sources[name] = {**record, "too_small": True}
            small += 1
        else:
            sources[name] = record
            with locked(DROP):
                listing = load(LISTING)
                listing[name] = {"page_url": v["itemUrl"], "image_url": image_url,
                                 "title_on_page": v["shortDescription"], "category": v["categoryId"],
                                 "fetched": today}
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
