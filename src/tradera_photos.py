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

Title searches (2026-11-25, the user: search for specific titles), one per release: the search page (/search?q=...,
for sale and sold) fetched in a tradera.com tab (src/tradera_tab.js; plain curl now gets a "Client Challenge" page),
its items taken in here, at most PER_RELEASE photos per release; searches recorded in downloaded-photos/tradera-searches.json.

    python3 src/tradera_photos.py queries releases.json <pass> > queries.json
    python3 src/tradera_photos.py ingest results.json queries.json

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


# Title searches (search_queries, ingest): a listing is kept when its title holds ¾ of the release title's words (STOP
# words left out), names no other system (ebay_photos.NOT_GAME_BOY), and isn't something other than a cartridge (NOT_CARTRIDGE).
STOP = {"the", "a", "an", "of", "and", "in", "to", "gba", "game", "boy", "color", "advance", "cartridge", "vs", "japan", "pal"}
NOT_CARTRIDGE = re.compile(r"\b(manual only|box only|empty box|endast (manual|kartong|box|ask)|bara (manual|kartong|box|ask)|"
                           r"tom (kartong|ask|box)|kartong utan|annons|reklam|affisch|poster|"
                           r"guide|strategy|guidebok|repro|reproduction|sticker|dekal|custom|fan ?made|homebrew|bootleg|"
                           r"pin|figur|kort|tröja|t-shirt|flipper|flipperspel)\b", re.I)
SEARCHES = os.path.join(OUT, "tradera-searches.json")
PER_RELEASE = 5


def words(s):
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))  # é -> e
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", s).split() if w not in STOP]


def boxed_last(title):
    """Sort key: complete in box, or with its manual, last (the user, 2026-11-17)."""
    return is_cib(title) or bool(re.search(r"\b(manual|manualen|instruktionsbok|anleitung)\b", title or "", re.I))


def title_matches(want, title):
    want, have = words(want), set(words(title))
    return sum(w in have for w in want) / max(1, len(want)) >= 0.75


def wanted_listing(want, title):
    return (title_matches(want, title) and not NOT_CARTRIDGE.search(title)
            and not re.search(ebay_photos.NOT_GAME_BOY, title, re.I))


def search_queries(releases, pass_name, searches):
    """One query per release (database ids, in that order), those not searched in the named pass: the title eBay's
    queries use (romanized for Japanese-script titles), without punctuation, no system or region words."""
    out = []
    for q in ebay_photos.queries(None, releases, "-", searched={}):
        if pass_name in searches.get(q["release"], {}):
            continue
        query = re.sub(r"\s+", " ", re.sub(r"[:!?&,/()]", " ", ebay_photos.query_title(q["title"]))).strip()
        out.append({"release": q["release"], "serial": q["serial"], "title": q["title"], "query": query, "pass": pass_name})
    return out


def fetch(v, sources, today, extra=None):
    """Downloads one listing's first photo: "kept", "small" or "failed"; records it in sources (not saved)."""
    name = f"tradera-{v['itemId']}.jpg"
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
        return "failed"
    wh = size(path)
    record = {"item": v["itemId"], "category": v["categoryId"], "listing": v["itemUrl"],
              "listing_title": v["shortDescription"], "image": image_url, "size": wh,
              "cib": is_cib(v["shortDescription"]), **(extra or {}), "fetched": today}
    if max(wh) < MIN_SIDE:
        os.remove(path)
        sources[name] = {**record, "too_small": True}
        return "small"
    sources[name] = record
    with locked(DROP):
        listing = load(LISTING)
        listing[name] = {"page_url": v["itemUrl"], "image_url": image_url, "title_on_page": v["shortDescription"],
                         "category": v["categoryId"], **({"searched_release": extra["release"], "searched_serial": extra["serial"],
                                                          "query": extra["query"]} if extra else {}), "fetched": today}
        save(LISTING, listing)
    return "kept"


def download(listings_file):
    listings = json.load(open(listings_file))
    listings.sort(key=lambda v: is_cib(v["shortDescription"]))  # stable: page order otherwise
    sources = load(SOURCES)
    today = datetime.date.today().isoformat()
    done = kept = small = 0
    for v in listings:
        if f"tradera-{v['itemId']}.jpg" in sources or not v.get("imageUrlTemplate"):
            continue
        r = fetch(v, sources, today)
        if r == "failed":
            continue
        kept += r == "kept"
        small += r == "small"
        save(SOURCES, sources)
        done += 1
        if done % 50 == 0:
            print(done, "done,", kept, "kept,", small, "too small", flush=True)
    print(done, "done,", kept, "kept,", small, "too small", flush=True)


def ingest(results_file, queries_file):
    """results: {release: [the search page's items, for sale and sold]}, from the tradera.com tab (src/tradera_tab.js).
    Per release, the listings wanted_listing keeps, complete-in-box last, until PER_RELEASE photos are kept; photos
    the page says are small aren't downloaded. Every release searched is recorded in SEARCHES under its pass."""
    sources, searches = load(SOURCES), load(SEARCHES)
    query_of = {q["release"]: q for q in json.load(open(queries_file))}
    have = {f"tradera-{v['item']}.jpg" for v in sources.values() if "item" in v} | set(sources)
    today = datetime.date.today().isoformat()
    for release, items in json.load(open(results_file)).items():
        q = query_of.get(release)
        if q is None or q["pass"] in searches.get(release, {}):
            continue
        cands = [v for v in items if v.get("imageUrlTemplate") and wanted_listing(q["title"], v["shortDescription"])]
        cands.sort(key=lambda v: boxed_last(v["shortDescription"]))
        kept = small = 0
        for v in cands:
            if kept >= PER_RELEASE:
                break
            if f"tradera-{v['itemId']}.jpg" in have:
                continue
            if max(v.get("imageWidth") or 0, v.get("imageHeight") or 0) and max(v["imageWidth"], v["imageHeight"]) < MIN_SIDE:
                small += 1
                continue
            r = fetch(v, sources, today, {"release": release, "serial": q["serial"], "query": q["query"]})
            have.add(f"tradera-{v['itemId']}.jpg")
            kept += r == "kept"
            small += r == "small"
        searches.setdefault(release, {})[q["pass"]] = {"query": q["query"], "results": len(items), "candidates": len(cands),
                                                        "kept": kept, "too_small": small, "date": today}
        save(SOURCES, sources)
        save(SEARCHES, searches)
        print(release, len(items), "results,", len(cands), "candidates,", kept, "kept,", small, "too small", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "download":  # download <listings.json>
        download(sys.argv[2])
    elif sys.argv[1] == "queries":  # queries <releases.json> <pass name>
        json.dump(search_queries(json.load(open(sys.argv[2])), sys.argv[3], load(SEARCHES)), sys.stdout, ensure_ascii=False)
    elif sys.argv[1] == "ingest":  # ingest <results> <queries>
        ingest(sys.argv[2], sys.argv[3])
