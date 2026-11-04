import collections, itertools, json, os, sys, cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import color, photos, serials
from fit_colors import CONSTANTS, auto, candidates, label_images, papers

# learn-colors: a tool, not a step. Learns each source's color settings (src/color.py) from the labels of releases
# photographed both by it and by a reference source (color.REFERENCES), into src/source-colors.json (committed;
# fit-colors reads it), and prints how near each source's labels come to the references'.
# Each pair of labels of a release, one from a reference source and one from another source, is compared on their
# images (generated/fit-colors/labels/, made where missing), blurred and shrunk to 46 x 40 px, their edges left out;
# the photo's settings that bring its label nearest the reference's are fitted on the pixels neither too dark nor too
# bright (the gains at white per channel and the contrast, on log brightness, the worst 30 % of pixels left out,
# four times over; see matching). A photo's: the median of its pairs'; a source's: the median of its photos', if it
# has at least MIN_PHOTOS. The reference sources' paper brightness (color.paper, after their own settings) is kept too:
# fit-colors makes a photo's paper as bright.
# The measure: the median ΔE (CIE76) between a photo's label and the reference's, both blurred and shrunk alike, each
# with its settings as fit-colors makes them, but its source's learned without its release (left out, release by
# release). Printed for no settings, the source's alone, and the source's with the paper's.
# Usage: learn_colors.py
MIN_PHOTOS = 5
SMALL = (46, 40)
EDGE = 8  # px of the 200 px label left out at its edges


def small(label):
    lin = color.LINEAR[label[EDGE:-EDGE, EDGE:-EDGE]]
    return cv2.resize(cv2.GaussianBlur(lin, (0, 0), 2), SMALL, interpolation=cv2.INTER_AREA)


def matching(a, b, rounds=4, keep=0.7):
    """The gains at white (stops, B, G, R) and the contrast that bring the small label a nearest b, or None. The
    contrast is fitted both ways (a to b, and b to a, inverted) and the two averaged (geometric mean): a least-squares
    slope fitted one way only comes out too low by the noise in what it's fitted from, and would flatten every label."""
    ok = (a > 0.01).all(2) & (b > 0.01).all(2) & (a < 0.95).all(2) & (b < 0.95).all(2)
    if ok.sum() < 100:
        return None
    la, lb = np.log2(a[ok]), np.log2(b[ok])
    use = np.ones(len(la), bool)
    for _ in range(rounds):
        n = use.sum()
        X, Y = np.zeros((3 * n, 4)), np.zeros((3 * n, 4))
        for c in range(3):
            X[c * n:(c + 1) * n, c] = Y[c * n:(c + 1) * n, c] = 1
        X[:, 3], Y[:, 3] = la[use].T.reshape(-1), lb[use].T.reshape(-1)
        forward = np.linalg.lstsq(X, Y[:, 3], rcond=None)[0][3]
        backward = np.linalg.lstsq(Y, X[:, 3], rcond=None)[0][3]
        contrast = np.sqrt(forward / backward) if forward > 0 and backward > 0 else forward
        gains = np.median(lb[use] - contrast * la[use], 0)
        error = np.abs(lb - (gains + contrast * la)).max(1)
        use = error <= np.quantile(error, keep)
    return gains, contrast


def applied(image, settings):
    return 2.0 ** color.gains_of(settings) * np.clip(image, 1e-4, None) ** settings["contrast"]


def delta_e(a, b):
    lab = lambda x: cv2.cvtColor(color.SRGB[np.clip(x * 4095 + 0.5, 0, 4095).astype(np.int32)].astype(np.float32) / 255, cv2.COLOR_BGR2Lab)
    return float(np.median(np.linalg.norm(lab(a) - lab(b), axis=2)))


def learned(per_photo, source_of, leave_out=None, release_of=None):
    """Each source's settings: the median of its photos' (those of release leave_out left out)."""
    by_source = collections.defaultdict(list)
    for stem, p in per_photo.items():
        if leave_out is None or release_of[stem] != leave_out:
            by_source[source_of[stem]].append(p)
    return {s: color.settings_of(np.median(v, 0)[:3], np.median(v, 0)[3]) | {"photos": len(v)}
            for s, v in by_source.items() if len(v) >= MIN_PHOTOS}


if __name__ == "__main__":
    found = candidates()
    labels = label_images(found)
    paper_of = papers(labels)
    release_of_serial = serials.releases_by_serial()
    source_of = {stem: found[stem][0] for stem in labels}
    release_of = {stem: serials.release_key(stem, release_of_serial)[0] for stem in labels}
    smalls = {stem: small(image) for stem, image in labels.items()}
    by_release = collections.defaultdict(list)
    for stem in labels:
        by_release[release_of[stem]].append(stem)
    pairs = [(a, b) for stems in by_release.values() for a, b in itertools.permutations(stems, 2)
             if source_of[b] in color.REFERENCES and source_of[a] != source_of[b]]
    fitted = collections.defaultdict(list)
    for a, b in pairs:
        m = matching(smalls[a], smalls[b])
        if m is not None:
            fitted[a].append(np.r_[m[0], m[1]])
    per_photo = {stem: np.median(v, 0) for stem, v in fitted.items()}

    def paper_target(sources):
        seen = [float(applied(paper_of[s][None, None], sources.get(source_of[s], color.NEUTRAL))[0, 0] @ color.LUMINANCE)
                for s in labels if source_of[s] in color.REFERENCES and paper_of[s] is not None]
        return float(np.median(seen))

    sources = learned(per_photo, source_of)
    constants = {"paper": round(paper_target(sources), 4),
                 "sources": {s: {k: round(v, 4) for k, v in c.items()} for s, c in sorted(sources.items())}}

    # The measure, each release's photos with settings learned without it.
    ways = ("none", "source", "source + paper")
    results = {w: collections.defaultdict(list) for w in ways}
    for release, stems in by_release.items():
        if not any(source_of[a] in color.REFERENCES for a in stems):
            continue
        without = {"paper": constants["paper"], "sources": learned(per_photo, source_of, release, release_of)}
        settings = {"none": lambda s: color.NEUTRAL,
                    "source": lambda s: without["sources"].get(source_of[s], color.NEUTRAL),
                    "source + paper": lambda s: auto(source_of[s], paper_of[s], without)}
        for a, b in itertools.permutations(stems, 2):
            if source_of[b] in color.REFERENCES and source_of[a] != source_of[b]:
                for w in ways:
                    results[w][source_of[a]].append(delta_e(applied(smalls[a], settings[w](a)), applied(smalls[b], settings[w](b))))
    shown = sorted(results["none"], key=lambda s: -len(results["none"][s]))
    print(f"Median ΔE to the reference sources' labels of the same release ({sum(len(v) for v in results['none'].values())} pairs):")
    print(f"{'':16s}{'all':>7s}" + "".join(f"{s[:11]:>12s}" for s in shown))
    print(f"{'pairs':16s}{sum(len(v) for v in results['none'].values()):7d}" + "".join(f"{len(results['none'][s]):12d}" for s in shown))
    for w in ways:
        print(f"{w:16s}{np.median([x for v in results[w].values() for x in v]):7.2f}" + "".join(f"{np.median(results[w][s]):12.2f}" for s in shown))
    json.dump(constants, open(CONSTANTS, "w"), indent=1)
    print(f"{CONSTANTS} written: the reference sources' paper at {constants['paper']:.3f} of white; " + ", ".join(
        f"{s} {c['brightness']:+.2f} stops, contrast {c['contrast']:.2f}, temperature {c['temperature']:+.2f}, tint {c['tint']:+.2f}"
        for s, c in constants["sources"].items()))
