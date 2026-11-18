"""El Rincon Del Retro (ePages Now): the category page is server-rendered, 12 products per page, but ?page=N shows the
first 12×N products (load-more style), and the page's hydration data says totalNumberOfProducts; so page 1 for the count,
then one request for the page that holds them all. Photos: the cards' /storage/images/image?remote=<original>&width=600
proxy; the remote= URL (the shop's own /WebRoot/Store19/Shops/... file) is the uploaded original."""
import html as htmllib
import math
import re
from urllib.parse import parse_qs, urljoin, urlparse


def products(base, s, system):
    out = []
    for b in s.split('class="product-item"')[1:]:
        u = re.search(r'class="product-item-link" href="([^"]+)"', b)
        img = re.search(r'<meta itemProp="image" content="([^"]+)"', b)
        t = re.search(r'itemProp="name">([^<]+)<', b)
        if not (u and img):
            continue
        im = htmllib.unescape(img.group(1))
        remote = (parse_qs(urlparse(im).query).get("remote") or [None])[0]
        out.append({"url": urljoin(base, u.group(1)), "title": htmllib.unescape(t.group(1)).strip() if t else u.group(1),
                    "image": remote or urljoin(base, im), "system": system})
    return out


def collect(shop, system, url):
    base = url.split("?")[0]
    code, s = shop.get(base + "?page=1&sort=position-asc")
    m = re.search(r'\\"totalNumberOfProducts\\":(\d+)', s or "")
    if not m:
        shop.say("no product count on", url)
        return None
    total = int(m.group(1))
    per = len(products(base, s, system)) or 12
    pages = math.ceil(total / per)
    if pages > 1:
        code, s = shop.get(f"{base}?page={pages}&sort=position-asc")
    out = list({p["url"]: p for p in products(base, s, system)}.values())
    shop.say(system, len(out), "of", total, "products (page", pages, ") of", url)
    return out
