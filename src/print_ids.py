# Persistent print ids (persistent-prints.md, stage 1): a print's id is the serial printed on its label, a hyphen and a
# short English first name (DMG-APSJ-JPN-lisa; the user, 2026-11-13: names imply no order or hierarchy and are easy to
# remember), made once and kept between runs in IDS_FILE (the repo root, committed; written by the prints step only:
# {"prints": {id: {"keys", "created", "split_from"?, "renamed_from"?}}, "gone": {id: {"why", "into"?, "datetime"}}}).
# Each run, the prints step's prints are matched to the last run's by the label photos they share: a label photo is the
# same between runs when its key is, or when it's in the same photo and the old key's centre lies in its outline (as
# keys work in find). Then:
#   - pairs (old print, new print) taken by the most label photos shared first, each old id and each new print once:
#     the new print keeps the old id;
#   - a new print sharing with no old one: a new id; sharing only with old ones taken by other new prints: a new id,
#     "split_from" the one it shares most with;
#   - an old id not taken: "gone", "merged" into the print holding most of its label photos, or "no label photo left";
#   - a kept id whose serial differs from the print's serial read now: renamed (the user: a wrong id is corrected), its
#     name kept if free with the new serial, the old id "gone" as "renamed" into the new one. A print with no serial read
#     takes its release (DMG-APSJ-jeff), else UNKNOWN (UNKNOWN-jeff); an id with a serial isn't renamed to a release or
#     UNKNOWN (that's less known, not a correction).
# A name is picked at random (seeded by the print's label photos, so a run is repeatable) among NAMES not yet used with
# that serial, gone ids included (never reused); a serial with every name used gets two (-lisa-bob), with every pair
# used three (-lisa-bob-tom).
import datetime, json, os, random, re

IDS_FILE = "print-ids.json"
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


def assign(prints, registry, key_map, when=None, forced=None):
    """Ids for this run's prints (list of {keys, serial, release}; "id" set on each) and the registry updated, from the
    last run's (registry) and key_map (old key -> new key or None); forced: {print index: id} (frozen prints: their id
    as it is, never renamed). Returns (registry, changes): changes lists {"kind": new|kept|split|merged|renamed|gone|
    frozen, ...} for the page."""
    when = when or now()
    forced = forced or {}
    old = registry.get("prints", {})
    gone = dict(registry.get("gone", {}))
    new_of_key = {k: i for i, p in enumerate(prints) for k in p["keys"]}
    shared = {}
    for pid, e in old.items():
        for k in e["keys"]:
            nk = key_map.get(k)
            if nk is not None and nk in new_of_key:
                pair = (pid, new_of_key[nk])
                shared[pair] = shared.get(pair, 0) + 1
    taken_old, taken_new, kept = set(forced.values()), set(forced), {}
    for (pid, i), n in sorted(shared.items(), key=lambda x: (-x[1], old[x[0][0]].get("created", ""), x[0][0])):
        if pid not in taken_old and i not in taken_new:
            taken_old.add(pid); taken_new.add(i); kept[i] = pid
    used = {}
    for pid in list(old) + list(gone):
        part, name = split_id(pid)
        used.setdefault(part, set()).add(name)
    def make(i, name=None):
        part = serial_part(prints[i])
        u = used.setdefault(part, set())
        name = name if name and name not in u else new_name(part, u, part + "|" + ",".join(sorted(prints[i]["keys"])))
        u.add(name)
        return f"{part}-{name}"
    out, changes = {}, []
    for i, p in enumerate(prints):
        if i in forced:
            pid = forced[i]
            entry = {k: v for k, v in old.get(pid, {"created": when}).items() if k != "keys"}
            gone.pop(pid, None)
            changes.append({"kind": "frozen", "id": pid})
        elif i in kept:
            pid = kept[i]
            entry = {k: v for k, v in old[pid].items() if k != "keys"}
            part, name = split_id(pid)
            want = serial_part(p)
            if want != part and not (is_serial(part) and not p.get("serial")):
                new = make(i, name)
                gone[pid] = {"why": "renamed", "into": new, "datetime": when}
                entry["renamed_from"] = pid
                changes.append({"kind": "renamed", "id": new, "from": pid})
                pid = new
            else:
                changes.append({"kind": "kept", "id": pid})
        else:
            pid = make(i)
            entry = {"created": when}
            olds = sorted(((n, o) for (o, j), n in shared.items() if j == i), reverse=True)
            if olds:
                entry["split_from"] = olds[0][1]
                changes.append({"kind": "split", "id": pid, "from": olds[0][1]})
            else:
                changes.append({"kind": "new", "id": pid})
        p["id"] = pid
        entry["keys"] = sorted(p["keys"])
        out[pid] = entry
    for pid in old:
        if pid in taken_old:
            continue
        holders = {}
        for k in old[pid]["keys"]:
            nk = key_map.get(k)
            if nk is not None and nk in new_of_key:
                into = prints[new_of_key[nk]]["id"]
                holders[into] = holders.get(into, 0) + 1
        if holders:
            into = max(holders, key=holders.get)
            gone[pid] = {"why": "merged", "into": into, "datetime": when}
            changes.append({"kind": "merged", "id": pid, "into": into})
        else:
            gone[pid] = {"why": "no label photo left", "datetime": when}
            changes.append({"kind": "gone", "id": pid})
    return {"prints": out, "gone": gone}, changes


def load(path=IDS_FILE):
    return json.load(open(path)) if os.path.exists(path) else {"prints": {}, "gone": {}}


def save(registry, path=IDS_FILE):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(registry, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
