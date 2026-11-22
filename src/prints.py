# prints: the stored prints (stored-prints.md; src/stored_prints.py, prints.json in the repo root: the truth) kept up
# with this run's label photos, and written out for restore and publish, into <generated>/prints/:
#   prints.json: {"prints": [{"id", "keys", "release", "serial", "shape", "family", "families"?, "frozen"? (its id),
#                 "several_serials"? (its label photos' straightened serials where they're two or more: restore skips it;
#                 the user fixes it in review-prints)}],
#                 "tile_mm": TILE_MM, "differences": {}}
#   few-photos.json: [print ids] of open prints with fewer than FEW label photos
#   id-changes.json: this run's changes to the store ([{"kind": new, added, removed, gone, "id", "keys"?}]), on the page
# Each run, through the store's interface, automatic (stored-prints.md rules 3-7, 10):
#   1. Frozen prints are left as they are: never touched (the interface raises if anything tries).
#   2. An open print's label photos are matched to this run's (print_ids.same_label_photo: the same key, else the one
#      current outline holding the old centre; none where several do). Those not found leave the print; a print left
#      with none is gone. The found ones get this run's outline (find's) and pose (solve's) written back.
#   3. New label photos (this run's in no stored print, frozen or not), each by its straightened serial (read-serials'
#      straightened_serial; a label photo read-serials hasn't read stops the step: the steps ran in the wrong order):
#      - with one: into the open stored print of that serial it matches best by pixels (below), else left over; the
#        left-over ones of a serial and shape grouped by pixels among themselves (split_family), each group a new print;
#      - with none: into the open stored print holding label photos of its family (solve's) it matches best by pixels,
#        whatever its serial (assumed rightly grouped: restored with it); else a print of its own with no serial.
#   Matching a print: compared with each of its label photos of the same shape; it matches where most are "same"
#   (differing on fewer than MIN_DIFF_TILES tiles), best by the fewest differing tiles on average.
# Comparing, in each family's ink coordinates (straighten's images): the label, 1 mm in from its edges, in TILE_MM
# tiles (the outermost millimetre left out: the cut wanders about 1 mm). Two label photos differ at a tile where both
# are textured (gray spread over TEXTURE) and their lighting-evened gray (minus the local mean, over the local spread,
# 0.25 mm blur) doesn't correlate over CORRELATION. Only that counts as evidence of a print difference: a tile textured
# in one photo only is blur, glare or dirt as often as other text. Different prints: different on MIN_DIFF_TILES tiles
# or more. Which prints a new label photo may join is its serial's (above); the pixels choose among them. (Where another print's label
# photos may be used in a restored print is restore's own comparison, not this one.) Measured on the full set at 1 mm
# tiles (pairs within a family, by their serials read): 3 or more different tiles on 10 % of same-serial pairs (dirt,
# misfits: split, then pooled back), 86 % of one release's region variants (many of the rest misread serials of one
# print: IPN for JPN, a cut-off serial) and 95 % of different releases. At 2 mm tiles a region code hardly showed (one tile, often still correlating).
#   pairs.npz: the pair cache (below)
# Done again when prints.json is older than this file, solve.json, serials.json or the store.
# Usage: prints.py [--sample]
import argparse, html, itertools, json, os, re, sys
from collections import Counter
import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, steps, straighten, shapes, print_ids, stored_prints
import serials as serials_module

TILE_MM = 1
TEXTURE = 6.0
CORRELATION = 0.0
FEW = 3
MIN_DIFF_TILES = 3
NOT_LABELS = "not-labels.json"  # find's (find.NOT_LABELS)


def tile_views(image_path, shape):
    """A straightened label photo's tiles: (lighting-evened gray per tile, flattened; gray spread per tile)."""
    P, M = straighten.PX_PER_MM, straighten.MARGIN
    img = cv2.imread(image_path).astype(np.float32)
    lw, lh = shapes.LABEL_MM[shape]
    x0, y0, x1, y1 = int((M + 1) * P), int((M + 1) * P), int((M + lw - 1) * P), int((M + lh - 1) * P)
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (0, 0), 0.25 * P)
    mean = cv2.GaussianBlur(g, (0, 0), P)
    spread = np.sqrt(cv2.GaussianBlur((g - mean) ** 2, (0, 0), P)) + 2
    hp = ((g - mean) / spread)[y0:y1, x0:x1]
    g = g[y0:y1, x0:x1]
    t = TILE_MM * P
    h, w = hp.shape[0] // t, hp.shape[1] // t
    cut = lambda a: a[:h * t, :w * t]
    return (cut(hp).reshape(h, t, w, t).transpose(0, 2, 1, 3).reshape(h, w, -1),
            cut(g).reshape(h, t, w, t).std((1, 3)))


def tiles_textured_in_both_and_not_correlating(va, vb):
    """Per tile, whether two label photos (their tile_views) show different detail there: textured in both (gray
    spread over TEXTURE) and their lighting-evened gray not correlating over CORRELATION. The outermost ring of tiles
    left out: the cut wanders up to about 1 mm past them."""
    textured = (va[1] > TEXTURE) & (vb[1] > TEXTURE)
    za = va[0] - va[0].mean(2, keepdims=True)
    zb = vb[0] - vb[0].mean(2, keepdims=True)
    corr = (za * zb).sum(2) / np.sqrt((za ** 2).sum(2) * (zb ** 2).sum(2) + 1e-9)
    differing = textured & ~(corr > CORRELATION)
    differing[0, :] = differing[-1, :] = differing[:, 0] = differing[:, -1] = False
    return differing


# The pair cache (the user, 2026-11-13): a pair's differing tiles depend only on the two straightened images, the shape
# and the comparison (COMPARISON's functions and settings), so each pair's result is kept in <generated>/prints/pairs.npz,
# named by both keys and each image's fingerprint (straighten writes an image only when it's drawn again: its file's
# size and modification time), all of it dropped when the comparison's fingerprint changes. A run compares only the
# pairs it hasn't seen; pairs no longer in a family are dropped. Saved every SAVE_EVERY families that compared anything.
SAVE_EVERY = 200


def comparison_version():
    """A fingerprint of what a pair's result depends on but its images."""
    import hashlib, inspect
    h = hashlib.sha1(inspect.getsource(tile_views).encode() + inspect.getsource(tiles_textured_in_both_and_not_correlating).encode())
    h.update(repr((TILE_MM, TEXTURE, CORRELATION, straighten.PX_PER_MM, straighten.MARGIN, shapes.LABEL_MM)).encode())
    return h.hexdigest()[:16]


def image_fingerprint(path):
    st = os.stat(path)
    return f"{st.st_size}:{st.st_mtime_ns}"


def load_pairs(path, version):
    """name -> differing tiles (bool array), from the cache, if it's of this comparison."""
    if not os.path.exists(path):
        return {}
    z = np.load(path)
    if str(z["version"]) != version:
        return {}
    out = {}
    bits, starts = z["bits"], z["starts"]  # each z[...] reads the array from the file again
    for name, (h, w), a, b in zip(z["names"], z["grids"], starts[:-1], starts[1:]):
        out[str(name)] = np.unpackbits(bits[a:b])[:h * w].astype(bool).reshape(h, w)
    return out


def save_pairs(path, version, pairs):
    names = sorted(pairs)
    packed = [np.packbits(pairs[n].ravel()) for n in names]
    starts = np.concatenate([[0], np.cumsum([len(b) for b in packed])]).astype(np.int64)
    steps.write_npz(path, version=np.array(version), names=np.array(names, dtype="U200"),
                    grids=np.array([pairs[n].shape for n in names], np.int32).reshape(-1, 2),
                    starts=starts, bits=np.concatenate(packed) if packed else np.zeros(0, np.uint8))


def components(n, edges):
    parent = list(range(n))
    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in edges:
        parent[root(a)] = root(b)
    return [root(i) for i in range(n)]


def split_family(D):
    """New label photos of one serial and shape grouped into prints: [[member index...]], and the tiles that tell the
    prints apart. D: n x n x tiles booleans (tiles_textured_in_both_and_not_correlating). Two label photos are different
    prints where they differ on MIN_DIFF_TILES tiles or more (dirt or glare rarely does; other text does). Prints are
    merged, the pairs with the fewest differing tiles first, where most cross pairs aren't different."""
    n = D.shape[0]
    count = D.sum(2)
    same = count < MIN_DIFF_TILES
    prints = [[i] for i in range(n)]
    where = list(range(n))
    for a, b in sorted(itertools.combinations(range(n), 2), key=lambda p: count[p]):
        pa, pb = where[a], where[b]
        if pa == pb or not same[a, b]:
            continue
        if np.mean([same[x, y] for x in prints[pa] for y in prints[pb]]) > 0.5:
            prints[pa] += prints[pb]
            for i in prints[pb]:
                where[i] = pa
            prints[pb] = []
    prints = [p for p in prints if p]
    differs = np.zeros(D.shape[2], bool)   # tiles where most cross pairs of some two prints differ
    for p, q in itertools.combinations(prints, 2):
        differs |= np.mean([D[i, j] for i in p for j in q], 0) > 0.5
    return prints, differs


def photo_sizes(shas, gen):
    """sha1 -> [w, h] of the photos read-text has read."""
    sizes = {}
    for s in shas:
        f = os.path.join(gen, "read-text", s + ".json")
        if os.path.exists(f):
            sizes[s] = json.load(open(f))["size"]
    return sizes


def serial_code(serial):
    """A serial's (or release id's) code: AGB-AC6D-NOE: AC6D; DMG-133 CHN: 133."""
    return re.split(r"[- ]", re.sub(r"^(DIS-)?(DMG|CGB|AGB)-", "", (serial or "").upper()))[0]


def game_code(serial):
    """A serial's game: its code without the language letter (AGB-AC6D-NOE: AC6; a short old code as it is: DMG-NR)."""
    code = serial_code(serial)
    return code[:3] if len(code) == 4 else code


def same_game(a, b):
    """Whether two serials (or release ids) are of one game by their codes: equal but for a look-alike (A05J, AO5J),
    or an old code and the same with J (DMG-NR, DMG-NRJ)."""
    ga, gb = game_code(a), game_code(b)
    ca, cb = serial_code(a), serial_code(b)
    return bool(ga and gb) and (serials_module.edit_cost(ga, gb) <= 0.5 or ca + "J" == cb or cb + "J" == ca)


def print_release(chosen, reads):
    """A print's release: the most common among its label photos' (reads: read-serials' records) of its serial's game
    (chosen: same_game, by the release id or else the serial read); all of them if it has no serial. Not another
    game's: a print of a serial the database lacks (AGB-BSPE-USA) has no release, not the one a stray label photo's
    misread gave it (AGB-AW2E, 2026-11-21); one of another language or a misread of the game's keeps it
    (AGB-AC6D-NOE: AGB-AC6P; DMG-A05J-JPN: DMG-AO5J)."""
    def mine(r):
        return not chosen or same_game(chosen, r["release"]) or same_game(chosen, r.get("serial"))
    rel = Counter(r["release"] for r in reads if r.get("release") and mine(r))
    return rel.most_common(1)[0][0] if rel else None


class Comparer:
    """Pairs of label photos compared (tiles_textured_in_both_and_not_correlating), through the pair cache."""
    def __init__(self, gen, solved, cached):
        self.gen, self.solved, self.cached, self.views, self.compared = gen, solved, cached, {}, 0

    def path(self, k):
        return os.path.join(self.gen, "straighten", straighten.file_name(k))

    def view(self, k):
        if k not in self.views:
            self.views[k] = tile_views(self.path(k), self.solved[k]["shape"])
        return self.views[k]

    def tiles(self, a, b):
        """The differing tiles (bool array) between two label photos of one shape, or None (an image missing)."""
        a, b = sorted((a, b))
        if not (os.path.exists(self.path(a)) and os.path.exists(self.path(b))):
            return None
        name = f"{a}|{b}|{image_fingerprint(self.path(a))}|{image_fingerprint(self.path(b))}"
        if name not in self.cached:
            self.cached[name] = tiles_textured_in_both_and_not_correlating(self.view(a), self.view(b))
            self.compared += 1
        return self.cached[name]

    def differing(self, a, b):
        m = self.tiles(a, b)
        return None if m is None else int(m.sum())

    def best(self, k, candidates, members):
        """The candidate print k matches best (members: id -> its label photos), or None."""
        shape, best = self.solved[k]["shape"], None
        for pid in candidates:
            counts = [self.differing(k, m) for m in members[pid] if m in self.solved and self.solved[m]["shape"] == shape]
            counts = [c for c in counts if c is not None]
            if not counts or sum(c < MIN_DIFF_TILES for c in counts) * 2 <= len(counts):
                continue
            mean = sum(counts) / len(counts)
            if best is None or mean < best[0]:
                best = (mean, pid)
        return best and best[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()
    gen = photos.generated(args.sample)
    solve_file = os.path.join(gen, "solve", "solve.json")
    serials_file = os.path.join(gen, "read-serials", "serials.json")
    found_file = os.path.join(gen, "find", "label-photos.json")
    for p in (solve_file, serials_file, found_file):
        if not os.path.exists(p):
            sys.exit(f"{p} missing: run make find, solve, straighten and read-serials first")
    out_dir = os.path.join(gen, "prints")
    out = os.path.join(out_dir, "prints.json")
    os.makedirs(out_dir, exist_ok=True)
    store_file = stored_prints.FILE if not args.sample else os.path.join(out_dir, stored_prints.FILE)
    inputs = [solve_file, serials_file, __file__, stored_prints.__file__] + [f for f in (store_file, NOT_LABELS) if os.path.exists(f)]
    if not os.path.exists(out) or os.path.getmtime(out) < max(os.path.getmtime(p) for p in inputs):
        solved = json.load(open(solve_file))["label_photos"]
        # deleted since solve ran (review-prints' Delete label photo: marked not a label, or its photo deleted): left out
        not_labels = json.load(open(NOT_LABELS)) if os.path.exists(NOT_LABELS) else {}
        present = set(photos.chosen(args.sample))
        solved = {k: r for k, r in solved.items() if k not in not_labels and r["photo"] in present}
        serial = json.load(open(serials_file))
        unread = [k for k in solved if "straightened_serial" not in serial.get(k, {})]
        if unread:
            sys.exit(f"{len(unread)} label photos read-serials hasn't read (like {unread[0]}): the steps ran in the wrong "
                     "order; run make straighten and make read-serials first (stored-prints.md, rule 5)")
        outlines = {lp["key"]: lp["outline"] for lp in json.load(open(found_file))["label_photos"]}
        store = stored_prints.Store(store_file)
        record = lambda k: {"outline": outlines.get(k), "pose": solved[k]}
        log_start = len(store.data["log"])
        frozen_keys = {k for p in store.prints.values() if p.get("frozen") for k in p["label_photos"]}
        # 2. open prints: their label photos matched to this run's
        of_photo = {}
        for k in solved:
            of_photo.setdefault(k.split("@")[0], []).append(k)
        taken = set(frozen_keys)
        for pid in sorted(store.prints):
            if store.prints[pid].get("frozen"):
                continue
            old = sorted(store.prints[pid]["label_photos"])
            sizes = photo_sizes({k.split("@")[0] for k in old if k not in solved}, gen)
            now = {k: print_ids.same_label_photo(k, of_photo.get(k.split("@")[0], []), outlines, sizes) for k in old}
            lost = [k for k in old if now[k] is None or now[k] in taken]
            moved = {k: n for k, n in now.items() if n is not None and n != k and n not in taken}
            taken.update(n for k, n in now.items() if n is not None and k not in lost)
            if moved:
                store.add(pid, {n: record(n) for n in moved.values()}, manual=False)
            if lost or moved:
                store.remove(pid, lost + list(moved), manual=False)
            if pid in store.prints:
                store.write_back(pid, {k: record(k) for k in store.prints[pid]["label_photos"] if k in solved})
        # 3. new label photos
        stored = store.print_of()
        new = sorted(k for k in solved if k not in stored)
        pairs_file, version = os.path.join(out_dir, "pairs.npz"), comparison_version()
        comparer = Comparer(gen, solved, load_pairs(pairs_file, version))
        members = lambda: {pid: sorted(p["label_photos"]) for pid, p in store.prints.items() if not p.get("frozen")}
        by_serial, by_family = {}, {}
        for pid, p in store.prints.items():
            if not p.get("frozen"):
                if p.get("serial"):
                    by_serial.setdefault(p["serial"], []).append(pid)
                for k in p["label_photos"]:
                    if k in solved:
                        by_family.setdefault(solved[k]["family"], set()).add(pid)
        mem = members()
        print(f"{len(store.prints)} stored prints; {len(new)} new label photos", flush=True)
        left = {}
        for n, k in enumerate(new):
            if n % 200 == 0 and n:
                print(f"placed {n} of {len(new)} new label photos ({comparer.compared} pairs compared)", flush=True)
            s = serial[k]["straightened_serial"]
            if s:
                pid = comparer.best(k, sorted(by_serial.get(s, [])), mem)
                if pid:
                    store.add(pid, {k: record(k)}, manual=False)
                    mem[pid].append(k)
                else:
                    left.setdefault((s, solved[k]["shape"]), []).append(k)
            else:
                pid = comparer.best(k, sorted(by_family.get(solved[k]["family"], set())), mem)
                if pid:
                    store.add(pid, {k: record(k)}, manual=False)
                    mem[pid].append(k)
                else:
                    store.make({k: record(k)}, None, manual=False, release=serial[k].get("release"))
        for (s, shape), keys in sorted(left.items()):
            n = len(keys)
            D = np.zeros((n, n) + comparer.view(keys[0])[1].shape, bool) if n > 1 else None
            for i, j in itertools.combinations(range(n), 2):
                m = comparer.tiles(keys[i], keys[j])
                if m is not None:
                    D[i, j] = D[j, i] = m
            groups = split_family(D.reshape(n, n, -1))[0] if n > 1 else [[0]]
            for g in groups:
                store.make({keys[i]: record(keys[i]) for i in g}, s, manual=False)
        save_pairs(pairs_file, version, {**comparer.cached})
        print(f"{comparer.compared} pairs compared", flush=True)
        store.save()
        # what this run changed
        changes = []
        for e in store.data["log"][log_start:]:
            for pid, after in e["after"].items():
                before = e["before"].get(pid)
                if before is None and after is not None:
                    changes.append({"kind": "new", "id": pid, "keys": after["keys"]})
                elif after is None:
                    changes.append({"kind": "gone", "id": pid})
                else:
                    gained = sorted(set(after["keys"]) - set(before["keys"]))
                    lost = sorted(set(before["keys"]) - set(after["keys"]))
                    if gained:
                        changes.append({"kind": "added", "id": pid, "keys": gained})
                    if lost:
                        changes.append({"kind": "removed", "id": pid, "keys": lost})
        # written out
        all_prints = []
        for pid, p in sorted(store.prints.items()):
            keys = sorted(p["label_photos"])
            pose = lambda k: solved.get(k) or p["label_photos"][k].get("pose") or {}
            fams = Counter(pose(k).get("family") for k in keys if pose(k).get("family"))
            e = {"id": pid, "keys": keys, "serial": p.get("serial"),
                 "shape": p.get("shape") or (pose(keys[0]).get("shape") if keys else None),
                 "family": fams.most_common(1)[0][0] if fams else None}
            if len(fams) > 1:
                e["families"] = sorted(fams)
            if p.get("frozen"):
                e["frozen"] = pid
            e["release"] = print_release(e["serial"], [serial.get(k, {}) for k in keys])
            read = sorted({serial.get(k, {}).get("straightened_serial") for k in keys} - {None})
            if len(read) > 1:  # not restored until fixed by hand (stored-prints.md); none-serial ones don't count
                e["several_serials"] = read
            all_prints.append(e)
        for d in os.listdir(out_dir):  # pair images (pooling masks) of earlier versions
            if os.path.isdir(os.path.join(out_dir, d)):
                for f in os.listdir(os.path.join(out_dir, d)):
                    os.remove(os.path.join(out_dir, d, f))
                os.rmdir(os.path.join(out_dir, d))
        steps.write_json(out, {"prints": all_prints, "tile_mm": TILE_MM, "differences": {}})
        steps.write_json(os.path.join(out_dir, "few-photos.json"), sorted(p["id"] for p in all_prints if len(p["keys"]) < FEW and not p.get("frozen")))
        steps.write_json(os.path.join(out_dir, "id-changes.json"), changes)
        counts = Counter(c["kind"] for c in changes)
        print("store changes: " + (", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "none"), flush=True)
    result = json.load(open(out))
    page(out_dir, result, gen)
    print(f"{len(result['prints'])} prints of {sum(len(p['keys']) for p in result['prints'])} label photos; page: {os.path.join(out_dir, 'index.html')}")


def page(out_dir, result, gen):
    """index.html: per family of several label photos, its prints side by side, the tiles that split them outlined in
    red; for a family of several prints, a viewer stacking one label photo per print in the same place, flipped by a
    click or by itself (they share ink coordinates, so only real differences move)."""
    by_family = {}
    for p in result["prints"]:
        if p["keys"]:  # a frozen print with none of its label photos left has nothing to show
            by_family.setdefault(p["family"], []).append(p)
    rel = os.path.relpath(os.path.join(gen, "straighten"), out_dir)
    P, M, T = straighten.PX_PER_MM, straighten.MARGIN, result["tile_mm"]
    blocks = []
    for fam, ps in sorted(by_family.items(), key=lambda kv: (-len(kv[1]), -sum(len(p["keys"]) for p in kv[1]))):
        if len(ps) < 2 and len(ps[0]["keys"]) < 2:
            continue
        shape = ps[0]["shape"]
        (w, h), _ = straighten.canvas(shape)
        d = result.get("differences", {}).get(fam)
        marks = ""
        if d:
            cols = d["grid"][1]
            for t in d["tiles"]:
                r, c = divmod(t, cols)
                marks += f'<rect x="{(M + 1 + c * T) * P}" y="{(M + 1 + r * T) * P}" width="{T * P}" height="{T * P}" fill="none" stroke="#f33" stroke-width="5"/>'
        overlay = f'<svg viewBox="0 0 {w} {h}">{marks}</svg>'
        figure = lambda k: f'<div class="ph"><img loading="lazy" src="{rel}/{straighten.file_name(k)}" >{overlay}</div>'
        name = lambda p: f'{html.escape(str(p["serial"] or p["release"] or "?"))} ({len(p["keys"])})'
        if len(ps) == 1:  # one print: its label photos side by side
            row = f'<div class="print"><div>{name(ps[0])}</div>{"".join(figure(k) for k in ps[0]["keys"][:steps.PAGE_SOURCES])}{steps.more(len(ps[0]["keys"]))}</div>'
        else:  # several: the viewer shows them, here only their names
            row = f'<p>Its prints (label photos): {", ".join(name(p) for p in ps)}</p>'
        viewer = ""
        if len(ps) > 1:
            layers = "".join(f'<img loading="lazy" src="{rel}/{straighten.file_name(p["keys"][0])}" data-label="{html.escape(str(p["serial"] or p["release"] or "?"))} ({len(p["keys"])} label photos)" style="display:{"block" if n == 0 else "none"}">' for n, p in enumerate(steps.few(ps)))
            viewer = (f'<div class="viewer" onclick="flip(this)"><div class="stack">{layers}{overlay}</div>'
                      f'<div class="caption">{html.escape(str(ps[0]["serial"] or ps[0]["release"] or "?"))} ({len(ps[0]["keys"])} label photos)</div>'
                      f'<label onclick="event.stopPropagation()"><input type="checkbox" onchange="auto(this)"> flip by itself</label></div>')
        blocks.append(f'<h3>Family {html.escape(fam[:10])}: {steps.shown(len(ps))} prints{", " + str(len(d["tiles"])) + " tiles differ" if d else ""}</h3>{viewer}{row}')
    n = len(result["prints"])
    multi = sum(1 for ps in by_family.values() if len(ps) > 1)
    changes_file = os.path.join(out_dir, "id-changes.json")
    changes = json.load(open(changes_file)) if os.path.exists(changes_file) else []
    counts = Counter(c["kind"] for c in changes)
    words = {"new": lambda c: f'{c["id"]}: new, {len(c["keys"])} label photos', "added": lambda c: f'{c["id"]}: {len(c["keys"])} label photos added',
             "removed": lambda c: f'{c["id"]}: {len(c["keys"])} label photos gone', "gone": lambda c: f'{c["id"]}: no label photo left'}
    listed = "".join(f"<li>{html.escape(words[c['kind']](c))}</li>" for c in changes if c["kind"] in words)
    ids = (f'<p>Changes to the stored prints this run: {", ".join(f"{v} {k}" for k, v in sorted(counts.items()))}.</p>'
           + (f"<ul>{listed}</ul>" if listed else "")) if changes else ""
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>prints</title>
<style>body{{font:14px system-ui;margin:16px;background:#333;color:#eee}} .print{{display:inline-block;vertical-align:top;margin:4px 12px 12px 0;padding:4px;border:1px solid #666}}
.ph{{position:relative;display:inline-block;margin:2px}} .ph img{{width:150px;display:block}} .ph svg, .stack svg{{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}}
.viewer{{display:inline-block;vertical-align:top;margin:0 16px 12px 0;cursor:pointer}} .stack{{position:relative;width:420px}} .stack img{{width:420px}} .caption{{font-weight:bold}}</style>
<script>
function flip(v){{const imgs=v.querySelectorAll('.stack img');let i=[...imgs].findIndex(x=>x.style.display!='none');imgs[i].style.display='none';i=(i+1)%imgs.length;imgs[i].style.display='block';v.querySelector('.caption').textContent=imgs[i].dataset.label;}}
function auto(box){{const v=box.closest('.viewer');if(box.checked){{v._t=setInterval(()=>flip(v),700);}}else{{clearInterval(v._t);}}}}
</script>
<h1>prints</h1>
<p>{n} prints; families with more than one print: {multi}. Tiles of {result["tile_mm"]} mm.</p>
{ids}
{steps.legend([("#f33", "a tile that tells the family's prints apart (a square on every image of the family)")])}
<p>The viewer stacks one label photo per print (the family's first {steps.PAGE_FIGURES}) in the same place: click it, or tick "flip by itself", to switch between them. A family of one print: its first {steps.PAGE_SOURCES} label photos. Families of one label photo left out.</p>
<h2>Families ({steps.shown(len(blocks))})</h2>
{"".join(steps.few(blocks))}""")


if __name__ == "__main__":
    main()
