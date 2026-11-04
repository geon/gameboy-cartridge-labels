import glob, hashlib, json, os, re, shutil, sys

# photos/: every photo of a cartridge, wherever it came from, in photos/<source>/<system>/<serial>[<note>][_<n>].<ext>,
# with one sources.json per folder (file name -> where it came from, and the file's "sha1").
# - source: where the photos came from (my-collection: my own; google: saved from Google image searches; the others
#   named after a site or seller), the subfolder of save-new-images-here/ they were dropped off in (src/add_photos.py).
# - system: dmg, cgb, agb, lrg (Limited Run Games' unlicensed releases, LRG-AP-USA), or unknown, from the serial.
# - serial: the serial printed on the label (DMG-ADQJ-JPN), else the release id it's known by (DMG-ADQJ), or UNKNOWN;
#   parentheses only where the label prints them (AGB-U3IJ-JPN(A));
# - note: what sets the release apart but isn't printed on the label, in square brackets (DMG-ATAJ-JPN[PINK]: the pink
#   cartridge bundled with a pink Game Boy Pocket; DMG-TRA[MINUET]); a photo with a note is a release of its own
#   (serials.release_key);
# - a number only when several photos have the same serial and note: the first has none, the next ones _2, _3...
# - ext: the format the photo came in (jpg, png, webp, avif, heic), never re-encoded.
# The file names are the truth: to identify a photo, or correct one, rename it (e.g. UNKNOWN_5.jpg -> DMG-A8-JPN.jpg),
# in whichever folder of its source; spaces become "-" (parentheses and square brackets are kept), and lower-case serials upper case. reconcile() (run by
# add-photos, or as photos.py reconcile) then finds its entry by its SHA-1, moves it to its system's folder, and numbers
# it if its name is taken.
# Usage: photos.py reconcile
ROOT = "photos"
SYSTEMS = ("dmg", "cgb", "agb", "lrg", "unknown")
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".heic", ".heif")
# The sources of fakes made from box art on a rendered cartridge: not photos.
FAKES = ("emumovies", "launchbox-abeezy1388")
# The sources, best first: Hit-Japan highest, otakaraou the lowest. A source not listed goes just above otakaraou.
SOURCES = ("ebay-hitjapan", "my-collection", "ebay-elrocinante", "yugiyahirano", "jnlgame", "jauce", "mercari", "rakuma",
           "retros-ae", "gbhwdb", "ebay", "tradera", "kleinanzeigen", "marktplaats", "gamestop", "google", "unrecorded",
           "otakaraou")
# Each release's preferred photo, chosen in find-doubles (src/find_doubles.py): release id -> the photo's SHA-1.
PREFERRED = "preferred.json"


def load_preferred():
    return json.load(open(PREFERRED)) if os.path.exists(PREFERRED) else {}


def save_preferred(preferred):
    """One line per release, so that the file's history reads as choices changed."""
    lines = [f"{json.dumps(k)}: {json.dumps(v)}" for k, v in sorted(preferred.items())]
    open(PREFERRED + ".tmp", "w").write("{\n" + ",\n".join(lines) + "\n}\n" if lines else "{}\n")
    os.replace(PREFERRED + ".tmp", PREFERRED)


def rank(source):
    """A source's place in SOURCES, lower is better."""
    return SOURCES.index(source) if source in SOURCES else SOURCES.index("otakaraou") - 0.5


def only(sources):
    """Of a release's photos' sources (fakes left out), the index of the photo that counts as its only one, or None: the
    one there is, or of exactly two, the one not from otakaraou when the other is (otakaraou is kept only for want of
    another). Such a release counts as having one photo, in every filter."""
    if len(sources) == 1:
        return 0
    if len(sources) == 2 and sources.count("otakaraou") == 1:
        return 1 - sources.index("otakaraou")
    return None


def system_of(serial):
    """The folder of a serial or release id: its system's prefix (DMG-, CGB-, AGB-, LRG-, or agb-1314 for releases
    without a serial), else unknown."""
    prefix = serial.split("-")[0].lower()
    return prefix if prefix in SYSTEMS[:-1] else "unknown"


def stem(name):
    return os.path.splitext(name)[0]


def tidy(name):
    """A photo's name without awkward characters, and serials as written: anything but letters, digits, "-", "_",
    parentheses (AGB-U3IJ-JPN(A): a label's serial may have them) and square brackets (a note) becomes "-", a lower-case serial (dmg-a8-ukv) upper case; release ids without a serial (agb-0014, digits after the system) stay as they are."""
    s, ext = os.path.splitext(name.strip())
    s = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9_()\[\]-]+", "-", s)).strip("-")
    s = re.sub(r"-_", "_", re.sub(r"-([(\[])", r"\1", s))  # AGB-U3IJ-JPN (A): no space before the parenthesis on a label
    head, sep, tail = s.rpartition("_") if re.search(r"_\d+$", s) else (s, "", "")
    if re.match(r"(dmg|cgb|agb|lrg)-(?!\d+$)[a-z0-9()\[\]-]+$", head, re.I):
        head = head.upper()
    return f"{head}{sep}{tail}{ext.lower()}"


def base_of(name):
    """A photo's name without the number and the extension: its serial and note (DMG-ATAJ-JPN[PINK])."""
    return re.sub(r"_\d+$", "", stem(name))


def serial_of(name):
    """The serial printed on a photo's label, as its name has it: without the note and the number."""
    return re.sub(r"\[[^]]*\]$", "", base_of(name))


def note_of(name):
    """The note in a photo's name (PINK for DMG-ATAJ-JPN[PINK]_2.jpg), else None."""
    found = re.search(r"\[([^]]*)\]$", base_of(name))
    return found.group(1) if found else None


def folder(source, system):
    path = os.path.join(ROOT, source, system)
    os.makedirs(path, exist_ok=True)
    return path


def sources(source, system):
    """A folder's sources.json: file name -> entry."""
    path = os.path.join(ROOT, source, system, "sources.json")
    return json.load(open(path)) if os.path.exists(path) else {}


def save_sources(source, system, entries):
    path = os.path.join(folder(source, system), "sources.json")
    json.dump(dict(sorted(entries.items())), open(path, "w"), ensure_ascii=False, indent=1)


def folders():
    """(source, system) of every folder in photos/."""
    return sorted((os.path.basename(os.path.dirname(d)), os.path.basename(d)) for d in glob.glob(os.path.join(ROOT, "*", "*")) if os.path.isdir(d))


def all_sources():
    """(source, system, file name, entry) for every photo in photos/."""
    for source, system in folders():
        for name, entry in sources(source, system).items():
            yield source, system, name, entry


def sha1s():
    """Each photo's SHA-1, by its stem: what the steps' data and the verdicts are tied to, as a name freed by a photo
    deleted or renamed may be given to another."""
    return {stem(n): e.get("sha1") for _, _, n, e in all_sources()}


def free_name(serial, ext, taken):
    """<serial><ext>, or the first <serial>_<n><ext> from 2 up, whose stem isn't in taken (lower case: macOS's file
    system ignores case)."""
    name, n = serial, 1
    while name.lower() in taken:
        n += 1
        name = f"{serial}_{n}"
    return name + ext


def taken_stems():
    return {stem(n).lower() for _, _, n, _ in all_sources()}


def add(serial, data, ext, entry, source):
    """Saves a photo (the file's bytes, unchanged) under its serial, numbered if taken, in its source's folder, with
    its entry; returns its name."""
    system = system_of(serial)
    name = free_name(serial, ext.lower().replace(".jpeg", ".jpg"), taken_stems())
    open(os.path.join(folder(source, system), name), "wb").write(data)
    entries = sources(source, system)
    entries[name] = dict(entry, sha1=hashlib.sha1(data).hexdigest())
    save_sources(source, system, entries)
    return name


def delete(path):
    """Deletes a photo from photos/: its file and its entry."""
    source, system, name = path.split(os.sep)[-3:]
    os.remove(path)
    entries = sources(source, system)
    entries.pop(name, None)
    save_sources(source, system, entries)


def rename(path, name):
    """Renames a photo in photos/ to name (a serial, without the extension), tidied and numbered if taken, in its
    system's folder within its source, with its entry; returns its new path."""
    source, system, old = path.split(os.sep)[-3:]
    ext = os.path.splitext(old)[1]
    base = base_of(tidy(name.replace(".", "-")))
    serial = serial_of(base)
    if not serial:
        raise ValueError(f"not a name: {name!r}")
    new = free_name(base, ext, taken_stems() - {stem(old).lower()})
    new_path = os.path.join(folder(source, system_of(serial)), new)
    shutil.move(path, new_path)
    entries = sources(source, system)
    entry = entries.pop(old)
    save_sources(source, system, entries)
    entries = sources(source, system_of(serial))
    entries[new] = entry
    save_sources(source, system_of(serial), entries)
    return new_path


def reconcile(verbose=True):
    """Brings sources.json in line with the files: a renamed or moved photo gets its entry back (found by SHA-1), and
    its system's folder within its source; a name taken by another photo gets the next
    number (photos keeping their names first); entries whose file is gone are dropped. Returns the number of changes."""
    entries = {f: sources(*f) for f in folders()}
    by_sha = {e["sha1"]: (f, n) for f in entries for n, e in entries[f].items() if e.get("sha1")}
    files = sorted((f, os.path.basename(p)) for f in entries for p in glob.glob(os.path.join(ROOT, *f, "*"))
                   if os.path.splitext(p)[1].lower() in EXTENSIONS)
    # Photos already known under their tidy names keep them; the renamed and new ones get what's free.
    files.sort(key=lambda fn: not (fn[1] in entries[fn[0]] and tidy(fn[1]) == fn[1]))
    claimed, taken, changes = set(), set(), 0
    for (source, system), name in files:
        path = os.path.join(ROOT, source, system, name)
        entry = entries[(source, system)].get(name)
        if entry is None or not entry.get("sha1"):
            sha = hashlib.sha1(open(path, "rb").read()).hexdigest()
            old = by_sha.get(sha)
            if entry is None and old and old != ((source, system), name):
                entry = entries[old[0]].pop(old[1])
                if verbose:
                    print(f"renamed {'/'.join(old[0])}/{old[1]} -> {source}/{system}/{name}")
            entry = dict(entry or {"note": "added by hand"}, sha1=sha)
            changes += 1
        new_name = tidy(name)
        if stem(new_name).lower() in taken:
            new_name = free_name(base_of(new_name), os.path.splitext(new_name)[1], taken)
        target = (source, system_of(serial_of(new_name)))
        taken.add(stem(new_name).lower())
        if target != (source, system) or new_name != name:
            shutil.move(path, os.path.join(folder(*target), new_name))
            if verbose:
                print(f"moved {source}/{system}/{name} -> {'/'.join(target)}/{new_name}")
            changes += 1
        entries[(source, system)].pop(name, None)
        entries.setdefault(target, {})[new_name] = entry
        claimed.add((target, new_name))
    for f in list(entries):
        for name in [n for n in entries[f] if (f, n) not in claimed]:
            del entries[f][name]
            if verbose:
                print(f"dropped {'/'.join(f)}/{name}: its file is gone")
            changes += 1
        if entries[f] != sources(*f):
            save_sources(*f, entries[f])
    return changes


if __name__ == "__main__" and sys.argv[1:] == ["reconcile"]:
    reconcile()
