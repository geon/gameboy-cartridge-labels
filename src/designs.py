import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, serials

# designs.json: which photos are of one label design (one art), where that isn't what gb-game-list's releases (one per
# ROM) say. Every photo is of one design: by default its release's (serials.release_key: DMG-AG, DMG-ATAJ[PINK] for a
# photo with a note, DIS-CGB-AZ7E for a prefixed serial); a design listed here is made of parts, each either
#   - a release's default design (DMG-AG): its photos, but those of a serial listed in another design; or
#   - a serial, with its note if it has one (DMG-AG-FAH, DMG-ATAJ-JPN[PINK]): its photos, those of its revisions too
#     (DMG-AG-NOE covers DMG-AG-NOE-1).
# So a release is split by putting some of its serials in designs of their own (Pang: DMG-AG-FAH alone, the other
# regions in DMG-AG), and releases or serials whose labels are alike are linked by putting them in one design. Photos of
# one serial with different art are told apart by a note in their names (DMG-MQ-UKV[ALT].jpg: photos.py), which makes
# a design of its own. A design is named after its first part, releases before serials (DMG-AG-FAH; DMG-AG-NOE-1's
# part DMG-AG-NOE); one not listed, after its release key.
# Only decisions are kept: how alike labels are is measured afresh (src/compare_labels.py, make review-designs), so a
# similarity found is never rejected, and labels alike but not linked (variants of a game: Pokémon Gold and Silver)
# simply stay in designs of their own.
FILE = "designs.json"
SERIAL_PART = re.compile(r".*-[A-Z]{3}(-[0-9])?(\[[^]]*\])?$")


def load():
    found = json.load(open(FILE)) if os.path.exists(FILE) else {}
    return {"designs": found.get("designs", [])}


def save(data):
    """One design per line, so that the file's history reads as decisions made."""
    groups = [sorted(set(g), key=part_order) for g in data["designs"]]
    groups = sorted((g for g in groups if len(g) > 1 or g and is_serial(g[0])), key=lambda g: part_order(g[0]))
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


class Designs:
    """The designs as listed now: design_of(name) for each photo."""

    def __init__(self, data=None, release_of=None):
        self.data = data or load()
        self.release_of = release_of or serials.releases_by_serial()
        self.group_of = {p: i for i, g in enumerate(self.data["designs"]) for p in g}
        self.names = [name_of(g) for g in self.data["designs"]]

    def part_of(self, name):
        """The part of a listed design a photo falls under (its serial, else its release's), or None."""
        key = serials.release_key(name, self.release_of)[0]
        note = f"[{photos.note_of(name)}]" if photos.note_of(name) is not None else ""
        return next((p for p in (photos.serial_of(name) + note, serial_part(name), key) if p in self.group_of), None)

    def design_of(self, name):
        """A photo's design (by its name): (the design's name, its parts, the photo's release in gb-game-list or None)."""
        key, release = serials.release_key(name, self.release_of)
        part = self.part_of(name)
        if part is not None:
            i = self.group_of[part]
            return self.names[i], self.data["designs"][i], release
        return key, [key], release

    def key(self, name):
        return self.design_of(name)[0]


def release_of(design, release_of):
    """The release in gb-game-list a design's name is of (its note, prefix and region dropped), or None."""
    plain = photos.unprefixed(re.sub(r"\[[^]]*\]$", "", design))
    return serials.release_of_serial(plain, release_of)


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
    parts |= {n for n in names if n not in by_design.names}  # a design not listed: its release key is its part
    return dict(data, designs=groups + [sorted(parts, key=part_order)])


def split_off(data, parts):
    """data with the serial parts made a design of their own (taken out of the designs they're in)."""
    parts = set(parts)
    groups = [[p for p in g if p not in parts] for g in data["designs"]]
    return dict(data, designs=[g for g in groups if g] + [sorted(parts, key=part_order)])


def unlinked(data, parts):
    """data with the parts taken out of the designs they're in: back to their releases' designs."""
    parts = set(parts)
    return dict(data, designs=[[p for p in g if p not in parts] for g in data["designs"]])


def dissolved(data, name, by_design):
    """data without the design named: its parts back to their defaults."""
    return dict(data, designs=[g for i, g in enumerate(data["designs"]) if by_design.names[i] != name])
