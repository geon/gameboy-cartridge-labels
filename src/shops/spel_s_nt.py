"""Spel & Sånt (Nuxt): the category page's product list is loaded by script from the shop's own API,
POST https://api.spelochsant.se/bombrest/products/json {"settings": {category, product_limit, limit_offset, ...}}
(50 products per answer at most). The category id is in the page's Nuxt data (ProductListSection's categoryId).
Photos: static.spelochsant.se/products/<id>_450x450.webp; <id>.webp is the original."""
import json
import re
import subprocess
import time

API = "https://api.spelochsant.se/bombrest/products/json"
SITE = "https://www.spelochsant.se"


def post(shop, url, body):
    """Like shop.get, but a JSON POST (the API takes no GET), spaced a second apart with the shop's other requests."""
    wait = 1.0 - (time.time() - shop.last)
    if wait > 0:
        time.sleep(wait)
    shop.last = time.time()
    import shop_photos
    r = subprocess.run(["curl", "-sL", "--max-time", "40", "-A", shop_photos.UA, "-H", "Content-Type: application/json",
                        "-X", "POST", "--data-binary", json.dumps(body), url], capture_output=True)
    return json.loads(r.stdout.decode("utf-8", "replace"))


def collect(shop, system, url):
    code, s = shop.get(url)
    m = re.search(r'"ProductListSection",\{"categoryId":(\d+)', s or "")
    if not m:
        shop.say("no categoryId on", url)
        return None
    # devalue: {"categoryId": n} holds the index of the value, not the value
    cid = m.group(1)
    data = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', s, re.S)
    if data:
        arr = json.loads(data.group(1))
        cid = arr[int(cid)]
    out, offset, total = [], 0, None
    while total is None or offset < total:
        d = post(shop, API, {"settings": {"sort_by": "popular", "sort_order": "desc", "product_limit": 50, "category": cid,
                                          "limit_offset": offset, "initial": offset == 0, "show_only_in_stock": False}})
        res = d.get("result") or {}
        prods = res.get("products") or []
        total = res.get("num_products", 0)
        if not prods:
            break
        offset += len(prods)
        for p in prods:
            if not p.get("main_image_id"):
                continue
            out.append({"url": f"{SITE}/produkt/{p['slug']}", "title": p["name"],
                        "image": f"https://static.spelochsant.se/products/{p['main_image_id']}.webp", "system": system})
    shop.say(system, "category", cid, ":", total, "products,", len(out), "with a photo")
    return out
