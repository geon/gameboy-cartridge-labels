"""Cartridge photos from Blocket (www.blocket.se), from a whole search, as tradera_photos.py.

The search pages (https://www.blocket.se/recommerce/forsale/search?...&page=<n>) load with plain curl; each page's
schema.org data (<script type="application/ld+json">, a CollectionPage) lists its listings: name (the title), url and
image (https://images.blocketcdn.se/dynamic/default/item/<id>/<uuid>, the first photo). The photo comes in widths
named in the path (dynamic/960w/..., 1600w; 2000w is HTTP 404): 1600w is downloaded. Whether 1600w scales a smaller
original up is not known. First crawled 2026-11-22: "gameboy" in Spel (product_category=2.93.3905.64), 64 listings in
2 pages.

    python3 src/blocket_photos.py list '<search URL>' > listings.json
    python3 src/blocket_photos.py download listings.json

Listings whose title says complete in box come last (tradera_photos.CIB); lots are kept (the user, 2026-11-17).
Only each listing's first photo, one a second. A photo under MIN_SIDE on its long side is not kept.
Photos go to downloaded-photos/blocket-search/ as blocket-<id>.jpg with a listing.json there, moved to
save-new-images-here/ by make move-downloads for make add-photos. Records: downloaded-photos/blocket-sources.json
(every listing whose photo was downloaded or found too small, also those deleted by hand afterwards: never downloaded
again).
"""
import datetime
import html as html_module
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import ebay_photos  # noqa: E402
import tradera_photos  # noqa: E402
from ebay_photos import load, locked, save, size  # noqa: E402

OUT = os.environ.get("BLOCKET_OUT", ebay_photos.DOWNLOADED)
DROP = os.environ.get("BLOCKET_DROP", os.path.join(ebay_photos.DOWNLOADED, "blocket-search"))
LISTING = os.path.join(DROP, "listing.json")
SOURCES = os.path.join(OUT, "blocket-sources.json")
MIN_SIDE = 1200
WIDTH = "1600w"


def page_items(page_html):
    """The listings of one search page: its CollectionPage's items."""
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page_html, re.S):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:  # an empty script on a page past the last
            continue
        if isinstance(d, dict) and d.get("@type") == "CollectionPage":
            return [e["item"] for e in d["mainEntity"]["itemListElement"]]
    return []


def list_search(url):
    """Every listing of the search, page by page until a page adds none, one page every 3 s."""
    out, seen = [], set()
    for n in range(1, 100):
        page = subprocess.run(["curl", "-sSf", f"{url}&page={n}"], capture_output=True, text=True, check=True).stdout
        new = [i for i in page_items(page) if i["url"] not in seen]
        if not new:
            break
        for i in new:
            seen.add(i["url"])
            out.append({"id": i["url"].rstrip("/").rsplit("/", 1)[1], "title": html_module.unescape(i.get("name", "")),
                        "url": i["url"], "image": i.get("image"), "price": (i.get("offers") or {}).get("price"),
                        "search": url})
        time.sleep(3)
    return out


def download(listings_file):
    listings = json.load(open(listings_file))
    listings.sort(key=lambda v: tradera_photos.is_cib(v["title"]))  # stable: page order otherwise
    sources = load(SOURCES)
    today = datetime.date.today().isoformat()
    kept = small = 0
    for v in listings:
        name = f"blocket-{v['id']}.jpg"
        if name in sources or not v.get("image"):
            continue
        image_url = v["image"].replace("/dynamic/default/", f"/dynamic/{WIDTH}/")
        os.makedirs(DROP, exist_ok=True)
        path = os.path.join(DROP, name)
        if subprocess.run(["curl", "-sSf", "-o", path, image_url]).returncode != 0:
            continue
        time.sleep(1)
        wh = size(path)
        record = {"listing": v["url"], "listing_title": v["title"], "image": image_url, "size": wh,
                  "search": v["search"], "fetched": today}
        if max(wh) < MIN_SIDE:
            os.remove(path)
            sources[name] = {**record, "too_small": True}
            small += 1
        else:
            sources[name] = record
            with locked(DROP):
                listing = load(LISTING)
                listing[name] = {"page_url": v["url"], "image_url": image_url, "title_on_page": v["title"],
                                 "fetched": today}
                save(LISTING, listing)
            kept += 1
        save(SOURCES, sources)
    print(kept, "kept,", small, "too small")


if __name__ == "__main__":
    if sys.argv[1] == "list":  # list <search URL>
        json.dump(list_search(sys.argv[2]), sys.stdout, ensure_ascii=False, indent=1)
    elif sys.argv[1] == "download":  # download <listings.json>
        download(sys.argv[1 + 1])
