"""Retro Nintendo Kopen: the games pages are filled in the browser from Algolia (a third-party search service, not used
here); the shop's own product sitemaps (sitemap/products/gameboy-classic.xml, gameboy-color.xml, gameboy-advance.xml)
list the same products, in stock or not (the listing shows sold-out ones too, behind "Toon ook niet-voorradige
producten"), each with its photos in page order. A page's products: sitemap URLs under <system>/games/ or
gameboy/games/<system>/ that have a photo; the first photo, already the original (.../ProductPhotos/Source/<id>.jpg on the
sister shop's domain retronintendokaufen.de, where the product page loads it from too)."""
import html as htmllib
import re
from urllib.parse import urlparse

SITEMAPS = ["gameboy-classic", "gameboy-color", "gameboy-advance"]
PATHS = {"gameboy": ("/gameboy-classic/games/", "/gameboy/games/gameboy-classic/"),
         "gameboy-color": ("/gameboy-color/games/", "/gameboy/games/gameboy-color/"),
         "gameboy-advance": ("/gameboy-advance/games/", "/gameboy/games/gameboy-advance-gba/")}


def entries(shop, root):
    if not hasattr(shop, "rnk_entries"):
        shop.rnk_entries = []
        for name in SITEMAPS:
            code, s = shop.get(f"{root}/sitemap/products/{name}.xml")
            for u in re.findall(r"<url>(.*?)</url>", s or "", re.S):
                loc = re.search(r"<loc>([^<]+)", u)
                img = re.search(r"<image:loc>([^<]+)", u)
                title = re.search(r"<image:title>([^<]*)", u)
                if loc and img:
                    shop.rnk_entries.append((htmllib.unescape(loc.group(1).strip()), htmllib.unescape(img.group(1).strip()),
                                             htmllib.unescape(title.group(1).strip()) if title else ""))
    return shop.rnk_entries


def collect(shop, system, url):
    p = urlparse(url)
    key = p.path.strip("/").split("/")[0]
    if key not in PATHS:
        return None
    out, seen = [], set()
    for loc, img, title in entries(shop, f"{p.scheme}://{p.netloc}"):
        if not urlparse(loc).path.startswith(PATHS[key]) or loc in seen or img in seen:
            continue
        seen.update((loc, img))
        out.append({"url": loc, "title": title or loc.rsplit("/", 1)[-1], "image": img, "system": system})
    return out
