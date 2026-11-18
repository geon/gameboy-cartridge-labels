"""Gameshop (gameshop.nl): the platform page (page=producten/index&platform=X) shows all products, accessories included,
the rest loaded by its script while scrolling. The games alone: page=producten/games&platform=X, 30 per answer, each
answer's data-doomscroll attribute naming the next (…&rows=30&offset=N; empty on the last). Tiles link
page=producten/product&id=N. Photos: the tile's files/producten/thumbs/<name> is the product's first photo;
files/producten/images/<name> is the one the product page (og:image) shows."""
import html as htmllib
import re
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse


def collect(shop, system, url):
    platform = (parse_qs(urlparse(url).query).get("platform") or [None])[0]
    if not platform:
        return None
    nxt = urljoin(url, f"./?portlet=webshop&page=producten/games&platform={quote_plus(platform)}&char=%2A&offset=0")
    out, seen, n = [], set(), 0
    while nxt and n < 200:
        n += 1
        code, s = shop.get(nxt)
        for c in re.split(r'<div class="card product-card', s or "")[1:]:
            m = re.search(r'href="([^"]*page=producten/product&(?:amp;)?id=\d+)" title="([^"]*)"', c)
            img = re.search(r'<img src="([^"]+/files/producten/)thumbs/([^"]+)"', c)
            if not (m and img):
                continue
            u = urljoin(url, htmllib.unescape(m.group(1)))
            if u in seen:
                continue
            seen.add(u)
            out.append({"url": u, "title": htmllib.unescape(m.group(2)).strip(), "image": img.group(1) + "images/" + img.group(2),
                        "system": system})
        d = re.search(r'data-doomscroll="([^"]+)"', s or "")
        nxt = urljoin(url, htmllib.unescape(d.group(1))) if d else None
    shop.say(system, len(out), "games on", n, "pages", url)
    return out
