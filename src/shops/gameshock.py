"""Gameshock (Lightspeed): the category page's JSON (?format=json), page N at <category>/pageN.html?format=json. Each
product carries its first photo's id; the original is cdn.webshopapp.com/shops/<shop id>/files/<image id>/<url slug>.jpg.
Products without a photo (image 0) are left out."""
import json
from urllib.parse import urljoin


def collect(shop, system, url):
    base = url.split("?")[0].rstrip("/") + "/"
    out = []
    for page in range(1, 100):
        code, s = shop.get(base + (f"page{page}.html" if page > 1 else "") + "?format=json")
        try:
            d = json.loads(s)
            c = d["collection"]
        except Exception:
            return None if page == 1 else out
        sid = d["shop"]["id"]
        for p in (c.get("products") or {}).values():
            if not p.get("image"):
                continue
            name = p["url"].rsplit("/", 1)[-1].removesuffix(".html")
            out.append({"url": urljoin(url, "/" + p["url"]), "title": p.get("fulltitle") or p["title"],
                        "image": f"https://cdn.webshopapp.com/shops/{sid}/files/{p['image']}/{name}.jpg", "system": system})
        if not c.get("page_next") or page >= int(c.get("pages") or 1):
            break
    return out
