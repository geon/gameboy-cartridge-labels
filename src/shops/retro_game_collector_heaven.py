"""Retro Game Collector Heaven (Zen Cart): each category page lists 48 products as centerBoxContentsProducts tiles
(main_page=product_info&...&products_id=N), numbered pages &page=N ("Zeige 1 bis 48 (von <total> Artikeln)"). Photos:
the tile's background images/medium/<name>_MED.jpg is the product's main photo; images/large/<name>_LRG.jpg is the one the
product page shows (1000 px; images/<name>.jpg is a small copy)."""
import html as htmllib
import re
from urllib.parse import urljoin


def collect(shop, system, url):
    out, seen = [], set()
    total = None
    for page in range(1, 100):
        code, s = shop.get(url + (f"&page={page}" if page > 1 else ""))
        new = 0
        for m in re.finditer(r'<a href="([^"]+products_id=\d+)"><div class="srb-article-thumbnail" style="background-image: url\(([^)]+)\)">'
                             r'</div><div class="srb-article-name">([^<]*)</div>', s or ""):
            u = htmllib.unescape(m.group(1))
            if u in seen:
                continue
            seen.add(u)
            new += 1
            img = re.sub(r"/medium/(.+)_MED(\.\w+)$", r"/large/\1_LRG\2", htmllib.unescape(m.group(2)).strip("'\""))
            out.append({"url": u, "title": htmllib.unescape(m.group(3)).strip(), "image": urljoin(url, img), "system": system})
        t = re.search(r"\(von <strong>(\d+)</strong> Artikeln\)", s or "")
        total = int(t.group(1)) if t else total
        if not new or (total and len(out) >= total):
            break
    shop.say(system, len(out), "products of", total, "on", page, "pages", url)
    return out
