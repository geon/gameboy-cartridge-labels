"""Cartridge photos from Yahoo! Auctions Japan, searched through Jauce (www.jauce.com, a proxy shop for it).

As ebay_photos.py: the searches run inside a jauce.com tab (driven through the Claude in Chrome extension; a search is
a form post to /directory_list.php, its results in the HTML); this script makes the query list and takes in the
results, downloading each listing's first photo. Yahoo refuses downloads outside a browser (HTTP 403, its image and
thumbnail servers alike), so photos come through Jauce's image proxy (/read_yafile/...), one a second.

    python3 src/jauce_photos.py queries releases.json > queries.json   (the Japanese ones among them, by Japanese title)
    python3 src/jauce_photos.py ingest results.json queries.json
    python3 src/jauce_photos.py queries releases.json <pass> short > queries.json   (searched again, a named pass;
        short: the title's first word and its numbers, GBA/GBC/GB)
    python3 src/jauce_photos.py ingest results.json queries.json <pass>

Photos go to downloaded-photos/jauce-search/ with a listing.json there (page_url: the Yahoo listing), moved to
save-new-images-here/ by make move-downloads for make add-photos. Records, as ebay_photos':
downloaded-photos/jauce-sources.json (every downloaded file, also those deleted by hand afterwards: never downloaded
again), downloaded-photos/jauce-searches.json (every release searched).
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(__file__))
import serials  # noqa: E402
import ebay_photos  # noqa: E402
from ebay_photos import load, locked, save, size  # noqa: E402

OUT = os.environ.get("JAUCE_OUT", ebay_photos.DOWNLOADED)
DROP = os.environ.get("JAUCE_DROP", os.path.join(ebay_photos.DOWNLOADED, "jauce-search"))
LISTING = os.path.join(DROP, "listing.json")
SOURCES = os.path.join(OUT, "jauce-sources.json")
SEARCHES = os.path.join(OUT, "jauce-searches.json")
PER_RELEASE = 5
MIN_SIDE = 1200  # px, longest side (Yahoo's photo names say their size: i-img1200x900-...)
PROXY = "https://www.jauce.com/read_yafile/https://auc-pctr.c.yimg.jp/i/auctions.c.yimg.jp/"
SYSTEM = {"agb": "ゲームボーイアドバンス", "cgb": "ゲームボーイカラー", "dmg": "ゲームボーイ"}
# Listing titles left out: lots and sets, boxes and manuals (but not "box: none"), guides, consoles, other systems
# (ファミコン, but not the GBA's ファミコンミニ series).
NOT_A_CARTRIDGE = (r"まとめ|セット|\d+本|外箱|空箱|箱(?!なし|無)|説明書(?!なし|無)|ソフト(なし|無し)|攻略本|ガイドブック|ケース|ポスター|チラシ|"
                   r"本体|アダプタ|ケーブル|リプロ|互換")
NOT_GAME_BOY = (r"(?<![A-Za-z0-9])(N?DS|DSi|DS ?Lite|3DS|PSP|PS[1-5]|SFC|N64|Wii|Switch)(?![A-Za-z0-9])|プレイステーション|プレステ|スーパーファミコン|ファミコン(?!ミニ)|"
                r"ゲームキューブ|セガ|サターン|メガドライブ|PCエンジン|ネオジオ|ワンダースワン|ニンテンドー64|スイッチ")


def japanese_title(r):
    """A release's title in Japanese script (gb-game-list's titles), else None."""
    for t in r.get("titles", []):
        if any(ord(c) > 0x3000 for c in t["title"]):
            return t["title"]
    return None


def query_title(title):
    """The title made plain (NFKC: full-width letters, digits and spaces), readings in brackets left out."""
    t = unicodedata.normalize("NFKC", title)
    t = re.sub(r"[(（][^)）]*[)）]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parts(title):
    """The title's parts a listing's title must hold (see the page script): its words, without punctuation."""
    return [p for p in re.split(r"[\s・:：~〜\-－!！?？、。,.『』「」]+", query_title(title).lower()) if p]


SHORT_SYSTEM = {"agb": "GBA", "cgb": "GBC", "dmg": "GB"}


def short_parts(title):
    """The short query's words: the title's first word (split at spaces and "/"; a Latin one with the next words until
    6 letters, a title in Latin letters only at least two words), then the numbers in the rest not already in them (a
    series' volume), each once."""
    words = [w for w in re.split(r"[\s/／]+", query_title(title)) if w]
    latin = all(ord(c) < 0x3000 for c in "".join(words))
    taken = words[:2] if latin else words[:1]
    while len(taken) < len(words) and len(re.sub(r"[^A-Za-z]", "", " ".join(taken))) < 6 and re.search(r"[A-Za-z]", taken[-1]):
        taken.append(words[len(taken)])
    numbers = []
    for w in words[len(taken):]:
        for n in re.findall(r"\d+", w):
            if n not in numbers and not any(n in t for t in taken):
                numbers.append(n)
    return taken + numbers


def searched_in(searches, release, pass_name):
    done = searches.get(release, {})
    return bool(done) if pass_name is None else pass_name in done.get("passes", {})


def queries(releases, pass_name=None, short=False):
    """The queries for the Japanese releases among the given ones, not yet searched (in the named pass): by the
    Japanese-script title and the system's Japanese name; short, by the title's first word and the numbers in it and
    the system's short name (GBA, GBC, GB), a release without a Japanese-script title by its romanized one."""
    db = {r["id"]: r for r in json.load(open(serials.DATABASE, encoding="utf-8"))}
    searched = load(SEARCHES)
    out = []
    for i in releases:
        r = db.get(i)
        if r is None or searched_in(searched, i, pass_name) or not i.endswith("J"):
            continue
        title = japanese_title(r) or (r["title"].split(" - ")[0] if short else None)
        if title is None:
            continue
        serial = next((s for s in r.get("cartridgeSerials", []) if s.endswith("-JPN")), i)
        if short:
            words = short_parts(title)
            q = {"parts": [w.lower() for w in words], "query": f"{' '.join(words)} {SHORT_SYSTEM[r['system']]}"}
        else:
            q = {"parts": parts(title), "query": f"{query_title(title)} {SYSTEM[r['system']]}"}
        out.append({"release": i, "serial": serial, "title": title, **q, "exclude": NOT_GAME_BOY, "bad": NOT_A_CARTRIDGE,
                    "pass": pass_name})
    return out


def ingest(results_file, queries_file, pass_name=None):
    """results: {release: [{id, title, image (the path after auctions.c.yimg.jp/), w, h}]}, filtered in the tab. With
    a pass name, a release searched before is searched again: the pass is recorded under its "passes"."""
    sources, searches = load(SOURCES), load(SEARCHES)
    query_of = {q["release"]: q for q in json.load(open(queries_file, encoding="utf-8"))}
    have = {v["auction"] for v in sources.values()}
    today = datetime.date.today().isoformat()
    given = pass_name
    for release, items in json.load(open(results_file, encoding="utf-8")).items():
        if release not in query_of:
            continue
        q = query_of[release]
        pass_name = q.get("pass", given)
        if searched_in(searches, release, pass_name):
            continue
        kept, small = 0, 0
        for it in items:
            if kept >= PER_RELEASE:
                break
            if it["id"] in have:
                continue
            if max(it.get("w") or 0, it.get("h") or 0) < MIN_SIDE:
                small += 1
                continue
            name = f"yahoo-{it['id']}.jpg"
            os.makedirs(DROP, exist_ok=True)
            path = os.path.join(DROP, name)
            if subprocess.run(["curl", "-sSf", "-o", path, PROXY + it["image"]]).returncode != 0:
                continue
            time.sleep(1)
            wh = size(path)
            if max(wh) < MIN_SIDE:
                os.remove(path)
                small += 1
                continue
            page_url = f"https://page.auctions.yahoo.co.jp/jp/auction/{it['id']}"
            image_url = "https://auctions.c.yimg.jp/" + it["image"]
            sources[name] = {"release": release, "serial": q["serial"], "query": q["query"], "auction": it["id"],
                             "listing": page_url, "via": f"https://www.jauce.com/auction/{it['id']}",
                             "listing_title": it["title"], "image": image_url, "size": wh, "fetched": today}
            with locked(DROP):
                listing = load(LISTING)
                listing[name] = {"page_url": page_url, "image_url": image_url, "title_on_page": it["title"],
                                 "via": sources[name]["via"], "searched_release": release,
                                 "searched_serial": q["serial"], "query": q["query"], "fetched": today}
                save(LISTING, listing)
            have.add(it["id"])
            kept += 1
        record = {"query": q["query"], "candidates": len(items), "kept": kept, "too_small": small, "date": today}
        if pass_name is None:
            searches[release] = record
        else:
            searches.setdefault(release, {}).setdefault("passes", {})[pass_name] = record
        save(SOURCES, sources)
        save(SEARCHES, searches)
        print(release, len(items), "candidates,", kept, "kept,", small, "too small", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "queries":  # queries <releases.json> [<pass name> [short]]
        json.dump(queries(json.load(open(sys.argv[2], encoding="utf-8")), sys.argv[3] if len(sys.argv) > 3 else None,
                          len(sys.argv) > 4 and sys.argv[4] == "short"), sys.stdout, ensure_ascii=False)
    elif sys.argv[1] == "ingest":  # ingest <results> <queries> [<pass name>]
        ingest(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
