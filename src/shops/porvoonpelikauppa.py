"""Porvoonpelikauppa: the category page's product tiles (#items-container-items), 24 at a time; the next 24 from the
"Lataa lisää tuotteita" link (#pager-ctrl, a cursor URL) until a page adds nothing. Tile photos are .../items/<id>/small/
<name>; the original is .../items/<id>/<name>. The Game Boy games page mixes in GBA games (system from the title) and the
odd game for another console (left out). A page without a product grid (the GBA "page" in webshop-gameboy-pages.json is
the product page of a used GBA console) gives nothing."""
import html as htmllib
import re
from urllib.parse import urljoin

TILE = re.compile(r'class="item-image register-anchor".*?href="([^"]+)"\s+title="([^"]*)".*?data-src="([^"]+)"', re.S)
PAGER = re.compile(r'id="pager-ctrl"[^>]*href="([^"]+)"')
OTHER = re.compile(r"\b(ps[1-5]|playstation|xbox|switch|wii|ds|3ds|pc|psp|vita|nes|snes|n64|gamecube)\b", re.I)


def system_of(title, default):
    t = title.lower()
    if re.search(r"\bgba\b|advance", t):
        return "GBA"
    if re.search(r"\bgbc\b|color", t):
        return "GBC"
    return default


def collect(shop, system, url):
    out, seen, nxt = [], set(), url
    for _ in range(100):
        code, s = shop.get(nxt)
        if not s or "items-container-items" not in s:
            break
        new = 0
        for href, title, img in TILE.findall(s):
            u = urljoin(url, htmllib.unescape(href))
            if u in seen:
                continue
            seen.add(u)
            new += 1
            title = htmllib.unescape(title).strip()
            if OTHER.search(title):
                continue
            img = urljoin(url, htmllib.unescape(img)).replace("/small/", "/").replace("/medium/", "/")
            out.append({"url": u, "title": title, "image": img, "system": system_of(title, system)})
        m = PAGER.search(s)
        if not new or not m:
            break
        nxt = urljoin(url, htmllib.unescape(m.group(1)))
    return out
