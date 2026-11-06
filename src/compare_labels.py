import concurrent.futures, hashlib, json, os, sys, cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fits
from fit_colors import LABELS, OUT as COLORS_OUT, candidates

# compare-labels: how alike photos' labels are, for review-designs. A photo of one shell only against those of the same
# shell (DMG with DMG, CGB with CGB, AGB with AGB). Only the photos whose label is accepted or placed by hand, from their
# label images made by make fit-colors (generated/fit-colors/labels/<photo>.png: straightened, at render-labels' size,
# the photo's colors as they are), so the comparison sees the label alone, nothing around it. Also, roughly, the photos
# whose plastic is accepted or placed by hand but not their label: their label as fitted but not accepted (almost), else
# the label's model where it sits on the plastic, at its median width (fit_label.MEDIAN_WIDTHS), from label images made
# here (generated/compare-labels/labels/<photo>.png, made again when the photo, the fit or the code changed: made.json).
# How alike two labels are: the mean of three correlations of their images (-1 to 1, 1 the same), in gray and in two
# color channels, made alike in lighting first:
#   - gray, each pixel divided by the image blurred over LIGHTING px (about 5 mm), so that uneven lighting, the
#     brightness and the contrast don't count;
#   - color: Lab's a and b (green-red, blue-yellow), each less the channel blurred over LIGHTING px, so that a color
#     cast doesn't count; labels printed on one template (the Classic NES Series) differ mostly in their art's colors;
#   - shrunk to SCALE (about 1.2 px per mm): noise, JPEG artifacts and the fit's small errors don't count;
#   - correlated over the whole label, the best of the shifts up to SHIFT px (about 1.7 mm) either way, so that a fit a
#     little off doesn't count; a scratch, a sticker or a different serial covers a small part of the label, and so
#     lowers it a little.
# Measured on the labels of 2026-11-04 (1640 DMG, 209 CGB, 370 AGB photos): two photos of the same release score a median
# 0.91 (97.7 % of them above 0.7, some of those below misnamed); photos of different games above 0.7: 43 DMG pairs of
# 1.3 million, 15 CGB of 22 thousand, 9 AGB of 68 thousand, the highest of them mostly misnamed photos or labels
# alike in art. Subtracting each shell's mean label didn't help at 0.7 (CGB fewer, but same releases missed).
# Color added 2026-11-06, measured on 3277 labels: pairs of photos of one serial score a median 0.91 either way; of
# different games, 109 pairs scored 0.7 or more in gray alone, 40 with color (and 99.5 % of one serial's pairs, from
# 98.8 %); at 0.78, 97 % of one serial's pairs and 22 of different games. Comparing at 2.4 px per mm didn't help more.
# So SIMILAR, for labels of different serials alike (to link), is 0.78; SAME, for a design's photos alike (else
# perhaps different designs), 0.7, forgiving a poor photo. All of them compared in about 20 s (6 s reading the
# images), so nothing is kept between runs.
LIGHTING = 25  # px at render-labels' 4.7 px per mm
SCALE = 0.25
SHIFT = 2  # px after SCALE
SIMILAR = 0.78
SAME = 0.7
ROUGH_OUT = "generated/compare-labels"
ROUGH = os.path.join(ROUGH_OUT, "labels")
CODE = hashlib.sha1(b"".join(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f), "rb").read()
                             for f in ("render.py", "fit_label.py"))).hexdigest()


def features(image):
    """A label image (BGR) made alike in lighting and shrunk: [gray, a, b], each as float32."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    channels = [gray / (cv2.GaussianBlur(gray, (0, 0), LIGHTING) + 1)]
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    channels += [lab[..., c] - cv2.GaussianBlur(lab[..., c], (0, 0), LIGHTING) for c in (1, 2)]
    return [cv2.resize(c, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA) for c in channels]


def normalized(x):
    x = x - x.mean(-1, keepdims=True)
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-6)


def scores(new, old):
    """The scores of each of new (n, h, w) against each of old (m, h, w): (n, m), the best over the shifts either way."""
    h, w = new.shape[1] - 2 * SHIFT, new.shape[2] - 2 * SHIFT
    middle = lambda f: normalized(f[:, SHIFT:SHIFT + h, SHIFT:SHIFT + w].reshape(len(f), -1))
    a, b = middle(new), middle(old)
    best = np.full((len(new), len(old)), -1.0, np.float32)
    for dy in range(-SHIFT, SHIFT + 1):
        for dx in range(-SHIFT, SHIFT + 1):
            shifted = lambda f: normalized(f[:, SHIFT + dy:SHIFT + dy + h, SHIFT + dx:SHIFT + dx + w].reshape(len(f), -1))
            best = np.maximum(best, np.maximum(shifted(new) @ b.T, a @ shifted(old).T))
    return best


def rough_label(fit, shell):
    """A photo's label, roughly, where it isn't accepted or placed by hand: its current fit (almost, or not reviewed),
    else the label's model on the plastic at its median width."""
    if fit.get("label") is not None:
        return fit["label"]["mm_to_photo"]
    from cartridge import SHELLS
    from fit_label import MEDIAN_WIDTHS, label_pose
    H = np.asarray(fit["plastic"]["mm_to_photo"], np.float64) @ label_pose(0, 0, 0, MEDIAN_WIDTHS[shell], SHELLS[shell].label)
    return (H / H[2, 2]).tolist()


def make_rough(stem, path, shell, label_H):
    import render
    from fit_cartridge import load
    cv2.setNumThreads(1)
    cv2.imwrite(os.path.join(ROUGH, stem + ".png"), render.label_image(load(path), shell, label_H))
    return stem


def rough_images(rough):
    """The rough label images (stem -> (path, shell, sha1, label homography)), made where missing or stale."""
    os.makedirs(ROUGH, exist_ok=True)
    made_path = os.path.join(ROUGH_OUT, "made.json")
    made = json.load(open(made_path)) if os.path.exists(made_path) else {}
    want = {stem: {"sha1": sha1, "label": H, "code": CODE} for stem, (_, _, sha1, H) in rough.items()}
    for stem in set(made) - set(want):
        if os.path.exists(os.path.join(ROUGH, stem + ".png")):
            os.remove(os.path.join(ROUGH, stem + ".png"))
        del made[stem]
    todo = [s for s in sorted(want) if made.get(s) != want[s] or not os.path.exists(os.path.join(ROUGH, s + ".png"))]
    if todo:
        print(f"{len(todo)} rough label images to make into {ROUGH}/")
        with concurrent.futures.ProcessPoolExecutor() as pool:
            for n, stem in enumerate(pool.map(make_rough, todo, *zip(*[(rough[s][0], rough[s][1], rough[s][3]) for s in todo]), chunksize=4), 1):
                made[stem] = want[stem]
                if n % 200 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)}", flush=True)
    json.dump(made, open(made_path, "w"))


def compared_photos():
    """The photos to compare: SHA-1 -> (stem, shell, label fit, label image, whether rough), those with a good label and
    its current image from make fit-colors, and those with a good plastic only, roughly; and the stems of those with a
    good label but no current image (run make fit-colors)."""
    made_path = os.path.join(COLORS_OUT, "made.json")
    made = json.load(open(made_path)) if os.path.exists(made_path) else {}
    known = fits.load()
    current, stale, rough = {}, [], {}
    for stem, (_, path, sha1, shell, H) in candidates().items():
        if H is None:
            rough[stem] = (path, shell, sha1, rough_label(fits.of(known, stem, sha1)["fit"], shell))
        elif made.get(stem, {}).get("sha1") == sha1 and made[stem].get("label") == H and os.path.exists(os.path.join(LABELS, stem + ".png")):
            current[sha1] = (stem, shell, H, os.path.join(LABELS, stem + ".png"), False)
        else:
            stale.append(stem)
    rough_images(rough)
    for stem, (_, shell, sha1, H) in rough.items():
        current[sha1] = (stem, shell, H, os.path.join(ROUGH, stem + ".png"), True)
    return current, stale


def all_scores(current):
    """Every pair's score, shell by shell: {shell: (the SHA-1s, their scores against each other: (n, n))}."""
    found = {}
    for shell in sorted({c[1] for c in current.values()}):
        shas = sorted(s for s in current if current[s][1] == shell)
        f = [features(cv2.imread(current[s][3])) for s in shas]
        channels = [np.stack([x[k] for x in f]) for k in range(len(f[0]))]
        found[shell] = (shas, sum(scores(c, c) for c in channels) / len(channels))
    return found
