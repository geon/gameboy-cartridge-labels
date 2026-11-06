import csv, html, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serials
from cartridge import AGB, BODY, SHELLS
import render

# label-page: a page of every DMG-shell release's label (make render-labels) laid on an empty cartridge of its shell's
# color, into generated/label-page/index.html (open it as a file). The empty cartridges are templates/dmg-gray.png and
# templates/dmg-black.png (from the collection-pipeline branch; 994 x 1132 px, framed on the 57 x 65 mm body), each a
# card's background image; the label is an element of its own on it, placed straight and centered in the recess, with
# rounded corners and a drop shadow, on its shell's label rectangle (cartridge.LABEL, CGB_LABEL). The CGB-shell releases (the clear Game Boy Color only cartridge) follow, on
# templates/cgb.png (framed the same way). Then the AGB-shell releases (Game Boy Advance), on templates/agb-gray.png
# (1190 x 688 px, about 20 px per mm; framed on its box with the shoulders, 60 x 34.5 mm).
# The cards are all one width, and the cartridges drawn at one scale: the widest (the AGB's 60 mm) fills its card, the
# DMG's and CGB's 57 mm bodies are centered in theirs.
# The shell's color: black for the releases gb-game-list marks gameBoyColorEnhanced, gray for the others, but for
# those in shell-colors.tsv. There are only gray and black templates: a light colored shell (white, pink...) is shown
# on the gray one, a dark one (dark blue, dark gray) on the black one, its color named under it. A few releases whose
# photo looked the other color (2026-11-04, the plastic's lightness in their cartridge images; the rest were wrong) are
# in shell-colors.tsv, to research.
# Usage: label_page.py
OUT = "generated/label-page/index.html"
TEMPLATES = {"gray": "templates/dmg-gray.png", "black": "templates/dmg-black.png", "cgb": "templates/cgb.png",
             "agb": "templates/agb-gray.png"}
# The width the cards are drawn for, mm: the widest cartridge's.
CARD_MM = max(max(s.box[2], BODY[0]) - min(s.box[0], 0) for s in SHELLS.values())
COLORS = "shell-colors.tsv"
# The template each color is shown on.
TEMPLATE_OF = {"gray": "gray", "black": "black", "white": "gray", "pink": "gray", "yellow": "gray", "red": "gray",
               "bright-blue": "gray", "blue": "black", "dark-blue": "black", "dark-gray": "black",
               "gold": "gray", "silver": "gray"}
LABEL_RADIUS = 1.4  # mm, as review-labels draws it
# The cards' width on the page: the columns fill it, each at least CART_MIN px wide, so under 2 * CART_MIN + the gap
# (else one more column would fit).
CART_MIN = 160
# Releases shown twice as high, spanning two rows of the grid, the others flowing around them: for the special carts
# (none yet).
TALL = set()


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


def card(classes, release, title, note=""):
    """A release's figure on the page: its label on the empty cartridge, its id and title under it."""
    src = html.escape(os.path.relpath(os.path.join(render.OUT["labels"], render.file_of(release)), os.path.dirname(OUT)))
    return f"""    <figure class="{classes}">
      <div class="cart"><img src="{src}" loading="lazy" alt=""></div>
      <figcaption><b>{html.escape(release)}</b> {html.escape(title)}{note}</figcaption>
    </figure>"""


def main():
    made = json.load(open(os.path.join(render.OUT["labels"], "made.json")))
    release_of = serials.releases_by_serial()
    # A design's release (key, its gb-game-list entry): that of the photo its label was rendered from.
    release = {design: serials.release_key(m["photo"], release_of) for design, m in made.items()}
    info_of = lambda design: release[design][1] or {}
    here = os.path.dirname(OUT)
    rel = lambda p: os.path.relpath(p, here)
    listed = colors()
    cards, counts, cgb_cards = [], {}, []
    for design in sorted(r for r, m in made.items() if m["shell"] == "dmg"):
        release_key, info = release[design][0], info_of(design)
        color = color_of(release_key, listed) or ("black" if info.get("gameBoyColorEnhanced") else "gray")
        counts[color] = counts.get(color, 0) + 1
        template = TEMPLATE_OF[color]
        title = info.get("title", "")
        note = ""
        if color != template:
            note = f' <span class="color">{color.replace("-", " ")} shell</span>'
        cards.append(card(f'dmg {template}{" tall" if design in TALL else ""}', design, title, note))
    for design in sorted(r for r, m in made.items() if m["shell"] == "cgb"):
        cgb_cards.append(card("cgb", design, info_of(design).get("title", "")))
    agb_cards = []
    for design in sorted(r for r, m in made.items() if m["shell"] == "agb"):
        agb_cards.append(card("agb", design, info_of(design).get("title", "")))
    places = "".join(f"""
    .{name} .cart img {{
      left: calc({l - box[0]:g} * var(--mm));
      top: calc({t - box[1]:g} * var(--mm));
      width: calc({r - l:g} * var(--mm));
      height: calc({b - t:g} * var(--mm));
    }}""" for name, (l, t, r, b), box in ((n, s.label, s.box) for n, s in SHELLS.items()))
    summary = ", ".join(f"{n} {c.replace('-', ' ')}" for c, n in sorted(counts.items(), key=lambda x: -x[1]))
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Game Boy labels</title>
  <style>
    body {{
      margin: 0;
      padding: 16px;
      background: #e8e6e1;
      font: 13px/1.3 system-ui, sans-serif;
      color: #222;
    }}
    h1 {{
      font-size: 18px;
      font-weight: 600;
      margin: 0 0 4px;
    }}
    h1 + p + main + h1 {{
      margin-top: 32px;
    }}
    p {{
      margin: 0 0 16px;
      color: #555;
    }}
    main {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax({CART_MIN}px, 1fr));
      grid-auto-flow: dense;
      gap: 20px;
    }}
    figure {{
      margin: 0;
      container-type: inline-size;
      --mm: calc(100cqw / {CARD_MM:g});
    }}
    .cart {{
      position: relative;
      width: calc({BODY[0]:g} * var(--mm));
      margin: 0 auto;
      aspect-ratio: {BODY[0]:g} / {BODY[1]:g};
      background: center / 100% 100% no-repeat;
    }}
    .tall {{
      grid-row: span 2;
    }}
    .tall .cart {{
      aspect-ratio: {BODY[0]:g} / {2 * BODY[1]:g};
    }}
    .gray .cart {{
      background-image: url("{rel(TEMPLATES["gray"])}");
    }}
    .black .cart {{
      background-image: url("{rel(TEMPLATES["black"])}");
    }}
    .cgb .cart {{
      background-image: url("{rel(TEMPLATES["cgb"])}");
    }}
    .agb .cart {{
      width: calc({AGB.box[2] - AGB.box[0]:g} * var(--mm));
      aspect-ratio: {AGB.box[2] - AGB.box[0]:g} / {AGB.box[3] - AGB.box[1]:g};
      background-image: url("{rel(TEMPLATES["agb"])}");
    }}
    .cart img {{
      position: absolute;
      border-radius: calc({LABEL_RADIUS:g} * var(--mm));
      box-shadow: 0 calc(0.2 * var(--mm)) calc(0.1 * var(--mm)) rgba(0, 0, 0, 0.4);
    }}
    {places}
    figcaption {{
      margin-top: 4px;
      overflow-wrap: anywhere;
    }}
    .color {{
      display: block;
      color: #555;
      font-style: italic;
    }}
  </style>
</head>
<body>
  <h1>DMG labels</h1>
  <p>{len(cards)} releases: {summary} (black: Game Boy Color enhanced in gb-game-list; other colors from {COLORS}, shown on the gray or black shell).</p>
  <main>
{chr(10).join(cards)}
  </main>
  <h1>CGB labels</h1>
  <p>{len(cgb_cards)} releases in the clear Game Boy Color only shell.</p>
  <main>
{chr(10).join(cgb_cards)}
  </main>
  <h1>AGB labels</h1>
  <p>{len(agb_cards)} releases in the Game Boy Advance shell.</p>
  <main>
{chr(10).join(agb_cards)}
  </main>
</body>
</html>
"""
    os.makedirs(here, exist_ok=True)
    open(OUT, "w").write(page)
    print(f"{len(cards)} DMG labels ({', '.join(f'{n} {c}' for c, n in sorted(counts.items(), key=lambda x: -x[1]))}), {len(cgb_cards)} CGB labels and {len(agb_cards)} AGB labels into {OUT}")


if __name__ == "__main__":
    main()
