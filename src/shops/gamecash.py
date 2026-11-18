"""Gamecash: the system page (jeux-occasion-game-boy-u29.html) is a hub with sliders only; the games are listed on its genre
pages (/<genre>-u29-c<N>.html, linked from the hub), 20 per page, numbered pages /gb-<genre>-u29-c<N>-p<K>.html (the
last one linked as "goLast"). A game in more than one genre is kept once. Photos: the tile's /thumbnail-120-130/<name>.jpg
is the product's first photo; /medias/<name>.jpg is the uploaded file (the product page's data-large). Sampled
2026-11-18: 290-620 px, so nearly all end up too small for MIN_SIDE."""
import html as htmllib
import re
from urllib.parse import urljoin


def tiles(base, s):
    for a in re.split(r'<article class="blockProduct', s)[1:]:
        u = re.search(r'<a href="([^"]+)" class="title"[^>]*>([^<]*)</a>', a)
        img = re.search(r'<img src="([^"]+)"', a)
        if u and img:
            yield urljoin(base, u.group(1)), htmllib.unescape(u.group(2)).strip(), urljoin(base, img.group(1))


def collect(shop, system, url):
    code, s = shop.get(url)
    m = re.search(r"-(u\d+)\.html", url)
    if not s or not m:
        return None
    genres = sorted(set(re.findall(rf'href="(/[a-z0-9-]+-{m.group(1)}-c\d+\.html)"', s)))
    out, seen = [], set()
    for g in genres:
        gurl = urljoin(url, g)
        code, s = shop.get(gurl)
        last = max([1] + [int(k) for k in re.findall(r'-p(\d+)\.html"[^>]*class="jsPagingLink', s or "")])
        first = re.search(r'href="([^"]+-p)1\.html"\s+class="jsPagingLink', s or "")
        n = 0
        for page in range(1, last + 1):
            if page > 1:
                code, s = shop.get(urljoin(url, f"{first.group(1)}{page}.html"))
            for u, title, img in tiles(gurl, s or ""):
                n += 1
                if u in seen:
                    continue
                seen.add(u)
                out.append({"url": u, "title": title, "image": re.sub(r"/thumbnail-[\d-]+/", "/medias/", img), "system": system})
            if not first:
                break
        shop.say(system, g, n, "tiles on", last, "pages")
    # products without a photo share a stand-in picture (e.g. /medias/retro-e112043.jpg): a photo on 3+ products is one
    uses = {}
    for it in out:
        uses[it["image"]] = uses.get(it["image"], 0) + 1
    shop.say(system, sum(1 for it in out if uses[it["image"]] >= 3), "products with a shared stand-in picture left out")
    return [it for it in out if uses[it["image"]] < 3]
