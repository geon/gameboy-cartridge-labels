# select-visually-distinct: of each game's prints, the ones that look different enough to browse (the user,
# 2026-11-20: prints differing only by serial, region or a slightly moved logo aren't interesting; different games,
# layouts, Japanese and Western art, colours are). Into <generated>/select-visually-distinct/:
#   scores.json: {"version", "pairs": [{"a", "b" (print ids), "a_image", "b_image" (fingerprints: the image's SHA-1
#     and its crop), "differ" (the share of 2 mm tiles that differ), "colour", "structure" (the shares differing by
#     each test)}]}: every pair of published prints with an image of one game (the database's game id) and one label
#     shape. A pair is compared again when either image or crop changes, or the comparison (version) does.
#   selected.json: {"selected": [print id]: the prints to browse, "left_out": {print id: the selected print of its game
#     it differs least from}}, every published print with an image in one of them. Per game, its prints by the label photos they're restored from
#     (most first, then by id), each kept unless it differs from a print already kept by under DISTINCT (shapes
#     differing: always kept). So any two kept prints of a game differ by DISTINCT or more, and each left out is within
#     it of a kept one. Prints of an unknown game are all kept.
#   index.html: the games with prints left out, each with the prints kept and left out.
# The comparison (compare): both restored prints placed in the label's frame by their crops (mm, PX per mm, blurred
# BLUR mm); B shifted onto A (phase correlation; none if over MAX_SHIFT); B's colour fitted onto A's per Lab channel
# (a scale within SCALE and an offset within CAST about the channel's middle, least squares, refitted on the pixels
# matching after the previous fit: ΔE under FIT_DE), then B's residual band (the Laplacian pyramid's coarsest:
# RESIDUAL_LEVELS halvings, about 8 mm a pixel) replaced by A's: restorations differ in overall colour, contrast and
# shading; the user, 2026-11-20). Then 2 mm tiles, 1 mm in from the edges (the cuts), seen where over half is in both
# crops; a tile differs if its colour differs (its mean ΔE over COLOUR_DE, each spot matching within LOCAL mm) or its
# structure does (the gray minus its 1 mm blur: spread over TEXTURE in either print, not correlating over CORRELATION).
# DISTINCT: from the user's judgments on the 2026-11-20 pairs: near identical 3-5 %, a moved logo 3 %, Antz USA/EUR
# 33 % (alike); AGB-AAOE-USA/AGB-AAOP-UKV 59 % and AGB-AWRE-USA/AGB-AWRP-EUR 60 % (where pairs become mostly
# interesting), AGB-BBGE-USA/AGB-BBGP-EUR 62 % (different layouts), Japanese and Western Link's Awakening 85 %
# (different). 60 %: the user's round number.
# Done again: pairs as above; selected.json and index.html every run (from scores.json and prints.json).
# Usage: select_visually_distinct.py [--sample] [--workers N]
import argparse, collections, hashlib, html, inspect, itertools, json, os, sys, warnings
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, steps, shapes, frozen, straighten
import serials as serials_module

PX = 8                # px per mm the prints are compared at
BLUR = 0.5            # mm
MAX_SHIFT = 3.0       # mm: prints' ink frames differ by a millimetre or two at most
SCALE = (0.8, 1.25)   # colour fit: each channel's scale
CAST = 10.0           # colour fit: each channel's offset, Lab units
FIT_DE = 12.0         # colour fit: pixels matching after a fit (ΔE under this) refitted on
RESIDUAL_LEVELS = 6   # B's residual band (this many halvings) replaced by A's
TILE = 2.0            # mm
EDGE = 1.0            # mm in from the label's edges, left out (the cuts)
LOCAL = 0.5           # mm: each spot may match within this
COLOUR_DE = 20.0      # a tile's colour differs: its mean ΔE over this
TEXTURE = 0.02        # a tile has structure: its high-passed gray's spread over this (0-1 gray)
CORRELATION = 0.5     # a tile's structure differs: correlating under this
DISTINCT = 0.60       # prints differ enough to both be browsed: this share of tiles differing, or more


def image_of(p, gen, frozen_entries):
    """A print's restored image and crop (restore's, or the frozen one's), or (None, None)."""
    if p.get("frozen") in frozen_entries:
        path = frozen.image_path(p["frozen"])
        return (path, frozen_entries[p["frozen"]]["crop"]) if os.path.exists(path) else (None, None)
    path = os.path.join(gen, "restore", straighten.file_name(p["id"]))
    desc = path[:-5] + ".json"
    if not os.path.exists(path) or not os.path.exists(desc):
        return None, None
    return path, json.load(open(desc))["crop"]


def fingerprint(path, crop):
    return hashlib.sha1(open(path, "rb").read()).hexdigest()[:16] + ":" + ",".join(f"{v:.3f}" for v in crop["mm"])


def placed(path, crop, shape):
    """The restored print placed in its label's frame (PX per mm, NaN where the crop doesn't reach), blurred."""
    im = cv2.imread(path).astype(np.float32) / 255
    x0, y0, x1, y1 = crop["mm"]
    w, h = shapes.LABEL_MM[shape]
    canvas = np.full((int(h * PX), int(w * PX), 3), np.nan, np.float32)
    im = cv2.GaussianBlur(im, (0, 0), BLUR * im.shape[1] / (x1 - x0))
    im = cv2.resize(im, (int(round((x1 - x0) * PX)), int(round((y1 - y0) * PX))), interpolation=cv2.INTER_AREA)
    X, Y = int(round(x0 * PX)), int(round(y0 * PX))  # may be negative: the crop reaching past the label
    sx, sy = max(0, -X), max(0, -Y)
    X, Y = max(X, 0), max(Y, 0)
    hh, ww = min(im.shape[0] - sy, canvas.shape[0] - Y), min(im.shape[1] - sx, canvas.shape[1] - X)
    canvas[Y:Y + hh, X:X + ww] = im[sy:sy + hh, sx:sx + ww]
    return canvas


def shifted(img, dx, dy):
    M = np.float32([[1, 0, dx], [0, 1, dy]])  # out px -> img px
    return cv2.warpAffine(img, M, img.shape[1::-1], flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(np.nan,) * 3)


def tiles(x, valid):
    """x's 2 mm tiles, EDGE in from the edges: (h, w, pixels) with NaN outside valid, and which are seen."""
    t, m = int(TILE * PX), int(EDGE * PX)
    x = np.where(valid, x, np.nan)[m:-m, m:-m]
    h, w = x.shape[0] // t, x.shape[1] // t
    b = x[:h * t, :w * t].reshape(h, t, w, t).transpose(0, 2, 1, 3).reshape(h, w, -1)
    return b, np.mean(~np.isnan(b), 2) > 0.5


def residual(lab, valid):
    """The Laplacian pyramid's residual band of an image (outside valid filled by the mean first)."""
    x = np.where(valid[..., None], lab, lab[valid].mean(0)).astype(np.float32)
    sizes = []
    for _ in range(RESIDUAL_LEVELS):
        sizes.append(x.shape[1::-1])
        x = cv2.pyrDown(x)
    for s in reversed(sizes):
        x = cv2.pyrUp(x, dstsize=s)
    return x


def colour_fitted(la, lb, valid):
    """lb's channels fitted onto la's (see the header)."""
    scale, offset = np.ones(3), np.zeros(3)
    xa, xb = la[valid][::7], lb[valid][::7]
    use = np.ones(len(xa), bool)
    mid = np.array([50.0, 0.0, 0.0])  # offsets about the channels' middles: L 50, a and b 0
    for _ in range(3):
        for c in range(3):
            s, o = np.polyfit(xb[use, c] - mid[c], xa[use, c] - mid[c], 1) if use.sum() > 100 else (1.0, 0.0)
            scale[c], offset[c] = np.clip(s, *SCALE), np.clip(o, -CAST, CAST)
        use = np.linalg.norm(xa - ((xb - mid) * scale + mid + offset), axis=1) < FIT_DE
    return (lb - mid) * scale + mid + offset


def structure_differs(A, B, valid):
    """Per tile: textured in either and the high-passed gray not correlating."""
    def high(X):
        g = cv2.cvtColor(np.nan_to_num(X, nan=0.5), cv2.COLOR_BGR2GRAY)
        return g - cv2.GaussianBlur(g, (0, 0), PX)
    ba, seen = tiles(high(A), valid)
    bb, _ = tiles(high(B), valid)
    ba, bb = np.nan_to_num(ba), np.nan_to_num(bb)
    za, zb = ba - ba.mean(2, keepdims=True), bb - bb.mean(2, keepdims=True)
    corr = (za * zb).sum(2) / np.sqrt((za ** 2).sum(2) * (zb ** 2).sum(2) + 1e-12)
    return (np.maximum(ba.std(2), bb.std(2)) > TEXTURE) & (corr < CORRELATION) & seen


def compare(A, B):
    """Two placed prints: (the share of tiles differing, by colour, by structure)."""
    gray = lambda X: cv2.cvtColor(np.nan_to_num(X, nan=0.5), cv2.COLOR_BGR2GRAY)
    ga, gb = gray(A), gray(B)
    win = cv2.createHanningWindow(ga.shape[::-1], cv2.CV_32F)
    (dx, dy), _ = cv2.phaseCorrelate(ga - ga.mean(), gb - gb.mean(), win)
    if np.hypot(dx, dy) > MAX_SHIFT * PX:
        dx = dy = 0.0
    B = shifted(B, dx, dy)
    valid = ~np.isnan(A[..., 0]) & ~np.isnan(B[..., 0])
    if valid.sum() < 100:
        return 1.0, 1.0, 1.0
    la = cv2.cvtColor(np.nan_to_num(A), cv2.COLOR_BGR2LAB)
    lb = colour_fitted(la, cv2.cvtColor(np.nan_to_num(B), cv2.COLOR_BGR2LAB), valid)
    lb = lb - residual(lb, valid) + residual(la, valid)
    lb[~valid] = np.nan
    r = int(LOCAL * PX)
    de = np.full(la.shape[:2], np.inf, np.float32)
    for sx in range(-r, r + 1, 2):
        for sy in range(-r, r + 1, 2):
            de = np.fmin(de, np.linalg.norm(la - shifted(lb, sx, sy), axis=2))
    de[np.isinf(de)] = np.nan
    bt, seen = tiles(de, valid)
    with warnings.catch_warnings():  # tiles all outside: their mean NaN (not seen)
        warnings.simplefilter("ignore", RuntimeWarning)
        colour = (np.nanmean(bt, 2) > COLOUR_DE) & seen
    struct = structure_differs(A, B, valid)
    n = max(int(seen.sum()), 1)
    return float((colour | struct)[seen].sum() / n), float(colour[seen].sum() / n), float(struct[seen].sum() / n)


def version():
    """A fingerprint of the comparison (its functions and settings)."""
    h = hashlib.sha1()
    for f in (placed, shifted, tiles, residual, colour_fitted, structure_differs, compare):
        h.update(inspect.getsource(f).encode())
    h.update(repr((PX, BLUR, MAX_SHIFT, SCALE, CAST, FIT_DE, RESIDUAL_LEVELS, TILE, EDGE, LOCAL, COLOUR_DE, TEXTURE,
                   CORRELATION, shapes.LABEL_MM)).encode())
    return h.hexdigest()[:16]


def compare_job(job):
    a, b, (pa, ca), (pb, cb), shape = job
    return (a, b) + compare(placed(pa, ca, shape), placed(pb, cb, shape))


def select(prints, games, used, differ):
    """The prints kept and those left out (see the header): prints [id], games {id: game id or None}, used {id: label
    photos used}, differ {(a, b): share} (both orders; a pair missing: different shapes, always kept). Returns
    (kept [id], left out {id: the kept print it differs least from})."""
    by_game = collections.defaultdict(list)
    for pid in prints:
        by_game[games[pid] or ("print", pid)].append(pid)
    kept, left_out = [], {}
    for ps in by_game.values():
        mine = []
        for pid in sorted(ps, key=lambda p: (-used[p], p)):
            if all(differ.get((pid, k), 1.0) >= DISTINCT for k in mine):
                mine.append(pid)
            else:
                left_out[pid] = min(mine, key=lambda k: differ.get((pid, k), 1.0))
        kept += mine
    return sorted(kept), dict(sorted(left_out.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    gen = photos.generated(args.sample)
    out = os.path.join(gen, "select-visually-distinct")
    os.makedirs(out, exist_ok=True)
    for f in ("prints/prints.json", "solve/solve.json", "restore/index.html"):
        if not os.path.exists(os.path.join(gen, f)):
            sys.exit(f"no {os.path.join(gen, f)}: run make prints, solve and restore first")
    import solve as solve_step
    solved = json.load(open(os.path.join(gen, "solve", "solve.json")))["label_photos"]
    releases = {r["id"]: r for r in serials_module.releases()}
    frozen_entries = frozen.load()
    info = {}
    for p in json.load(open(os.path.join(gen, "prints", "prints.json")))["prints"]:
        if len(p["keys"]) < 2:  # not published
            continue
        path, crop = image_of(p, gen, frozen_entries)
        if path:
            info[p["id"]] = {"image": path, "crop": crop, "shape": p["shape"],
                             "game": (releases.get(p["release"]) or {}).get("gameId"),
                             "used": sum(1 for k in p["keys"] if k in solved and not solve_step.poor_fit(solved[k]))}
    for i in info.values():
        i["fingerprint"] = fingerprint(i["image"], i["crop"])

    v = version()
    scores_file = os.path.join(out, "scores.json")
    old = json.load(open(scores_file)) if os.path.exists(scores_file) else {}
    have = {(s["a"], s["b"]): s for s in old.get("pairs", [])} if old.get("version") == v else {}
    by_game = collections.defaultdict(list)
    for pid, i in sorted(info.items()):
        if i["game"]:
            by_game[i["game"], i["shape"]].append(pid)
    pairs, jobs = [], []
    for ps in by_game.values():
        for a, b in itertools.combinations(ps, 2):
            s = have.get((a, b))
            if s and s["a_image"] == info[a]["fingerprint"] and s["b_image"] == info[b]["fingerprint"]:
                pairs.append(s)
            else:
                jobs.append((a, b, (info[a]["image"], info[a]["crop"]), (info[b]["image"], info[b]["crop"]), info[a]["shape"]))
    print(f"{len(pairs) + len(jobs)} pairs of prints of one game, {len(jobs)} to compare", flush=True)
    if jobs:
        from multiprocessing import Pool
        with Pool(args.workers) as pool:
            for n, (a, b, d, c, s) in enumerate(pool.imap_unordered(compare_job, jobs, chunksize=4), 1):
                pairs.append({"a": a, "b": b, "a_image": info[a]["fingerprint"], "b_image": info[b]["fingerprint"],
                              "differ": round(d, 4), "colour": round(c, 4), "structure": round(s, 4)})
                if n % 200 == 0 or n == len(jobs):
                    print(f"compared {n} of {len(jobs)}", flush=True)
    pairs.sort(key=lambda s: (s["a"], s["b"]))
    steps.write_json(scores_file, {"version": v, "pairs": pairs})

    differ = {}
    for s in pairs:
        differ[s["a"], s["b"]] = differ[s["b"], s["a"]] = s["differ"]
    kept, left_out = select(list(info), {p: i["game"] for p, i in info.items()}, {p: i["used"] for p, i in info.items()}, differ)
    steps.write_json(os.path.join(out, "selected.json"), {"selected": kept, "left_out": left_out})
    page(out, info, kept, left_out, differ, releases)
    print(f"{len(kept)} of {len(info)} prints selected (visually distinct within their game)")
    print(f"page: {os.path.join(out, 'index.html')}")


def page(out, info, kept, left_out, differ, releases):
    """The games with prints left out: each print kept and left out, a left-out one with the kept print it's nearest."""
    kept_set = set(kept)
    games = collections.defaultdict(list)
    for pid, i in info.items():
        if i["game"]:
            games[i["game"]].append(pid)
    left = sorted((g for g, ps in games.items() if any(p not in kept_set for p in ps)),
                  key=lambda g: (releases.get(g) or {}).get("title") or g)
    rows = []
    for g in steps.few(left):
        ps = sorted(games[g], key=lambda p: (p not in kept_set, -info[p]["used"], p))
        figs = []
        for p in ps:
            src = os.path.relpath(os.path.abspath(info[p]["image"]), os.path.abspath(out))
            note = "kept" if p in kept_set else "left out"
            d = f", {100 * differ[p, left_out[p]]:.0f} % differs from {html.escape(left_out[p])}" if p in left_out else ""
            figs.append(f'<figure><img src="{html.escape(src)}"><figcaption>{html.escape(p)}: {note}{d}</figcaption></figure>')
        title = (releases.get(g) or {}).get("title") or g
        rows.append(f'<div class=row><b>{html.escape(title)}</b> ({html.escape(g)})<div class=imgs>{"".join(figs)}</div></div>')
    open(os.path.join(out, "index.html"), "w").write(
        '<!doctype html><meta charset=utf-8><title>Visually distinct prints</title><style>body{font:14px system-ui;'
        'margin:16px;background:#fff;color:#111}.row{border-top:1px solid #ccc;padding:10px 0}.imgs{display:flex;gap:8px;'
        'flex-wrap:wrap}figure{margin:0}figcaption{font-size:12px;max-width:260px}img{height:220px}</style>'
        f'<h1>Visually distinct prints</h1><p>{len(kept)} of {len(info)} prints kept for browsing: of a game\'s prints, '
        f'one is left out when under {100 * DISTINCT:.0f} % of its 2 mm tiles differ from a print kept. '
        f'Games with prints left out: {steps.shown(len(left))}.</p>' + "\n".join(rows))


if __name__ == "__main__":
    main()
