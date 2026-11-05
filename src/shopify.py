import json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos

# Downloads the first photo of each loose game in a Shopify shop's Game Boy, Game Boy Color and Game Boy Advance
# collections (SHOPS), mostly the cartridge's front, into save-new-images-here/<shop>/, named <shop>-<product
# handle>.<ext>, with a listing.json there (file name -> its product page, the image, the product's title, the
# collection), which make add-photos copies into sources.json. A collection's products come from Shopify's
# products.json, 250 a page. Fetched with curl: these shops answer Python's urllib with 429 (too many requests) from
# the first request on, curl not. Products already downloaded (their page in photos/'s sources.json, or in the listing)
# are skipped. One request every 1.5 s, and on 429 a wait as asked (a minute if not said), 5 times.
# - retroraven: Retro Raven Games (retroravengames.com), every product; on 5 Game Boy games, 3 read their serial;
#   about 1000 x 750.
# - zockbar: Zockbar (zockbar.ch, Swiss), the products of type Games not tagged OVP (boxed): its "Modul" filter isn't
#   in products.json; on 5 Game Boy games, 5 read their serial; 2048 x 2048. Its robots.txt (2026-11-05) shuts out
#   the collections' sort and filter URLs, not products.json.
# Usage: shopify.py [--limit <n per collection>] <shop> [collection...]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
DELAY = 1.5
SHOPS = {
    "retroraven": dict(site="https://retroravengames.com", keep=lambda p: True,
                       collections=("game-boy-games", "game-boy-color-games", "game-boy-advance-games")),
    "zockbar": dict(site="https://zockbar.ch", keep=lambda p: p["product_type"] == "Games" and "OVP" not in p["tags"],
                    collections=("game-boy", "game-boy-color", "game-boy-advance")),
}

args = sys.argv[1:]
limit = None
if args[:1] == ["--limit"]:
    limit, args = int(args[1]), args[2:]
shop, collections = args[0], args[1:]
SITE, keep = SHOPS[shop]["site"], SHOPS[shop]["keep"]
collections = collections or SHOPS[shop]["collections"]
OUT = os.path.join("save-new-images-here", shop)
os.makedirs(OUT, exist_ok=True)
listing_path = os.path.join(OUT, "listing.json")
listing = json.load(open(listing_path)) if os.path.exists(listing_path) else {}
done = {e.get("page_url") for _, _, _, e in photos.all_sources()} | {e["page_url"] for e in listing.values()}


def get(url):
    """A URL's body, through curl; on 429, waits as told (Retry-After, else a minute) and tries again, 5 times."""
    for attempt in range(6):
        time.sleep(DELAY)
        result = subprocess.run(["curl", "-sSL", "-A", UA, "-D", "-", "-o", "/dev/stderr", url], capture_output=True)
        head = result.stdout.decode("latin-1").split("\r\n\r\n")[-2] if b"\r\n\r\n" in result.stdout else ""
        status = int(head.split(" ", 2)[1]) if head.startswith("HTTP/") else 0
        if result.returncode == 0 and status == 200:
            return result.stderr
        if status != 429 or attempt == 5:
            raise RuntimeError(f"{status or result.stderr[-200:]!r}: {url}")
        wait = next((int(line.split(":", 1)[1]) for line in head.split("\r\n") if line.lower().startswith("retry-after:")
                     and line.split(":", 1)[1].strip().isdigit()), 60)
        print(f"429, waiting {wait} s: {url}", flush=True)
        time.sleep(wait)


for collection in collections:
    saved, number, count, kept = 0, 1, 0, 0
    while limit is None or saved < limit:
        products = json.loads(get(f"{SITE}/collections/{collection}/products.json?limit=250&page={number}"))["products"]
        if not products:
            break
        count += len(products)
        for product in products:
            page_url = f"{SITE}/products/{product['handle']}"
            if not keep(product) or not product["images"]:
                continue
            kept += 1
            if page_url in done or (limit is not None and saved >= limit):
                continue
            image_url = product["images"][0]["src"].split("?")[0]
            data = get(image_url)
            if not data.startswith((b"\xff\xd8", b"\x89PNG", b"RIFF")):
                print(f"not an image: {image_url}", flush=True)
                continue
            ext = os.path.splitext(image_url)[1].lower().replace(".jpeg", ".jpg")
            file = f"{shop}-{product['handle']}{ext}"
            open(os.path.join(OUT, file), "wb").write(data)
            listing[file] = {"page_url": page_url, "image_url": image_url, "site": SITE.split("//")[1],
                             "title_on_page": product["title"], "collection": collection}
            done.add(page_url)
            saved += 1
            json.dump(listing, open(listing_path, "w"), ensure_ascii=False, indent=1)
        number += 1
    print(f"{collection}: {count} products, {kept} kept, {saved} new photos", flush=True)
print(len(listing), "photos in", OUT)
