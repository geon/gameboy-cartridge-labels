import concurrent.futures, glob, hashlib, json, os, sys, cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import color, fits, photos
from cartridge import shell_of

# fit-colors: each photo's own color settings (src/color.py: brightness, contrast, temperature, tint) into
# colors.json, auto-generated; settings placed by hand (make adjust-colors) are kept. For every photo but the fakes
# whose plastic is accepted or placed by hand:
#   - its source's settings (src/source-colors.json, learned by make learn-colors from the labels of releases also
#     photographed by a reference source), none if its source has none;
#   - then, for a source whose photos aren't all lit alike (not in color.LIT_ALIKE), if its label is accepted or placed
#     by hand and white paper is found on it (color.paper): brightness, temperature and tint set so that the paper
#     comes out neutral, as bright as the reference sources' paper.
# The labels are read from their images in generated/fit-colors/labels/<photo>.png: straightened, at render-labels'
# size, evened out by their source (color.corrected) but without their own settings; made again when the photo, its
# label's fit or the code changed (made.json).
# Usage: fit_colors.py
OUT = "generated/fit-colors"
LABELS = os.path.join(OUT, "labels")
CONSTANTS = "src/source-colors.json"
CODE = hashlib.sha1(b"".join(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f), "rb").read()
                             for f in ("fit_colors.py", "color.py", "render.py"))).hexdigest()


def candidates():
    """The photos to set colors for: stem -> (source, path, sha1, shell name, label homography or None)."""
    known, found = fits.load(), {}
    for source, system, name, entry in photos.all_sources():
        if source in photos.FAKES:
            continue
        stem, sha1 = photos.stem(name), entry.get("sha1")
        fit = fits.of(known, stem, sha1)["fit"]
        if fits.good(fit.get("plastic")):
            label = fit["label"]["mm_to_photo"] if fits.good(fit.get("label")) else None
            found[stem] = (source, os.path.join(photos.ROOT, source, system, name), sha1, shell_of(photos.serial_of(name)).name, label)
    return found


def make_label(stem, path, shell, label_H):
    import render
    from fit_cartridge import load
    cv2.setNumThreads(1)
    image = render.label_image(load(path), shell, label_H)
    cv2.imwrite(os.path.join(LABELS, stem + ".png"), image)
    return stem


def label_images(found):
    """Each photo's label image (stem -> BGR array) for the photos with a good label, made where missing or stale."""
    os.makedirs(LABELS, exist_ok=True)
    made_path = os.path.join(OUT, "made.json")
    made = json.load(open(made_path)) if os.path.exists(made_path) else {}
    want = {stem: {"sha1": sha1, "label": H, "code": CODE} for stem, (_, _, sha1, _, H) in found.items() if H is not None}
    for stem in set(made) - set(want):
        if os.path.exists(os.path.join(LABELS, stem + ".png")):
            os.remove(os.path.join(LABELS, stem + ".png"))
        del made[stem]
    todo = [s for s in sorted(want) if made.get(s) != want[s] or not os.path.exists(os.path.join(LABELS, s + ".png"))]
    if todo:
        print(f"{len(todo)} label images to make into {LABELS}/")
        with concurrent.futures.ProcessPoolExecutor() as pool:
            for n, stem in enumerate(pool.map(make_label, todo, *zip(*[(found[s][1], found[s][3], found[s][4]) for s in todo]), chunksize=4), 1):
                made[stem] = want[stem]
                if n % 200 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)}", flush=True)
                    json.dump(made, open(made_path, "w"))
    json.dump(made, open(made_path, "w"))
    return {stem: cv2.imread(os.path.join(LABELS, stem + ".png")) for stem in want}


def papers(labels):
    """White paper's color on each label (color.paper), stem -> linear BGR or None."""
    stems = sorted(labels)
    with concurrent.futures.ProcessPoolExecutor() as pool:
        return dict(zip(stems, pool.map(color.paper, [labels[s] for s in stems], chunksize=16)))


def load_constants():
    return json.load(open(CONSTANTS)) if os.path.exists(CONSTANTS) else {"paper": None, "sources": {}}


def auto(source, paper, constants):
    """A photo's auto-generated settings: its source's, then its paper made neutral at the reference sources' paper
    brightness if its source isn't lit alike and paper was found."""
    base = constants["sources"].get(source)
    base = {k: base[k] for k in color.SETTINGS} if base else dict(color.NEUTRAL)
    if source in color.LIT_ALIKE or paper is None or constants.get("paper") is None:
        return base
    k, contrast = color.gains_of(base), base["contrast"]
    seen = 2.0 ** k * np.asarray(paper, np.float64) ** contrast  # the paper after its source's settings
    y = float(seen @ color.LUMINANCE)
    return color.settings_of(k - np.log2(seen / y) + np.log2(constants["paper"] / y), contrast)


if __name__ == "__main__":
    found = candidates()
    labels = label_images(found)
    paper_of = papers(labels)
    constants = load_constants()
    print(f"{len(found)} photos with a good plastic fit, {len(labels)} with a good label, white paper found on "
          f"{sum(p is not None for p in paper_of.values())}; source settings for {len(constants['sources'])} sources ({CONSTANTS})")
    kept = changed = 0
    with color.editing_colors() as colors:
        for stem in list(colors):
            if stem not in found and colors[stem]["colors"].get("source") != "hand-placed":
                del colors[stem]
        for stem, (source, _, sha1, _, _) in sorted(found.items()):
            current = color.colors_of(colors, stem, sha1)
            if current and current.get("source") == "hand-placed":
                kept += 1
                continue
            settings = {k: round(v, 4) for k, v in auto(source, paper_of.get(stem), constants).items()} | {"source": "auto-generated"}
            changed += current != settings
            colors[stem] = {"sha1": sha1, "colors": settings}
    print(f"{kept} placed by hand, kept; {changed} auto-generated settings changed, into {color.FILE}")
