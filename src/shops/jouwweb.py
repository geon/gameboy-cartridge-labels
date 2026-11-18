"""JouwWeb webshops (shared by replay_games.py and timmy_s_vintage_finds.py). The product gallery is server-rendered,
but its pagination links all point at the page itself: the site's script reloads the page with
?ep[<gallery element id>][page]=<0-based page> and swaps the gallery in. So: page 1, read data-page-total from the
gallery's <nav class="jw-pagination">, then ?ep[id][page]=1..total-1. Each tile has data-webshop-product (id, title, url)
and its main image; photos: primary.jwwb.nl/...-high.jpg is the largest rendition JouwWeb serves (it keeps no larger
original: -full, -original and the bare name are 404; ?enable=upscale only upscales), so the tile's src without its
?enable-io resize query."""
import html as htmllib
import json
import re
from urllib.parse import urljoin


def tiles(base, s, system):
    out = []
    for b in s.split('data-webshop-product="')[1:]:
        try:
            p = json.loads(htmllib.unescape(b[:b.index('"')]))
        except Exception:
            continue
        m = re.search(r'<img[^>]*class="product-image__image product-image__image--main"[^>]*\bsrc="([^"]+)"', b[:4000]) or \
            re.search(r'<img[^>]*\bsrc="(https://primary\.jwwb\.nl/[^"]+)"', b[:4000])
        img = htmllib.unescape(m.group(1)).split("?")[0] if m else (p.get("image") or {}).get("url")
        if not img:
            continue
        out.append({"url": urljoin(base, p["url"]), "title": p["title"], "image": img, "system": system})
    return out


def collect(shop, system, url):
    base = url.split("?")[0]
    code, s = shop.get(base)
    m = re.search(r'data-jw-element-id="(\d+)"\s+class="[^"]*\bjw-product-gallery\b', s or "")
    if not m:
        shop.say("no product gallery on", url)
        return None
    el = m.group(1)
    t = re.search(r'data-page-total="(\d+)"', s[m.end():])
    total = int(t.group(1)) if t else 1
    out = tiles(base, s, system)
    for page in range(1, total):
        code, s = shop.get(f"{base}?ep%5B{el}%5D%5Bpage%5D={page}")
        got = tiles(base, s or "", system)
        if not got:
            shop.say("nothing on page", page + 1, "of", url)
            break
        out += got
    out = list({p["url"]: p for p in out}.values())
    shop.say(system, len(out), "products on", total, "pages of", url)
    return out
