# wanted: the prints that need photos, for people helping to find them (written by publish: wanted.html, wanted.json).
# Quality over quantity (the user, 2026-11-16): the prints closest to being restored, not every release without one.
#   A print without an image (restore's, or its frozen one) that is short of restore's MIN_PHOTOS label photos (poor
#   fits not counted), or of MIN_PRECISE that aren't approximate cuts, by at most MAX_NEEDED, is wanted.
#   Not wanted: a print of a game (system and title) that already has an image in the same region group; USA and Europe
#   are one group, their labels are often alike (REGION_GROUP; Japan is its own, and so is any other region).
#   Prints with no release (no title) aren't listed.
# Ranked by photos needed, then whether the label photos agree (all read the same serial, and no tile differs between
#   any two: prints.py's pair comparison), then the lowest resolution among them (photo px per mm at the label): the
#   more likely one more photo makes a good image, the higher.
# wanted.json per print: title, system, serials (its own as read; else the release's in its region group), the photos
# it has (their sources), the numbers ranked by, and search links (eBay by title, Google Images by serial).
# wanted.html: plain, for the people helping: a section per system (Game Boy, Color, Advance), linked from the top
# with its count, and the total, listed as on index.html (the user, 2026-11-17, 2026-11-18); in each, one row per game and region group (the user, 2026-11-17: a game's prints of
# one region group were rows that looked alike), at its best print's rank: title, serials, search links (games()).
import html, json, os, re, sys, unicodedata
import urllib.parse
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import solve, shapes, serials as serials_module
import ebay_photos

MIN_PHOTOS, MIN_PRECISE = 3, 2  # as restore's (not imported: restore loads much more)
MAX_NEEDED = 2
REGION_GROUP = {**ebay_photos.REGION_GROUP, **{r: "USA/EUR" for r, g in ebay_photos.REGION_GROUP.items() if g in ("USA", "EUR")},
                "SCN": "USA/EUR"}  # Scandinavia (the user, 2026-11-16)
SYSTEMS = {"dmg": "Game Boy", "cgb": "Game Boy Color", "agb": "Game Boy Advance"}


def px_per_mm(r):
    """A label photo's photo pixels per mm at the label (its solve record)."""
    lw, lh = shapes.LABEL_MM[r["shape"]]
    return float(solve.local_scale(np.array(r["cut_to_photo"]), [0, 0, lw, lh]))


def needed(keys, solved):
    """How many more label photos a print needs to be restored."""
    used = [k for k in keys if not solve.poor_fit(solved[k])]
    precise = [k for k in used if not solve.approximate_cut(solved[k])]
    return max(MIN_PHOTOS - len(used), MIN_PRECISE - len(precise), 0)


def region_group(serial, release):
    """A print's region group: its serial's region, else its release's (ebay_photos.region_of)."""
    region = serials_module.region_of(serial)
    if region:
        return REGION_GROUP.get(region, region)
    if release:
        s, g = ebay_photos.region_of(release)
        return REGION_GROUP.get(serials_module.region_of(s)) or {"USA": "USA/EUR", "EUR": "USA/EUR"}.get(g, g)
    return None


def game(release):
    return release["system"], re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", release["title"]).casefold())


def entries(prints, has_image, solved, serials, releases, sources, pair_differences):
    """The wanted prints, best first. prints: prints.json's; has_image: print ids with an image; serials: read-serials'
    serials.json; releases: database id -> record; sources: SHA-1 -> {source, page_url, image_url};
    pair_differences: (key, key) -> differing tiles (either order)."""
    covered = set()
    for p in prints:
        r = releases.get(p["release"])
        if p["id"] in has_image and r:
            covered.add((game(r), region_group(p["serial"], r)))
    out = []
    for p in prints:
        r = releases.get(p["release"])
        if p["id"] in has_image or not r or not p["keys"]:
            continue
        group = region_group(p["serial"], r)
        n = needed(p["keys"], solved)
        if not 0 < n <= MAX_NEEDED or (game(r), group) in covered:
            continue
        reads = {(serials.get(k) or {}).get("serial") for k in p["keys"]}
        tiles = [pair_differences.get((a, b)) for i, a in enumerate(p["keys"]) for b in p["keys"][i + 1:]]
        agree = None if len(p["keys"]) < 2 else (len(reads) == 1 and None not in reads and all(t == 0 for t in tiles))
        if p["serial"]:
            serial_list = [p["serial"]]
        else:
            serial_list = [s for s in serials_module.cartridge_serials(r) if region_group(s, None) in (group, None)] or [r["id"]]
        out.append({"print": p["id"], "release": r["id"], "title": r["title"], "system": r["system"],
                    "region": group, "serials": serial_list, "needed": n, "photos": len(p["keys"]), "agree": agree,
                    "px_per_mm": round(min(px_per_mm(solved[k]) for k in p["keys"]), 1),
                    "sources": [sources.get(k.split("@")[0], {}) for k in p["keys"]],
                    "search": search_links(r, serial_list, group)})
    out.sort(key=lambda e: (e["needed"], e["agree"] is not True, -e["px_per_mm"], e["title"].casefold()))
    return out


def search_links(release, serial_list, group):
    query = " ".join(w for w in (ebay_photos.query_title(ebay_photos.search_title(release)), ebay_photos.SYSTEM[release["system"]],
                                 {"JPN": "Japan", "USA/EUR": ""}.get(group, ""), "cartridge") if w)
    links = [("eBay", "https://www.ebay.com/sch/i.html?" + urllib.parse.urlencode({"_nkw": query}))]
    links += [(f"Google Images: {s}", "https://www.google.com/search?" + urllib.parse.urlencode({"tbm": "isch", "q": f'"{s}"'}))
              for s in serial_list]
    return [{"label": l, "url": u} for l, u in links]


def games(wanted):
    """The wanted prints as rows, one per game and region group, at its best print's place: title (the best print's),
    system, region, serials (all its prints', best first), search links, prints."""
    rows = {}
    for e in wanted:
        row = rows.setdefault((e["system"], game({"system": e["system"], "title": e["title"]})[1], e["region"]),
                              {"title": e["title"], "system": e["system"], "region": e["region"], "serials": [],
                               "search": [], "prints": []})
        row["prints"].append(e)
        for s in e["serials"]:
            if s not in row["serials"]:
                row["serials"].append(s)
        for l in e["search"]:
            if l not in row["search"]:
                row["search"].append(l)
    return list(rows.values())


def page(out_dir, wanted):
    """wanted.html: the wanted prints, best first, kept plain for the people helping (the user, 2026-11-16: no talk of
    agreement or of the photos already there)."""
    toc, sections = [], []
    for system, name in SYSTEMS.items():
        rows = []
        for e in games(wanted):
            if e["system"] != system:
                continue
            links = " · ".join(f'<a href="{html.escape(l["url"])}">{html.escape(l["label"])}</a>' for l in e["search"])
            rows.append(f'<tr><td><b>{html.escape(e["title"])}</b></td>'
                        f'<td>{"<br>".join(html.escape(s) for s in e["serials"])}</td><td>{links}</td></tr>')
        if rows:
            toc.append((f'<li><a href="#{system}">{name}</a>: {len(rows)} cartridges</li>', len(rows)))
            sections.append(f'<h2 id="{system}">{name}</h2>\n<table><tr><th>Game</th><th>Serial</th><th>Search</th></tr>{"".join(rows)}</table>')
    with open(os.path.join(out_dir, "wanted.html"), "w") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Wanted photos</title>
<style>body{{font:14px system-ui;margin:16px;background:#333;color:#eee}} a{{color:#9cf}} .dim{{color:#bbb;font-size:12px}}
table{{border-collapse:collapse}} td,th{{padding:4px 8px;border-bottom:1px solid #555;text-align:left;vertical-align:top}}</style>
<p><a href="index.html">All labels</a></p>
<h1>Wanted photos</h1>
<p>Photos of these cartridges help the most, top of the list first. Sharp photos showing the whole label are best.</p>
<p>If you take or find some photos, please upload them here: <a href="https://www.dropbox.com/request/9pv35ozb0iieahq3z3uf">https://www.dropbox.com/request/9pv35ozb0iieahq3z3uf</a>
<ul>{"".join(t for t, _ in toc)}<li>Total: {sum(n for _, n in toc)} cartridges</li></ul>
{chr(10).join(sections)}""")
