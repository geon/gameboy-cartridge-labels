import html, json, os, pathlib, re, sys, unicodedata, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, render, serials

# search-photos: a local page of searches for photos of the Game Boy, Game Boy Color and Game Boy Advance releases still
# without one (gb-game-list lists about half the Game Boy Advance ones): no
# cartridge photo in gb-game-list, and no photo in photos/ (a photo's release from its name, or from its name without
# its region, if gb-game-list lacks that), whether or not its fit works. Releases with photos from otakaraou alone are
# listed apart: they are worth replacing. The emumovies and launchbox-abeezy1388 images aren't photos but fakes, labels
# made from box art on a rendered cartridge: they don't count, so releases with only those are listed as without a
# photo (marked "fake only"). Releases sold through Nintendo Power, written to its flash cartridge at a kiosk, are
# listed apart too: No-Intro tags their ROMs (NP), and these are the releases whose every No-Intro ROM has it. Some are
# games that also had an ordinary cartridge, listed as a release of their own; the Nintendo Power one's serial is from
# its ROM's header, printed on no label. Nintendo Power was Japanese, so they're searched as Japanese releases. Their cartridge's label is Nintendo Power's (DMG-MMSA-JPN), so they're listed whether or not gb-game-list
# has a serial for them; releases.json lists some twice, so they're listed once per title. The cartridge's own menu
# (GB-Memory Multi Menu) is no game, and left out. Their titles are kept whole: the Loppi Puzzle Magazine issues differ
# only in their subtitles.
# A table, one row per release, with a column per place to search:
# Google's image search; for Japanese releases, the stores of the eBay sellers elrocinante and Hit-Japan and Yahoo!
# Auctions through Jauce; for the others, the stores of the eBay sellers ASANOSHOP and KONSOLENKOST (each sells the one kind
# alone, nearly). Japanese releases are searched by their Japanese title, with ゲームボーイ (ゲームボーイアドバンス) and カセット on
# the image search (listings there are titled in Japanese, rarely with the serial), the others by their English title,
# with "game boy" ("game boy advance") and cartridge; the eBay sellers title their listings in English, so they get the English title alone. Each serial links to Google's image search for it, quoted. Long titles are cut at their subtitle. Last, Google Lens
# searches by image: with the release's cartridge photo from game-boy-database.com, and with its otakaraou photo (by the
# URLs they're found at, so Lens can fetch them). gb-game-list has only the box photos from game-boy-database.com; the
# cartridge's is next to it, by the same number (vizu/3741.jpg, cartridges/3741.jpg), for most games.
# At the top, apart: the releases whose label is rendered (render-labels' photo) from a photo with fewer than LOW_RESOLUTION
# px per mm on the label (at its middle, render.label_px_per_mm): worth a sharper photo. By shell (Game Boy, Game Boy
# Color, Game Boy Advance), the lowest resolution first; a release gb-game-list doesn't list (a serial with a note, say)
# by its name in photos/, without searches.
# Usage: search_photos.py
RELEASES = serials.RELEASES
OUT = "generated/search-photos/index.html"
SYSTEMS = ("dmg", "cgb", "agb")
SYSTEM_NAMES = (("dmg", "Game Boy"), ("cgb", "Game Boy Color"), ("agb", "Game Boy Advance"))
LOW_RESOLUTION = 15  # px per mm
# The console's name in the searches, Japanese and English.
CONSOLE = {"dmg": ("ゲームボーイ", "game boy"), "cgb": ("ゲームボーイ", "game boy"), "agb": ("ゲームボーイアドバンス", "game boy advance")}
LENS = "https://lens.google.com/uploadbyurl?url="
# eBay's sellers, of Japanese releases and of the others: name shown, seller id, store name, eBay's site.
JAPANESE_EBAY_SELLERS = (("elrocinante", "elrocinante119", "elrocinantesecondhandshop", "www.ebay.com"),
                         ("Hit-Japan", "hit-japan", "hitjapanvideogamesandanime", "www.ebay.com"))
WESTERN_EBAY_SELLERS = (("ASANOSHOP", "thorgans1", "asanoshop", "www.ebay.fr"), ("KONSOLENKOST", "konsolenkost", "konsolenkost", "www.ebay.at"))


def short(title, release=None):
    """The title before its subtitle, if that leaves enough to search by (whole for a release sold on Nintendo Power)."""
    t = unicodedata.normalize("NFKC", title).strip()
    if release and release["id"] in nintendo_power:
        return t
    head = re.split(r"\s+-\s+|\s{2,}|[~～〜:：「『]|\s(?=[(（])", t)[0].strip()
    return head if len(head) >= 3 else t


def japanese(release):
    return any(s.endswith("-JPN") for s in release["cartridgeSerials"]) or release["id"].endswith("J") or release["id"] in nintendo_power


def no_intro_game(label):
    """No-Intro's name for the game, without the tags of its ROM: "Balloon Fight GB (Japan) (NP)" -> "Balloon Fight GB"."""
    return re.sub(r"\s*\(.*$", "", label)


def nintendo_power_only(all_releases):
    """The ids of the releases whose every No-Intro ROM is tagged (NP): the game may have had an ordinary cartridge too
    (Mr. Driller's CGB-BMDJ-JPN), but this release's serial is only in the ROM's header (CGB-BV3J-JPN), on no label."""
    no_intro = lambda r: [l["label"] for l in r.get("links", []) if l["source"] == "no-intro.org"]
    return {r["id"] for r in all_releases
            if r["system"] in SYSTEMS and no_intro(r) and all("(NP)" in l for l in no_intro(r))
            and r["title"] != "GB-Memory Multi Menu"}


def japanese_title(release):
    return short(next((t["title"] for t in release["titles"] if "ja" in t["languages"]), release["title"]), release)


def links(release):
    """(label, url) for each place to search for the release's photos, None where there's nothing to search with."""
    q = lambda s: urllib.parse.quote(s)
    if japanese(release):
        title = japanese_title(release)
        image_query = f'"{title}" {CONSOLE[release["system"]][0]} カセット'
    else:
        title = short(release["title"], release)
        image_query = f'"{title}" "{CONSOLE[release["system"]][1]}" cartridge'
    found = [("Google", "https://www.google.com/search?udm=2&q=" + q(image_query))]
    found += [(f"eBay {name}", f"https://{site}/sch/i.html?" + urllib.parse.urlencode({"_ssn": seller, "store_name": store, "_nkw": short(release["title"], release)}))
              if japanese(release) == of_japanese else None
              for sellers, of_japanese in ((JAPANESE_EBAY_SELLERS, True), (WESTERN_EBAY_SELLERS, False)) for name, seller, store, site in sellers]
    found.append(("Jauce", "https://www.jauce.com/search/" + urllib.parse.quote(f"{title} {CONSOLE[release['system']][0]}", safe="")) if japanese(release) else None)
    box = next((i["url"] for i in release["images"] if i["kind"] == "box"), None)
    found.append(("Lens game-boy-database", LENS + q(box.replace("/vizu/", "/cartridges/"))) if box else None)
    found.append(("Lens otakaraou", LENS + q(otakaraou[release["id"]])) if release["id"] in otakaraou else None)
    return found



def serial_links(release):
    """The release's serials, each linking to Google's image search for it."""
    return "<br>".join(f'<a href="https://www.google.com/search?udm=2&q={urllib.parse.quote(chr(34) + s + chr(34))}" target="_blank">{html.escape(s)}</a>'
                    for s in release["cartridgeSerials"])


def region_free(key):
    """A release key without its region if its release is split by region (CGB-AW8A for CGB-AW8A-JPN), else as it is."""
    plain = re.sub(r"-[A-Z]{3}$", "", key)
    return plain if plain in serials.SPLIT else key


all_releases = json.load(open(RELEASES))
nintendo_power = nintendo_power_only(all_releases)
releases = [r for r in all_releases if r["system"] in SYSTEMS and (r["cartridgeSerials"] or r["id"] in nintendo_power)]
release_of = serials.releases_by_serial()
covered, otakaraou, fake = set(), {}, set()  # otakaraou: release -> the URL of its otakaraou photo
for source, _, name, entry in photos.all_sources():
    key, found = serials.release_key(name, release_of)
    # A photo with a note is of another release; one of a release split by region (serials.SPLIT) covers it.
    release = found["id"] if found and region_free(key) == found["id"] else None
    if release:
        if source == "otakaraou":
            otakaraou.setdefault(release, entry["image_url"])
        elif source in photos.FAKES:
            fake.add(release)
        else:
            covered.add(release)
missing = [r for r in releases if r["id"] not in covered and not any(i["kind"] == "cartridgePhoto" for i in r["images"])]
replace = [r for r in missing if r["id"] in otakaraou]
missing = [r for r in missing if r["id"] not in otakaraou]
# One per title: a title with a photo for any of its releases is covered.
np_covered = {r["title"] for r in releases if r["id"] in nintendo_power and r not in missing}
np_missing = {}
for r in missing:
    if r["id"] in nintendo_power and r["title"] not in np_covered:
        merged = np_missing.setdefault(r["title"], dict(r, cartridgeSerials=[]))["cartridgeSerials"]
        merged += [s for s in r["cartridgeSerials"] if s not in merged]
np_missing = list(np_missing.values())
missing = [r for r in missing if r["id"] not in nintendo_power]
fake_only = sum(r["id"] in fake for r in missing)

groups = [(f"{system_name}: {label}", [r for r in missing if r["system"] == system and japanese(r) == ja])
          for system, system_name in SYSTEM_NAMES
          for ja, label in ((True, "Japanese releases"), (False, "Other releases"))]
groups.append(("On Nintendo Power", np_missing))
groups.append(("Only from otakaraou: worth replacing", replace))
by_id = {r["id"]: r for r in all_releases}
low = []  # (px per mm, release key, shell)
for key, (stem, path, sha1, shell, plastic_H, label_H, settings) in render.chosen("labels").items():
    resolution = render.label_px_per_mm(shell, label_H)
    if resolution < LOW_RESOLUTION:
        low.append((resolution, key, shell))
sections = [f"<h2>Labels under {LOW_RESOLUTION} px per mm ({len(low)})</h2>"]
for shell, system_name in SYSTEM_NAMES:
    rows = []
    for resolution, key, _ in sorted(l for l in low if l[2] == shell):
        r = by_id.get(region_free(key))
        title = (japanese_title(r) if japanese(r) else r["title"]) if r else ""
        serial = serial_links(r) if r and r["cartridgeSerials"] else html.escape(key)
        searches = "".join(f'<td><a href="{html.escape(link[1])}" target="_blank">{link[0]}</a></td>' if link else "<td></td>" for link in links(r)) if r else ""
        rows.append(f'<tr><td>{resolution:.1f}</td><td>{html.escape(title)}</td><td><small>{serial}</small></td><td></td>{searches}</tr>')
    sections.append(f"<h3>{system_name} ({len(rows)})</h3><table>{''.join(rows)}</table>")
for heading, group in groups:
    rows = []
    for r in sorted(group, key=lambda r: r["title"]):
        title = japanese_title(r) if japanese(r) else r["title"]
        searches = "".join(f'<td><a href="{html.escape(link[1])}" target="_blank">{link[0]}</a></td>' if link else "<td></td>" for link in links(r))
        marks = "fake only" if r["id"] in fake and r["id"] not in otakaraou else ""
        rows.append(f'<tr><td>{html.escape(title)}</td><td><small title="{html.escape(r["title"])}">{serial_links(r)}</small></td><td><small>{marks}</small></td>{searches}</tr>')
    sections.append(f"<h2>{heading} ({len(group)})</h2><table>{''.join(rows)}</table>")

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Photo searches</title>
<style>body{{font:14px system-ui;margin:16px;background:#f4f4f4;color:#222}}table{{border-collapse:collapse}}
td{{padding:3px 8px;white-space:nowrap}}tr:nth-child(odd){{background:#fff}}small{{color:#888}}</style></head><body>
<h1>Photo searches</h1>
<p>{len(missing)} Game Boy, Game Boy Color and Game Boy Advance releases without a cartridge photo in gb-game-list or in photos/ ({fake_only} of them
with only fakes made from box art, from emumovies or launchbox-abeezy1388),
{len(np_missing)} sold on Nintendo Power (their cartridge's label reads DMG-MMSA-JPN; the serials are from the ROMs' headers), and
{len(replace)} with photos from otakaraou alone; first, {len(low)} whose label is rendered from a photo with under {LOW_RESOLUTION} px per mm on it
(px per mm in the first column). Save the photos found in a subfolder of save-new-images-here/ named after where they came from, and file them with
make add-photos.</p>
{''.join(sections)}
</body></html>"""
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w").write(page)
print(f"{len(missing)} releases to search ({fake_only} with fakes alone), {len(np_missing)} on Nintendo Power, {len(replace)} from otakaraou alone -> {pathlib.Path(OUT).resolve().as_uri()}")
