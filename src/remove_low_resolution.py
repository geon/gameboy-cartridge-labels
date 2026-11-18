# remove-low-resolution: deletes from photos/ (photos.delete: the file and its record in photo-sources.json) every
# photo whose label photos all have fewer than MIN_PX_PER_MM photo pixels per mm at the label (the fit's, solve's
# local_scale), by the last solve.json (the user, 2026-11-12: a step, so photos added later are deleted once measured;
# 2026-11-11 done once by hand). The first step of make all: a photo measured in one run is deleted at the start of the
# next, before find and solve, which leave out photos since deleted (deleting after solve would leave the same run's
# later steps a solve.json with label photos no longer drawn). A photo with one label photo above it is kept (a low one
# beside it is more likely a misfit than a blurry photo); one with no solved label photo is left to remove-photos'
# Unused tab. Each deletion is recorded in <generated>/remove-low-resolution/deleted.json ({sha1: {"px_per_mm" (its
# label photos'), "source" (its photo-sources.json record), "date"}}), kept across runs.
# Usage: remove_low_resolution.py [--sample]
import argparse, datetime, json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, shapes, steps

MIN_PX_PER_MM = 10.0
SOURCES = "photo-sources.json"


def low_resolution(solved, present):
    """sha1 -> its label photos' pixels per mm, for the photos in present whose label photos are all under MIN_PX_PER_MM."""
    import solve
    by_photo = {}
    for r in solved.values():
        if r["photo"] in present:
            lw, lh = shapes.LABEL_MM[r["shape"]]
            by_photo.setdefault(r["photo"], []).append(solve.local_scale(np.array(r["cut_to_photo"]), [0, 0, lw, lh]))
    return {s: sorted(round(float(v), 1) for v in ppm) for s, ppm in by_photo.items() if max(ppm) < MIN_PX_PER_MM}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()
    gen = photos.generated(args.sample)
    solve_file = os.path.join(gen, "solve", "solve.json")
    if not os.path.exists(solve_file):
        print("no solve.json yet: nothing measured, nothing deleted")
        return
    present = photos.chosen(args.sample)
    low = low_resolution(json.load(open(solve_file, encoding="utf-8"))["label_photos"], present)
    log_file = os.path.join(gen, "remove-low-resolution", "deleted.json")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    log = json.load(open(log_file, encoding="utf-8")) if os.path.exists(log_file) else {}
    sources = json.load(open(SOURCES, encoding="utf-8")) if os.path.exists(SOURCES) else {}
    today = datetime.date.today().isoformat()
    for s, ppm in sorted(low.items()):
        log[s] = {"px_per_mm": ppm, "source": sources.get(s), "date": today}
        photos.delete(s)
    steps.write_json(log_file, log)
    print(f"{len(low)} photos deleted (every label photo under {MIN_PX_PER_MM:g} px/mm); {len(log)} in all: {log_file}")


if __name__ == "__main__":
    main()
