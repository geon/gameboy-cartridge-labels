# refreeze: a tool, not a step (the user, 2026-11-14: the frozen prints updated to today's pipeline): every frozen print
# (src/frozen.py), or the one given, restored again with today's restore (restore.restore_print) and its frozen image
# replaced (frozen.refreeze). What the user accepted stays: the print's label photos (as prints.json has them now, a
# new photo of it included; poor fits left out, as restore does), their poses (solve keeps a frozen label photo's), and
# the frozen crop. A print with too few label photos to restore (restore.MIN_PHOTOS, MIN_PRECISE) keeps its image.
# Its work in <generated>/refreeze/ (the restored images and descriptions, as restore's). The new images have new
# SHA-1s: the next make all matches them again (features, match) and find, prints and publish take them.
# Usage: refreeze.py [--sample] [--workers N] [print id ...]
import argparse, json, multiprocessing, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, steps, straighten, restore, frozen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("ids", nargs="*")
    args = ap.parse_args()
    gen = photos.generated(args.sample)
    prints_file, solve_file = os.path.join(gen, "prints", "prints.json"), os.path.join(gen, "solve", "solve.json")
    for p in (prints_file, solve_file):
        if not os.path.exists(p):
            sys.exit(f"{p} missing: run make prints first")
    entries = frozen.load()
    unknown = [i for i in args.ids if i not in entries]
    if unknown:
        sys.exit(f"not frozen: {' '.join(unknown)}")
    wanted = set(args.ids or entries)
    solved = json.load(open(solve_file, encoding="utf-8"))["label_photos"]
    info = restore.fit_info(gen, solved)
    out_dir = os.path.join(gen, "refreeze")
    os.makedirs(out_dir, exist_ok=True)
    base = lambda pid: os.path.join(out_dir, straighten.file_name(pid)[:-5])
    jobs, kept = [], []
    by_frozen = {p["frozen"]: p for p in json.load(open(prints_file, encoding="utf-8"))["prints"] if p.get("frozen")}
    for pid in sorted(wanted):
        p = by_frozen.get(pid)
        job = p and restore.job_of({**p, "id": pid}, info, entries[pid]["crop"])
        if job:
            jobs.append(job + (base(pid),))
        else:
            kept.append(pid)
    done = 0
    print(f"restoring {len(jobs)} frozen prints again, {args.workers} at a time", flush=True)
    with multiprocessing.Pool(args.workers) as pool:
        for n, (pid, desc) in enumerate(pool.imap_unordered(restore.restore_print, jobs), 1):
            if desc is not None:
                steps.write_json(base(pid) + ".json", desc)
                frozen.refreeze(pid, base(pid))
                done += 1
            else:
                kept.append(pid)
            print(f"{n} of {len(jobs)}: {pid}" + ("" if desc is not None else " (kept its image)"), flush=True)
    print(f"{done} frozen prints restored again; {len(kept)} kept their image (too few label photos): {' '.join(sorted(kept))}")


if __name__ == "__main__":
    main()
