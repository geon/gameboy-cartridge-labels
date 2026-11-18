"""VPD (Magento 2): the category page's product tiles, 25 a page, ?p=N until a page adds nothing. Tile photos are cache
(often Amasty webp) copies, .../media/[amasty/webp/]catalog/product/cache/<hash>/a/b/<name>[_jpg.webp]; the original is
.../media/catalog/product/a/b/<name>.jpg. Products without a photo (Magento's placeholder) are left out.
The pages mix games with accessories, consoles, spare parts and merchandise, and there is no games-only filter; games are
the titles carrying a system tag (Pokemon Red (L) GB (Käytetty), Doom (CIB) GBA (Käytetty), ... (GBC) (Käytetty)) that
aren't consoles or accessories. The system is taken from that tag: the pages list each other's games too.
The GBA page in webshop-gameboy-pages.json (pelit/3ds/gba-pelit-ja-tarvikkeet.html) holds 2 products; the retro GBA
category (pelit/retropelit-ja-tarvikkeet/gba.html) is read instead."""
import html as htmllib
import re
from urllib.parse import urlparse

TILE = re.compile(r'<a href="([^"]+)" class="product photo product-item-photo".*?data-name="([^"]*)".*?'
                  r'<img class="product-image-photo" src="([^"]+)"', re.S)
TAG = re.compile(r"\(?\b(GBA|GBC|GB)\b\)?")
NOT_GAME = re.compile(r"^game ?boy|konsoli|console|paristo|battery|kotelo|kaapeli|näyttö|kalvo|kontaktikumi|kasettisuoja|"
                      r"protector|lasinalunen|ruuvi|tarvike|muki|juomapullo|stressilelu|rocker|palapeli|kirja", re.I)
RETRO = "https://www.vpd.fi/pelit/retropelit-ja-tarvikkeet/"


def original(img):
    p = urlparse(img)
    path = p.path.replace("/media/amasty/webp/", "/media/")
    path = re.sub(r"/catalog/product/cache/[0-9a-f]+/", "/catalog/product/", path)
    path = re.sub(r"_(jpe?g|png|gif)\.webp$", r".\1", path)
    return p._replace(path=path, query="").geturl()


def tiles(shop, url):
    """[(product url, title, photo url)] from every page of a category."""
    out, seen = [], set()
    for n in range(1, 100):
        code, s = shop.get(url + (f"?p={n}" if n > 1 else ""))
        if not s:
            break
        new = 0
        for href, name, img in TILE.findall(s):
            href = htmllib.unescape(href)
            if href in seen:
                continue
            seen.add(href)
            new += 1
            out.append((href, re.sub(r"\s+", " ", htmllib.unescape(name)).strip(), htmllib.unescape(img)))
        if not new:
            break
    return out


def collect(shop, system, url):
    url = url.split("?")[0]
    if "/3ds/gba-pelit-ja-tarvikkeet" in url:
        url = RETRO + "gba.html"
    out = []
    for href, title, img in tiles(shop, url):
        tags = TAG.findall(title)
        if not tags or NOT_GAME.search(title) or "placeholder" in img:
            continue
        out.append({"url": href, "title": title, "image": original(img), "system": tags[-1]})
    return out
