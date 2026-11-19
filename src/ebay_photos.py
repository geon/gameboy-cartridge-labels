"""Cartridge photos from eBay searches, for releases no label photo has.

The searches run inside an eBay tab (driven through the Claude in Chrome extension); this script makes the
query list and takes in the search results, downloading each listing's first photo at eBay's largest size.

    python3 src/ebay_photos.py queries USA > queries.json
    python3 src/ebay_photos.py ingest results.json queries.json
    python3 src/ebay_photos.py queries USA releases.json <pass> > queries.json   (given releases, a named pass)
    python3 src/ebay_photos.py ingest results.json queries.json <pass>
    python3 src/ebay_photos.py store <listings.json> <store name>   (every listing of one seller's store)

Photos go to downloaded-photos/ebay-search/ with a listing.json there; make move-downloads moves them to save-new-images-here/
for make add-photos, when the user is ready to add them (the user, 2026-11-12: a running download must not land in an
add-photos run).
downloaded-photos/sources.json: one record per downloaded file (kept, or deleted by hand afterwards: never downloaded again) (release, query, listing, image URL, size, date).
downloaded-photos/searches.json: every release searched, so a run can be stopped and resumed.
"""
import contextlib
import datetime
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(__file__))
import serials  # noqa: E402

DOWNLOADED = "downloaded-photos"  # the downloaders' photos (until make move-downloads) and records
OUT = os.environ.get("EBAY_OUT", DOWNLOADED)  # the downloader's own records
DROP = os.environ.get("EBAY_DROP", os.path.join(DOWNLOADED, "ebay-search"))
LISTING = os.path.join(DROP, "listing.json")
SOURCES = os.path.join(OUT, "sources.json")
SEARCHES = os.path.join(OUT, "searches.json")
MISSING = "generated/read-serials/missing.json"
PER_RELEASE = 5
MIN_SIDE = 1200  # px, longest side (2026-11-11: at 1000 px most labels came out under 10 px/mm)
OTHER_REGIONS = {  # listing titles naming another region than the release's
    "USA": r"\b(japan|japanese|jpn|jp|ntsc-j|pal|eur|europe|european|uk|german|deutsch|french|fran[cç]ais|spanish|italian|import|chinese|korean)\b|AGB-P-\w{3}[^E\W]"}
# Regions for the searches of given releases (queries with a release list): the release's group, from its cartridge
# serial's suffix, else its game id's last letter. Per group: words added to the query (imports are listed on ebay.com,
# named so). No listing is left out for its region (the user: all cartridge photos are welcome; read-serials reads each
# photo's own serial), nor for naming another Game Boy system: only other systems (NOT_GAME_BOY).
REGION_GROUP = {"USA": "USA", "CAN": "USA", "JPN": "JPN",
                **{r: "EUR" for r in ("EUR", "UKV", "NOE", "FRA", "ESP", "ITA", "HOL", "EUU", "EUB", "FAH", "FRG", "DAN", "AUS", "GRA", "SPA")}}
ID_LETTER_GROUP = {"J": "JPN", "E": "USA", "P": "EUR"}
REGIONS = {"USA": {"query": ""}, "JPN": {"query": "Japan"}, "EUR": {"query": "PAL"}}
NOT_GAME_BOY = r"\b(nds|ds|3ds|psp|gamecube|n64|sega|dreamcast|playstation|ps[1-5x]|sony|xbox|wii|disc|dvd|slps|slus|sles)\b"
SYSTEM = {"agb": "GBA", "cgb": "Game Boy Color", "dmg": "Game Boy"}
OTHER_SYSTEMS = {"agb": r"\b(gbc|game ?boy colou?r|nds|ds|3ds|psp|gamecube|sega)\b",  # listing titles naming another system
                 "cgb": r"\b(gba|advance|nds|ds|3ds|psp|n64|sega)\b", "dmg": r"\b(gba|advance|nds|ds|3ds|psp|n64|sega)\b"}


def load(path):
    return json.load(open(path)) if os.path.exists(path) else {}


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(folder):
    """Holds folder's lock, so a downloader adding to its listing.json and make move-downloads taking from it don't
    overwrite each other's changes."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, ".lock"), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def query_title(title):
    t = re.sub(r"^(.*), (The|A|An)( - |$)", r"\2 \1\3", title)
    return re.sub(r"\s+", " ", t.replace(" - ", " ")).strip()


def queries(region, releases=None, pass_name=None, searched=None):
    """The queries for the region's releases no label photo has (missing.json), not yet searched; or for the given
    releases (a list of database ids, in that order), not yet searched in the named pass. searched: the record of
    searches done (eBay's when not given; mercari_photos gives an empty one and keeps its own)."""
    db = json.load(open(serials.DATABASE))
    searched = load(SEARCHES) if searched is None else searched
    if releases is None:
        missing = set(json.load(open(MISSING)))
        wanted = [r for r in db if r["id"] in missing and r["id"] not in searched]
    else:
        by_id = {r["id"]: r for r in db}
        wanted = [by_id[i] for i in releases if i in by_id and pass_name not in searched.get(i, {}).get("passes", {})]
    out = []
    for r in wanted:
        if releases is None:
            cart = [s for s in serials.cartridge_serials(r) if s.endswith("-" + region)]
            if not cart:
                continue
            serial, group = cart[0], "USA" if region == "USA" else None
        else:
            serial, group = region_of(r)
            if group is None or not re.search(r"[A-Za-z]", search_title(r)):  # no group, or no word the title check can use
                continue
        g = REGIONS.get(group, {"query": ""})
        title = search_title(r)
        out.append({"release": r["id"], "serial": serial, "title": title, "region": group,
                    "query": " ".join(w for w in (query_title(title), SYSTEM[r["system"]], g["query"], "cartridge") if w),
                    "exclude": OTHER_SYSTEMS[r["system"]] if releases is None else NOT_GAME_BOY,
                    **({} if releases is None else {"require_region": "", "exclude_region": ""})})
    return out


ROMANIZED = "ebay-romanized-titles.json"  # romanized titles for releases titled in Japanese script, written by hand


def search_title(r):
    """The title to search a release by: its romanized one (ROMANIZED) if written, else the database's, full-width
    letters made plain (NFKC)."""
    romanized = load(ROMANIZED)
    return romanized.get(r["id"]) or unicodedata.normalize("NFKC", r["title"])


def region_of(r):
    """(serial, region group) of a database record: its first cartridge serial with a known region, else its game
    id's last letter (serial: the id)."""
    for s in serials.cartridge_serials(r):
        group = REGION_GROUP.get(s.rsplit("-", 1)[-1])
        if "-" in s and group:
            return s, group
    return r["id"], ID_LETTER_GROUP.get(r["id"][-1])


def size(path):
    o = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", path], capture_output=True, text=True).stdout
    w, h = (int(re.search(rf"{k}: (\d+)", o).group(1)) for k in ("pixelWidth", "pixelHeight"))
    return [w, h]


def ingest(results_file, queries_file, pass_name=None):
    """results: {release: [{item, title, image}]}, items already filtered and ranked in the eBay tab. With a pass name,
    a release searched before is searched again: the pass is recorded under its "passes"."""
    sources, searches = load(SOURCES), load(SEARCHES)
    query_of = {q["release"]: q for q in json.load(open(queries_file))}
    have_items = {v["listing"].rsplit("/", 1)[1] for v in sources.values()}
    today = datetime.date.today().isoformat()
    for release, items in json.load(open(results_file)).items():
        if release not in query_of:  # taken in before the query file was made again
            continue
        res = dict(query_of[release], items=items)
        done = searches.get(res["release"], {})
        if (pass_name is None and done) or (pass_name is not None and pass_name in done.get("passes", {})):
            continue
        kept, small = 0, 0
        pattern = res["exclude_region"] if "exclude_region" in res else OTHER_REGIONS[res["serial"].rsplit("-", 1)[1]]
        other_region = re.compile(pattern, re.I) if pattern else None
        this_region = re.compile(res["require_region"], re.I) if res.get("require_region") else None
        for it in res["items"]:
            if (other_region and other_region.search(it["title"])) or (this_region and not this_region.search(it["title"])):
                continue
            if kept >= PER_RELEASE:
                break
            if it["item"] in have_items:
                continue
            name = f"ebay-{it['item']}.jpg"
            os.makedirs(DROP, exist_ok=True)
            path = os.path.join(DROP, name)
            url = f"https://i.ebayimg.com/images/g/{it['image']}/s-l1600.jpg"
            if subprocess.run(["curl", "-sSf", "-o", path, url]).returncode != 0:
                continue
            time.sleep(1)
            wh = size(path)
            if max(wh) < MIN_SIDE:
                os.remove(path)
                small += 1
                continue
            sources[name] = {"release": res["release"], "serial": res["serial"], "query": res["query"],
                             "listing": f"https://www.ebay.com/itm/{it['item']}", "listing_title": it["title"],
                             "image": url, "size": wh, "fetched": today}
            with locked(DROP):
                listing = load(LISTING)
                listing[name] = {"page_url": sources[name]["listing"], "image_url": url, "title_on_page": it["title"],
                                 "searched_release": res["release"], "searched_serial": res["serial"],
                                 "query": res["query"], "fetched": today}
                save(LISTING, listing)
            have_items.add(it["item"])
            kept += 1
        record = {"query": res["query"], "candidates": len(res["items"]), "kept": kept, "too_small": small, "date": today}
        if pass_name is None:
            searches[res["release"]] = record
        else:
            searches.setdefault(res["release"], {}).setdefault("passes", {})[pass_name] = record
        save(SOURCES, sources)
        save(SEARCHES, searches)
        print(res["release"], len(res["items"]), "candidates,", kept, "kept,", small, "too small", flush=True)


STORE_DROP = os.path.join(DOWNLOADED, "ebay-store")
# Not a Game Boy cartridge, in a store's listing titles: manuals, other systems' games, cases and covers, books.
# Lots and Japanese cartridges are kept (the user, 2026-11-17).
NOT_CARTRIDGE = re.compile(r"\bmanual\b|famicom|\bcases?\b|dust cover|connector cover|strategy|\bbook\b|encyclopedia|"
                           r"wonder ?swan", re.I)
CIB = re.compile(r"\b(cib|complete|boxed|with box|w/ ?box|in box)\b", re.I)


def store(listings_file, store_name):
    """Every listing of one seller's store: listings [{item, title, image}], as the eBay tab collected them from the
    store's search pages (the seller's own search, 240 a page). Each listing's first photo at eBay's largest size, those
    not a Game Boy cartridge (NOT_CARTRIDGE) left out, complete-in-box ones last. A photo under MIN_SIDE is recorded as
    too small (never downloaded again) and not kept."""
    listings = [v for v in json.load(open(listings_file)) if not NOT_CARTRIDGE.search(v["title"])]
    listings.sort(key=lambda v: bool(CIB.search(v["title"])))
    sources = load(SOURCES)
    have_items = {v["listing"].rsplit("/", 1)[1] for v in sources.values()}
    listing_path = os.path.join(STORE_DROP, "listing.json")
    today = datetime.date.today().isoformat()
    done = kept = small = 0
    for it in listings:
        if it["item"] in have_items or not it.get("image"):
            continue
        name = f"ebay-{it['item']}.jpg"
        os.makedirs(STORE_DROP, exist_ok=True)
        path = os.path.join(STORE_DROP, name)
        url = f"https://i.ebayimg.com/images/g/{it['image']}/s-l1600.jpg"
        ok = subprocess.run(["curl", "-sSf", "-o", path, url]).returncode == 0
        time.sleep(1)
        if not ok:
            if os.path.exists(path):
                os.remove(path)
            print("failed", it["item"], url, flush=True)
            continue
        wh = size(path)
        record = {"store": store_name, "listing": f"https://www.ebay.com/itm/{it['item']}", "listing_title": it["title"],
                  "image": url, "size": wh, "fetched": today}
        if max(wh) < MIN_SIDE:
            os.remove(path)
            sources[name] = {**record, "too_small": True}
            small += 1
        else:
            sources[name] = record
            with locked(STORE_DROP):
                listing = load(listing_path)
                listing[name] = {"page_url": record["listing"], "image_url": url, "title_on_page": it["title"],
                                 "store": store_name, "fetched": today}
                save(listing_path, listing)
            kept += 1
        have_items.add(it["item"])
        save(SOURCES, sources)
        done += 1
        if done % 50 == 0:
            print(done, "done,", kept, "kept,", small, "too small", flush=True)
    print(done, "done,", kept, "kept,", small, "too small", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "queries":  # queries <region> [<releases.json> <pass name>]
        releases = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else None
        json.dump(queries(sys.argv[2], releases, sys.argv[4] if len(sys.argv) > 4 else None), sys.stdout, ensure_ascii=False)
    elif sys.argv[1] == "ingest":  # ingest <results> <queries> [<pass name>]
        ingest(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    elif sys.argv[1] == "store":  # store <listings.json> <store name>
        store(sys.argv[2], sys.argv[3])
