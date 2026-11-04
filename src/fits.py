import contextlib, fcntl, json, os, sys, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos

# fits.json: every photo's fit, the steps' and the ones placed by hand, and what's known about them, by the photo's
# stem:
#   {"sha1": the photo's SHA-1,
#    "fit": {"plastic": part, "label": part}  (the current fit; either part may be missing),
#    "rejected": [{"plastic": part}, {"plastic": part, "label": part}...],
#    "start": {"mm_to_photo": homography}  (optional: a rough plastic placed by hand for fit-cartridge to fit from)}
# A part is {"mm_to_photo": homography, "source": "auto-generated" or "hand-placed", "accepted": true or "almost"}:
# the plastic's homography maps mm on the cartridge's front to the photo's pixels, the label's maps mm on the label's
# model (cartridge's shell.label) to them; "accepted" is missing until it's reviewed (a part placed by hand is
# accepted). The label is fitted on the plastic of the same fit, so it goes with it. In "rejected", the last part of an
# entry is the one found wrong: a plastic alone, or a label on that plastic. A fit equal to a rejected one isn't made
# current again, so no fit is reviewed twice. An entry whose SHA-1 isn't its photo's is of another photo once under the
# same name: it doesn't count, and is replaced. Entries follow their photos by SHA-1 (renamed by hand, say), and go with
# them when they're deleted. A start is no fit: fit-cartridge fits the photo from it alone, and its fit is reviewed as
# any other.
# Steps and tools change it through editing(), which holds a lock and reads it afresh, so they can run side by side.
FILE = "fits.json"
SOURCES = ("auto-generated", "hand-placed")


def load():
    return json.load(open(FILE)) if os.path.exists(FILE) else {}


def save(fits):
    """One line per photo, so that the file's history reads as fits changed; entries with nothing in them are left out."""
    lines = [f"{json.dumps(name)}: {json.dumps(entry, ensure_ascii=False)}" for name, entry in sorted(fits.items()) if entry["fit"] or entry["rejected"] or entry.get("start")]
    open(FILE + ".tmp", "w").write("{\n" + ",\n".join(lines) + "\n}\n" if lines else "{}\n")
    os.replace(FILE + ".tmp", FILE)


@contextlib.contextmanager
def editing():
    """fits.json, read afresh under a lock, and saved when the block ends without an error."""
    with open(FILE + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fits = reconcile(load())
        yield fits
        save(fits)


def reconcile(fits):
    """Each entry under the name of the photo with its SHA-1 (one renamed keeps its fits); those of photos no longer in
    photos/ dropped. A photo filed under two names (the same cartridge sold as two releases) has an entry under each."""
    sha1s = photos.sha1s()
    kept = {name: e for name, e in fits.items() if sha1s.get(name) == e["sha1"]}
    for name, e in sorted(fits.items()):
        if name not in kept:  # renamed: to a name with its SHA-1 that has no entry yet
            free = [n for n, sha1 in sorted(sha1s.items()) if sha1 == e["sha1"] and n not in kept]
            if free:
                kept[free[0]] = e
    return kept


def entry(fits, name, sha1):
    """The photo's entry, made anew if it's missing or of another photo once under that name."""
    if fits.get(name, {}).get("sha1") != sha1:
        fits[name] = {"sha1": sha1, "fit": {}, "rejected": []}
    return fits[name]


def of(fits, name, sha1):
    """The photo's entry if it's of this photo, else an empty one (not stored)."""
    found = fits.get(name)
    return found if found and found.get("sha1") == sha1 else {"sha1": sha1, "fit": {}, "rejected": []}


# Points spanning the cartridge's front (mm), where two poses are compared.
FRONT = np.array([[0, 0, 1], [57, 0, 1], [57, 65, 1], [0, 65, 1]], np.float64)


def same(a, b):
    """Whether two parts (or homographies) are the same pose: they put the corners of the cartridge's front within
    0.01 px of each other (poses passed through a page come back a little changed)."""
    a, b = (np.asarray(x["mm_to_photo"] if isinstance(x, dict) else x, np.float64) for x in (a, b))
    pa, pb = FRONT @ a.T, FRONT @ b.T
    return bool(np.abs(pa[:, :2] / pa[:, 2:] - pb[:, :2] / pb[:, 2:]).max() < 0.01)


def good(part):
    """Whether a part is known to be right: accepted, or placed by hand."""
    return part is not None and part.get("accepted") is True


def part(mm_to_photo, source="auto-generated", accepted=None):
    made = {"mm_to_photo": np.asarray(mm_to_photo, np.float64).tolist(), "source": source}
    if accepted is not None:
        made["accepted"] = accepted
    return made


def bare(part):
    """A part as kept in "rejected": its pose and source, without its review."""
    return {k: v for k, v in part.items() if k != "accepted"}


def was_rejected(e, plastic, label=None):
    """Whether this plastic (or this label on that plastic) is among the photo's rejected fits."""
    for r in e["rejected"]:
        if same(r["plastic"], plastic) and (label is None) == ("label" not in r) and (label is None or same(r["label"], label)):
            return True
    return False


def reject_plastic(e):
    """Moves the current plastic (its label goes with it) to the rejected fits."""
    if "plastic" in e["fit"]:
        if not was_rejected(e, e["fit"]["plastic"]):
            e["rejected"].append({"plastic": bare(e["fit"]["plastic"])})
        e["fit"] = {}


def reject_label(e):
    """Moves the current label, on its plastic, to the rejected fits."""
    if "label" in e["fit"]:
        if not was_rejected(e, e["fit"]["plastic"], e["fit"]["label"]):
            e["rejected"].append({"plastic": bare(e["fit"]["plastic"]), "label": bare(e["fit"]["label"])})
        del e["fit"]["label"]


def unreject(e, plastic, label=None):
    """Takes a fit back out of the rejected fits."""
    e["rejected"] = [r for r in e["rejected"] if not (same(r["plastic"], plastic) and (label is None) == ("label" not in r) and (label is None or same(r["label"], label)))]


def state(e, plastic, label=None):
    """What's known of a plastic fit (or of a label on it): "hand-placed", True (accepted), "almost", "rejected", or
    None (not reviewed, or not in the entry)."""
    current = e["fit"].get("plastic")
    if label is None:
        found = current if current is not None and same(current, plastic) else None
    else:
        found = e["fit"].get("label") if current is not None and same(current, plastic) and "label" in e["fit"] and same(e["fit"]["label"], label) else None
    if found is not None:
        return "hand-placed" if found["source"] == "hand-placed" else found.get("accepted")
    return "rejected" if was_rejected(e, plastic, label) else None


def judge_plastic(e, plastic, verdict):
    """Gives a plastic fit (a homography) a verdict: True (accepted), "almost", "rejected", or None (not reviewed). It
    becomes the current fit unless rejected; the fit it replaces goes to the rejected ones if it was almost. A plastic
    no longer good loses its label (fitted on it while it was)."""
    unreject(e, plastic)
    current = e["fit"].get("plastic")
    is_current = current is not None and same(current, plastic)
    if verdict == "rejected":
        if is_current:
            reject_plastic(e)
        else:
            e["rejected"].append({"plastic": part(plastic)})
        return
    if not is_current:
        if current is not None and current.get("accepted") == "almost":
            reject_plastic(e)
        e["fit"] = {"plastic": part(plastic)}
    if verdict is None:
        e["fit"]["plastic"].pop("accepted", None)
    else:
        e["fit"]["plastic"]["accepted"] = verdict
    if not good(e["fit"]["plastic"]):
        e["fit"].pop("label", None)


def judge_label(e, label, verdict):
    """Gives the current plastic's label (a homography) a verdict, as judge_plastic does the plastic's."""
    plastic = e["fit"]["plastic"]
    unreject(e, plastic, label)
    current = e["fit"].get("label")
    is_current = current is not None and same(current, label)
    if verdict == "rejected":
        if is_current:
            reject_label(e)
        else:
            e["rejected"].append({"plastic": bare(plastic), "label": part(label)})
        return
    if not is_current:
        if current is not None and current.get("accepted") == "almost":
            reject_label(e)
        e["fit"]["label"] = part(label)
    if verdict is None:
        e["fit"]["label"].pop("accepted", None)
    else:
        e["fit"]["label"]["accepted"] = verdict
