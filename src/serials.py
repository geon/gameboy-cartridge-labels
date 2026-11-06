import glob, json, os, re, unicodedata
from difflib import SequenceMatcher

import photos

# The serial on each photo's label, for add-photos: the serial-like strings in its text (src/text.py)
# matched against gb-game-list's serials: "exact", "near" (one character off, e.g. DMG-UKJ for DMG-HKJ, with a single
# closest serial), or "unknown" (a serial-like read that matches nothing: a misread, or a serial missing from the list);
# "none" when nothing serial-like was read. O and 0, I and 1 are tried both ways. Early Japanese labels print the serial
# without its region (DMG-KGA), which gb-game-list may only list in full (DMG-KGA-JPN): a release's id and game id count
# as its serials too. A misread can be another release's serial (DMG-UKJ, Yu Yu Hakusho, for DMG-HKJ, Hokuto no Ken), so
# the matched release's titles are looked for in the photo's text: "title" when some run of 4 characters (3 for short
# titles; letters and kana alike) of one was read, and a "near" match only counts with its title read; without it, the
# read is "unknown". The text is normalized first: full-width characters, dashes read as ー, –, 一 or :, DMG read as
# OMG, and spaces dropped (vertical text on the strips is read with gaps, "DMG-Z G-NOE"), and also kept, for text after
# the serial ("DMG-PVJ MADE IN JAPAN"). A region code read without its dash (AGB・A20JJPN for AGB-A2OJ-JPN) is read too, for the known region
# codes, and every read with a region also without it, as gb-game-list lists some serials only so (AGB-A2OJ).
RELEASES = "../gb-game-list/database/releases.json"
SPLIT_BY_REGION = "split-by-region.tsv"
RANK = {"exact": 0, "near": 1, "unknown": 2}
REGIONS = ("ASI", "AUS", "BRA", "CAN", "CHN", "DAN", "ESA", "ESP", "EUB", "EUR", "EUU", "FAH", "FRA", "FRG", "GPS", "HKG",
           "HOL", "ITA", "JPG", "JPN", "KOR", "MSA", "NOE", "SCN", "SPA", "UKV", "USA")
PREFIX = r"(?:(" + "|".join(photos.SERIAL_PREFIXES) + r")-?)?"  # DIS-CGB-AZ7E-USA
SERIAL = re.compile(PREFIX + r"(DMG|CGB|AGB)-?([A-Z0-9]{1,5})(?:-([A-Z]{3}))?(?:-([0-9]))?")
NO_DASH = re.compile(PREFIX + r"(DMG|CGB|AGB)-?([A-Z0-9]{1,5})(" + "|".join(REGIONS) + r")(?:-([0-9]))?")


def releases_by_serial():
    """Each serial in gb-game-list, and each release's id and game id, -> its release."""
    releases = json.load(open(RELEASES))
    release_of = {}
    for r in releases:
        for s in r["cartridgeSerials"]:
            release_of.setdefault(s, r)
    for key in ("id", "gameId"):  # a release's own id before another's game id (DMG-AVBJ, not DMG-AVBE of game DMG-AVBJ)
        for r in releases:
            release_of.setdefault(r[key], r)
    return release_of


def split_by_region():
    """The release ids in SPLIT_BY_REGION."""
    rows = (line.split("\t")[0].strip() for line in open(SPLIT_BY_REGION) if not line.startswith("#"))
    return {r for r in rows if r}


SPLIT = split_by_region()


def save_split(release, title, split):
    """Adds the release to SPLIT_BY_REGION (with its title), or takes it out; SPLIT follows."""
    lines = open(SPLIT_BY_REGION).read().splitlines()
    head = [l for l in lines if l.startswith("#")]
    rows = {l.split("\t")[0]: l for l in lines if l.strip() and not l.startswith("#")}
    if split:
        rows.setdefault(release, f"{release}\t{title}")
    else:
        rows.pop(release, None)
    open(SPLIT_BY_REGION, "w").write("\n".join(head + [rows[r] for r in sorted(rows)]) + "\n")
    SPLIT.clear()
    SPLIT.update(rows)


def release_key(name, release_of):
    """A photo's release (release_of: releases_by_serial()), by its name: (the release's id, else its serial, with its
    note if it has one, as DMG-ATAJ[PINK]: a release of its own, and so with a prefix, as DIS-CGB-AZ7E; with its region
    if the release is split by region (SPLIT_BY_REGION), as CGB-AW8A-JPN; the release in gb-game-list, or None)."""
    serial, note = photos.serial_of(name), photos.note_of(name)
    release, prefix = release_of_serial(serial, release_of), photos.prefix_of(serial)
    key = release["id"] if release else photos.unprefixed(serial)
    if release and release["id"] in SPLIT and (region := re.search(r"-([A-Z]{3})(?:-[0-9])?$", photos.unprefixed(serial))):
        key += f"-{region.group(1)}"
    key = f"{prefix}-{key}" if prefix and release else key if release else serial
    return (f"{key}[{note}]" if note is not None else key), release


def plain_release(key):
    """A release key's release id in gb-game-list, without its note, prefix and region (CGB-AZ7E for
    DIS-CGB-AZ7E[NOTE], CGB-AW8A for CGB-AW8A-JPN, split by region)."""
    key = photos.unprefixed(re.sub(r"\[[^]]*\]$", "", key))
    plain = re.sub(r"-[A-Z]{3}$", "", key)
    return plain if plain in SPLIT else key


def release_of_serial(serial, release_of):
    """The release a photo's serial is filed under (release_of: releases_by_serial()), the region dropped if gb-game-list
    lacks it (DMG-A8-UKV), and its prefix (DIS-CGB-AZ7E-USA); None if it isn't listed."""
    serial = photos.unprefixed(serial)
    match = next((s for s in (serial, re.sub(r"-[A-Z]{3}$", "", serial)) if s in release_of), None)
    return release_of[match] if match else None


def reads(text):
    """The serial-like strings in a line of text."""
    t = unicodedata.normalize("NFKC", text).upper()
    t = re.sub(r"[ー―–—一:・.]", "-", t)
    t = re.sub(r"\bOMG(?=-)", "DMG", t)
    found = []
    for u in (t.replace(" ", ""), t):
        for m in [*SERIAL.finditer(u), *NO_DASH.finditer(u)]:
            found.append("-".join(p for p in m.groups() if p))
            if m.group(4):
                found.append("-".join(p for p in m.groups()[:3] if p))
    return found


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def match(found, release_of):
    """How a read serial matches gb-game-list's: (status, serial), its prefix (DIS-) kept."""
    prefix = photos.prefix_of(found)
    status, serial = match_unprefixed(photos.unprefixed(found), release_of)
    return status, (f"{prefix}-{serial}" if prefix else serial)


def match_unprefixed(found, release_of):
    prefix, rest = found[:4], found[4:]
    for variant in (rest, rest.replace("0", "O"), rest.replace("O", "0"), rest.replace("1", "I"), rest.replace("I", "1")):
        if prefix + variant in release_of:
            return "exact", prefix + variant
    near = [s for s in release_of if s[:3] == found[:3] and abs(len(s) - len(found)) <= 1 and distance(s, found) == 1]
    return ("near", near[0]) if len(near) == 1 else ("unknown", found)


def plain(text):
    return re.sub(r"[^0-9A-Z぀-ヿ一-鿿]", "", unicodedata.normalize("NFKC", text).upper())


def title_seen(release, text):
    """Whether some run of characters of one of the release's titles was read in text."""
    for t in release["titles"]:
        t = plain(t["title"])
        need = min(4, max(3, len(t) // 2))
        if len(t) >= need and SequenceMatcher(None, t, text, autojunk=False).find_longest_match(0, len(t), 0, len(text)).size >= need:
            return True
    return False


def serials(text_dir):
    """The serial on each photo's label, from its text in text_dir (src/text.py): rows of photo, status, serial, release
    id, title, whether the title was read too ("title"), and the serial-like strings found (space-separated)."""
    release_of = releases_by_serial()
    rows = []
    for path in sorted(glob.glob(os.path.join(text_dir, "*.json"))):
        name = os.path.basename(path)[:-5]
        lines = [l["text"] for l in json.load(open(path))]
        found = sorted({r for line in lines for r in reads(line)})
        if not found:
            rows.append((name, "none", "", "", "", "", ""))
            continue
        label = plain(" ".join(lines))
        matches = []
        for r in found:
            status, serial = match(r, release_of)
            seen = status != "unknown" and title_seen(release_of[photos.unprefixed(serial)], label)
            if status == "near" and not seen:
                status, serial = "unknown", r
            matches.append((status, not seen, serial))
        # Of the best-matching reads, those whose title was read (DMG-UQJ, Ultra Quiz, rather than a misread DMG-UOJ),
        # the longest (DMG-AJYJ-JPN rather than DMG-AJYJ).
        status, _, serial = min(matches, key=lambda m: (RANK[m[0]], m[1], -len(m[2])))
        r = release_of.get(photos.unprefixed(serial))
        seen = "title" if r and title_seen(r, label) else ""
        rows.append((name, status, serial, r["id"] if r else "", r["title"] if r else "", seen, " ".join(found)))
    return rows
