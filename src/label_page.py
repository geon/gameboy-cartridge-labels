import csv, html, json, os, re, sys, cv2, numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serials
from cartridge import BODY, SHELLS
import render

# label-page: a page of every DMG-shell release's label (make render-labels) laid on an empty cartridge of its shell's
# color, into generated/label-page/index.html (open it as a file). The empty cartridges are templates/dmg-gray.png and
# templates/dmg-black.png (from the collection-pipeline branch; 994 x 1132 px, framed on the 57 x 65 mm body), each a
# card's background image; the label is an element of its own on it, placed straight and centered in the recess, with
# rounded corners and a drop shadow. The CGB-shell releases (the clear Game Boy Color only cartridge) follow, on
# templates/cgb.png (framed the same way), each label on the shell's label rectangle (cartridge.CGB_LABEL).
# The shell's color: black for the releases gb-game-list marks gameBoyColorEnhanced, gray for the others, but for
# those in shell-colors.tsv. There are only gray and black templates: a light colored shell (white, pink...) is shown
# on the gray one, a dark one (dark blue, dark gray) on the black one, its color named under it. As a check, the plastic's lightness in the release's cartridge image (make render-carts; the
# median at points beside and below the recess, PLASTIC) is measured: a release looking black (below BLACK_BELOW) but
# given gray, or the other way round, is marked on the page (not those in shell-colors.tsv). Measured on 1084 releases (2026-11-03, OpenCV's L, 0-255):
# gray shells 120 to 200, black ones mostly below 60, few between 73 and 85; 18 disagreed with gb-game-list.
# Usage: label_page.py
OUT = "generated/label-page/index.html"
TEMPLATES = {"gray": "templates/dmg-gray.png", "black": "templates/dmg-black.png", "cgb": "templates/cgb.png"}
PLASTIC = np.array([[x, y] for x in (2.5, 3.5, 4.5, 52.5, 53.5, 54.5) for y in np.linspace(22, 54, 9)]
                   + [[x, y] for x in np.linspace(12, 45, 12) for y in (59.0, 60.5)], np.float64)
BLACK_BELOW = 80
COLORS = "shell-colors.tsv"
# The template each color is shown on.
TEMPLATE_OF = {"gray": "gray", "black": "black", "white": "gray", "pink": "gray", "yellow": "gray", "red": "gray",
               "bright-blue": "gray", "blue": "black", "dark-blue": "black", "dark-gray": "black",
               "gold": "gray", "silver": "gray"}
LABEL_RADIUS = 1.4  # mm, as review-labels draws it
CART_WIDTH = 200  # px, on the page
# Releases shown twice as high, spanning two rows of the grid, the others flowing around them: for the special carts
# (none yet).
TALL = set()


def lightness(release):
    """The plastic's median lightness (0-255) in the release's cartridge image, None if it has none."""
    path = os.path.join(render.OUT["carts"], render.file_of(release))
    if not os.path.exists(path):
        return None
    image = np.array(Image.open(path).convert("RGB"))[..., ::-1]
    xy = ((PLASTIC + render.CART_MARGIN) * render.CART_PX_PER_MM).round().astype(int)
    return float(np.median(cv2.cvtColor(image[xy[:, 1], xy[:, 0]][None], cv2.COLOR_BGR2Lab)[0, :, 0]))


def colors():
    """shell-colors.tsv: [(release id or start of a serial, color)], longest first."""
    rows = csv.DictReader((l for l in open(COLORS) if not l.startswith("#")), delimiter="\t")
    found = [(r["release"], r["color"]) for r in rows]
    unknown = {c for _, c in found} - set(TEMPLATE_OF)
    if unknown:
        sys.exit(f"{COLORS}: unknown colors {sorted(unknown)}")
    return sorted(found, key=lambda r: -len(r[0]))


def color_of(release, listed):
    """The release's color in shell-colors.tsv (listed: colors()), or None: the longest row its id starts with, up to
    a "-", a note's "[" or its end; a row with a note matches only that note's release."""
    return next((c for code, c in listed if re.match(re.escape(code) + r"(-|\[|$)", release) and ("[" in code or "[" not in release)), None)


def main():
    made = json.load(open(os.path.join(render.OUT["labels"], "made.json")))
    releases = {r["id"]: r for r in json.load(open(serials.RELEASES))}
    here = os.path.dirname(OUT)
    rel = lambda p: os.path.relpath(p, here)
    w, h = render.LABEL_MM
    left, top = BODY[0] / 2 - w / 2, 37.5 - h / 2  # the recess's middle (cartridge.RECESS)
    pct = lambda part, whole: f"calc({part:g} / {whole:g} * 100%)"  # mm of the cartridge's width or height (the label's, for its corners)
    px = lambda mm: f"calc({mm:g} * {CART_WIDTH}px / {BODY[0]:g})"  # mm on the page
    listed = colors()
    cards, counts, doubts, cgb_cards = [], {}, 0, []
    for release in sorted(r for r, m in made.items() if m["shell"] == "dmg"):
        info = releases.get(re.sub(r"\[[^]]*\]$", "", release), {})  # a release with a note (DMG-ATAJ[PINK]): its title
        given = color_of(release, listed)
        color = given or ("black" if info.get("gameBoyColorEnhanced") else "gray")
        counts[color] = counts.get(color, 0) + 1
        template = TEMPLATE_OF[color]
        title = info.get("title", "")
        L = lightness(release)
        looks = None if L is None else "black" if L < BLACK_BELOW else "gray"
        doubt = looks is not None and looks != color and given is None
        doubts += doubt
        note = f' <span class="doubt">photo looks {looks} (L {L:.0f})</span>' if doubt else ""
        if color != template:
            note += f' <span class="color">{color.replace("-", " ")} shell</span>'
        cards.append(f'<figure class="{template}{" tall" if release in TALL else ""}"><div class="cart"><img src="{html.escape(rel(os.path.join(render.OUT["labels"], render.file_of(release))))}" '
                     f'loading="lazy" alt=""></div><figcaption><b>{html.escape(release)}</b> {html.escape(title)}{note}</figcaption></figure>')
    cl, ct, cr, cb = SHELLS["cgb"].label
    for release in sorted(r for r, m in made.items() if m["shell"] == "cgb"):
        title = releases.get(re.sub(r"\[[^]]*\]$", "", release), {}).get("title", "")
        cgb_cards.append(f'<figure class="cgb"><div class="cart"><img src="{html.escape(rel(os.path.join(render.OUT["labels"], render.file_of(release))))}" '
                         f'loading="lazy" alt=""></div><figcaption><b>{html.escape(release)}</b> {html.escape(title)}</figcaption></figure>')
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Game Boy labels</title>
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
.cgb .cart {{ background-image: url("{rel(TEMPLATES["cgb"])}"); }}
.cart img {{ position: absolute; left: {pct(left, BODY[0])}; top: {pct(top, BODY[1])}; width: {pct(w, BODY[0])}; height: {pct(h, BODY[1])};
  border-radius: {pct(LABEL_RADIUS, w)} / {pct(LABEL_RADIUS, h)}; box-shadow: 0 {px(0.15)} {px(0.5)} rgba(0, 0, 0, 0.35); }}
.cgb .cart img {{ left: {pct(cl, BODY[0])}; top: {pct(ct, BODY[1])}; width: {pct(cr - cl, BODY[0])}; height: {pct(cb - ct, BODY[1])};
  border-radius: {pct(LABEL_RADIUS, cr - cl)} / {pct(LABEL_RADIUS, cb - ct)}; }}
h1 + p + main + h1 {{ margin-top: 32px; }}
figcaption {{ margin-top: 4px; overflow-wrap: anywhere; }}
.doubt {{ display: block; color: #b4400a; }}
.color {{ display: block; color: #555; font-style: italic; }}
</style></head><body>
<h1>DMG labels</h1>
<p>{len(cards)} releases: {", ".join(f"{n} {c.replace('-', ' ')}" for c, n in sorted(counts.items(), key=lambda x: -x[1]))} (black: Game Boy Color enhanced in gb-game-list; other colors from {COLORS}, shown on the gray or black shell). {doubts} whose photo looks the other color are marked.</p>
<main>
{chr(10).join(cards)}
</main>
<h1>CGB labels</h1>
<p>{len(cgb_cards)} releases in the clear Game Boy Color only shell.</p>
<main>
{chr(10).join(cgb_cards)}
</main>
</body></html>
"""
    os.makedirs(here, exist_ok=True)
    open(OUT, "w").write(page)
    print(f"{len(cards)} DMG labels ({', '.join(f'{n} {c}' for c, n in sorted(counts.items(), key=lambda x: -x[1]))}; {doubts} whose photo looks the other color) and {len(cgb_cards)} CGB labels into {OUT}")


if __name__ == "__main__":
    main()
