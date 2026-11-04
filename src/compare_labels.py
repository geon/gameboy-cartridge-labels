import hashlib, json, os, sys, cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, serials
from fit_colors import LABELS, OUT as COLORS_OUT, candidates

# compare-labels: finds the photos whose labels look alike but which are filed under different releases (as find-doubles
# groups them: serials.release_key, so DMG-AS2J and DMG-AS2J-JPN_2 are one release) and printed with different serials
# (DMG-ATAJ-JPN and DMG-ATAJ-JPN[PINK], a release in another shell's color, are not), a photo of one shell only against
# those of the same shell (DMG with DMG, CGB with CGB, AGB with AGB). Only the photos whose label is accepted or placed by
# hand, from their label images made by make fit-colors (generated/fit-colors/labels/<photo>.png: straightened, at
# render-labels' size, the photo's colors as they are), so the comparison sees the label alone, nothing around it.
# How alike two labels are: the correlation of their images (-1 to 1, 1 the same), made alike in lighting first:
#   - gray, each pixel divided by the image blurred over LIGHTING px (about 5 mm), so that uneven lighting, the
#     brightness and the contrast don't count;
#   - shrunk to SCALE (about 1.2 px per mm): noise, JPEG artifacts and the fit's small errors don't count;
#   - correlated over the whole label, the best of the shifts up to SHIFT px (about 1.7 mm) either way, so that a fit a
#     little off doesn't count; a scratch, a sticker or a different serial covers a small part of the label, and so
#     lowers it a little.
# Measured on the labels of 2026-11-04 (1640 DMG, 209 CGB, 370 AGB photos): two photos of the same release score a median
# 0.91 (97.7 % of them above 0.7, some of those below misnamed); photos of different games above 0.7: 43 DMG pairs of
# 1.3 million, 15 CGB of 22 thousand, 9 AGB of 68 thousand, the highest of them mostly misnamed photos or labels
# alike in art. Subtracting each shell's mean label didn't help at 0.7 (CGB fewer, but same releases missed).
# Each pair's score is kept in generated/compare-labels/scores.json, by the photos' SHA-1s, so that a photo is compared
# once: a new photo only with those already there; a photo compared again when its label's fit changes; those gone dropped.
# Only scores of at least FLOOR are kept, so that THRESHOLD can be lowered without comparing again.
# The pairs scoring at least THRESHOLD of different releases, by score, with the photos' names as they are now and
# whether gb-game-list has them as the same game (another region's release, its label often alike), into
# generated/compare-labels/matches.tsv, to review.
# Usage: compare_labels.py
OUT = "generated/compare-labels"
SCORES = os.path.join(OUT, "scores.json")
MATCHES = os.path.join(OUT, "matches.tsv")
LIGHTING = 25  # px at render-labels' 4.7 px per mm
SCALE = 0.25
SHIFT = 2  # px after SCALE
FLOOR = 0.5
THRESHOLD = 0.7
CODE = hashlib.sha1(open(os.path.abspath(__file__), "rb").read().split(b"\nFLOOR")[0]).hexdigest()


def features(image):
    """A label image (BGR) made alike in lighting and shrunk, as float32."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    flat = gray / (cv2.GaussianBlur(gray, (0, 0), LIGHTING) + 1)
    return cv2.resize(flat, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)


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


def pair(a, b):
    return " ".join(sorted((a, b)))


def main():
    found = candidates()
    made_path = os.path.join(COLORS_OUT, "made.json")
    made = json.load(open(made_path)) if os.path.exists(made_path) else {}
    # The photos to compare: SHA-1 -> (stem, shell, label fit), those with a current label image.
    current, stale = {}, []
    for stem, (_, _, sha1, shell, H) in found.items():
        if H is None:
            continue
        if made.get(stem, {}).get("sha1") == sha1 and made[stem].get("label") == H and os.path.exists(os.path.join(LABELS, stem + ".png")):
            current[sha1] = (stem, shell, H)
        else:
            stale.append(stem)
    if stale:
        print(f"{len(stale)} photos with a good label but no current label image, left out: run make fit-colors first")

    os.makedirs(OUT, exist_ok=True)
    kept = json.load(open(SCORES)) if os.path.exists(SCORES) else {}
    if kept.get("code") != CODE:
        kept = {}
    compared = {s: c for s, c in kept.get("compared", {}).items() if s in current and c == {"shell": current[s][1], "label": current[s][2]}}
    pairs = {k: v for k, v in kept.get("scores", {}).items() if all(s in compared for s in k.split())}
    todo = [s for s in current if s not in compared]

    for shell in sorted({current[s][1] for s in todo}):
        new = sorted(s for s in todo if current[s][1] == shell)
        old = sorted(s for s in compared if compared[s]["shell"] == shell)
        load = lambda shas: np.stack([features(cv2.imread(os.path.join(LABELS, current[s][0] + ".png"))) for s in shas])
        print(f"{shell.upper()}: {len(new)} photos to compare, with each other and with {len(old)} compared before")
        n = load(new)
        for (i, j), score in np.ndenumerate(np.triu(scores(n, n), 1)):
            if j > i and score >= FLOOR:
                pairs[pair(new[i], new[j])] = round(float(score), 3)
        if old:
            for (i, j), score in np.ndenumerate(scores(n, load(old))):
                if score >= FLOOR:
                    pairs[pair(new[i], old[j])] = round(float(score), 3)
        compared.update({s: {"shell": shell, "label": current[s][2]} for s in new})

    open(SCORES + ".tmp", "w").write(json.dumps({"code": CODE, "compared": compared, "scores": pairs}))
    os.replace(SCORES + ".tmp", SCORES)

    release_of = serials.releases_by_serial()
    release = {s: serials.release_key(current[s][0], release_of) for s in compared}
    differ = lambda a, b: release[a][0] != release[b][0] and photos.serial_of(current[a][0]) != photos.serial_of(current[b][0])
    game = lambda s: release[s][1]["gameId"] if release[s][1] else release[s][0]
    matches = sorted(((v, *sorted(k.split(), key=lambda s: current[s][0])) for k, v in pairs.items()
                      if v >= THRESHOLD and differ(*k.split())), reverse=True)
    lines = ["score\tshell\tphoto\tother photo\tsame game\tsha1\tother sha1"]
    lines += [f"{v:.3f}\t{current[a][1].upper()}\t{current[a][0]}\t{current[b][0]}\t{'yes' if game(a) == game(b) else 'no'}\t{a}\t{b}"
              for v, a, b in matches]
    open(MATCHES, "w").write("\n".join(lines) + "\n")
    counts = {sh: sum(current[a][1] == sh for _, a, _ in matches) for sh in sorted({c[1] for c in current.values()})}
    print(f"{len(compared)} photos compared; {len(matches)} pairs alike (score at least {THRESHOLD}) of different releases "
          f"({', '.join(f'{sh.upper()} {n}' for sh, n in counts.items())}; {sum(game(a) == game(b) for _, a, b in matches)} of the same game) -> {MATCHES}")


if __name__ == "__main__":
    main()
