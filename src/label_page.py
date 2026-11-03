import html, json, os, sys, cv2, numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serials
from cartridge import BODY
import render

# label-page: a page of every DMG-shell release's label (make render-labels) laid on an empty cartridge of its shell's
# color, into generated/label-page/index.html (open it as a file). The empty cartridges are templates/dmg-gray.png and
# templates/dmg-black.png (from the collection-pipeline branch; 994 x 1132 px, framed on the 57 x 65 mm body), each a
# card's background image; the label is an element of its own on it, placed straight and centered in the recess, with
# rounded corners and a drop shadow.
# The shell's color: black for the releases gb-game-list marks gameBoyColorEnhanced, gray for the others, but for
# those in EXCEPTIONS. As a check, the plastic's lightness in the release's cartridge image (make render-carts; the
# median at points beside and below the recess, PLASTIC) is measured: a release looking black (below BLACK_BELOW) but
# given gray, or the other way round, is marked on the page. Measured on 1084 releases (2026-11-03, OpenCV's L, 0-255):
# gray shells 120 to 200, black ones mostly below 60, few between 73 and 85; 18 disagreed with gb-game-list.
# Usage: label_page.py
OUT = "generated/label-page/index.html"
TEMPLATES = {"gray": "templates/dmg-gray.png", "black": "templates/dmg-black.png"}
PLASTIC = np.array([[x, y] for x in (2.5, 3.5, 4.5, 52.5, 53.5, 54.5) for y in np.linspace(22, 54, 9)]
                   + [[x, y] for x in np.linspace(12, 45, 12) for y in (59.0, 60.5)], np.float64)
BLACK_BELOW = 80
# Releases whose shell isn't the color gb-game-list implies: release id -> "gray" or "black".
EXCEPTIONS = {}
LABEL_RADIUS = 1.4  # mm, as review-labels draws it
CART_WIDTH = 200  # px, on the page
# A test: releases shown twice as high, spanning two rows of the grid, the others flowing around them.
TALL = {"DMG-A3PJ"}


def lightness(release):
    """The plastic's median lightness (0-255) in the release's cartridge image, None if it has none."""
    path = os.path.join(render.OUT["carts"], render.file_of(release))
    if not os.path.exists(path):
        return None
    image = np.array(Image.open(path).convert("RGB"))[..., ::-1]
    xy = ((PLASTIC + render.CART_MARGIN) * render.CART_PX_PER_MM).round().astype(int)
    return float(np.median(cv2.cvtColor(image[xy[:, 1], xy[:, 0]][None], cv2.COLOR_BGR2Lab)[0, :, 0]))


def main():
    made = json.load(open(os.path.join(render.OUT["labels"], "made.json")))
    releases = {r["id"]: r for r in json.load(open(serials.RELEASES))}
    here = os.path.dirname(OUT)
    rel = lambda p: os.path.relpath(p, here)
    w, h = render.LABEL_MM
    left, top = BODY[0] / 2 - w / 2, 37.5 - h / 2  # the recess's middle (cartridge.RECESS)
    pct = lambda part, whole: f"calc({part:g} / {whole:g} * 100%)"  # mm of the cartridge's width or height (the label's, for its corners)
    px = lambda mm: f"calc({mm:g} * {CART_WIDTH}px / {BODY[0]:g})"  # mm on the page
    cards, counts, doubts = [], {"gray": 0, "black": 0}, 0
    for release in sorted(r for r, m in made.items() if m["shell"] == "dmg"):
        info = releases.get(release, {})
        color = EXCEPTIONS.get(release, "black" if info.get("gameBoyColorEnhanced") else "gray")
        counts[color] += 1
        title = info.get("title", "")
        L = lightness(release)
        looks = None if L is None else "black" if L < BLACK_BELOW else "gray"
        doubt = looks is not None and looks != color and release not in EXCEPTIONS
        doubts += doubt
        note = f' <span class="doubt">photo looks {looks} (L {L:.0f})</span>' if doubt else ""
        cards.append(f'<figure class="{color}{" tall" if release in TALL else ""}"><div class="cart"><img src="{html.escape(rel(os.path.join(render.OUT["labels"], render.file_of(release))))}" '
                     f'loading="lazy" alt=""></div><figcaption><b>{html.escape(release)}</b> {html.escape(title)}{note}</figcaption></figure>')
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DMG labels</title>
<style>
body {{ margin: 0; padding: 16px; background: #e8e6e1; font: 13px/1.3 system-ui, sans-serif; color: #222; }}
h1 {{ font-size: 18px; font-weight: 600; margin: 0 0 4px; }}
p {{ margin: 0 0 16px; color: #555; }}
main {{ display: grid; grid-template-columns: repeat(auto-fill, {CART_WIDTH}px); grid-auto-flow: dense; gap: 20px; }}
figure {{ margin: 0; width: {CART_WIDTH}px; }}
.cart {{ position: relative; aspect-ratio: {BODY[0]:g} / {BODY[1]:g}; width: {CART_WIDTH}px; background: center / 100% 100% no-repeat; }}
.tall {{ grid-row: span 2; }}
.tall .cart {{ aspect-ratio: {BODY[0]:g} / {2 * BODY[1]:g}; }}
.gray .cart {{ background-image: url("{rel(TEMPLATES["gray"])}"); }}
.black .cart {{ background-image: url("{rel(TEMPLATES["black"])}"); }}
.cart img {{ position: absolute; left: {pct(left, BODY[0])}; top: {pct(top, BODY[1])}; width: {pct(w, BODY[0])}; height: {pct(h, BODY[1])};
  border-radius: {pct(LABEL_RADIUS, w)} / {pct(LABEL_RADIUS, h)}; box-shadow: 0 {px(0.15)} {px(0.5)} rgba(0, 0, 0, 0.35); }}
figcaption {{ margin-top: 4px; overflow-wrap: anywhere; }}
.doubt {{ display: block; color: #b4400a; }}
</style></head><body>
<h1>DMG labels</h1>
<p>{len(cards)} releases: {counts["gray"]} on gray shells, {counts["black"]} on black (black: Game Boy Color enhanced in gb-game-list, but for {len(EXCEPTIONS)} exceptions). {doubts} whose photo looks the other color are marked.</p>
<main>
{chr(10).join(cards)}
</main>
</body></html>
"""
    os.makedirs(here, exist_ok=True)
    open(OUT, "w").write(page)
    print(f"{len(cards)} labels ({counts['gray']} gray, {counts['black']} black; {doubts} whose photo looks the other color) into {OUT}")


if __name__ == "__main__":
    main()
