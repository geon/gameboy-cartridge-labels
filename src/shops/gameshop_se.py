"""Gameshop (gameshop.se, WooCommerce with the Store API closed): the category page lists 40 products per page as
li.product tiles, numbered pages /page/N/ (the last one linked). Photos: the tile's image is the product's first photo as a
WordPress -418x418 copy (the full-size original without the suffix: shop_photos.full_size); products without a photo show
woocommerce-placeholder.png and are left out (the product page has none either)."""
import html as htmllib
import re


def collect(shop, system, url):
    base = url.rstrip("/") + "/"
    out, seen, last, page, no_photo, fetched = [], set(), 1, 1, 0, 0
    while page <= last:
        fetched += 1
        code, s = shop.get(base + (f"page/{page}/" if page > 1 else ""))
        last = max([last] + [int(k) for k in re.findall(r'class="page-numbers" href="[^"]*/page/(\d+)/', s or "")])
        new = 0
        for li in re.findall(r'<li class="product type-product.*?</li>', s or "", re.S):
            u = re.search(r'<a href="([^"]+)"', li)
            img = re.search(r'<img[^>]*\bsrc="([^"]+)"', li)
            t = re.search(r'woocommerce-loop-product__title">([^<]*)<', li)
            if not u or u.group(1) in seen:
                continue
            seen.add(u.group(1))
            new += 1
            if not img or "placeholder" in img.group(1):
                no_photo += 1
                continue
            out.append({"url": htmllib.unescape(u.group(1)), "title": htmllib.unescape(t.group(1)).strip() if t else u.group(1),
                        "image": htmllib.unescape(img.group(1)), "system": system})
        if not new:
            break
        page += 1
    shop.say(system, len(out), "products with a photo,", no_photo, "without, on", fetched, "pages")
    return out
