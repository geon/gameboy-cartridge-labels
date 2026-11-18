"""Gamewalhalla (OpenCart): product tiles (<div class="product-thumb">) on the listing and its /page-N pages; each tile has
the product link and its photo (image/cache/catalog/...-300x200h.JPG, original under image/catalog/, made by
shop_photos.full_size). Products and menu pages share one URL level here, so the generic crawler mixed them up."""
import html
import re


def collect(shop, system, url):
    out, seen = [], set()
    for n in range(1, 200):
        code, s = shop.get(url if n == 1 else url.rstrip("/") + f"/page-{n}")
        if code != "200" or not s:
            break
        new = 0
        for tile in re.split(r'<div class="product-thumb"', s)[1:]:
            a = re.search(r'<a href="([^"]+)" class="product-img', tile)
            img = re.search(r'<img src="([^"]+)"', tile)
            if not a or not img or a.group(1) in seen:
                continue
            alt = re.search(r'<img [^>]*alt="([^"]*)"', tile)
            seen.add(a.group(1))
            out.append({"url": html.unescape(a.group(1)), "title": html.unescape(alt.group(1)) if alt else "",
                        "image": html.unescape(img.group(1)), "system": system})
            new += 1
        if not new:
            break
    shop.say(system, len(out), "products on", n - 1, "pages")
    return out
