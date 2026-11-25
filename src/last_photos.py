"""The last photo of Jauce (Yahoo! Auctions) and Tradera listings whose first photo was downloaded and then deleted by
hand, for releases still on the wanted list (the user, 2026-11-25: a deleted first photo often meant it wasn't the
cartridge; the last photo often is).

Deleted by hand: downloaded (in jauce-sources.json or tradera-sources.json, not too small), but no longer in
photo-sources.json, not removed by remove-low-resolution (its deleted.json), and not still waiting in downloaded-photos/
or save-new-images-here/ (remove-photos keeps no log of its own). A Jauce photo's release is the one it was searched
for; a Tradera category photo's is the database title that fits its listing title best (best_release).

The listings' photo lists are read in a browser tab (src/listing_photos_tab.js; Yahoo and Tradera refuse curl for
pages), then the last photo is downloaded (Jauce through its image proxy, Tradera's full size), named
yahoo-<id>-last.jpg / tradera-<id>-last.jpg, into the site's folder in downloaded-photos/ with its listing.json entry
and a record in the site's sources file ("photo": "last", "photos": how many the listing has). Every listing looked at
is recorded in downloaded-photos/last-photos.json, so none is looked at twice.

    python3 src/last_photos.py queue <wanted releases.json> <out dir>   (writes listing-photos-<site>-queue.json there)
    python3 src/last_photos.py ingest <site> <batch.json> <queue.json>
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
import jauce_photos  # noqa: E402
import serials  # noqa: E402
import tradera_photos  # noqa: E402
from ebay_photos import load, locked, save, size  # noqa: E402

RECORD = os.path.join(ebay_photos.DOWNLOADED, "last-photos.json")
SYS_OF_CAT = {300201: ("dmg", "cgb"), 300306: ("agb",)}
GENERIC = {"nintendo", "gameboy", "gb", "gbc", "dmg", "cgb", "agb", "version", "till", "spel", "svensk", "pal", "scn",
           "eur", "usa", "ntsc", "nes", "cart", "kassett", "only", "endast", "loose", "original", "org", "1", "2"}


def deleted_by_hand(sources):
    in_photos = {v.get("file") for v in json.load(open("photo-sources.json")).values()}
    low = {v["source"].get("file") for v in load("generated/remove-low-resolution/deleted.json").values()}
    pending = set()
    for root in (ebay_photos.DOWNLOADED, "save-new-images-here"):
        for _, _, files in os.walk(root):
            pending.update(files)
    return {n: v for n, v in sources.items()
            if not v.get("too_small") and n not in in_photos and n not in low and n not in pending}


def best_release(title, cat, wanted_titles, all_words):
    """The wanted release whose title's words all appear in the listing title, when no other database title (of the
    category's systems) fits with more words; a one-word title only when the listing names nothing else."""
    if tradera_photos.NOT_CARTRIDGE.search(title) or re.search(ebay_photos.NOT_GAME_BOY, title, re.I):
        return None
    have = set(tradera_photos.words(title))
    systems = SYS_OF_CAT.get(cat, ("dmg", "cgb", "agb"))
    fits = [(len(w), i) for i, sy, w in all_words if w and w <= have and sy in systems]
    if not fits:
        return None
    best = max(n for n, _ in fits)
    if best == 1 and len(have - GENERIC) > 1:
        return None
    return next((i for n, i in fits if n == best and i in wanted_titles), None)


def queue(releases_file, out_dir):
    wanted = json.load(open(releases_file))
    db = {r["id"]: r for r in serials.releases()}
    titles = {r: ebay_photos.search_title(db[r]) for r in wanted if r in db}
    done = load(RECORD)
    q = {"jauce": [], "tradera": []}
    for name, v in deleted_by_hand(load(jauce_photos.SOURCES)).items():
        if v.get("release") in titles and f"jauce:{v['auction']}" not in done:
            q["jauce"].append({"key": f"jauce:{v['auction']}", "id": v["auction"], "release": v["release"],
                               "serial": v.get("serial"), "title": v.get("listing_title"), "first": name})
    all_words = [(r["id"], r["system"], set(tradera_photos.words(ebay_photos.search_title(r)))) for r in db.values()]
    for name, v in deleted_by_hand(load(tradera_photos.SOURCES)).items():
        if "item" not in v or f"tradera:{v['item']}" in done:
            continue
        rel = v.get("release") or best_release(v["listing_title"], v.get("category"), titles, all_words)
        if rel:
            q["tradera"].append({"key": f"tradera:{v['item']}", "id": v["item"], "release": rel,
                                 "serial": v.get("serial"), "title": v["listing_title"], "listing": v["listing"],
                                 "category": v.get("category"), "first": name})
    for site, L in q.items():
        L = list({x["key"]: x for x in L}.values())
        json.dump(L, open(os.path.join(out_dir, f"listing-photos-{site}-queue.json"), "w"), ensure_ascii=False)
        print(site, len(L), "listings,", len({x["release"] for x in L}), "releases")


def ingest(site, batch_file, queue_file):
    of = {x["key"]: x for x in json.load(open(queue_file))}
    record = load(RECORD)
    if site == "jauce":
        sources_file, drop, min_side = jauce_photos.SOURCES, jauce_photos.DROP, jauce_photos.MIN_SIDE
    else:
        sources_file, drop, min_side = tradera_photos.SOURCES, tradera_photos.DROP, tradera_photos.MIN_SIDE
    sources = load(sources_file)
    today = datetime.date.today().isoformat()
    for key, paths in json.load(open(batch_file)).items():
        x = of.get(key)
        if x is None or key in record:
            continue
        result = {"photos": len(paths), "date": today}
        if len(paths) >= 2:
            last = paths[-1]
            if site == "jauce":
                name, url, image_url = f"yahoo-{x['id']}-last.jpg", jauce_photos.PROXY + last, "https://auctions.c.yimg.jp/" + last
                page_url = f"https://page.auctions.yahoo.co.jp/jp/auction/{x['id']}"
                wh_name = re.search(r"i-img(\d+)x(\d+)-", last)
                if wh_name and max(int(wh_name[1]), int(wh_name[2])) < min_side:
                    result["kept"] = "too small"
                    record[key] = result
                    continue
            else:
                name, url = f"tradera-{x['id']}-last.jpg", "https://img.tradera.net/images/" + last
                image_url, page_url = url, x["listing"]
            os.makedirs(drop, exist_ok=True)
            path = os.path.join(drop, name)
            ok = subprocess.run(["curl", "-sSf", "-A", "Mozilla/5.0", "-o", path, url], stderr=subprocess.DEVNULL).returncode == 0
            time.sleep(1)
            wh = size(path) if ok else [0, 0]
            rec = {"release": x["release"], "serial": x.get("serial"), "listing": page_url, "listing_title": x["title"],
                   "image": image_url, "size": wh, "photo": "last", "photos": len(paths), "first_deleted": x["first"],
                   "fetched": today, **({"auction": x["id"]} if site == "jauce" else {"item": x["id"], "category": x.get("category")})}
            if max(wh) < min_side:
                if os.path.exists(path):
                    os.remove(path)
                sources[name] = {**rec, "too_small": True}
                result["kept"] = "too small" if ok else "failed"
            else:
                sources[name] = rec
                with locked(drop):
                    listing = load(os.path.join(drop, "listing.json"))
                    listing[name] = {"page_url": page_url, "image_url": image_url, "title_on_page": x["title"],
                                     "searched_release": x["release"], "searched_serial": x.get("serial"),
                                     "photo": "last", "fetched": today}
                    save(os.path.join(drop, "listing.json"), listing)
                result["kept"] = name
        record[key] = result
        save(sources_file, sources)
        save(RECORD, record)
        print(key, x["release"], len(paths), "photos,", result.get("kept", "only one photo"), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "queue":
        queue(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "ingest":
        ingest(sys.argv[2], sys.argv[3], sys.argv[4])
