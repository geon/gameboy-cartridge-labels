import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, serials

# designs.json: which photos are of one label design (one art), where that isn't the default.
#
# The default, implicit and never stored: one design per game stem and market (stem_of, default_key).
#   - The stem is the game's code without its region letter: Nintendo's four-letter codes share their first three
#     characters across a game's versions and end in a letter for the region or language (E the USA, J Japan, P Europe,
#     D Germany, F France, S Spain, I Italy...: in gb-game-list, 1163 E codes are printed -USA, 1145 J codes -JPN, 1082
#     P codes -EUR). gb-game-list has a release per ROM, so a game's language versions (AGB-AXPP, -AXPD, -AXPS, Pokémon
#     Ruby) are releases of their own; their labels are one design, and the stem is what ties them together. The old
#     codes of two letters (DMG-MC-USA, -EUR) are one code in every region anyway, and codes of numbers (DMG-110-CHN)
#     have no region letter: their stem is the code.
#   - The markets are Japan, the USA and the rest of the world: the USA's own, as labels there and in Europe differ
#     about as often as not (2026-11-06: of 107 games with labels from both, 46 alike, 45 different, 16 unclear; the
#     older DMG games mostly alike, the later DMG and AGB ones mostly not), and the rules are to be consistent.
#
# The default designs' names (default_key), self-contained and never clashing:
#   - the USA: the code with -USA (DMG-MC-USA, AGB-AXPE-USA, CGB-AW8A-USA), and Japan: the code with -JPN (DMG-KYJ-JPN,
#     DMG-PMA-JPN, AGB-AXPJ-JPN): a market there has one code per game, and that code with the region names it as on a
#     label (an old Japanese code mostly prints no region, but gb-game-list lists them with it too: DMG-PMA-JPN);
#   - the rest of the world: the stem, with + where the code's region letter was cut off (AGB-AXP+ for AGB-AXPP, -AXPD,
#     -AXPS); the code itself for the old codes of two letters and the codes of numbers (DMG-MC, DMG-110). The rest of
#     the world has many serials per game (DMG-MC-EUR, -NOE, -FAH, -UKV), so none of them names it.
#   - Why the -JPN and the +: the old codes of three letters and the four-letter codes share one namespace, so a
#     four-letter code without its region letter can be an old Japanese code: DMG-A2J is Shounen Ashibe (Japanese),
#     DMG-A2JE and DMG-A2JP Jurassic Park Part 2 (also DMG-AEA, -ALA, -AVA, -BRA). Named DMG-A2J-JPN and DMG-A2J+, they
#     can't clash: the USA's and Japan's names end in a region, the rest of the world's never do, and + is never in a
#     serial. (All 5849 names of gb-game-list's serials and the photos', 2026-11-06, are of one stem and market each.)
#   - Why +: the names are file names (render's images), URL paths and JSON keys, and appear next to serials; it should
#     need no encoding there. Serials and photo names already use A-Z, 0-9, -, [] (notes), () (on some labels) and _
#     (photo numbers); * and ? are shell wildcards, ? # % / : mean something in URLs; $ is a shell variable, an end of
#     line in regular expressions and special in make; . is the extension's separator. + is literal in paths, URL
#     fragments and file names (only form-encoded query strings read it as a space, which none of these tools rely on).
#   - Where a stem has several codes in a market (DMG-E6-USA and DMG-E6E-USA, DMG-WA-USA and DMG-WAE-USA), the shortest
#     (then the first) names it, from gb-game-list's serials and the photos' (codes), so a design isn't renamed by a
#     photo being added.
#   - A prefix (DIS-CGB-AZ7E-USA) and a note (DMG-ATAJ-JPN[PINK]) are kept: a release of its own (photos.py).
#
# A design listed in designs.json is made of parts, each either
#   - a default design (DMG-AG): its photos, but those of a serial listed in another design; or
#   - a serial, with its note if it has one (DMG-AG-FAH, DMG-ATAJ-JPN[PINK]): its photos, those of its revisions too
#     (DMG-AG-NOE covers DMG-AG-NOE-1).
# So a default design is split by putting some of its serials in designs of their own (DMG-ALNP-FRA apart from the
# rest of Europe), and designs whose labels are alike are linked by putting them in one design (DMG-KY with DMG-KY-USA).
# Photos of one serial with different art are told apart by a note in their names (DMG-MQ-UKV[ALT].jpg: photos.py),
# which makes a design of its own. A design joining whole markets of one stem (its parts all defaults, without a note
# or a prefix) is named after the stem, with + and the regions it adds to the rest of the world, alphabetically
# (agreed with the user 2026-11-07): AGB-A7K+USA (AGB-A7K+ and AGB-A7KE-USA), AGB-ATW+JPN, AGB-ATW+JPN+USA, DMG-AC+USA
# (DMG-AC and DMG-AC-USA), DMG-KY+JPN (DMG-KY and DMG-KYJ-JPN); without the rest of the world, the stem, - and the
# regions: AGB-A7K-JPN+USA. Such a name can't clash: + is never in a serial, and the defaults end in a region or a lone
# +. Any other design is named after its first part, defaults before serials (DMG-AG-FAH; DMG-AG-NOE-1's part
# DMG-AG-NOE); one not listed is its default. Saving leaves out what's implicit: a design of one
# default part, a serial in the design of its own default, a design of one serial of Japan or the USA; designs sharing
# a part are one.
# Only decisions are kept: how alike labels are is measured afresh (src/compare_labels.py, make review-designs), so a
# similarity found is never rejected, and labels alike but not linked (variants of a game: Pokémon Gold and Silver)
# simply stay in designs of their own.
FILE = "designs.json"
SERIAL_PART = re.compile(r"(.+-)?(DMG|CGB|AGB)-[A-Z0-9]+-[A-Z]{3}(-[0-9])?(\[[^]]*\])?$")


def load():
    found = json.load(open(FILE)) if os.path.exists(FILE) else {}
    return {"designs": found.get("designs", [])}


def save(data):
    """One design per line, so that the file's history reads as decisions made; what's implicit left out (see above)."""
    # Designs sharing a part made one.
    groups = []
    for g in data["designs"]:
        g = set(g)
        for other in [o for o in groups if o & g]:
            groups.remove(other)
            g |= other
        groups.append(g)
    # A serial in the design of its own default, a design of one default part, and one of one serial of Japan or the USA
    # (where a market's serials of a stem are all one), are implicit.
    groups = [{p for p in g if not (is_serial(p) and default_key(p) != p and default_key(p) in g)} for g in groups]
    alone = lambda p: is_serial(p) and (stem_of(p) or (None, ""))[1] in ("J", "E")
    groups = [sorted(g, key=part_order) for g in groups if len(g) > 1 or g and is_serial(next(iter(g))) and not alone(next(iter(g)))]
    groups.sort(key=lambda g: part_order(g[0]))
    text = '{\n"designs": [' + ("\n" + ",\n".join(json.dumps(g, ensure_ascii=False) for g in groups) + "\n" if groups else "") + "]\n}\n"
    open(FILE + ".tmp", "w").write(text)
    os.replace(FILE + ".tmp", FILE)


def is_serial(part):
    return bool(SERIAL_PART.match(part))


def part_order(part):
    return is_serial(part), part


def serial_part(name):
    """The serial part a photo's name falls under: its serial without a revision (DMG-AG-NOE for DMG-AG-NOE-1), with its
    note; a serial without a region as it is."""
    serial, note = photos.serial_of(name), photos.note_of(name)
    plain = re.sub(r"(-[A-Z]{3})-[0-9]$", r"\1", serial)
    return plain + (f"[{note}]" if note is not None else "")


def market_of(part):
    """A part's (stem, market) where it's a whole market's default design (AGB-A7K+, AGB-A7KE-USA, DMG-AC, DMG-KYJ-JPN),
    without a note or a prefix; else None."""
    if photos.note_of(part) is not None or photos.prefix_of(part):
        return None
    if part.endswith("+"):  # stem_of can't read these: AGB-A7K+ would be the old code AGB-A7K's stem AGB-A7
        return (part[:-1], "") if re.fullmatch(r"(DMG|CGB|AGB)-[A-Z0-9]+", part[:-1]) else None
    stem = stem_of(part)
    if stem is None or default_key(part) != part or (stem[1] == "" and is_serial(part)):
        return None
    return stem


REGIONS = {"J": "JPN", "E": "USA"}


def name_of(group):
    markets = [market_of(p) for p in group]
    if len(group) > 1 and all(markets) and len({s for s, _ in markets}) == 1 and len({m for _, m in markets}) == len(group):
        stem, found = markets[0][0], {m for _, m in markets}
        regions = "+".join(sorted(REGIONS[m] for m in found if m))
        return stem + ("+" if "" in found else "-") + regions
    first = sorted(group, key=part_order)[0]
    return re.sub(r"(-[A-Z]{3})-[0-9](?=$|\[)", r"\1", first)


CODES = None


def codes():
    """The codes of each stem and market, (stem, market) -> the shortest (then the first), from gb-game-list's serials
    and the photos' (read once)."""
    global CODES
    if CODES is None:
        found = {s for r in json.load(open(serials.RELEASES)) for s in r["cartridgeSerials"] + [r["id"]]}
        found |= {photos.serial_of(n) for _, _, n, _ in photos.all_sources()}
        CODES = {}
        for serial in found:
            stem, code = stem_of(serial), code_of(serial)
            if stem and (stem not in CODES or (len(code), code) < (len(CODES[stem]), CODES[stem])):
                CODES[stem] = code
    return CODES


def code_of(name):
    """A serial's code with its system (DMG-AXPE for AGB-AXPE-USA... DMG-MC for DMG-MC-USA), or None."""
    m = re.match(r"(DMG|CGB|AGB)-[A-Z0-9]+", photos.unprefixed(photos.serial_of(name)))
    return m.group(0) if m else None


def default_key(name):
    """A photo's default design (by its name, or a serial's), named as above; for a serial not of the usual form, the
    serial."""
    serial, note = photos.serial_of(name), photos.note_of(name)
    stem = stem_of(name)
    if stem is None:
        key = serial
    else:
        prefix = photos.prefix_of(serial)
        code = codes().get(stem, code_of(name))
        if stem[1] == "E":
            key = f"{code}-USA"
        elif stem[1] == "J":
            key = f"{code}-JPN"
        else:
            key = stem[0] + ("+" if stem[0] != code_of(name) else "")  # the region letter cut off
        key = (f"{prefix}-" if prefix else "") + key
    return key + (f"[{note}]" if note is not None else "")


class Designs:
    """The designs as listed now: design_of(name) for each photo."""

    def __init__(self, data=None, release_of=None):
        self.data = data or load()
        self.release_of = release_of or serials.releases_by_serial()
        self.group_of = {p: i for i, g in enumerate(self.data["designs"]) for p in g}
        self.names = [name_of(g) for g in self.data["designs"]]

    def part_of(self, name):
        """The part of a listed design a photo falls under (its serial, else its default), or None."""
        note = f"[{photos.note_of(name)}]" if photos.note_of(name) is not None else ""
        return next((p for p in (photos.serial_of(name) + note, serial_part(name), default_key(name)) if p in self.group_of), None)

    def design_of(self, name):
        """A photo's design (by its name): (the design's name, its parts, the photo's release in gb-game-list or None)."""
        key, release = default_key(name), serials.release_key(name, self.release_of)[1]
        part = self.part_of(name)
        if part is not None:
            i = self.group_of[part]
            return self.names[i], self.data["designs"][i], release
        return key, [key], release

    def key(self, name):
        return self.design_of(name)[0]


def stem_of(name):
    """A photo's game stem and market: (stem, "J" for Japan, "E" for the USA, "" for the rest of the world). Labels of
    one stem and market are expected to look alike (see above). The stem is the code without its region letter, with
    its system: AXP for AGB-AXPE, -AXPP and -AXPJ; KY for DMG-KY-USA, -KY-EUR and DMG-KYJ (the old Japanese codes of
    three letters); the whole code where it ends in a digit (DMG-110). The market: by the serial's region (JPN; USA,
    or CAN, sold alike), else by the code's region letter (J, E; in the old codes of three letters, A is Japanese
    too: DMG-PMA, DMG-B2A, all 249 photos of 2026-11-06 of releases gb-game-list lists with a JPN serial, their labels
    unlike the USA's and Europe's). None for a serial not of that form."""
    m = re.match(r"(DMG|CGB|AGB)-([A-Z0-9]+)(?:-([A-Z]{3}))?", photos.unprefixed(photos.serial_of(name)))
    if not m:
        return None
    system, code, region = m.groups()
    # A code of numbers (DMG-110-CHN) has no region letter: it's all stem.
    stem, letter = (code[:-1], code[-1]) if len(code) in (3, 4) and code[-1].isalpha() else (code, "")
    if region:
        market = "J" if region == "JPN" else "E" if region in ("USA", "CAN") else ""
    else:
        market = "J" if letter == "J" or letter == "A" and len(code) == 3 else "E" if letter == "E" else ""
    return f"{system}-{stem}", market


def preferred(key_of_sha1):
    """preferred.json by design: design -> the preferred photo's SHA-1, each entry under its photo's design as the photos
    are named and the designs listed now (key_of_sha1: sha1 -> design), so that splitting and joining designs keeps it;
    entries of photos gone dropped; where a design has several, the one stored under its own name."""
    stored = photos.load_preferred()
    found = {}
    for key, sha1 in sorted(stored.items(), key=lambda kv: kv[0] in (key_of_sha1.get(kv[1]),)):
        if sha1 in key_of_sha1:
            found[key_of_sha1[sha1]] = sha1
    return found


def merged(data, names, by_design):
    """data with the designs named made one (their parts together)."""
    parts, groups = set(), []
    for i, g in enumerate(data["designs"]):
        if by_design.names[i] in names:
            parts |= set(g)
        else:
            groups.append(g)
    parts |= {n for n in names if n not in by_design.names}  # a design not listed: its default is its part
    return dict(data, designs=groups + [sorted(parts, key=part_order)])


def split_off(data, parts):
    """data with the serial parts made a design of their own (taken out of the designs they're in)."""
    parts = set(parts)
    groups = [[p for p in g if p not in parts] for g in data["designs"]]
    return dict(data, designs=[g for g in groups if g] + [sorted(parts, key=part_order)])


def unlinked(data, parts):
    """data with the parts taken out of the designs they're in: back to their default designs."""
    parts = set(parts)
    return dict(data, designs=[[p for p in g if p not in parts] for g in data["designs"]])


def dissolved(data, name, by_design):
    """data without the design named: its parts back to their defaults."""
    return dict(data, designs=[g for i, g in enumerate(data["designs"]) if by_design.names[i] != name])
