"""Cartridge photos found by Google Lens reverse image search, from the wanted prints' straightened label photos.

The searches run inside a www.google.com tab (driven through the Claude in Chrome extension): the page script posts
each label photo to Lens's upload form into a hidden frame, fetches the "Visual matches" page for it (with a text
added to the image, e.g. "gameboy cartridge") and reads the matches from its HTML: each one's full-size image address
and size, page address and page title. It saves them in batches to ~/Downloads/lens-batch-<n>.json; this script takes
a batch in and downloads the matches that are the right game:

    python3 src/lens_photos.py images <dir>                  (one JPEG per wanted print to search, into <dir>)
    python3 src/lens_photos.py ingest <batch.json>

Right game: the match's page title holds the release's serial code (L8A, AAKJ), or half the words of one of its titles
(English or Japanese script), one of 5 letters or more among them; and names no other system. At least MIN_SIDE px on the long side; not screenshot
or box-art sites (SKIP_HOSTS); not an image already in photo-sources.json or downloaded before (eBay by image id). eBay
images are fetched at s-l1600, the largest. One image every 5 to 8 s.

Photos go to downloaded-photos/google-lens/ with a listing.json (page_url, image_url, title_on_page, searched_print,
...), moved to save-new-images-here/ by make move-downloads for make add-photos. Records, as ebay_photos':
downloaded-photos/google-lens-sources.json (every downloaded file, also those deleted by hand afterwards: never
downloaded again), downloaded-photos/google-lens-searches.json (every print searched, with the label photo and text).
"""
import datetime
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(__file__))
import serials  # noqa: E402
import ebay_photos  # noqa: E402
import jauce_photos  # noqa: E402
from ebay_photos import load, locked, save  # noqa: E402

OUT = ebay_photos.DOWNLOADED
DROP = os.path.join(OUT, "google-lens")
LISTING = os.path.join(DROP, "listing.json")
SOURCES = os.path.join(OUT, "google-lens-sources.json")
SEARCHES = os.path.join(OUT, "google-lens-searches.json")
WANTED = "generated/publish/wanted.json"
PRINTS = "prints.json"
STRAIGHTENED = "generated/straighten"
MIN_SIDE = 1000
SKIP_HOSTS = ("ytimg.com", "mobygames.com", "launchbox-app.com", "lutris.net", "igdb.com", "gamefaqs", "fandom.com",
              "wikipedia.org", "imdb.com", "game-boy-database.com")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
STOP = {"the", "of", "a", "an", "and", "in", "to", "no", "de", "game", "boy", "gameboy", "color", "colour", "advance",
        "gb", "gbc", "gba", "series", "edition", "games", "one", "vs"}
OTHER_SYSTEM = re.compile(
    r"(?<![a-z0-9])(sega|genesis|mega ?drive|game ?gear|master system|famicom(?! ?mini)|snes|super nintendo|"
    r"super famicom|n64|nintendo 64|playstation|ps[1-5]|psp|n?ds|3ds|gamecube|wii|switch|xbox|amiga|atari|neo ?geo|"
    r"pc engine|turbografx|wonderswan)(?![a-z0-9])|" + jauce_photos.NOT_GAME_BOY, re.I)
EBAY_ID = re.compile(r"ebayimg\.com/(?:images/g|\d+/s/[^/]+/z)/([^/]+)/")


def straightened(key):
    return os.path.join(STRAIGHTENED, key.replace("@", "_").replace(",", "_") + ".avif")


def images(out_dir):
    """One JPEG per wanted print not yet searched: its label photo with the highest edge-model label confidence,
    straightened (generated/straighten/), long side at most 1024 px. Writes <out_dir>/queue.json (print -> label
    photo), in wanted order (best chances first)."""
    os.makedirs(out_dir, exist_ok=True)
    prints = json.load(open(PRINTS))["prints"]
    searched = load(SEARCHES)
    queue = {}
    for e in json.load(open(WANTED)):
        if e["print"] in searched:
            continue
        lp = prints.get(e["print"], {}).get("label_photos", {})
        keys = [k for k in lp if os.path.exists(straightened(k))]
        if not keys:
            continue
        k = max(keys, key=lambda k: lp[k]["pose"].get("edge", {}).get("label_confidence") or 0)
        out = os.path.join(out_dir, e["print"] + ".jpg")
        if not os.path.exists(out):
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", "-Z", "1024", straightened(k),
                            "--out", out], capture_output=True, check=True)
        queue[e["print"]] = k
    save(os.path.join(out_dir, "queue.json"), queue)
    print(f"{len(queue)} prints to search, in {out_dir}")


def words(title):
    t = unicodedata.normalize("NFKC", title).lower()
    if any(ord(c) > 0x3000 for c in t):
        return [w for w in jauce_photos.parts(title) if len(w) > 1]
    return [w for w in re.split(r"[^a-z0-9']+", t.replace("'", "")) if w and w not in STOP]


def right_game(match_title, release, wanted_title):
    """Whether a match's page title names the release (see the module's docstring)."""
    t = unicodedata.normalize("NFKC", match_title or "").lower().replace("'", "").replace("\u2019", "")
    if not t or OTHER_SYSTEM.search(t):
        return False
    code = release.split("-")[-1].lower() if release else None
    if code and re.search(rf"(?<![a-z0-9]){re.escape(code)}(?![a-z0-9])", t):
        return True
    titles = {wanted_title}
    r = serials_db().get(release)
    if r:
        titles |= {x["title"] for x in r.get("titles", [])} | {r["title"]}
    for title in titles:
        ws = words(title)
        found = [w for w in ws if w in t]
        if ws and len(found) >= 0.5 * len(ws) and any(len(w) >= 5 or ord(w[0]) > 0x3000 for w in found):
            return True
    return False


_db = None


def serials_db():
    global _db
    if _db is None:
        _db = {r["id"]: r for r in serials.releases()}
    return _db


def ingest(batch_file):
    """Records the batch's searches and downloads the right-game matches."""
    batch = json.load(open(batch_file))
    wanted = {e["print"]: e for e in json.load(open(WANTED))}
    known = open("photo-sources.json").read()
    today = datetime.date.today().isoformat()
    todo = []
    with locked(OUT):
        searches = load(SEARCHES)
        sources = load(SOURCES)
        known += json.dumps(sources)
        known_ebay = set(EBAY_ID.findall(known))
        for s in batch:
            p = s["print"]
            e = wanted.get(p, {})
            picked = []
            for i, m in enumerate(s["matches"]):
                u = m["image_url"]
                if max(m["width"], m["height"]) < MIN_SIDE or any(h in u.split("/")[2] for h in SKIP_HOSTS):
                    continue
                if not right_game(m.get("title"), e.get("release"), e.get("title", "")):
                    continue
                eid = EBAY_ID.search(u)
                if eid:
                    if eid.group(1) in known_ebay:
                        continue
                    known_ebay.add(eid.group(1))
                    u = re.sub(r"s-l\d+\.(jpg|jpeg|webp|png)", "s-l1600.jpg", u)
                elif json.dumps(u)[1:-1] in known:
                    continue
                known += json.dumps(u)
                picked.append((i, u, m))
            searches[p] = {"searched": s.get("searched", today), "text": s.get("text"), "label_photo": s.get("label_photo"),
                           "serial": (e.get("serials") or [None])[0], "release": e.get("release"),
                           "visual_matches": len(s["matches"]), "picked": len(picked),
                           **({"error": s["error"]} if s.get("error") else {})}
            todo += [(p, i, u, m, s, e) for i, u, m in picked]
        save(SEARCHES, searches)
    print(f"{len(batch)} searches, {len(todo)} photos to download", flush=True)
    for n, (p, i, u, m, s, e) in enumerate(todo):
        ext = os.path.splitext(u.split("?")[0])[1].lower()
        ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".avif") else ".jpg"
        name = f"lens-{p}-{i:02d}{ext}"
        record = {"page_url": m.get("page_url"), "image_url": u, "title_on_page": m.get("title"),
                  "size_on_google": [m["width"], m["height"]], "searched_print": p,
                  "searched_serial": (e.get("serials") or [None])[0], "searched_release": e.get("release"),
                  "query_label_photo": s.get("label_photo"), "query_text": s.get("text"), "fetched": today}
        tmp = os.path.join(DROP, name + ".part")
        os.makedirs(DROP, exist_ok=True)
        rc = subprocess.run(["curl", "-sSL", "--max-time", "60", "-A", UA, "-o", tmp, u]).returncode
        kind = subprocess.run(["file", "-b", "--mime-type", tmp], capture_output=True, text=True).stdout.strip() \
            if os.path.exists(tmp) else ""
        with locked(OUT):
            sources = load(SOURCES)
            if rc == 0 and kind.startswith("image/"):
                data = open(tmp, "rb").read()
                with locked(DROP):
                    os.replace(tmp, os.path.join(DROP, name))
                    listing = load(LISTING)
                    listing[name] = record
                    save(LISTING, listing)
                sources[name] = {**record, "sha1": hashlib.sha1(data).hexdigest(), "bytes": len(data)}
                print(f"{n + 1}/{len(todo)} ok {name}", flush=True)
            else:
                if os.path.exists(tmp):
                    os.remove(tmp)
                sources[name] = {**record, "failed": f"curl {rc}, {kind or 'no file'}"}
                print(f"{n + 1}/{len(todo)} FAILED {name} curl {rc} {kind}", flush=True)
            save(SOURCES, sources)
        time.sleep(random.uniform(5, 8))


if __name__ == "__main__":
    if sys.argv[1] == "images":
        images(sys.argv[2])
    elif sys.argv[1] == "ingest":
        ingest(sys.argv[2])
