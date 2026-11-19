# read-serials: every solved label photo's serial, into <generated>/read-serials/:
#   serials.json: {key: {"reads": [{"text", "serial", "kind" (exact, near, unknown), "from" (straightened, photo)}],
#                        "serial", "release" (the database's id or null), "decided_by", "family"}}
#   missing.json: the database's entries no label photo has (sorted by id)
#   unknown-serials.json: {serial-looking string the database doesn't know: [keys]} (possible new releases)
# The reads: OCR (read_text, RapidOCR) of the straightened label photo (straighten: upright, no perspective), and the
# serials find read in the photo (its own and those of the label photos solve merged into it: the same sticker). Decided, in order:
#   own: its own exact reads give one release;
#   own, with its title or family: they give several, the one whose title the label's text holds, else the one most
#     of its family's own exact reads support;
#   near: no exact read, a near serial (serials.near) its family supports or whose title is on the label, or its only
#     one;
#   family: no exact or near read of its own, and its family's own exact reads agree on one release, read by more
#     than half its other members that read anything serial-like (one cut-off serial that's a real release, DMG-BQ,
#     isn't passed on to the members reading DMG-BON for DMG-BQIJ);
#   (a release found by title alone is only a guess, "title_guess": on the full set 4 of 8 were right. Template words,
#     GAME BOY COLOR and the like, are left out of the comparison: they matched titles like "Game Boy Color".)
#   unknown: else (a serial-looking string the database doesn't know is kept, as a possible new release).
#   corrected by hand: serial-corrections.json ({label photo key: serial}, hand-edited) has the last word.
# Every label photo also gets "title_score" (how much of its release's title the label's text holds; low on many
# right ones: logos, stylised titles, Japanese against romanised titles) and, without a release, "title_guess".
# The family (solve: label photos joined by links whose points and pixels agree) only settles a label photo's own
# doubt: families can hold a series' games sharing a layout, and nearly-same prints have serials of their own.
# Done again when serials.json is older than this file, solve.json or find's label-photos.json; the OCR of a
# straightened label photo is cached in <generated>/read-serials/ocr/<file>.json, the fit it was read from beside it
# (<file>.fit.json); redone when read_text is newer, or its fit has moved the straightened image by REREAD_MM or more
# since (the user, 2026-11-12: text isn't in the label's outer mm, and the image has straighten.MARGIN around it).
# The page, <generated>/read-serials/index.html.
# Usage: read_serials.py [--sample] [--workers N]
import argparse, html, json, os, re, sys
from collections import Counter
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, serials, steps, read_text, straighten


CORRECTIONS = "serial-corrections.json"


REREAD_MM = 1.0


def fit_file(ocr_path):
    return ocr_path[:-5] + ".fit.json"


def ocr_job(job):
    image_path, out, photo_to_ink = job
    img = cv2.imread(image_path)
    lines = read_text.read(img) if img is not None else []
    steps.write_json(out, lines)
    steps.write_json(fit_file(out), {"photo_to_ink": photo_to_ink})
    return out


def reread(ocr_path, r, code_time):
    """Whether a label photo's OCR is to be done (again): missing, older than read_text, or its fit moved REREAD_MM or
    more since."""
    if not os.path.exists(ocr_path) or os.path.getmtime(ocr_path) < code_time or not os.path.exists(fit_file(ocr_path)):
        return True
    old = json.load(open(fit_file(ocr_path)))["photo_to_ink"]
    return straighten.moved_px(old, r["photo_to_ink"], r["shape"]) / straighten.PX_PER_MM >= REREAD_MM


PLATFORMS = {"dmg": ("DMG", "CGB"), "cgb": ("CGB",), "agb": ("AGB",)}  # the serial prefixes a shape's labels carry


def own_reads(lines, strings, release_of, regions, shape=None):
    """A label photo's reads: the straightened image's lines and find's strings from the photo. A near serial must be
    of the shape's platforms (a garbled AGB-ATUJ-JPN isn't near DMG-ATVJ-JPN)."""
    reads = []
    for source, texts in (("straightened", [l["text"] for l in lines]), ("photo", [t["text"] for t in strings])):
        for text in texts:
            exact = [s for s in serials.reads(text) if serials.release(s, release_of)]
            if exact:
                reads.append({"text": text, "serial": exact[0], "kind": "exact", "from": source})
                continue
            near = [n for n in serials.near(text, regions)
                    if shape is None or n[0].replace("DIS-", "").startswith(PLATFORMS.get(shape, ("DMG", "CGB", "AGB")))]
            if near:
                reads.append({"text": text, "serial": near[0][0], "kind": "near", "from": source})
                continue
            unknown = serials.reads(text)
            if unknown:
                reads.append({"text": text, "serial": unknown[0], "kind": "unknown", "from": source})
    return reads


def decide(reads, family_reads, release_of, family_readers=0, title=None, by_title=None):
    """(serial, release id, decided_by) from a label photo's reads, its family's own exact reads (Counter of release
    ids, its own left out: how many members read each), how many of its other members read anything serial-like,
    title(release id) -> how much of its title the label's text holds, and by_title: (release id, serial) found by
    title alone, or None."""
    title = title or (lambda rid: 0.0)
    rel = lambda s: serials.release(s, release_of)["id"]
    exact = [r for r in reads if r["kind"] == "exact"]
    # an exact read that's the start of another (a cut-off read: DMG-VF of DMG-VFJ, DMG-BQ of DMG-BQIJ) gives way to it
    codes = lambda s: s[:-4] if serials.region_of(s) else s  # the region dropped only if it is one (not DMG-VFJ's code)
    exact = [r for r in exact if not any(o is not r and codes(o["serial"]) != codes(r["serial"]) and
                                         codes(o["serial"]).startswith(codes(r["serial"])) for o in exact)] or exact
    if exact:
        by_release = Counter(rel(r["serial"]) for r in exact)
        if len(by_release) == 1:
            r = exact[0]
            return r["serial"], rel(r["serial"]), "own"
        best = max(by_release, key=lambda k: (title(k) >= TITLE_SEEN, family_reads.get(k, 0), title(k), by_release[k]))
        r = next(r for r in exact if rel(r["serial"]) == best)
        return r["serial"], best, "own, with its title or family"
    near = [r for r in reads if r["kind"] == "near"]
    if near:
        supported = [r for r in near if family_reads.get(rel(r["serial"]), 0) > 0 or title(rel(r["serial"])) >= TITLE_SEEN]
        if supported or len({r["serial"] for r in near}) == 1:
            r = max(supported or near, key=lambda r: title(rel(r["serial"])))
            return r["serial"], rel(r["serial"]), "near"
    if len(family_reads) == 1 and next(iter(family_reads.values())) > family_readers / 2:
        # more than half the members reading anything serial-like agree (a cut-off serial that's a real release, read
        # by one, isn't passed on to those reading something else: DMG-BQ for DMG-BQIJ)
        release = next(iter(family_reads))
        return None, release, "family"
    if by_title:
        return by_title[1], by_title[0], "title"
    unknown = [r for r in reads if r["kind"] == "unknown"]
    if unknown:
        return unknown[0]["serial"], None, "unknown"
    return None, None, "unknown"


# Titles: the label's text (all of the straightened label photo's lines, and the photo's lines within the label
# photo's circle) against the database's titles (serials.title_score). A title counts as seen at TITLE_SEEN. Found by
# title alone (no exact or near serial): the best match at TITLE_FOUND or more, of a title of at least 5 characters,
# among the shape's platforms; one release, or the one of the best's game whose region a serial-looking read gives;
# else the game is recorded ("title_game"), not a release.
TITLE_SEEN = 0.5
TITLE_FOUND = 0.7
SYSTEMS = {"dmg": {"dmg", "cgb"}, "cgb": {"cgb"}, "agb": {"agb"}}


def find_by_title(text_plain, shape, reads, index, release_of):
    """((release id, serial) or None, the best match's game or None)."""
    found = index.search(text_plain, SYSTEMS.get(shape)) if text_plain else []
    found = [(sc, r) for sc, r in found if sc >= TITLE_FOUND and len(serials.plain(r["title"])) >= 5]
    if not found:
        return None, None
    top = found[0][0]
    best = [r for sc, r in found if sc >= top - 0.05]
    game = best[0]["gameId"][:7]
    if len({r["id"] for r in best}) == 1:
        r = best[0]
    else:
        regions = {serials.region_of(x["serial"]) for x in reads if x["serial"]}
        pick = [r for r in best if any(s.endswith("-" + g) for s in serials.cartridge_serials(r) for g in regions if g)]
        if len(pick) != 1:
            return None, game
        r = pick[0]
    serial = (serials.cartridge_serials(r) or [r["id"]])[0]
    return (r["id"], serial), game


def page(out_dir, result, missing, unknown, gen):
    decided = Counter(v["decided_by"] for v in result.values())
    with_release = sum(1 for v in result.values() if v["release"])
    rel = os.path.relpath(os.path.join(gen, "straighten"), out_dir)
    doubtful = [(k, v) for k, v in result.items() if v["decided_by"] != "own"]
    figs = []
    for k, v in steps.few(doubtful):
        reads = "<br>".join(html.escape(r["from"] + ": " + r["text"]) for r in v["reads"]) or "<i>no reads</i>"
        figs.append(f'<figure><img loading="lazy" src="{rel}/{straighten.file_name(k)}"><figcaption><code>{html.escape(k[:14])}</code> '
                    f'<b>{html.escape(str(v["serial"] or v["release"]))}</b> ({html.escape(v["decided_by"])})<br>{reads}</figcaption></figure>')
    figs = "".join(figs)
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>read-serials</title>
<style>body{{font:14px system-ui;margin:16px;background:#333;color:#eee}} figure{{display:inline-block;margin:6px;vertical-align:top;width:280px}} img{{width:280px}} figcaption{{font-size:11px}}</style>
<h1>read-serials</h1>
<p>{len(result)} label photos; a release the database knows for {with_release}. Decided by: {", ".join(f"{k} {n}" for k, n in decided.most_common())}. Database entries with no label photo: {len(missing)}. Serial-looking strings the database doesn't know: {len(unknown)} ({html.escape(", ".join(sorted(unknown)[:30]))}).</p>
<h2>Not decided by their own reads alone ({steps.shown(len(doubtful))})</h2>{figs}""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    gen = photos.generated(args.sample)
    solve_file, find_file = os.path.join(gen, "solve", "solve.json"), os.path.join(gen, "find", "label-photos.json")
    for p in (solve_file, find_file):
        if not os.path.exists(p):
            sys.exit(f"{p} missing: run make find, solve and straighten first")
    solved = json.load(open(solve_file))["label_photos"]
    found = {lp["key"]: lp for lp in json.load(open(find_file))["label_photos"]}
    out_dir = os.path.join(gen, "read-serials")
    ocr_dir = os.path.join(out_dir, "ocr")
    os.makedirs(ocr_dir, exist_ok=True)
    images = {k: os.path.join(gen, "straighten", straighten.file_name(k)) for k in solved}
    missing_images = [k for k, p in images.items() if not os.path.exists(p)]
    if missing_images:
        sys.exit(f"{len(missing_images)} straightened images missing: run make straighten first")
    ocr_out = {k: os.path.join(ocr_dir, straighten.file_name(k)[:-5] + ".json") for k in solved}
    keep = {os.path.basename(f) for p in ocr_out.values() for f in (p, fit_file(p))}
    for f in os.listdir(ocr_dir):
        if f not in keep:
            os.remove(os.path.join(ocr_dir, f))
    code_time = os.path.getmtime(read_text.__file__)
    jobs = [(images[k], ocr_out[k], solved[k]["photo_to_ink"]) for k in solved if reread(ocr_out[k], solved[k], code_time)]
    threads = max(1, (os.cpu_count() or 4) // args.workers)
    steps.run(ocr_job, jobs, args.workers, read_text.init_worker, (threads,), "straightened label photos read:")
    out = os.path.join(out_dir, "serials.json")
    newest = max(os.path.getmtime(p) for p in [solve_file, find_file, __file__] + list(ocr_out.values()) +
                 ([CORRECTIONS] if os.path.exists(CORRECTIONS) else []))
    release_of = serials.load_database()
    if not os.path.exists(out) or os.path.getmtime(out) < newest:
        regions = serials.by_region(release_of)
        index = serials.TitleIndex(json.load(open(serials.DATABASE)))
        by_id = {}
        for r_ in release_of.values():
            by_id.setdefault(r_["id"], r_)
        ocr = {k: json.load(open(ocr_out[k])) for k in solved}
        strings = lambda k: [t for m in [k] + solved[k].get("merged", []) for t in found.get(m, {}).get("strings", [])]  # merged: the same sticker
        reads = {k: own_reads(ocr[k], strings(k), release_of, regions, solved[k]["shape"]) for k in solved}
        photo_lines = {}
        def label_text(k):
            lp = found.get(k)
            lines = [l["text"] for l in ocr[k]]
            if lp is not None:
                if lp["photo"] not in photo_lines:
                    photo_lines[lp["photo"]] = json.load(open(os.path.join(gen, "read-text", lp["photo"] + ".json")))["lines"]
                c, rad = lp["centre"], lp["radius"]
                for l in photo_lines[lp["photo"]]:
                    m = [sum(p[0] for p in l["corners"]) / 4, sum(p[1] for p in l["corners"]) / 4]
                    if (m[0] - c[0]) ** 2 + (m[1] - c[1]) ** 2 < rad ** 2:
                        lines.append(l["text"])
            return serials.plain(" ".join(lines))
        family_of = {k: v["family"] for k, v in solved.items()}
        own_release = {k: Counter(serials.release(r["serial"], release_of)["id"] for r in rs if r["kind"] == "exact") for k, rs in reads.items()}
        result = {}
        for k in solved:
            fam, readers = Counter(), 0
            for o, f in family_of.items():
                if f == family_of[k] and o != k:
                    fam.update({rid: 1 for rid in own_release[o]})
                    readers += bool(reads[o])
            text = label_text(k)
            title = lambda rid, text=text: serials.title_score(by_id[rid], text) if rid in by_id else 0.0
            has_serial = bool(reads[k]) or bool(fam)  # title search only where nothing serial-like is read: a clear
            # serial the database lacks (AGB-ATUJ-JPN) is a possible new release, not to be replaced by another region's
            by_title, game = (None, None) if has_serial else find_by_title(text, solved[k]["shape"], reads[k], index, release_of)
            serial, release, how = decide(reads[k], fam, release_of, readers, title)
            result[k] = {"reads": reads[k], "serial": serial, "release": release, "decided_by": how, "family": family_of[k],
                         "title_score": round(title(release), 2) if release else None,
                         "title_guess": (by_title[1] if by_title else game) if not release else None}
        corrections = json.load(open(CORRECTIONS)).get("corrections", {}) if os.path.exists(CORRECTIONS) else {}
        for k, serial in corrections.items():
            if k in result:
                r_ = serials.release(serial, release_of)
                result[k].update(serial=serial, release=r_["id"] if r_ else None, decided_by="corrected by hand")
        steps.write_json(out, result)
        covered = {v["release"] for v in result.values() if v["release"]}
        everything = sorted({r["id"] for r in json.load(open(serials.DATABASE))})
        steps.write_json(os.path.join(out_dir, "missing.json"), [r for r in everything if r not in covered])
        unknown = {}
        for k, v in result.items():
            for r in v["reads"]:
                if r["kind"] == "unknown":
                    unknown.setdefault(r["serial"], []).append(k)
        steps.write_json(os.path.join(out_dir, "unknown-serials.json"), {s: sorted(set(ks)) for s, ks in sorted(unknown.items())})
    result = json.load(open(out))
    page(out_dir, result, json.load(open(os.path.join(out_dir, "missing.json"))), json.load(open(os.path.join(out_dir, "unknown-serials.json"))), gen)
    print(f"{sum(1 for v in result.values() if v['release'])} of {len(result)} with a release; page: {os.path.join(out_dir, 'index.html')}")


if __name__ == "__main__":
    main()
