import json, os, sys, time, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos

# Downloads the first photo of each product in Retro Raven Games' (retroravengames.com, a Shopify shop) Game Boy, Game
# Boy Color and Game Boy Advance collections, mostly the cartridge's front (on 5 Game Boy games, 3 read their serial),
# at about 1000 x 750, into save-new-images-here/retroraven/, named retroraven-<product handle>.<ext>, with a
# listing.json there (file name -> its product page, the image, the product's title, the collection), which make
# add-photos copies into sources.json. A collection's products come from Shopify's products.json, 250 a page. Products
# already downloaded (their page in photos/'s sources.json, or in the listing) are skipped. Its robots.txt (2026-11-05)
# allows the collections and products; one request every 1.5 s, and on 429 a wait as asked.
# Usage: retroraven.py [--limit <n per collection>] [collection...]
SITE = "https://retroravengames.com"
COLLECTIONS = ("game-boy-games", "game-boy-color-games", "game-boy-advance-games")
OUT = os.path.join("save-new-images-here", "retroraven")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
DELAY = 1.5

args = sys.argv[1:]
limit = None
if args[:1] == ["--limit"]:
    limit, args = int(args[1]), args[2:]
collections = args or COLLECTIONS
os.makedirs(OUT, exist_ok=True)
listing_path = os.path.join(OUT, "listing.json")
listing = json.load(open(listing_path)) if os.path.exists(listing_path) else {}
done = {e.get("page_url") for _, _, _, e in photos.all_sources()} | {e["page_url"] for e in listing.values()}


def get(url):
    """A URL's body; on 429 (too many requests), waits as told (Retry-After, else a minute) and tries again, 5 times."""
    for attempt in range(6):
        time.sleep(DELAY)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 5:
                raise
            wait = int(error.headers.get("Retry-After") or 60)
            print(f"429, waiting {wait} s: {url}", flush=True)
            time.sleep(wait)


for collection in collections:
    saved, number, count = 0, 1, 0
    while limit is None or saved < limit:
        products = json.loads(get(f"{SITE}/collections/{collection}/products.json?limit=250&page={number}"))["products"]
        if not products:
            break
        count += len(products)
        for product in products:
            page_url = f"{SITE}/products/{product['handle']}"
            if page_url in done or not product["images"] or (limit is not None and saved >= limit):
                continue
            image_url = product["images"][0]["src"].split("?")[0]
            data = get(image_url)
            if not data.startswith((b"\xff\xd8", b"\x89PNG", b"RIFF")):
                print(f"not an image: {image_url}", flush=True)
                continue
            ext = os.path.splitext(image_url)[1].lower().replace(".jpeg", ".jpg")
            file = f"retroraven-{product['handle']}{ext}"
            open(os.path.join(OUT, file), "wb").write(data)
            listing[file] = {"page_url": page_url, "image_url": image_url, "site": "retroravengames.com",
                             "title_on_page": product["title"], "collection": collection}
            done.add(page_url)
            saved += 1
            json.dump(listing, open(listing_path, "w"), ensure_ascii=False, indent=1)
        number += 1
    print(f"{collection}: {count} products, {saved} new photos", flush=True)
print(len(listing), "photos in", OUT)
