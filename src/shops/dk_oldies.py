"""DK Oldies (BigCommerce + Searchspring): the category page's products are filled in by its script from the shop's own
endpoint https://inventory.dkoldies.com/admin/searchspring?pageurl=<category URL ?page=N>&data_cat_hirarchey[]=<breadcrumb
names>&per_page=48, which answers gzipped JSON whose productData is the rendered product cards (24 per page) and the
pagination links. Photos: the card's cdn11.bigcommerce.com .../images/stencil/175x175/products/... thumbnail is the
product's first photo; /stencil/original/ is the uploaded file."""
import html as htmllib
import json
import re
import subprocess
import time
from urllib.parse import urlencode

API = "https://inventory.dkoldies.com/admin/searchspring"


def get_json(shop, url):
    """Like shop.get, but decompressing (the endpoint gzips whatever the request says), spaced with the shop's requests."""
    wait = 1.0 - (time.time() - shop.last)
    if wait > 0:
        time.sleep(wait)
    shop.last = time.time()
    import shop_photos
    r = subprocess.run(["curl", "-sL", "--compressed", "--max-time", "40", "-A", shop_photos.UA,
                        "-H", "Origin: https://www.dkoldies.com", "-H", "Referer: https://www.dkoldies.com/", url], capture_output=True)
    try:
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        return None


def collect(shop, system, url):
    code, s = shop.get(url)
    i = (s or "").find('class="breadcrumbs"')
    crumbs = [htmllib.unescape(c).strip() for c in re.findall(r"<span>([^<]+)</span>", s[i:i + 3000])] if i >= 0 else []
    crumbs = [c for c in crumbs if c.lower() != "home"]
    out, seen, last = [], set(), 1
    page = 1
    while page <= last:
        q = [("pageurl", url + (f"?page={page}" if page > 1 else ""))] + [("data_cat_hirarchey[]", c) for c in crumbs] + [("per_page", "48")]
        d = get_json(shop, API + "?" + urlencode(q))
        h = (d or {}).get("productData") or ""
        if not h:
            shop.say("no product data for page", page, url)
            break
        last = max([last] + [int(n) for n in re.findall(r'pagination-link"\s+href="[^"]*[?&]page=(\d+)', h)])
        new = 0
        for c in re.split(r"<article\b", h)[1:]:
            u = re.search(r'href="([^"]+)"', c)
            img = re.search(r'<img[^>]*\bsrc="([^"]+/products/[^"]+)"', c)
            t = re.search(r'card-title[^>]*>\s*<a[^>]*>([^<]+)', c)
            if not (u and img) or u.group(1) in seen:
                continue
            seen.add(u.group(1))
            new += 1
            image = re.sub(r"/stencil/[^/]+/products/", "/stencil/original/products/", htmllib.unescape(img.group(1)))
            out.append({"url": u.group(1), "title": htmllib.unescape(t.group(1)).strip() if t else u.group(1), "image": image,
                        "system": system})
        if not new:
            break
        page += 1
    shop.say(system, len(out), "products on", page - 1, "of", last, "pages of", url)
    return out
