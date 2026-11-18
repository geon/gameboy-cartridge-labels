# Serials: the serial-looking strings in a line of text (as OCR reads them: spaces, missing dashes, look-alike
# characters), and the database (gb-game-list's releases.json): which serials it knows, and their releases. Ported from
# main's src/serials.py.
import json, re, unicodedata

DATABASE = "../gb-game-list/database/releases.json"
PREFIXES = ("DIS",)  # DIS-CGB-AZ7E-USA
REGIONS = ("ASI", "AUS", "BRA", "CAN", "CHN", "DAN", "ESA", "ESP", "EUB", "EUR", "EUU", "FAH", "FRA", "FRG", "GPS", "HKG",
           "HOL", "ITA", "JPG", "JPN", "KOR", "MSA", "NOE", "SCN", "SPA", "UKV", "USA")
PREFIX = r"(?:(" + "|".join(PREFIXES) + r")-?)?"
SERIAL = re.compile(PREFIX + r"(DMG|CGB|AGB)-?([A-Z0-9]{1,5})(?:-([A-Z]{3}))?(?:-([0-9]))?")
NO_DASH = re.compile(PREFIX + r"(DMG|CGB|AGB)-?([A-Z0-9]{1,5})(" + "|".join(REGIONS) + r")(?:-([0-9]))?")


def reads(text):
    """The serial-looking strings in a line of text, upper case, dashed (a region read without its dash too); a serial
    with a region also without it."""
    t = unicodedata.normalize("NFKC", text).upper()
    t = re.sub(r"[ー―–—一:・.]", "-", t)
    t = re.sub(r"\bOMG(?=-)", "DMG", t)
    found = []
    for u in (t.replace(" ", ""), t):
        for m in [*SERIAL.finditer(u), *NO_DASH.finditer(u)]:
            found.append("-".join(p for p in m.groups() if p))
            if m.group(4):
                found.append("-".join(p for p in m.groups()[:3] if p))
    return list(dict.fromkeys(found))


def load_database(path=DATABASE):
    """Each serial the database knows (its cartridges' serials, its releases' ids and game ids) -> its release."""
    releases = json.load(open(path, encoding="utf-8"))
    release_of = {}
    for r in releases:
        for s in r["cartridgeSerials"]:
            release_of.setdefault(s, r)
    for key in ("id", "gameId"):  # a release's own id before another's game id
        for r in releases:
            release_of.setdefault(r[key], r)
    return release_of


def release(serial, release_of):
    """The database's release of a serial (its prefix dropped; its region dropped if the database lacks it), or None."""
    s = re.sub(r"^(" + "|".join(PREFIXES) + r")-", "", serial)
    for candidate in (s, re.sub(r"-[A-Z]{3}$", "", s)):
        if candidate in release_of:
            return release_of[candidate]
    return None


# Near serials: OCR garbles or cuts off serials (B-B96J-JPN, COB-B96J-JPN, GAB-896J-JPN for CGB-B96J-JPN). A code with a
# known region and up to 3 characters before it for the platform, compared with the database's serials of that region:
# the code by an edit distance where look-alikes cost half, plus half if the platform isn't read exactly (garbled, cut
# off or missing).
LOOK_ALIKE = [set("8B"), set("0OD"), set("1IL"), set("5S"), set("6G"), set("2Z"), set("UV")]
NEAR = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{0,3})-?([A-Z0-9]{2,5})-?(" + "|".join(REGIONS) + r")(?![A-Z])")
NEAR_MAX = 1.0     # the most a near serial may cost
NEAR_MARGIN = 1.0  # by how much the second best must cost more
PLATFORM_COST = 0.5


def _sub(a, b):
    return 0 if a == b else 0.5 if any(a in s and b in s for s in LOOK_ALIKE) else 1


def edit_cost(a, b):
    """Edit distance, look-alike substitutions costing half."""
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(b) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + _sub(a[i - 1], b[j - 1]))
    return d[-1]


def near_cost(platform, code, serial_platform, serial_code):
    return edit_cost(code, serial_code) + (0 if platform == serial_platform else PLATFORM_COST)


def by_region(release_of):
    """Region -> [(platform, code, the serial)] of the database's serials, for near serials."""
    out = {}
    for s in release_of:
        m = re.fullmatch(r"(DMG|CGB|AGB)-([A-Z0-9]{1,5})-([A-Z]{3})", s)
        if m:
            out.setdefault(m.group(3), []).append((m.group(1), m.group(2), s))
    return out


def near(text, regions):
    """The near serials in a line of text (regions: by_region()): [(the database serial, cost, what was read)], only
    where the best costs at most NEAR_MAX and clearly less than the second best; exact reads are left to reads()."""
    t = unicodedata.normalize("NFKC", text).upper()
    t = re.sub(r"[ー―–—一:・.]", "-", t)
    found = []
    for u in dict.fromkeys((t, t.replace(" ", ""))):
        for m in NEAR.finditer(u):
            costs = sorted((near_cost(m.group(1), m.group(2), p, c), s) for p, c, s in regions.get(m.group(3), []))
            if costs and 0 < costs[0][0] <= NEAR_MAX and (len(costs) == 1 or costs[1][0] >= costs[0][0] + NEAR_MARGIN):
                found.append((costs[0][1], costs[0][0], m.group(0)))
    return list(dict.fromkeys(found))


# Titles: the database's titles of a release (several, in Latin and Japanese) found in a label's text.
def plain(text):
    """Letters and digits only, upper case, full width folded (NFKC): Latin, kana, kanji."""
    return re.sub(r"[^0-9A-Z぀-ヿ一-鿿]", "", unicodedata.normalize("NFKC", text).upper())


# Words printed on every label of a platform (and in some titles: "Game Boy Color", "Jinsei Game Advance", "Ninja
# Boy"): left out of both a label's text and the titles before comparing.
TEMPLATE_WORDS = ["GAMEBOYCOLOR", "GAMEBOYADVANCE", "GAMEBOY", "COLOR", "ADVANCE", "NINTENDO", "ゲームボーイ", "カラー",
                  "アドバンス", "専用", "共通"]
MIN_TITLE = 5


def without_template(p):
    for w in TEMPLATE_WORDS:
        p = p.replace(w, "")
    return p


def title_score(release, text_plain, min_run=3):
    """The share of the release's best title's characters found in the text, in runs of min_run or more (0 to 1);
    template words left out of both, titles shorter than MIN_TITLE left then skipped."""
    from difflib import SequenceMatcher
    best = 0.0
    text_plain = without_template(text_plain)
    for t in release.get("titles", []) + [{"title": release.get("title", "")}]:
        title = without_template(plain(t["title"]))
        if len(title) < max(min_run, MIN_TITLE):
            continue
        blocks = SequenceMatcher(None, title, text_plain, autojunk=False).get_matching_blocks()
        best = max(best, sum(b.size for b in blocks if b.size >= min_run) / len(title))
    return best


class TitleIndex:
    """The database's releases by the character trigrams of their titles, for finding a release by its title."""

    def __init__(self, releases):
        self.releases = {r["id"]: r for r in releases}
        self.grams = {}
        self.count = {}
        for r in releases:
            g = set()
            for t in r.get("titles", []) + [{"title": r.get("title", "")}]:
                p = without_template(plain(t["title"]))
                if len(p) >= MIN_TITLE:
                    g |= {p[i:i + 3] for i in range(len(p) - 2)}
            self.count[r["id"]] = max(len(g), 1)
            for x in g:
                self.grams.setdefault(x, set()).add(r["id"])

    def search(self, text_plain, systems=None, top=8):
        """[(score, release)] of the releases whose titles best match the text (title_score), best first."""
        hits = {}
        text_plain = without_template(text_plain)
        for x in {text_plain[i:i + 3] for i in range(len(text_plain) - 2)}:
            for rid in self.grams.get(x, ()):
                hits[rid] = hits.get(rid, 0) + 1
        ranked = sorted(hits, key=lambda rid: -hits[rid] / self.count[rid])
        ranked = [rid for rid in ranked if systems is None or self.releases[rid].get("system") in systems][:top * 3]
        scored = sorted(((title_score(self.releases[rid], text_plain), self.releases[rid]) for rid in ranked), key=lambda x: -x[0])
        return scored[:top]


def region_of(serial):
    """A serial's region: its last part, if it has three (DMG-ASWP-EUR, not the old code of DMG-UJA) and it's one."""
    parts = re.sub(r"^(" + "|".join(PREFIXES) + r")-", "", serial or "").split("-")
    return parts[2] if len(parts) >= 3 and parts[2] in REGIONS else None
