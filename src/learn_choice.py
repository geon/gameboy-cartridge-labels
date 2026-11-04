import concurrent.futures, glob, json, os, random, sys, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fits, photos
from cartridge import SHELLS, shell_of
from fit_cartridge import CHOICE, DERIVED, FEATURES, candidates_of, choice_rows, load, same_place

# learn-choice: a tool, not a step. Learns fit-cartridge's choice among a photo's fits (src/fit_cartridge.py, scores)
# from the photos whose plastic is accepted or placed by hand (fakes from emumovies and launchbox-abeezy1388 left out:
# copies of one fit each): every fit fit-cartridge finds on each, with what the choice weighs, into
# generated/learn-choice/<photo>.json (made again when the photo, its good fit, its text or fit-cartridge's code
# changed), labelled right when its recess's corners lie within GOOD mm of the good fit's on average. The score is
# linear in the features, standardized; a softmax over each photo's fits is trained to put the probability on its right
# ones (photos with none left out). Prints how many photos each choice gets right, cross-validated by photo (5 folds),
# beside the strongest recess line's (the choice before) and the best of the fits; writes the score to src/choice.json,
# which fit-cartridge reads (it fits again the photos not yet known to be right).
# Usage: learn_choice.py [number of photos per shell, at random; default all]
OUT = "generated/learn-choice"
GOOD = 0.5


def found(stem, path, text, sha1, plastic):
    """A photo's fits, as kept in its file."""
    import cv2
    cv2.setNumThreads(1)
    photo = load(path)
    shell = shell_of(photos.serial_of(stem))
    candidates, groups = candidates_of(photo, json.load(open(text)), shell) if photo is not None else ([], [])
    G = np.array(plastic)
    kept = [{k: v for k, v in c.items() if k != "group"} | {"H": c["H"].tolist(), "error_mm": same_place(c["H"], G, shell.recess)} for c in candidates]
    result = {"sha1": sha1, "plastic": plastic, "shell": shell.name, "candidates": kept}
    json.dump(result, open(os.path.join(OUT, stem + ".json"), "w"))
    return stem


def train(photos_, l2=1e-2, steps=3000, rate=0.05):
    """The score's weights, and the features' mean and spread, from [(rows, right)] (Adam on the softmax's loss)."""
    X = np.vstack([rows for rows, _ in photos_])
    mean, sd = X.mean(axis=0), X.std(axis=0) + 1e-9
    usable = [((rows - mean) / sd, right / right.sum()) for rows, right in photos_ if right.any()]
    w, m, v = np.zeros(X.shape[1]), np.zeros(X.shape[1]), np.zeros(X.shape[1])
    for t in range(1, steps + 1):
        g = l2 * w
        for Z, q in usable:
            s = Z @ w
            p = np.exp(s - s.max())
            g += Z.T @ (p / p.sum() - q) / len(usable)
        m, v = 0.9 * m + 0.1 * g, 0.999 * v + 0.001 * g * g
        w -= rate * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
    return w, mean, sd


def strongest(candidates):
    """The choice before: of the fits clear of a line below the recess and possible, the strongest recess line."""
    clear = [c for c in candidates if c["band_line"] < 0.8] or candidates
    return max([c for c in clear if c["inconsistency"] <= 5] or clear, key=lambda c: c["recess_strength"])


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    per_shell = int(sys.argv[1]) if len(sys.argv) > 1 else None
    known, sha1s = fits.load(), photos.sha1s()
    good = []
    for source, system, name, _ in photos.all_sources():
        stem = photos.stem(name)
        plastic = fits.of(known, stem, sha1s[stem])["fit"].get("plastic")
        text = os.path.join("generated/read-text", stem + ".json")
        if source not in photos.FAKES and system in ("dmg", "cgb", "agb") and fits.good(plastic) and os.path.exists(text):
            good.append((stem, os.path.join(photos.ROOT, source, system, name), text, sha1s[stem], plastic["mm_to_photo"]))
    if per_shell:
        random.seed(0)
        random.shuffle(good)
        good = [g for shell in SHELLS for g in [g for g in good if shell_of(photos.serial_of(g[0])).name == shell][:per_shell]]
    code = max(os.path.getmtime(p) for p in ("src/cartridge.py", "src/fit_cartridge.py"))
    todo = []
    for stem, path, text, sha1, plastic in good:
        out = os.path.join(OUT, stem + ".json")
        old = json.load(open(out)) if os.path.exists(out) else None
        if old is None or old["sha1"] != sha1 or old["plastic"] != plastic or os.path.getmtime(out) < max(os.path.getmtime(path), os.path.getmtime(text), code):
            todo.append((stem, path, text, sha1, plastic))
    print(f"{len(good)} photos with a good plastic fit; {len(todo)} to find the fits of")
    with concurrent.futures.ProcessPoolExecutor() as pool:
        for done, stem in enumerate(pool.map(found, *zip(*todo)) if todo else (), 1):
            if done % 50 == 0 or done == len(todo):
                print(f"{done} of {len(todo)}", flush=True)
    data = []
    for stem, *_ in good:
        r = json.load(open(os.path.join(OUT, stem + ".json")))
        if r["candidates"]:
            data.append((stem, r["shell"], r["candidates"], choice_rows(r["candidates"]), np.array([c["error_mm"] < GOOD for c in r["candidates"]])))
    # Cross-validated: each photo chosen by a score learned without it.
    fold = np.random.default_rng(0).integers(0, 5, len(data))
    learned = [None] * len(data)
    for k in range(5):
        w, mean, sd = train([(rows, right) for (_, _, _, rows, right), f in zip(data, fold) if f != k])
        for i, (_, _, candidates, rows, _) in enumerate(data):
            if fold[i] == k:
                learned[i] = candidates[int(np.argmax((rows - mean) / sd @ w))]["error_mm"]
    for shell in SHELLS:
        idx = [i for i, d in enumerate(data) if d[1] == shell]
        if not idx:
            continue
        within = lambda errors, t: sum(e < t for e in errors)
        before = [strongest(data[i][2])["error_mm"] for i in idx]
        after = [learned[i] for i in idx]
        best = [min(c["error_mm"] for c in data[i][2]) for i in idx]
        print(f"{shell.upper()}: {len(idx)} photos with fits; within 0.5 mm: learned {within(after, .5)}, strongest recess line {within(before, .5)}, "
              f"best of the fits {within(best, .5)}; within 1 mm: {within(after, 1)}, {within(before, 1)}, {within(best, 1)}")
    w, mean, sd = train([(rows, right) for _, _, _, rows, right in data])
    json.dump({"features": FEATURES + list(DERIVED), "mean": mean.tolist(), "sd": sd.tolist(), "weights": w.tolist(), "photos": len(data)},
              open(CHOICE, "w"), indent=1)
    print(f"{CHOICE} written; the largest weights: " + ", ".join(f"{n} {x:+.2f}" for n, x in sorted(zip(FEATURES + list(DERIVED), w), key=lambda p: -abs(p[1]))[:8]))
