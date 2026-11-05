import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos

# Downloads a photo of each loose Game Boy, Game Boy Color and Game Boy Advance game in stock at Konsolenkost.de (a
# German shop, on plentymarkets): the first photo of one copy's product page, mostly its cartridge's front, at about
# 700-800 px. Saved into save-new-images-here/konsolenkost/, named konsolenkost-<photo's item id>-<file name>, with a
# listing.json there (file name -> its product page, the image, the game's name, its system), which make add-photos
# copies into sources.json.
# The games come from the shop's own search (Typesense, as its category pages ask it, with the search-only key they
# use): in stock, "nur Modul", not bundles, 250 a page. A game is a group of copies, each in a condition of its own,
# with a product page and photos of its own; one copy is taken: the one the search shows, or the first copy in stock
# sold loose, but not one whose label is missing ("modulaufkleber-fehlt"). The search's cover images are no use (about
# 500 px, none of 5 read). On the product page, the photos are in its item's JSON ("images":{"all":[...]}, by
# position); a photo that comes back empty or not found is passed over for the next. Games of which a copy was downloaded before
# (its page, by its variation id, in photos/'s sources.json or in the listing) are skipped. Its robots.txt
# (2026-11-05) shuts out /plenty/ and /xml/ only; one request every 1.5 s; a dropped connection is tried again.
# Usage: konsolenkost.py [--limit <n per system>] [system...] (default: GameBoy, "GameBoy Color", "GameBoy Advance")
SITE = "https://www.konsolenkost.de"
SEARCH = "https://articles-search-new.konsolenkost-tools.de/typesense/collections/item_group/documents/search"
KEY = "jZTCb103h1Ywxz86ASiciAyBGGewODPZ"
SYSTEMS = ("GameBoy", "GameBoy Color", "GameBoy Advance")
OUT = os.path.join("save-new-images-here", "konsolenkost")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
DELAY = 1.5
SKIP = ("modulaufkleber-fehlt",)
# A product page's variation id: the last number in its URL.
VARIATION = re.compile(r"_(\d+)/?$")

args = sys.argv[1:]
limit = None
if args[:1] == ["--limit"]:
    limit, args = int(args[1]), args[2:]
systems = args or SYSTEMS
os.makedirs(OUT, exist_ok=True)
listing_path = os.path.join(OUT, "listing.json")
listing = json.load(open(listing_path)) if os.path.exists(listing_path) else {}
pages = {e.get("page_url") or "" for _, _, _, e in photos.all_sources()} | {e["page_url"] for e in listing.values()}
done = {m.group(1) for m in map(VARIATION.search, pages) if m}


def get(url, referer=None):
    """A URL's body; a dropped connection (not an HTTP error) is tried again after 30, 60 and 120 s."""
    headers = {"User-Agent": UA} | ({"Referer": referer} if referer else {})
    for wait in (30, 60, 120, None):
        time.sleep(DELAY)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
            if wait is None:
                raise
            print(f"{error}, waiting {wait} s: {url}", flush=True)
            time.sleep(wait)


def games(system):
    """The loose games in stock for a system, as the search gives them."""
    found, number = [], 1
    while True:
        query = {"q": "*", "per_page": "250", "page": str(number), "x-typesense-api-key": KEY,
                 "filter_by": f"system:=`{system}` && genre:!=[BUNDLEARTIKEL] && availability:!=`Ausverkauft` && items.packaging:=`nur Modul`",
                 "exclude_fields": "description,eans,attributes,bundle,category_pages"}
        hits = json.loads(get(SEARCH + "?" + urllib.parse.urlencode(query), SITE + "/"))["hits"]
        found += [h["document"] for h in hits]
        if len(hits) < 250:
            return found
        number += 1


def copy(game):
    """The URL path of the copy to take, or None."""
    loose = [i["url_path"] for i in game.get("items", []) if "nur Modul" in i.get("packaging", [])
             and i.get("availability") != "Ausverkauft" and not any(s in i["url_path"] for s in SKIP)]
    return game["url"] if game["url"] in loose else (loose or [None])[0]


def images(text):
    """A product page's photos' URLs, full size, by their position."""
    start = text.find('"images":{"all":')
    if start < 0:
        return []
    found, _ = json.JSONDecoder().raw_decode(text[start + len('"images":{"all":'):])
    return [i["url"] for i in sorted(found, key=lambda i: i.get("position", 0))]


for system in systems:
    found = games(system)
    saved = skipped = 0
    for game in found:
        if limit is not None and saved >= limit:
            break
        variations = {m.group(1) for m in (VARIATION.search(i["url_path"]) for i in game.get("items", [])) if m}
        path = copy(game)
        if variations & done or path is None:
            skipped += 1
            continue
        page_url = SITE + path.rstrip("/") + "/"
        try:
            urls = images(get(page_url).decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            print(f"{error.code}: {page_url}", flush=True)
            continue
        for image_url in urls:
            try:
                data = get(image_url)
            except urllib.error.HTTPError as error:
                print(f"{error.code}: {image_url}", flush=True)
                continue
            if data.startswith((b"\xff\xd8", b"\x89PNG", b"RIFF")):
                break
        else:
            print(f"no photo: {page_url}", flush=True)
            continue
        file = f"konsolenkost-{image_url.split('/')[-3]}-{image_url.split('/')[-1]}"
        open(os.path.join(OUT, file), "wb").write(data)
        listing[file] = {"page_url": page_url, "image_url": image_url, "site": "www.konsolenkost.de",
                         "title_on_page": game.get("short_name") or game.get("name"), "system": system}
        done |= variations
        saved += 1
        json.dump(listing, open(listing_path, "w"), ensure_ascii=False, indent=1)
    print(f"{system}: {len(found)} games, {saved} new photos, {skipped} skipped (downloaded before, or no loose copy)", flush=True)
print(len(listing), "photos in", OUT)
