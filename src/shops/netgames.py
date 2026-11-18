"""Netgames (Gambio/xt:Commerce): the category page lists its products (also those of its subcategories neu/gebraucht) as
article-list-item tiles, ?listing_count=192 per page, numbered pages &page=N. Photos: the tile's
images/product_images/thumbnail_images/<id>_0.jpg is the product's first photo; original_images/ holds the uploaded file
(popup_images/ and info_images/ are 600 px copies)."""
import html as htmllib
import re


def collect(shop, system, url):
    out, seen = [], set()
    sep = "&" if "?" in url else "?"
    for page in range(1, 100):
        code, s = shop.get(f"{url}{sep}listing_count=192" + (f"&page={page}" if page > 1 else ""))
        new = 0
        for t in re.split(r'<div class="article-list-item">', s or "")[1:]:
            m = re.search(r'<a href="([^"]+)"><img src="([^"]+/product_images/)\w+_images/([^"]+)" alt="([^"]*)"', t)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            new += 1
            out.append({"url": htmllib.unescape(m.group(1)), "title": htmllib.unescape(m.group(4)).strip(),
                        "image": m.group(2) + "original_images/" + m.group(3), "system": system})
        total = re.search(r"von insgesamt <b>(\d+)</b>", s or "")
        if not new or (total and len(out) >= int(total.group(1))):
            break
    shop.say(system, len(out), "products of", total.group(1) if total else "?", "on", page, "pages")
    return out
