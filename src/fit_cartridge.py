import concurrent.futures, glob, json, os, subprocess, sys, tempfile, cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fits, photos
from cartridge import DISTANCE_TOLERANCE, MAX_TILT, SPECIAL_SHELLS, Fitter, agb_logo_lines, agb_logo_start, camera_distance, color_lines, color_start, corners_of, emboss_lines, emboss_start, outline_quads, outline_starts, project, shell_of, special_shell, text_starts, tilt

# fit-cartridge: fits the model of the cartridge's shell (src/cartridge.py: the Game Boy's, the Game Boy Color
# only cartridge's for CGB- serials, or the Game Boy Advance's for AGB- ones) to every photo in photos/ but those of
# cartridges with another shell (special-shells.tsv: rumble, tilt sensor...), started from its text in
# generated/read-text/ (make read-text) and from the outlines in the photo (the label, the recess or the body), or
# from a rough fit placed by hand alone (fits.json's start: fit-by-hand's Save for refit; fitted again when it changes), or,
# for a plastic judged almost (and no rough fit placed by hand), from it and VARIED random variations of it, the fit
# chosen among those found by a score learned from the fits judged right (src/choice.json, make learn-choice). The fit,
# the plastic's pose as a homography from mm on the cartridge's front to the photo's pixels, goes into fits.json (src/fits.py) as the photo's current plastic, not yet reviewed; what this step
# found on the way goes into generated/fit-cartridge/<photo>.json: the shell, the fit, the camera's distance from the
# cartridge that explains it (a range, mm; fits no camera 20 to 100 cm away could have seen are left out), how far to
# trust it, and the candidates. The label, stuck on a little shifted and turned, is fitted in a later step, once the
# plastic's fit is known to be right. A photo whose plastic is accepted or placed by hand isn't fitted; one judged almost
# is (from it, as above), and a different fit takes its place (the almost one goes to the rejected fits, as it wasn't right); a fit equal to
# a rejected one isn't made current again. A photo is fitted again only when its file is missing, older than the photo,
# its text, or this step's code, or made from another photo under the same name (the file has the SHA-1 of the photo
# it was made from); one without its text is skipped and reported, and one renamed since read-text ran waits for it. A
# photo that can't be fitted gets {"error": why}, so it isn't tried again on every run. Files of photos no longer in
# photos/ are removed.
# Usage: fit_cartridge.py
TEXT = "generated/read-text"
OUT = "generated/fit-cartridge"
SYSTEMS = ("dmg", "cgb", "agb", "lrg", "unknown")  # lrg: Limited Run Games' cartridges, fitted as DMG shells
SIDES = ("top", "right", "bottom", "left")


def load(path):
    """The photo, upright (OpenCV applies the EXIF orientation, as the text recognition does); formats OpenCV can't
    read (HEIC) through a JPEG copy made by sips. Its colors as they are (its color settings are applied when it's
    rendered: src/color.py)."""
    photo = cv2.imread(path)
    if photo is None:
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "photo.jpg")
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "95", path, "--out", copy], check=True, capture_output=True)
            photo = cv2.imread(copy)
    return photo


def crop(photo, lines, shell):
    """The box (x0, y0, x1, y1) of one cartridge in the photo, found by its embossed "Nintendo GAME BOY": the body the
    line implies (cartridge.emboss_start), with a margin (box_of). Of the lines like it, the one with the best score less
    its distance from the photo's center (in shares of the photo's size): photos of my collection show the neighbouring
    cartridges at the edges. Without any, a "GAME BOY COLOR" on the label (cartridge.color_start), likewise nearest the
    center. Without the crop, the fitter (which works at about 900 px across) saw a cartridge filling 60 % of a phone
    photo at about 10 px/mm, and nearly every fit had a broken recess line. The CGB's shell has no such embossing: by its
    "GAME BOY COLOR" alone; the AGB's by its embossed "GAME BOY ADVANCE" alone. Returns the box and the line, or None."""
    h, w = photo.shape[:2]
    candidates, start = (emboss_lines(lines, count=10), emboss_start) if shell.name == "dmg" else (agb_logo_lines(lines)[:10], agb_logo_start) if shell.name == "agb" else ([], None)
    if not candidates and shell.color_text is not None:
        candidates, start = color_lines(lines), lambda line: color_start(line, text=shell.color_text)
    if not candidates:
        return None
    off_center = lambda l: float(np.linalg.norm(np.array(l["quad"]).mean(axis=0) / [w, h] - 0.5))
    line = min(candidates, key=lambda l: candidates.index(l) / len(candidates) + off_center(l))
    return box_of(start(line), shell, (w, h)), line


def box_of(H, shell, size):
    """The box (x0, y0, x1, y1) of the body H (mm -> the photo's pixels) puts in the photo (its box: with the AGB's
    shoulders), with a margin of 12 % of its size for the start's error in scale and place, within the photo."""
    body = project(H, corners_of(shell.box))
    margin = 0.12 * (body.max(axis=0) - body.min(axis=0))
    x0, y0 = np.maximum(np.floor(body.min(axis=0) - margin).astype(int), 0)
    x1, y1 = np.minimum(np.ceil(body.max(axis=0) + margin).astype(int), list(size))
    return int(x0), int(y0), int(x1), int(y1)


def recess_plausible(H, recess):
    """The recess's proportions: photos are taken nearly head on, so its width over its height stays close to the
    model's (44:39 on the DMG). In 59 photos placed by hand it was 0.992 to 1.048 of that; every fit outside 0.98 to
    1.05 was off by over 1.4 mm."""
    q = project(H, corners_of(recess))
    width = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    height = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    return 0.97 <= width / height / ((recess[2] - recess[0]) / (recess[3] - recess[1])) <= 1.06


# The choice among a photo's fits: a score, linear in what Fitter.features and choice_rows measure (standardized),
# learned from the fits accepted or placed by hand (make learn-choice, src/learn_choice.py). On 400 such photos (cross-
# validated by photo, 2026-11-01), starts from both the text and the outlines, within 0.5 mm: DMG 174 of 200 (the
# strongest recess line's, the earlier choice: 170; the text's starts alone 158), CGB 131 of 200 (56; 78).
CHOICE = "src/choice.json"
RIVAL = 0.3
# A rough fit placed by hand is close: searched from 1.4 mm, not 3, so the fit doesn't slide off to another edge. On 6
# photos placed by hand, from starts 0.9 and 1.85 mm off (2026-11-04): within 0.5 mm of the hand fit 5 of 6 each, against
# 2 with the usual bands; from 3.7 mm off, none either way. So "rough" means within about 2 mm.
HAND_START_BANDS = (1.4, 1.0, 0.7, 0.5, 0.4, 0.4)
# A plastic judged almost: fitted from it and VARIED variations of it (random: shifted VARY_SHIFT mm, turned VARY_TURN
# degrees about the recess's center and scaled VARY_SCALE, each a standard deviation), with HAND_START_BANDS, the fit
# chosen by the score. Measured 2026-11-07 on 657 rejected fits 0.5 to 3 mm off a photo's accepted or hand-placed one
# (median 1.15 mm), within 0.5 mm of it: from the rejected fit alone 164, from it and 12 variations 293 (the best of
# the 13 fits: 321); DMG 46 -> 136 of 310, CGB 65 -> 95 of 261, AGB 53 -> 62 of 86. 149 came out no closer.
# Only fits AWAY mm or more from the almost one (recess corners, on average) are chosen from: closer, it's the same fit
# to review again. Measured again on 667 such fits: within 0.5 / 1 mm 306 / 450 -> 312 / 428, 15 left with none.
VARIED, VARY_SHIFT, VARY_TURN, VARY_SCALE = 12, 0.7, 1.0, 0.015
AWAY = 0.1
FEATURES = ["from_outline"] + [f"{kind}_{m}" for kind in ("recess", "label", "face", "arrow", "pill", "groove") for m in ("near", "str", "offset")] + \
    ["recess_strength", "band_line", "quality", "cont_min", "cont_mean", "inconsistency", "tilt", "support"]
DERIVED = ("rs_rel", "rs_top", "dscale", "possible", "clear", "log_inc")


def choice_rows(candidates):
    """What the choice weighs of each of a photo's fits, as rows: Fitter.features and the fit's own (from_outline,
    inconsistency, tilt, support: the share of the photo's fits within 0.5 mm of it), and against the photo's other fits:
    the recess's strength over the strongest's, whether it's the strongest, how far its scale is from their median (log),
    and whether it's possible and clear of a line in the band below the recess."""
    X = np.array([[c[n] for n in FEATURES] for c in candidates], np.float64)
    strength = np.array([c["recess_strength"] for c in candidates])
    scale = np.log([c["px_per_mm"] for c in candidates])
    inconsistency = np.array([c["inconsistency"] for c in candidates])
    derived = {"rs_rel": strength / (strength.max() + 1e-9), "rs_top": (strength == strength.max()).astype(float),
               "dscale": np.abs(scale - np.median(scale)), "possible": (inconsistency <= DISTANCE_TOLERANCE).astype(float),
               "clear": (np.array([c["band_line"] for c in candidates]) < 0.8).astype(float), "log_inc": np.log1p(inconsistency)}
    return np.c_[X, np.stack([derived[n] for n in DERIVED], axis=1)]




def scores(candidates):
    """The choice's score of each of a photo's fits (higher: likelier right)."""
    with open(CHOICE) as f:
        model = json.load(f)
    if model["features"] != FEATURES + list(DERIVED):
        sys.exit(f"{CHOICE} was learned on other features: make learn-choice")
    return (choice_rows(candidates) - model["mean"]) / model["sd"] @ np.array(model["weights"])


def same_place(a, b, recess):
    """The mean distance (mm) between the recess's corners as fit a puts them and as fit b does, in b's frame."""
    return float(np.linalg.norm(project(np.linalg.inv(b), project(a, corners_of(recess))) - corners_of(recess), axis=1).mean())


def varied(H, shell):
    """H (mm -> the photo's pixels) and VARIED random variations of it, the same each run."""
    rng = np.random.default_rng(0)
    cx, cy = (shell.recess[0] + shell.recess[2]) / 2, (shell.recess[1] + shell.recess[3]) / 2
    found = [H]
    for _ in range(VARIED):
        a, k = np.radians(rng.normal(0, VARY_TURN)), 1 + rng.normal(0, VARY_SCALE)
        dx, dy = rng.normal(0, VARY_SHIFT, 2)
        c, s = np.cos(a) * k, np.sin(a) * k
        found.append(H @ np.array([[c, -s, cx - c * cx + s * cy + dx], [s, c, cy - s * cx - c * cy + dy], [0, 0, 1]]))
    return found


def candidates_of(photo, lines, shell, start=None, almost=False):
    """Every plausible fit of the photo, with what the choice weighs, and the groups of starts they came from: the
    text's, in the box of the cartridge it shows (crop), and the outlines', each quadrilateral taken for the label,
    recess or body in the box it implies (fits from those kept upright, as their starts don't tell up from down).
    Returns (candidates, groups); a candidate's "H" is in the photo's pixels, its "group" an index into groups, each
    (fitter, shift from the crop to the photo, box, starts in the crop, found_by). With start (a rough fit placed by hand,
    mm -> the photo's pixels), from it alone; if almost (a plastic judged almost), from it and its variations."""
    size = (photo.shape[1], photo.shape[0])
    groups = []
    if start is not None:
        start = np.asarray(start, np.float64)
        groups.append((box_of(start, shell, size), varied(start, shell) if almost else [start], "almost start" if almost else "hand start"))
    found = crop(photo, lines, shell) if start is None else None
    if found is not None:
        box, line = found
        shift = np.array([[1, 0, box[0]], [0, 1, box[1]], [0, 0, 1]], np.float64)
        in_crop = [dict(l, quad=(np.array(l["quad"]) - box[:2]).tolist()) for l in lines]
        groups.append((box, [shift @ H0 for H0 in text_starts(in_crop, shell)], line["text"]))
    by_outline = {}
    for H0, i, what in outline_starts(outline_quads(photo), shell, size) if start is None else ():
        by_outline.setdefault((i, what), []).append(H0)
    groups += [(box_of(group[0], shell, size), group, "outline") for group in by_outline.values()]
    candidates, fitters = [], []
    for (x0, y0, x1, y1), starts, found_by in groups:
        fitter = Fitter(photo[y0:y1, x0:x1], shell, center=(photo.shape[1] / 2 - x0, photo.shape[0] / 2 - y0))
        shift = np.array([[1, 0, x0], [0, 1, y0], [0, 0, 1]], np.float64)
        fitters.append((fitter, shift, (x0, y0, x1, y1), [np.linalg.inv(shift) @ H0 for H0 in starts], found_by))
        for H0 in fitters[-1][3]:
            H, _ = fitter.fit(H0, bands=HAND_START_BANDS) if found_by in ("hand start", "almost start") else fitter.fit(H0)
            Hp = shift @ H
            Hp /= Hp[2, 2]
            # A rough fit placed by hand is trusted to be roughly right: photos too slanted for these checks are what it's for.
            if found_by in ("hand start", "almost start") or recess_plausible(H, shell.recess) and (found_by != "outline" or abs(tilt(Hp)) <= MAX_TILT):
                candidates.append({"H": Hp, "group": len(fitters) - 1, "from_outline": float(found_by == "outline"), **fitter.features(H),
                                   "inconsistency": float(camera_distance(Hp, size)[0]), "tilt": abs(tilt(Hp)),
                                   "px_per_mm": float(np.sqrt(abs(np.linalg.det(Hp[:2, :2]))))})
    for c in candidates:
        c["support"] = float(np.mean([same_place(o["H"], c["H"], shell.recess) < 0.5 for o in candidates]))
    return candidates, fitters


def fit(photo_path, text_path, start=None, almost=False):
    """The fit of one photo, as written to its file; from start alone if given (fits.json's: a rough fit placed by hand;
    or, if almost, a plastic judged almost, and its variations)."""
    cv2.setNumThreads(1)
    photo = load(photo_path)
    if photo is None:
        return {"error": "the photo can't be read"}
    lines = json.load(open(text_path))
    shell = shell_of(photos.serial_of(os.path.basename(photo_path)))
    size = (photo.shape[1], photo.shape[0])
    recess = shell.recess
    possible = lambda H: camera_distance(H, size)[0] <= DISTANCE_TOLERANCE
    candidates, groups = candidates_of(photo, lines, shell, start, almost)
    if almost:
        candidates = [c for c in candidates if same_place(c["H"], np.asarray(start, np.float64), recess) >= AWAY]
        if not candidates:
            return {"error": f"no fit {AWAY} mm or more from the almost one"}
    if not candidates:
        return {"error": "no plausible fit" if groups else "no text or outline to start from"}
    score = scores(candidates)
    k = int(np.argmax(score))
    best = candidates[k]
    fitter, shift, (x0, y0, x1, y1), starts, found_by = groups[best["group"]]
    Hp = best["H"]
    H = np.linalg.inv(shift) @ Hp
    quality = best["quality"]
    # Ambiguity: the likeliest rival that lands clearly elsewhere (recess corners over 0.5 mm away on average), as
    # likely as the winner (exp of the score's difference). One at RIVAL or more flags the fit for review: on the 400
    # photos it was learned from (cross-validated) that flagged 84 and caught 31 of the 41 fits off by 1 mm or more.
    rival = max(((float(np.exp(score[j] - score[k])), d) for j, c in enumerate(candidates) if (d := same_place(c["H"], Hp, recess)) > 0.5), default=(0.0, 0.0))
    # A broken recess line: a side with under 40 % of its samples on one straight line. On the photos placed by hand
    # every fit off by more than 1 mm had one (21 to 36 %), and 3 good fits. Label art along that side (a logo's
    # letters) may have been taken for the recess: fitted again without that side's recess and label samples, from
    # every start, and kept if the recess's line is then less broken.
    continuity = fitter.line_continuity(H)
    refit_without = None
    if min(continuity) < 0.4:
        side = int(np.argmin(continuity))
        reduced = fitter.without_side(side)
        retry = (-1.0, None)
        for H0 in starts + [H]:
            Hr, _ = reduced.fit(H0)
            if recess_plausible(Hr, recess) and possible(shift @ Hr):
                s = reduced.recess_strength(Hr)
                if s > retry[0]:
                    retry = (s, Hr)
        if retry[1] is not None:
            retry_continuity = fitter.line_continuity(retry[1])
            if min(retry_continuity) > min(continuity):
                H, continuity, refit_without = retry[1], retry_continuity, SIDES[side]
                quality = fitter.quality(H)
    Hp = shift @ H
    Hp = Hp / Hp[2, 2]
    if almost and same_place(Hp, np.asarray(start, np.float64), recess) < AWAY:  # the refit without a side came back to it
        return {"error": f"no fit {AWAY} mm or more from the almost one"}
    if not possible(Hp) and start is None:
        return {"error": "no fit a camera 20 to 100 cm away could have seen", "crop": [x0, y0, x1, y1], "found_by": found_by}
    return {"shell": shell.name, "mm_to_photo": Hp.tolist(), "photo_size": list(size), "distance_mm": camera_distance(Hp, size)[1],
            "crop": [x0, y0, x1, y1], "found_by": found_by, "quality": quality, "recess_strength": best["recess_strength"], "score": float(score[k]),
            "rival_strength": rival[0], "rival_distance_mm": rival[1], "ambiguous": rival[0] >= RIVAL,
            "line_continuity": continuity, "broken_line": min(continuity) < 0.4, "refit_without": refit_without,
            "candidates": [{"mm_to_photo": c["H"].tolist(), "score": float(s), "recess_strength": c["recess_strength"], "band_line": c["band_line"],
                            "possible": c["inconsistency"] <= DISTANCE_TOLERANCE, "found_by": groups[c["group"]][4]} for c, s in zip(candidates, score)]}


def fit_into(stem, photo_path, text_path, sha1, start=None, almost=False):
    out = os.path.join(OUT, stem + ".json")
    try:
        result = fit(photo_path, text_path, start, almost)
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}
    result["sha1"] = sha1
    result["start"] = start
    result["almost"] = almost
    json.dump(result, open(out, "w"))
    return stem, result


def take(e, found):
    """Puts a photo's fit as this step found it (its file; None: not fitted) into its entry in fits.json, unless its
    plastic is known to be right. Returns whether it's current."""
    current = e["fit"].get("plastic")
    if fits.good(current):
        return False
    if found is None or "error" in found or fits.was_rejected(e, found["mm_to_photo"]):
        if current is not None and "accepted" not in current:
            e["fit"] = {}
        return False
    if current is not None and fits.same(current, found["mm_to_photo"]):
        return True
    if current is not None and current.get("accepted") == "almost":
        fits.reject_plastic(e)
    e["fit"] = {"plastic": fits.part(found["mm_to_photo"])}
    return True


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    # Photos renamed since read-text last ran are left for it, which takes their new names (photos.reconcile).
    paths = {photos.stem(n): os.path.join(photos.ROOT, s, system, n) for s, system, n, _ in photos.all_sources() if system in SYSTEMS}
    paths = {stem: path for stem, path in paths.items() if os.path.exists(path)}
    special = {stem for stem in paths if special_shell(photos.serial_of(stem))}
    paths = {stem: path for stem, path in paths.items() if stem not in special}
    for path in glob.glob(os.path.join(OUT, "*.json")):
        if photos.stem(os.path.basename(path)) not in paths:
            os.remove(path)
    code = max(os.path.getmtime(p) for p in ("src/cartridge.py", __file__, CHOICE))
    sha1s = photos.sha1s()
    known = fits.load()
    todo, no_text, kept = [], [], set()
    for stem, path in sorted(paths.items()):
        e = fits.of(known, stem, sha1s[stem])
        if fits.good(e["fit"].get("plastic")):
            kept.add(stem)
            continue
        start = (e.get("start") or {}).get("mm_to_photo")
        current = e["fit"].get("plastic")
        almost = start is None and current is not None and current.get("accepted") == "almost"
        if almost:
            start = current["mm_to_photo"]
        text = os.path.join(TEXT, stem + ".json")
        out = os.path.join(OUT, stem + ".json")
        # A fit made from an almost one and not yet reviewed (the almost one now rejected): its start is still that one.
        before = json.load(open(out)) if os.path.exists(out) else {}
        if start is None and before.get("almost") and current is not None and "accepted" not in current \
                and "mm_to_photo" in before and fits.same(current, before["mm_to_photo"]):
            start, almost = before["start"], True
        if not os.path.exists(text):
            no_text.append(stem)
        elif not os.path.exists(out) or (made := json.load(open(out))).get("sha1") != sha1s[stem] or os.path.getmtime(out) < max(os.path.getmtime(path), os.path.getmtime(text), code) \
                or made.get("start") != start or made.get("almost", False) != almost:
            todo.append((stem, path, text, sha1s[stem], start, almost))
    print(f"{len(paths)} photos ({len(special)} of cartridges with another shell left out, {SPECIAL_SHELLS}), {len(kept)} with their plastic accepted or placed by hand, kept; {len(todo)} to fit" + (f"; {len(no_text)} without their text (make read-text): {' '.join(no_text)}" if no_text else ""))
    with concurrent.futures.ProcessPoolExecutor() as pool:
        for done, (stem, result) in enumerate(pool.map(fit_into, *zip(*todo)) if todo else (), 1):
            print(f"{done} of {len(todo)}: {stem}: {result.get('error') or 'quality %.2f' % result['quality']}", flush=True)
    # Every photo's fit into fits.json, from the files (so that an interrupted run loses nothing).
    with fits.editing() as known:
        current = 0
        for stem in paths:
            out = os.path.join(OUT, stem + ".json")
            found = json.load(open(out)) if os.path.exists(out) else None
            if found is not None and found.get("sha1") != sha1s[stem]:
                found = None
            current += take(fits.entry(known, stem, sha1s[stem]), found)
    # Only the photos this step fits: the files of kept ones may be of an older version of it.
    results = [json.load(open(p)) for p in glob.glob(os.path.join(OUT, "*.json")) if photos.stem(os.path.basename(p)) not in kept]
    print(f"{len(kept)} kept, {current} fitted and not known to be wrong; {sum('error' in r for r in results)} couldn't be fitted, "
          f"{sum('error' not in r and not r['ambiguous'] and not r['broken_line'] for r in results)} files not flagged (ambiguous or broken recess line)")
