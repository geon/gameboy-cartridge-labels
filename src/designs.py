import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, serials

# designs.json: which photos are of one label design (one art), where that isn't the default. Every photo is of one
# design: by default its game stem's in its market, Japan, the USA or the rest of the world (stem_of), named
# (default_key):
#   - the USA: the code with -USA (DMG-MC-USA, AGB-AXPE-USA, CGB-AW8A-USA);
#   - Japan: the code with -JPN (DMG-KYJ-JPN, DMG-PMA-JPN, AGB-AXPJ-JPN);
#   - the rest of the world: the stem, with + where the code's region letter was cut off (AGB-AXP+ for AGB-AXPP, -AXPD,
#     -AXPS; DMG-A2J+ for DMG-A2JP), the code itself for the old codes of two letters and codes of numbers (DMG-MC,
#     DMG-110);
#   where a stem has several codes in a market (DMG-E6-USA and DMG-E6E-USA), the shortest (then the first) names it;
#   with its prefix (DIS-CGB-AZ7E-USA) and note (DMG-ATAJ-JPN[PINK]). Rest-of-world names never end in a region, so
#   they can't clash with the others (DMG-A2J, Shounen Ashibe, is DMG-A2J-JPN; DMG-A2JP, Jurassic Park 2, DMG-A2J+);
#   + is never in a serial. That is implicit, never stored. (The USA is a market of its own as labels there and in Europe differ about as often as not: 2026-11-06,
# of 107 games with labels from both, 46 alike, 45 different, 16 unclear.) A design
# listed here is made of parts, each either
#   - a default design (DMG-AG): its photos, but those of a serial listed in another design; or
#   - a serial, with its note if it has one (DMG-AG-FAH, DMG-ATAJ-JPN[PINK]): its photos, those of its revisions too
#     (DMG-AG-NOE covers DMG-AG-NOE-1).
# So a release is split by putting some of its serials in designs of their own (Pang: DMG-AG-FAH alone, the other
# regions in DMG-AG), and releases or serials whose labels are alike are linked by putting them in one design. Photos of
# one serial with different art are told apart by a note in their names (DMG-MQ-UKV[ALT].jpg: photos.py), which makes
# a design of its own. A design is named after its first part, defaults before serials (DMG-AG-FAH; DMG-AG-NOE-1's
# part DMG-AG-NOE); one not listed is its default. Saving leaves out what's implicit: a design of one default part, a
# serial in the design of its own default; designs sharing a part are one.
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


def name_of(group):
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
    one stem and market are expected to look alike. The stem is the code without its region letter: AXP for AGB-AXPE,
    -AXPP and -AXPJ; KY for DMG-KY-USA, -KY-EUR and DMG-KYJ (the old Japanese and worldwide codes of three letters);
    with its system. The market: by the serial's region (JPN; USA or CAN), else by the code's region letter (J, E;
    in the old codes of three letters, A is Japanese too: DMG-PMA, DMG-B2A, all 249 photos of 2026-11-06 of releases
    gb-game-list lists with a JPN serial, their labels unlike the USA's and Europe's). None for a serial not of that
    form."""
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
