import html, http.cookiejar, json, os, re, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos

# Downloads the photo of each loose game in RetroNintendoStore.com's (a Dutch shop) Game Boy Classic, Game Boy Color
# and Game Boy Advance categories, at its largest (the 1920x1080 size: about 1100 x 1080), into
# save-new-images-here/retronintendostore/, named retronintendostore-<photo id>.jpg, with a listing.json there (file
# name -> its product page, the image, the product's name on the page, the category), which make add-photos copies
# into sources.json. A category page shows its first 28-odd products; the rest come page by page from the shop's
# xajax handler (CategoryFilter, Page 2, 3...), as its "load more" button gets them. Products already downloaded (their
# page in photos/'s sources.json, or in the listing) are skipped. Its robots.txt (2026-11-05) shuts out Yandex only and
# no product pages; one request every 1.5 s.
# Usage: retronintendostore.py [--limit <n per category>] [category path...] (default: the three below)
SITE = "https://www.retronintendostore.com"
CATEGORIES = ("gameboy-classic/games", "gameboy-color/games", "gameboy-advance/games")
OUT = os.path.join("save-new-images-here", "retronintendostore")
AJAX = SITE + "/website/Includes/AjaxFunctions/WebsiteAjaxHandler.php?Show=ProductCategory"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
DELAY = 1.5
# A product in a category page: its page, its photo (by id, here in the 400x400 size), its name.
ITEM = re.compile(r'<a href="(https://www\.retronintendostore\.com/[^"]+)">\s*(?:<!--(?:(?!-->).)*-->)?\s*<img\s+src="[^"]*/ProductPhotos/'
                  r'400x400/(\d+)\.(jpg|jpeg|png)"[^>]*alt="([^"]*)"', re.S)
FIELD = re.compile(r'<input type="hidden" name="(CategoryId|CategoryLayoutId|NumberOfItems|OrderBy)"[^>]*value="([^"]*)"')

args = sys.argv[1:]
limit = None
if args[:1] == ["--limit"]:
    limit, args = int(args[1]), args[2:]
categories = args or CATEGORIES
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
os.makedirs(OUT, exist_ok=True)
listing_path = os.path.join(OUT, "listing.json")
listing = json.load(open(listing_path)) if os.path.exists(listing_path) else {}
done = {e.get("page_url") for _, _, _, e in photos.all_sources()} | {e["page_url"] for e in listing.values()}


def get(url, data=None, referer=None):
    time.sleep(DELAY)
    headers = {"User-Agent": UA} | ({"Referer": referer} if referer else {})
    body = urllib.parse.urlencode(data).encode() if data else None
    with opener.open(urllib.request.Request(url, body, headers), timeout=60) as response:
        return response.read()


def page(fields, number, referer):
    """A category's products on one page, from the xajax handler."""
    fields = dict(fields, Page=str(number))
    args = "<xjxobj>" + "".join(f"<e><k>{k}</k><v>{html.escape(v)}</v></e>" for k, v in fields.items()) + "</xjxobj>"
    return get(AJAX, {"xajax": "CategoryFilter", "xajaxr": str(int(time.time() * 1000)), "xajaxargs[]": args}, referer).decode("utf-8", "replace")


for category in categories:
    url = f"{SITE}/{category}"
    text = get(url).decode("utf-8", "replace")
    fields = dict(FIELD.findall(text))
    seen, saved, number = set(), 0, 1
    while True:
        items = [i for i in ITEM.findall(text) if i[0] not in seen]
        for page_url, photo, ext, name in items:
            seen.add(page_url)
            if page_url in done or (limit is not None and saved >= limit):
                continue
            image_url = f"{SITE}/Files/2/40000/40305/ProductPhotos/1920x1080/{photo}.{ext}"
            data = get(image_url, referer=page_url)
            if not (data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG")):
                print(f"not an image: {image_url}", flush=True)
                continue
            file = f"retronintendostore-{photo}.{ext.replace('jpeg', 'jpg')}"
            open(os.path.join(OUT, file), "wb").write(data)
            listing[file] = {"page_url": page_url, "image_url": image_url, "site": "www.retronintendostore.com",
                             "title_on_page": html.unescape(name), "category": category}
            done.add(page_url)
            saved += 1
            json.dump(listing, open(listing_path, "w"), ensure_ascii=False, indent=1)
        if not items or (limit is not None and saved >= limit):
            break
        number += 1
        text = page(fields, number, url)
    print(f"{category}: {number} pages, {len(seen)} products, {saved} new photos", flush=True)
print(len(listing), "photos in", OUT)
