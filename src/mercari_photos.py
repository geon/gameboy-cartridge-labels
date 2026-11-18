"""Cartridge photos from Mercari US (www.mercari.com), searched in a mercari.com tab.

As ebay_photos.py: the searches run inside a www.mercari.com tab (driven through the Claude in Chrome extension). The
results are drawn by the page's own script (from Mercari's API), so the tab script types each query into the site's
search box, presses Enter and reads the listings it shows (item ids and titles), filtered as eBay's: most of the
title's words, no box/lot/manual words (the tab's BAD), not another system (NOT_GAME_BOY). This script makes the query
list (eBay's queries: the English or romanized title, the system, a region word) and takes in the results, downloading
each listing's first photo from u-mercari-images.mercdn.net without parameters: the stored photo (1600 px, or 1080 px
for some uploads; asking for a larger width only scales it up). A photo under MIN_SIDE is not kept.
(Mercari Japan, jp.mercari.com, tried 2026-11-12: its photos are at most 1080 px, and this server refuses them.)

    python3 src/mercari_photos.py queries releases.json <pass> > queries.json
    python3 src/mercari_photos.py ingest results.json queries.json

Photos go to downloaded-photos/mercari-search/ with a listing.json there (page_url: the listing), moved to
save-new-images-here/ by make move-downloads for make add-photos. Records: downloaded-photos/mercari-sources.json
(every listing whose photo was downloaded or found too small, also those deleted by hand afterwards: never downloaded
again), downloaded-photos/mercari-searches.json (every release searched, per pass).
"""
import datetime
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import ebay_photos  # noqa: E402
from ebay_photos import load, locked, save, size  # noqa: E402

OUT = os.environ.get("MERCARI_OUT", ebay_photos.DOWNLOADED)
DROP = os.environ.get("MERCARI_DROP", os.path.join(ebay_photos.DOWNLOADED, "mercari-search"))
LISTING = os.path.join(DROP, "listing.json")
SOURCES = os.path.join(OUT, "mercari-sources.json")
SEARCHES = os.path.join(OUT, "mercari-searches.json")
PER_RELEASE = 5
MIN_SIDE = 1200
PHOTO = "https://u-mercari-images.mercdn.net/photos/{id}_1.jpg"


def queries(releases, pass_name):
    """eBay's queries for the given releases (database ids, in that order), those not yet searched on Mercari in the
    named pass."""
    searched = load(SEARCHES)
    out = []
    for q in ebay_photos.queries(None, releases, "-", searched={}):
        if pass_name not in searched.get(q["release"], {}):
            out.append({**q, "query": q["query"].replace(" cartridge", ""), "pass": pass_name})
    return out


def ingest(results_file, queries_file):
    """results: {release: [{id, title}]}, filtered in the tab."""
    sources, searches = load(SOURCES), load(SEARCHES)
    query_of = {q["release"]: q for q in json.load(open(queries_file, encoding="utf-8"))}
    have = {v["item"] for v in sources.values()}
    today = datetime.date.today().isoformat()
    for release, items in json.load(open(results_file, encoding="utf-8")).items():
        q = query_of.get(release)
        if q is None or q["pass"] in searches.get(release, {}):
            continue
        kept, small = 0, 0
        for it in items:
            if kept >= PER_RELEASE:
                break
            if it["id"] in have:
                continue
            have.add(it["id"])
            name = f"mercari-{it['id']}.jpg"
            page_url = f"https://www.mercari.com/us/item/{it['id']}/"
            image_url = PHOTO.format(id=it["id"])
            os.makedirs(DROP, exist_ok=True)
            path = os.path.join(DROP, name)
            ok = subprocess.run(["curl", "-sSf", "-A", "Mozilla/5.0", "-o", path, image_url],
                                stderr=subprocess.DEVNULL).returncode == 0
            time.sleep(1)
            wh = size(path) if ok else [0, 0]
            if max(wh) < MIN_SIDE:
                if os.path.exists(path):
                    os.remove(path)
                small += 1
                sources[name] = {"release": release, "item": it["id"], "listing": page_url, "size": wh,
                                 "too_small": True, "fetched": today}
                continue
            sources[name] = {"release": release, "serial": q["serial"], "query": q["query"], "item": it["id"],
                             "listing": page_url, "listing_title": it["title"], "image": image_url, "size": wh,
                             "fetched": today}
            with locked(DROP):
                listing = load(LISTING)
                listing[name] = {"page_url": page_url, "image_url": image_url, "title_on_page": it["title"],
                                 "searched_release": release, "searched_serial": q["serial"], "query": q["query"],
                                 "fetched": today}
                save(LISTING, listing)
            kept += 1
        searches.setdefault(release, {})[q["pass"]] = {"query": q["query"], "candidates": len(items), "kept": kept,
                                                        "too_small": small, "date": today}
        save(SOURCES, sources)
        save(SEARCHES, searches)
        print(release, len(items), "candidates,", kept, "kept,", small, "too small", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "queries":  # queries <releases.json> <pass name>
        json.dump(queries(json.load(open(sys.argv[2], encoding="utf-8")), sys.argv[3]), sys.stdout, ensure_ascii=False)
    elif sys.argv[1] == "ingest":  # ingest <results> <queries>
        ingest(sys.argv[2], sys.argv[3])
