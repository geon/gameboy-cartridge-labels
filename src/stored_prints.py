# The stored prints (stored-prints.md, the user 2026-11-22): every print, frozen or not, in FILE (the repo root,
# committed), the truth the pipeline works from. Every change goes through Store's methods (rule 10), each told whether
# it's manual (the user, in a tool) or automatic (a step):
#   - automatic: a change to a frozen print raises FrozenError before anything changes (the step is wrong);
#   - manual: a change to a frozen print unfreezes it (rule 8), without asking; setting the serial it already has
#     doesn't, nor do freezing and refreezing.
# FILE: {"prints": {id: {"created", "serial", "frozen": bool, "label_photos": {key: {"outline" (find's), "pose" (solve's
#                        record)}}, "shape"?, "image"? ({"sha1", "crop", "paper", "restored_from", "refrozen"?}: the
#                        frozen image's, frozen/<id>.avif), "photo_label_photos"? (match: src/frozen.py), "frozen_at"?,
#                        "split_from"?, "renamed_from"?}},
#        "gone": {id: {"why", "into"?, "datetime"}} (ids are never reused),
#        "looked_at": {"same_serial": {serial: [[id...]]}} (review-prints' "All different": the prints of a serial the user
#                     looked at and left apart; shown again once they differ;
#                     "optimized": {id: [key...]}: review-prints' Optimize accepted, hidden there while these are its
#                     label photos),
#        "log": [{"datetime", "kind", "manual", "before": {id: summary or null}, "after": {id: summary or null}}]}
#   a summary: {"serial", "frozen", "keys"}. Written one label photo, gone id and log entry per line, so a run's diff
#   shows what changed. The log is what Undo works from (the latest change only, while what it made is unchanged);
#   outlines and poses written back by a run aren't logged.
# A frozen print's image stays at frozen/<id>.avif when it's unfrozen (so Undo can refreeze it); freezing again
# overwrites it. frozen.STAMP is touched only when the frozen prints change, so the steps that read them (find, solve)
# aren't redone each time a run writes the open prints.
import datetime, hashlib, json, os
import print_ids

FILE = "prints.json"
STAMP = os.path.join("frozen", ".changed")


class FrozenError(Exception):
    pass


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def empty():
    return {"prints": {}, "gone": {}, "looked_at": {"same_serial": {}}, "log": []}


def load(path=None):
    path = path or FILE
    data = json.load(open(path)) if os.path.exists(path) else empty()
    for k, v in empty().items():
        data.setdefault(k, v)
    return data


def _dump(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def frozen_view_hash(data):
    return hashlib.sha1(_dump({pid: p for pid, p in data["prints"].items() if p.get("frozen")}).encode()).hexdigest()


def save(data, path=None, stamp=None):
    """Written one label photo, gone id, looked-at entry and log entry per line; the stamp touched if the frozen prints
    changed."""
    path, stamp = path or FILE, stamp or (STAMP if (path or FILE) == FILE else path + ".frozen-changed")
    out = ["{", ' "prints": {']
    ids = sorted(data["prints"])
    for n, pid in enumerate(ids):
        p = data["prints"][pid]
        head = {k: v for k, v in p.items() if k != "label_photos"}
        out.append(f"  {_dump(pid)}: {_dump(head)[:-1]}, \"label_photos\": {{")
        lps = sorted(p["label_photos"])
        out += [f"   {_dump(k)}: {_dump(p['label_photos'][k])}" + ("," if i < len(lps) - 1 else "") for i, k in enumerate(lps)]
        out.append("  }}" + ("," if n < len(ids) - 1 else ""))
    out.append(" },")
    for name in ("gone",):
        out.append(f' "{name}": {{')
        keys = sorted(data[name])
        out += [f"  {_dump(k)}: {_dump(data[name][k])}" + ("," if i < len(keys) - 1 else "") for i, k in enumerate(keys)]
        out.append(" },")
    out.append(' "looked_at": {')
    parts = sorted(data["looked_at"])
    for n, part in enumerate(parts):
        out.append(f"  {_dump(part)}: {{")
        keys = sorted(data["looked_at"][part])
        out += [f"   {_dump(k)}: {_dump(data['looked_at'][part][k])}" + ("," if i < len(keys) - 1 else "") for i, k in enumerate(keys)]
        out.append("  }" + ("," if n < len(parts) - 1 else ""))
    out.append(" },")
    out.append(' "log": [')
    out += ["  " + _dump(e) + ("," if i < len(data["log"]) - 1 else "") for i, e in enumerate(data["log"])]
    out += [" ]", "}"]
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, path)
    h = frozen_view_hash(data)
    old = open(stamp).read().strip() if os.path.exists(stamp) else None
    if h != old:
        os.makedirs(os.path.dirname(stamp) or ".", exist_ok=True)
        with open(stamp, "w") as f:
            f.write(h + "\n")


class Store:
    def __init__(self, path=None, folder=None):
        self.path = path
        self.folder = folder or "frozen"
        self.data = load(path)

    @property
    def prints(self):
        return self.data["prints"]

    def save(self):
        save(self.data, self.path)

    # --- reading
    def summary(self, pid):
        p = self.prints.get(pid)
        return None if p is None else {"serial": p.get("serial"), "frozen": bool(p.get("frozen")), "keys": sorted(p["label_photos"])}

    def print_of(self):
        """key -> id of every stored label photo."""
        return {k: pid for pid, p in self.prints.items() for k in p["label_photos"]}

    def used_names(self, part):
        return {print_ids.split_id(pid)[1] for pid in list(self.prints) + list(self.data["gone"]) if print_ids.split_id(pid)[0] == part}

    # --- the rules
    def _check(self, ids, manual):
        """Before a change: an automatic one to a frozen print raises (nothing changed yet)."""
        if not manual:
            for pid in ids:
                if self.prints.get(pid, {}).get("frozen"):
                    raise FrozenError(f"an automatic change to the frozen print {pid} (stored-prints.md, rule 7)")

    def _unfreeze(self, ids):
        """A manual change unfreezes (rule 8)."""
        for pid in ids:
            p = self.prints.get(pid)
            if p and p.get("frozen"):
                p["frozen"] = False
                p["unfrozen"] = now()

    def _logged(self, kind, manual, ids, change, unfreezes=True):
        """Checks, unfreezes (manual), runs change() (returning ids it made) and logs the before and after of all."""
        self._check(ids, manual)
        before = {pid: self.summary(pid) for pid in ids}
        heads = {pid: {k: v for k, v in self.prints[pid].items() if k != "label_photos"} for pid in ids if pid in self.prints}
        gone_before = set(self.data["gone"])
        records = {k: v for pid in ids if pid in self.prints for k, v in self.prints[pid]["label_photos"].items()}
        if unfreezes:
            self._unfreeze(ids)
        made = change() or []
        touched = list(dict.fromkeys(list(ids) + list(made)))
        for pid in touched:
            before.setdefault(pid, None)
        kept = {k for pid in touched if pid in self.prints for k in self.prints[pid]["label_photos"]}
        self.data["log"].append({"dropped": {k: v for k, v in records.items() if k not in kept},"datetime": now(), "kind": kind, "manual": manual, "before": before, "heads": heads,
                                 "after": {pid: self.summary(pid) for pid in touched},
                                 "gone_added": sorted(set(self.data["gone"]) - gone_before)})
        return made

    def _new_id(self, serial, release, keys):
        part = print_ids.serial_part({"serial": serial, "release": release})
        return f"{part}-{print_ids.new_name(part, self.used_names(part), part + '|' + ','.join(sorted(keys)))}"

    # --- changes
    def make(self, label_photos, serial, manual, release=None, split_from=None):
        """A new print of these label photos ({key: {"outline", "pose"}}): its id."""
        pid = self._new_id(serial, release, label_photos)

        def change():
            self.prints[pid] = {"created": now(), "serial": serial, "frozen": False, "label_photos": dict(label_photos)}
            if split_from:
                self.prints[pid]["split_from"] = split_from
            return [pid]
        self._logged("make", manual, [], change)
        return pid

    def add(self, pid, label_photos, manual):
        self._logged("add", manual, [pid], lambda: self.prints[pid]["label_photos"].update(label_photos))

    def remove(self, pid, keys, manual, why="no label photo left"):
        """Label photos out of a print; a print left with none is gone."""
        def change():
            for k in keys:
                self.prints[pid]["label_photos"].pop(k, None)
            if not self.prints[pid]["label_photos"]:
                self._gone(pid, why)
        self._logged("remove", manual, [pid], change)

    def join(self, pids, manual, into=None):
        """The prints joined into one (into, else the one with the most label photos): its id."""
        into = into or max(pids, key=lambda p: (len(self.prints[p]["label_photos"]), p))

        def change():
            for pid in pids:
                if pid != into:
                    self.prints[into]["label_photos"].update(self.prints[pid]["label_photos"])
                    self._gone(pid, "merged", into)
        self._logged("join", manual, list(pids), change)
        return into

    def split(self, pid, keys, manual, serial=None):
        """Some label photos of a print made a print of their own (serial: the print's if not given): its id."""
        keys = [k for k in keys if k in self.prints[pid]["label_photos"]]
        serial = serial or self.prints[pid].get("serial")
        new = self._new_id(serial, None, keys)

        def change():
            lps = {k: self.prints[pid]["label_photos"].pop(k) for k in keys}
            self.prints[new] = {"created": now(), "serial": serial, "frozen": False, "label_photos": lps, "split_from": pid}
            if not self.prints[pid]["label_photos"]:
                self._gone(pid, "no label photo left")
            return [new]
        self._logged("split", manual, [pid], change)
        return new

    def set_serial(self, pid, serial, manual):
        """The print's serial set (renamed: its name kept if free with the new serial): its id. The serial it already
        has changes nothing (a frozen print stays frozen)."""
        if self.prints[pid].get("serial") == serial:
            return pid
        part, name = print_ids.split_id(pid)
        want = print_ids.serial_part({"serial": serial})
        used = self.used_names(want)
        new = pid if want == part else f"{want}-{name if name not in used else print_ids.new_name(want, used, want + '|' + pid)}"

        def change():
            self.prints[pid]["serial"] = serial
            if new != pid:
                self.prints[new] = {**self.prints.pop(pid), "renamed_from": pid}
                self.data["gone"][pid] = {"why": "renamed", "into": new, "datetime": now()}
            return [new]
        self._logged("set serial", manual, [pid], change)
        return new

    def write_back(self, pid, label_photos, manual=False):
        """A run's outlines and poses for label photos already in the print (not logged)."""
        self._check([pid], manual)
        p = self.prints[pid]
        for k, v in label_photos.items():
            if k in p["label_photos"]:
                p["label_photos"][k] = v

    def freeze(self, pid, label_photos, shape, image, photo_label_photos):
        """Freezes a print (manual only): its label photos' outlines and poses as they are now, its image."""
        def change():
            p = self.prints[pid]
            p["label_photos"].update({k: v for k, v in label_photos.items() if k in p["label_photos"]})
            p.update(frozen=True, frozen_at=now(), shape=shape, image=image, photo_label_photos=photo_label_photos)
            p.pop("unfrozen", None)
        self._logged("freeze", True, [pid], change, unfreezes=False)

    def refreeze(self, pid, image):
        """A frozen print's image replaced (make refreeze, the user's say): nothing else changes."""
        self.prints[pid]["image"] = {**self.prints[pid].get("image", {}), **image, "refrozen": now()}

    def unfreeze(self, pid):
        self._logged("unfreeze", True, [pid], lambda: None)

    def mark_gone(self, pid, why, manual):
        self._logged("gone", manual, [pid], lambda: self._gone(pid, why))

    def _gone(self, pid, why, into=None):
        self.prints.pop(pid)
        self.data["gone"][pid] = {"why": why, "datetime": now(), **({"into": into} if into else {})}

    # --- undo
    def undo(self):
        """Undoes the latest manual change, if what it made is unchanged since: None, or why not."""
        log = self.data["log"]
        n = next((i for i in range(len(log) - 1, -1, -1) if log[i]["manual"]), None)
        if n is None:
            return "Nothing to undo."
        e = log[n]
        for pid, s in e["after"].items():
            if self.summary(pid) != s:
                return f"{pid} has changed since: undo it by hand."
        pool = dict(e.get("dropped", {}))
        for pid, s in e["after"].items():
            if s is not None:
                pool.update(self.prints.pop(pid)["label_photos"])
        for pid in e.get("gone_added", []):
            self.data["gone"].pop(pid, None)
        for pid, s in e["before"].items():
            if s is None:
                continue
            p = {**e.get("heads", {}).get(pid, {"created": now()}), "serial": s["serial"],
                 "label_photos": {k: pool[k] for k in s["keys"] if k in pool}}
            p["frozen"] = bool(s["frozen"] and os.path.exists(os.path.join(self.folder, pid + ".avif")))
            if p["frozen"]:
                p.pop("unfrozen", None)
            self.prints[pid] = p
        log.pop(n)
        return None
