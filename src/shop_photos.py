"""Cartridge photos from retro game webshops: every product on each shop's Game Boy game pages (webshop-gameboy-pages.json,
found from regall.nl's webshop index, 2026-11-18), the first photo of each product, at full size.

Per shop, one request at a time (a second apart); shops run in parallel. How a shop's products are listed:
- Shopify: <collection>/products.json?limit=250&page=N (every product with its photos; product_type filter from the page's
  filter.p.product_type parameter).
- WooCommerce: the Store API, /wp-json/wc/store/v1/products?category=<id> (the category id by its slug, the listing URL's
  last part); a shop whose API is closed falls back to the generic way.
- Anything else (generic): the listing page and its numbered pages (page links found on the page: ?page=N, /page/N,
  ?p=N, ...); product links are the largest group of links sharing one URL shape that aren't menu links (links that also
  appear on another of the shop's pages); each product page's photo from og:image or its JSON-LD Product image.
- A shop with its own module, src/shops/<slug>.py (slug with underscores): its collect(shop, system, url).
Photo URLs are turned into the full-size original where the platform's pattern is known (WordPress -300x300 suffixes,
Shopify _600x sizes, PrestaShop -large_default, Lightspeed /600x600x2/ folders, width parameters); the URL as found if
that fails.

    python3 src/shop_photos.py run [<shop name> ...]      (all certain shops when none given)
    python3 src/shop_photos.py dry [<shop name> ...]      (find products, open 2 product pages per listing, no downloads)
    python3 src/shop_photos.py ingest <shop name> <items.json>   (products collected in a browser tab, for shops that refuse curl)

Listings: downloaded-photos/shop-listings/<slug>.json (every product found, so a run can be checked or resumed).
Photos: downloaded-photos/shop-<slug>/<slug>-<n>.<ext> with listing.json (page_url, image_url, title_on_page, shop, system),
moved to save-new-images-here/ by make move-downloads for make add-photos. Records: downloaded-photos/shop-sources/
<slug>.json (every product whose photo was downloaded or found too small, by page URL: never downloaded again).
"""
import datetime
import hashlib
import html as htmllib
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

sys.path.insert(0, os.path.dirname(__file__))
import ebay_photos  # noqa: E402
from ebay_photos import load, locked, save, size  # noqa: E402

PAGES = "webshop-gameboy-pages.json"
OUT = ebay_photos.DOWNLOADED
LISTINGS = os.path.join(OUT, "shop-listings")
SOURCES_DIR = os.path.join(OUT, "shop-sources")  # one records file per shop, so shops can run as separate processes
MIN_SIDE = 1000
# Shops whose photos are all smaller, kept anyway (the user, 2026-11-18).
SMALL_OK = {"Player 2 Gamestore", "Press Start Games", "Mad Gameshop", "Retro Gameland", "Gameshop Enter", "Gamewalhalla",
            "Retro Game World"}
MAX_PAGES = 400
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
# Not crawled by curl: shops that refuse it (403/Cloudflare: done through the browser instead), shops whose pages are
# not certain yet (webshop-gameboy-pages.json notes), Konsolenkost (its photos are already in, as composites).
SKIP = {"Tradergames", "Gameretro", "Lukie Games", "Konsolenkost", "RetroWorld", "Player 2 Gamestore", "Press Start Games",
        "Mad Gameshop", "Gameshop Enter", "Nedgame", "Retro Gameland", "eStarland", "Goat Store",
        "Gameshop Twente", "DK Oldies", "Netgames", "Gamecash", "Gameshop"}  # Netgames, gameshop.se: no cartridge photos; gameshop.nl: small stock pictures (the user, 2026-11-18); Gamecash: same style, small  # DK Oldies: no actual cartridge photos (the user, 2026-11-18)  # Gameshop Twente: photos named by EAN barcode, likely stock box pictures (held back, 2026-11-18)
sources_lock = threading.Lock()
DRY = False  # dry: find the products but open only 2 product pages per listing page, download nothing


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class Shop:
    def __init__(self, rec):
        self.rec, self.name, self.slug = rec, rec["name"], slug(rec["name"] + ("-se" if "gameshop.se" in rec["shop"] else ""))
        self.last = 0.0
        self.log = []
        self.is_woo = None

    def get(self, url, binary_to=None):
        """(status, text) with a second between requests to this shop."""
        wait = 1.0 - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        args = ["curl", "-sL", "--max-time", "40", "-A", UA, "-H", "Accept-Language: en,nl,sv,de;q=0.8", "-w", "%{http_code}"]
        if binary_to:
            r = subprocess.run(args + ["-o", binary_to, url], capture_output=True, text=True)
            return r.stdout.strip(), None
        r = subprocess.run(args + [url], capture_output=True)
        out = r.stdout
        return out[-3:].decode(), out[:-3].decode("utf-8", "replace")

    def say(self, *a):
        line = " ".join(str(x) for x in a)
        self.log.append(line)
        print(f"[{self.name}] {line}", flush=True)


# ---------- full-size photo URLs ----------

def full_size(u):
    """The original of a resized photo URL, where the platform's pattern is known."""
    p = urlparse(u)
    path = p.path
    if "cdn.shopify.com" in p.netloc or "/cdn/shop/" in path:
        path = re.sub(r"_(\d+x\d*|\d*x\d+|pico|icon|thumb|small|compact|medium|large|grande)(?=(@\dx)?\.\w+$)", "", path)
        return urlunparse(p._replace(path=path, query=""))
    if "webshopapp.com" in p.netloc:
        path = re.sub(r"/\d+x\d+x\d/", "/", path)
        return urlunparse(p._replace(path=path))
    if "/image/cache/catalog/" in path:                                                             # OpenCart
        path = re.sub(r"-\d{2,4}x\d{2,4}(?=\.\w+$)", "", path.replace("/image/cache/catalog/", "/image/catalog/"))
    path = re.sub(r"-\d{2,4}x\d{2,4}(?=\.\w+$)", "", path)                                         # WordPress
    path = re.sub(r"-(large|medium|home|small|cart|thickbox)_default(?=/)", "", path)               # PrestaShop
    q = {k: v for k, v in parse_qs(p.query).items() if k.lower() not in ("width", "height", "w", "h", "size", "resize", "fit", "quality", "q")}
    return urlunparse(p._replace(path=path, query=urlencode(q, doseq=True)))


# ---------- Shopify ----------

def shopify(shop, system, url):
    p = urlparse(url)
    m = re.search(r"/collections/([^/?#]+)", p.path)
    if not m:
        return None
    ptype = (parse_qs(p.query).get("filter.p.product_type") or [None])[0]
    root = f"{p.scheme}://{p.netloc}"
    out = []
    for page in range(1, MAX_PAGES):
        code, s = shop.get(f"{root}/collections/{m.group(1)}/products.json?limit=250&page={page}")
        try:
            prods = json.loads(s)["products"]
        except Exception:
            return None if page == 1 else out
        if not prods:
            break
        for pr in prods:
            if ptype and pr.get("product_type") != ptype:
                continue
            img = (pr.get("images") or [{}])[0].get("src")
            if img:
                out.append({"url": f"{root}/products/{pr['handle']}", "title": pr["title"], "image": img, "system": system})
    return out


# ---------- WooCommerce Store API ----------

def woocommerce(shop, system, url):
    p = urlparse(url)
    root = f"{p.scheme}://{p.netloc}"
    want = [s for s in p.path.split("/") if s][-1]
    if not hasattr(shop, "woo_cats"):
        shop.woo_cats = {}
        for page in range(1, 20):
            code, s = shop.get(f"{root}/wp-json/wc/store/v1/products/categories?per_page=100&page={page}")
            try:
                cats = json.loads(s)
            except Exception:
                break
            if not isinstance(cats, list) or not cats:
                break
            for c in cats:
                shop.woo_cats[c["slug"]] = c["id"]
    cid = shop.woo_cats.get(want)
    if not cid:
        return None
    out = []
    for page in range(1, MAX_PAGES):
        code, s = shop.get(f"{root}/wp-json/wc/store/v1/products?category={cid}&per_page=100&page={page}")
        try:
            prods = json.loads(s)
        except Exception:
            break
        if not isinstance(prods, list) or not prods:
            break
        for pr in prods:
            img = (pr.get("images") or [{}])[0].get("src")
            if img:
                out.append({"url": pr["permalink"], "title": htmllib.unescape(pr["name"]), "image": img, "system": system})
    return out


# ---------- generic ----------

def links(base, s, with_img=None):
    """{url: link text}; with_img (a set) gets the urls of links that wrap an image."""
    out = {}
    for m in re.finditer(r'<a\b[^>]*?href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', s, re.S | re.I):
        v = urljoin(base, htmllib.unescape(m.group(1).strip()))
        if urlparse(v).netloc.replace("www.", "") != urlparse(base).netloc.replace("www.", ""):
            continue
        out.setdefault(v, htmllib.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(2))).strip()[:120])
        if with_img is not None and re.search(r"<(img|picture)\b", m.group(2), re.I):
            with_img.add(v)
    return out


def shape(u):
    p = urlparse(u)
    segs = [s for s in p.path.split("/") if s]
    last = segs[-1] if segs else ""
    ext = "." + last.rsplit(".", 1)[1] if "." in last else ""
    head = "/".join(re.sub(r"\d+", "N", s) for s in segs[:-1])
    return f"{head}/*{ext}" + ("?" + "&".join(sorted(parse_qs(p.query))) if p.query else "")


PAGE_RX = re.compile(r"([?&](?:page|pagina|p|pg|seite|sayfa|pagenumber|paged)=)(\d+)|(/page/|/pagina/|/seite/)(\d+)|(/p|/page)(\d+)(?=/?$|\.html$)", re.I)
NOT_PRODUCT = re.compile(r"/(cart|checkout|account|login|wishlist|compare|contact|blog|news|search|zoek|sok|tag|brand|merk)\b|"
                         r"[?&](sort|order|orderby|filter|limit|view|mode)=|/page/\d|[?&]page=", re.I)


def page_urls(url, s):
    """The listing's numbered page links: {n: url}."""
    found = {}
    for v in links(url, s):
        m = PAGE_RX.search(v)
        if not m:
            continue
        n = int(next(g for g in (m.group(2), m.group(4), m.group(6)) if g))
        base_v = PAGE_RX.sub("", v).rstrip("/?&")
        if urlparse(base_v).path.rstrip("/") == urlparse(url).path.rstrip("/") or base_v.rstrip("/") == url.split("?")[0].rstrip("/"):
            found[n] = v
    return found


def rel_next(url, s):
    m = re.search(r'<(?:link|a)\b[^>]*rel=["\']next["\'][^>]*href=["\']([^"\']+)', s, re.I) or \
        re.search(r'<(?:link|a)\b[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\']next["\']', s, re.I)
    return urljoin(url, htmllib.unescape(m.group(1))) if m else None


def with_page(template, n):
    return PAGE_RX.sub(lambda m: (m.group(1) or m.group(3) or m.group(5)) + str(n), template, count=1)


def product_image(shop, url):
    code, s = shop.get(url)
    if not s:
        return None, None
    title = None
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', s, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict) and "Product" in str(it.get("@type")):
                img = it.get("image")
                if isinstance(img, list):
                    img = img[0] if img else None
                if isinstance(img, dict):
                    img = img.get("url") or img.get("contentUrl")
                title = it.get("name")
                if img:
                    return urljoin(url, img), title
    m = re.search(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)', s, re.I) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', s, re.I)
    t = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', s, re.I)
    return (urljoin(url, htmllib.unescape(m.group(1))) if m else None), (htmllib.unescape(t.group(1)) if t else title)


def generic(shop, system, url, menu):
    code, s = shop.get(url)
    if not s:
        shop.say("no answer", code, url)
        return []
    pages = page_urls(url, s)
    template = pages[max(pages)] if pages else None
    found, order = {}, []
    n, misses = 1, 0
    while True:
        imgs = set()
        L = {v: t for v, t in links(url, s, imgs).items() if v not in menu and not NOT_PRODUCT.search(v) and not PAGE_RX.search(v)}
        groups = {}
        for v in L:
            groups.setdefault(shape(v), []).append(v)
        # products: the group with most image links (product tiles), then the largest
        best = max(groups.values(), key=lambda g: (sum(v in imgs for v in g), len(g))) if groups else []
        new = [v for v in best if v not in found] if len(best) >= 3 else []
        for v in new:
            found[v] = L[v]
            order.append(v)
        nxt_rel = rel_next(url, s)
        if not new or not (template or nxt_rel):
            break
        n += 1
        if n > MAX_PAGES:
            break
        more = page_urls(url, s)
        if more and (not pages or max(more) > max(pages)):
            pages.update(more)
        nxt = nxt_rel or pages.get(n) or with_page(template, n)
        code, s = shop.get(nxt)
        if not s or code != "200":
            break
    shop.say(system, len(order), "product links on", n, "pages of", url)
    shop.found_links = getattr(shop, "found_links", 0) + len(order)
    out = []
    for v in (order[:2] if DRY else order):
        if shop_done(shop, v):
            continue
        img, title = product_image(shop, v)
        if img:
            out.append({"url": v, "title": title or found[v], "image": img, "system": system})
    return out


def sources_path(shop):
    return os.path.join(SOURCES_DIR, shop.slug + ".json")


def shop_done(shop, page_url):
    with sources_lock:
        return page_url in load(sources_path(shop))


# ---------- downloading ----------

def download(shop, items):
    drop = os.path.join(OUT, "shop-" + shop.slug)
    listing_path = os.path.join(drop, "listing.json")
    today = datetime.date.today().isoformat()
    kept = small = failed = 0
    for it in items:
        if shop_done(shop, it["url"]):
            continue
        os.makedirs(drop, exist_ok=True)
        tries = [full_size(it["image"]), it["image"]]
        ok = None
        for img in dict.fromkeys(tries):
            ext = os.path.splitext(urlparse(img).path)[1].lower()
            ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".avif") else ".jpg"
            name = f"{shop.slug}-{hashlib.sha1(it['url'].encode()).hexdigest()[:10]}{ext}"
            path = os.path.join(drop, name)
            code, _ = shop.get(img, binary_to=path)
            if code == "200" and os.path.exists(path) and os.path.getsize(path) > 2000:
                try:
                    wh = size(path)
                    ok = (img, name, path, wh)
                    break
                except Exception:
                    pass
            if os.path.exists(path):
                os.remove(path)
        record = {"shop": shop.name, "system": it["system"], "listing": it["url"], "listing_title": it["title"], "fetched": today}
        if not ok:
            failed += 1
            continue
        img, name, path, wh = ok
        record.update(image=img, size=wh, file=name)
        if max(wh) < MIN_SIDE and shop.name not in SMALL_OK:
            os.remove(path)
            record["too_small"] = True
            small += 1
        else:
            with locked(drop):
                listing = load(listing_path)
                listing[name] = {"page_url": it["url"], "image_url": img, "title_on_page": it["title"], "shop": shop.name,
                                 "system": it["system"], "fetched": today}
                save(listing_path, listing)
            kept += 1
        with sources_lock:
            os.makedirs(SOURCES_DIR, exist_ok=True)
            sources = load(sources_path(shop))
            sources[it["url"]] = record
            save(sources_path(shop), sources)
    shop.say("photos:", kept, "kept,", small, "too small,", failed, "failed")
    return kept, small, failed


def custom_collector(shop):
    """src/shops/<slug>.py's collect(shop, system, url) -> [{url, title, image, system}], for shops the generic way
    can't read; None from it falls back to the usual ways."""
    path = os.path.join(os.path.dirname(__file__), "shops", shop.slug.replace("-", "_") + ".py")
    if not os.path.exists(path):
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("shop_" + shop.slug.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.collect


def run_shop(rec):
    shop = Shop(rec)
    try:
        flat = [(k, u) for k, v in rec["pages"].items() for u in (v if isinstance(v, list) else [v])]
        menu = set()
        if len(flat) < 2:
            code, s = shop.get(rec["shop"])
            menu = set(links(rec["shop"], s or ""))
        else:  # links on two of the shop's listing pages: the menu
            seen = []
            for k, u in flat[:2]:
                code, s = shop.get(u)
                seen.append(set(links(u, s or "")))
            menu = seen[0] & seen[1]
        items, how = [], {}
        custom = custom_collector(shop)
        for system, u in flat:
            got, kind = None, None
            if custom:
                got, kind = custom(shop, system, u), "custom"
            if got is None and "/collections/" in u:
                got, kind = shopify(shop, system, u), "shopify"
            if got is None and getattr(shop, "is_woo", None) is not False:
                if shop.is_woo is None:
                    code, s = shop.get(u)
                    shop.is_woo = bool(re.search(r"woocommerce|wp-content/plugins/woo", s or "", re.I))
                if shop.is_woo:
                    got, kind = woocommerce(shop, system, u) or None, "woocommerce"  # none found: the generic way
            if got is None:
                got, kind = generic(shop, system, u, menu), "generic"
            how[u] = (kind, len(got))
            shop.say(system, kind, len(got), "products", u)
            items += got
        uniq = list({it["url"]: it for it in items}.values())
        if DRY:
            return shop.name, getattr(shop, "found_links", 0) or len(uniq), (how, [(it["title"][:35], full_size(it["image"])[-60:]) for it in uniq[:2]])
        os.makedirs(LISTINGS, exist_ok=True)
        save(os.path.join(LISTINGS, shop.slug + ".json"), {"shop": rec["name"], "pages": how, "products": uniq})
        return shop.name, len(uniq), download(shop, uniq)
    except Exception as e:
        shop.say("ERROR", repr(e))
        return shop.name, 0, (0, 0, 0)


def run(names=None):
    shops = [r for r in json.load(open(PAGES)) if r["pages"] and r["name"] not in SKIP and "system pages" not in r.get("note", "")]
    if names:
        shops = [r for r in shops if r["name"] in names]
    with ThreadPoolExecutor(len(shops) or 1) as ex:
        res = list(ex.map(run_shop, shops))
    print("\nSUMMARY")
    if DRY:
        for name, n, (how, sample) in res:
            print(f"{name:28s} {n:5d}  " + " ".join(f"{k}:{c}" for k, c in how.values()) + f"  {sample}")
        return
    for name, n, (k, sm, f) in res:
        print(f"{name:30s} {n:5d} products  {k:5d} kept  {sm:4d} too small  {f:4d} failed")


if __name__ == "__main__":
    if sys.argv[1] == "ingest":  # ingest <shop name> <items.json>: products collected in a browser tab
        rec = next(r for r in json.load(open(PAGES)) if r["name"] == sys.argv[2])
        shop, items = Shop(rec), json.load(open(sys.argv[3]))
        os.makedirs(LISTINGS, exist_ok=True)
        save(os.path.join(LISTINGS, shop.slug + ".json"), {"shop": rec["name"], "pages": "browser", "products": items})
        download(shop, items)
    elif sys.argv[1] in ("run", "dry"):
        DRY = sys.argv[1] == "dry"
        run(sys.argv[2:] or None)
