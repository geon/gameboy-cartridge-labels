import html, json, os, re, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos

# Downloads the first photo of each product in a category of Konsolenkost.de (a German shop, on plentymarkets), by
# default its loose Game Boy, Game Boy Color and Game Boy Advance games: the product's first photo is mostly its cartridge's front, at about 700-800 px.
# Saved into save-new-images-here/konsolenkost/, named konsolenkost-<photo's item id>-<file name>, with a listing.json
# there (file name -> its product page, the image, the product's name, the category), which make add-photos copies into
# sources.json. A category page lists 60 products in its JSON-LD (page=2, 3... until one brings nothing new); each
# product page holds its photos in its item's JSON ("images":{"all":[...]}, by position). The shop sells one game in
# several conditions, each a product of its own with photos of its own; those whose label is missing
# ("modulaufkleber-fehlt") are skipped. A first photo that comes back empty is passed over for the next. Products
# already downloaded (their page in photos/'s sources.json, or in the listing) are skipped. Its robots.txt (2026-11-05)
# shuts out /plenty/ and /xml/ only; one request every 1.5 s.
# Usage: konsolenkost.py [--limit <n per category>] [category URL...]
CATEGORIES = ("https://www.konsolenkost.de/gameboy-classic/spiele/?f_umfang=lose",
              "https://www.konsolenkost.de/gameboy-color/spiele/?f_umfang=lose",
              "https://www.konsolenkost.de/gameboy-advance/spiele/?f_umfang=lose")
OUT = os.path.join("save-new-images-here", "konsolenkost")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
DELAY = 1.5
SKIP = ("modulaufkleber-fehlt",)
LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)

args = sys.argv[1:]
limit = None
if args[:1] == ["--limit"]:
    limit, args = int(args[1]), args[2:]
categories = args or CATEGORIES
os.makedirs(OUT, exist_ok=True)
listing_path = os.path.join(OUT, "listing.json")
listing = json.load(open(listing_path)) if os.path.exists(listing_path) else {}
done = {e.get("page_url") for _, _, _, e in photos.all_sources()} | {e["page_url"] for e in listing.values()}


def get(url):
    time.sleep(DELAY)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as response:
        return response.read()


def products(text):
    """A category page's products: (page URL, name), from its JSON-LD item list."""
    for block in LD.findall(text):
        try:
            graph = json.loads(block).get("@graph", [])
        except ValueError:
            continue
        for node in graph:
            if node.get("@type") == "CollectionPage":
                return [(i["url"], i["name"]) for i in node["mainEntity"]["itemListElement"]]
    return []


def images(text):
    """A product page's photos' URLs, full size, by their position."""
    start = text.find('"images":{"all":')
    if start < 0:
        return []
    found, _ = json.JSONDecoder().raw_decode(text[start + len('"images":{"all":'):])
    return [i["url"] for i in sorted(found, key=lambda i: i.get("position", 0))]


for category in categories:
    seen, saved, number = set(), 0, 1
    while limit is None or saved < limit:
        url = category + ("&" if "?" in category else "?") + f"page={number}" if number > 1 else category
        items = [i for i in products(get(url).decode("utf-8", "replace")) if i[0] not in seen]
        if not items:
            break
        for page_url, name in items:
            seen.add(page_url)
            if page_url in done or any(s in page_url for s in SKIP) or (limit is not None and saved >= limit):
                continue
            for image_url in images(get(page_url).decode("utf-8", "replace")):
                data = get(image_url)
                if data.startswith((b"\xff\xd8", b"\x89PNG", b"RIFF")):
                    break
            else:
                print(f"no photo: {page_url}", flush=True)
                continue
            item, file = image_url.split("/")[-3], image_url.split("/")[-1]
            file = f"konsolenkost-{item}-{file}"
            open(os.path.join(OUT, file), "wb").write(data)
            listing[file] = {"page_url": page_url, "image_url": image_url, "site": "www.konsolenkost.de",
                             "title_on_page": html.unescape(name), "category": category}
            done.add(page_url)
            saved += 1
            json.dump(listing, open(listing_path, "w"), ensure_ascii=False, indent=1)
        number += 1
    print(f"{category}: {number} pages, {len(seen)} products, {saved} new photos", flush=True)
print(len(listing), "photos in", OUT)
