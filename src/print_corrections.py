# Print corrections (the user, 2026-11-14): the user's decisions on which label photos are one print, made in
# review-prints (src/review_prints.py) and kept in FILE (the repo root, committed; written by review-prints only):
#   {"decisions": [{"kind": "join", "prints": [[key...], ...]}
#                  | {"kind": "split", "keys": [key...], "rest": [key...]}
#                  | {"kind": "apart", "serial": s, "prints": [[key...], ...]}, each with "datetime"]}
# Applied in order on the prints step's own grouping (its automatic prints, <generated>/prints/automatic.json), by the
# prints step and by review-prints (which shows what the next make prints gives):
#   - join: the prints holding any of its label photos become one, across families too;
#   - split: its label photos leave their prints and become one print of their own ("rest": the others of the print they
#     left, as it was then; only shown);
#   - apart: changes nothing: the prints of one serial were looked at and are different prints; review-prints' "same
#     serial" list leaves the serial out while its prints are those.
# A decision's keys are matched to the current label photos as print ids match them (print_ids.same_label_photo); keys
# no longer found are left out. A frozen print (src/frozen.py) is never split and two frozen prints are never joined:
# such a decision is skipped (review-prints doesn't make them).
import datetime, json, os
import print_ids

FILE = "print-corrections.json"


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load(path=FILE):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"decisions": []}


def save(data, path=FILE):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def key_mapper(current_keys, outlines, sizes):
    """old key -> the current key of that label photo, or None (print_ids.same_label_photo; outlines: find's, key ->
    outline; sizes: sha1 -> [w, h])."""
    of_photo, cache = {}, {}
    for k in current_keys:
        of_photo.setdefault(k.split("@")[0], []).append(k)

    def mapped(k):
        if k not in cache:
            cache[k] = print_ids.same_label_photo(k, of_photo.get(k.split("@")[0], []), outlines, sizes)
        return cache[k]
    return mapped


def apply(groups, decisions, mapped, frozen_of=None):
    """The prints after the decisions: (groups, [whether each decision changed or kept something]). groups: [[key...]],
    each print's label photos; mapped: key_mapper's; frozen_of: {key: frozen print id}."""
    frozen_of = frozen_of or {}
    groups = [list(g) for g in groups]
    where = {k: i for i, g in enumerate(groups) for k in g}
    applied = []
    for d in decisions:
        if d["kind"] == "join":
            keys = {mapped(k) for p in d["prints"] for k in p} - {None}
            gs = sorted({where[k] for k in keys if k in where})
            frozen = {frozen_of[k] for i in gs for k in groups[i] if k in frozen_of}
            if len(gs) < 2 or len(frozen) > 1:
                applied.append(len(gs) == 1)  # already one print: nothing to do
                continue
            into = gs[0]
            for i in gs[1:]:
                for k in groups[i]:
                    where[k] = into
                groups[into] += groups[i]
                groups[i] = []
            applied.append(True)
        elif d["kind"] == "split":
            keys = {mapped(k) for k in d["keys"]} - {None}
            keys = {k for k in keys if k in where}
            if not keys or any(k in frozen_of for k in keys):
                applied.append(False)
                continue
            for k in keys:
                groups[where[k]].remove(k)
            groups.append(sorted(keys))
            for k in keys:
                where[k] = len(groups) - 1
            applied.append(True)
        else:  # apart
            applied.append(True)
    return [g for g in groups if g], applied
