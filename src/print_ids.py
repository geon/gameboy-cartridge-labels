# Print ids (persistent-prints.md stage 1; since 2026-11-22 kept in the store, src/stored_prints.py): a print's id is
# the serial printed on its label, a hyphen and a short English first name (DMG-APSJ-JPN-lisa; the user, 2026-11-13:
# names imply no order or hierarchy and are easy to remember). A print with no serial takes its release (DMG-APSJ-jeff),
# else UNKNOWN (UNKNOWN-jeff). A name is picked at random (seeded by the print's label photos, so a run is repeatable)
# among NAMES not yet used with that serial, gone ids included (never reused); a serial with every name used gets two
# (-lisa-bob), with every pair used three (-lisa-bob-tom).
# same_label_photo: a stored label photo's key matched to this run's (as keys work in find).
import datetime, json, os, random, re

NAMES = ["alex", "amy", "ann", "beth", "bob", "carl", "dan", "dave", "dora", "ella", "emma", "eve", "frank", "fred",
         "gina", "greg", "hugo", "ivan", "jack", "jane", "jeff", "jill", "joe", "john", "karl", "kate", "kim", "lee",
         "lisa", "lucy", "luke", "mark", "mary", "max", "meg", "mike", "nick", "nora", "paul", "pete", "rick", "rose",
         "ruth", "sara", "ted", "tess", "tina", "tom", "vera", "zoe"]


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def serial_part(p):
    """What an id starts with for a print ({serial, release}): its serial, else its release, else UNKNOWN; characters
    other than letters, digits and "-" made "-"."""
    return re.sub(r"[^A-Za-z0-9-]", "-", p.get("serial") or p.get("release") or "UNKNOWN").upper()


def split_id(pid):
    """(serial part, name part): the name part is the trailing lowercase words."""
    m = re.match(r"^(.*?)((?:-[a-z]+)+)$", pid)
    return (m.group(1), m.group(2)[1:]) if m else (pid, "")


def is_serial(part):
    return part.count("-") >= 2  # DMG-APSJ-JPN; a release is DMG-APSJ


def new_name(part, used, seed):
    """A name not in used (names already taken with this serial part)."""
    rng = random.Random(seed)
    free = [n for n in NAMES if n not in used]
    if free:
        return rng.choice(free)
    pairs = [f"{a}-{b}" for a in NAMES for b in NAMES if a != b and f"{a}-{b}" not in used]
    if pairs:
        return rng.choice(pairs)
    for words in range(3, 10):  # every pair used too (UNKNOWN ran out, 2026-11-19): three names, then more
        for _ in range(1000):
            name = "-".join(rng.sample(NAMES, words))
            if name not in used:
                return name
    raise RuntimeError(f"no free name for {part}")


def same_label_photo(old_key, new_keys_of_photo, outlines, sizes):
    """The new key that is the old key's label photo, or None: the same key, else the one whose outline holds the old
    key's centre (its photo's size from sizes, sha1 -> [w, h]). None where several outlines hold it (an old label photo
    over two cartridges, which find now tells apart: either may be it). The first one holding it was taken until
    2026-11-22, in set order, so it differed from run to run: make prints and review-prints each grouped by another
    random pick (25 such label photos in the decisions)."""
    if old_key in new_keys_of_photo:
        return old_key
    import cv2, numpy as np
    sha1, pos = old_key.split("@")
    if sha1 not in sizes:
        return None
    x, y = (int(v) for v in pos.split(","))
    w, h = sizes[sha1]
    pt = ((x + 0.5) / 100 * w, (y + 0.5) / 100 * h)
    holding = [k for k in new_keys_of_photo if k in outlines and cv2.pointPolygonTest(np.float32(outlines[k]), pt, False) >= 0]
    return holding[0] if len(holding) == 1 else None
