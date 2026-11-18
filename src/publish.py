# publish (make build): the outputs collected into the folder given (generated/publish; make publish pushes it to gh-pages):
#   prints/<print>.avif: each restored print, restore's image as it is (paper white where found, else median colours),
#     named by the print's persistent id (it starts with the serial: DMG-APSJ-JPN-lisa.avif)
#   No label photo images (the user, 2026-11-10: the straightened photos aren't worth distributing, over 1 GB): each
#     label photo is in index.json, with where it came from. Poor fits (solve.poor_fit) are listed with
#     poor_fit true; restore leaves them out.
#   index.json: {"prints": {id: {serial, release, title (the database's), shape, image, size (its w, h px), paper,
#     label_photos, frozen, restored_from (the label photos its image was restored from)}}, "label_photos": {key: {print,
#     serial, source, page_url, image_url, poor_fit}}}. Print ids persist between runs (print-ids.json); keys hold within a run only.
#   missing.json, unknown-serials.json (read-serials), few-photos.json (prints): the lists, copied as they are.
#   wanted.html, wanted.json: the prints that need photos (src/wanted.py), linked from index.html.
#   index.html: per platform (linked from the top, with its image count) every print with an image, by game title,
#     with its label photos' sources.
# Prints of a single label photo (poor fits counted) are left out, with their label photo (the user, 2026-11-15).
# The source and URLs come from photo-sources.json (by SHA-1): for output only, never read by a detection step.
# The folder starts empty (make build removes it first), so every file is written anew.
# Usage: publish.py [--sample] OUT
import argparse, html, json, os, re, shutil, sys
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, steps, shapes, straighten, frozen, wanted
import prints as prints_step
import serials as serials_module

SOURCES = "photo-sources.json"
QUALITY = straighten.QUALITY
LISTS = [("read-serials", "missing.json"), ("read-serials", "unknown-serials.json"), ("prints", "few-photos.json")]


def crop_box(shape, crop=None):
    """The crop in a straightened image: x, y, w, h in whole pixels (restore's crop, else the canonical label)."""
    if crop:
        return crop["x"], crop["y"], crop["w"], crop["h"]
    lw, lh = shapes.LABEL_MM[shape]
    m = round(straighten.MARGIN * straighten.PX_PER_MM)
    return m, m, round(lw * straighten.PX_PER_MM), round(lh * straighten.PX_PER_MM)


def cut(img, shape, crop=None):
    x, y, w, h = crop_box(shape, crop)
    return img[y:y + h, x:x + w]


def sources(path=SOURCES):
    """SHA-1 -> {source, page_url, image_url}, from photo-sources.json (src/add_photos.py)."""
    return {k: {"source": e.get("source"), "page_url": e.get("page_url"), "image_url": e.get("image_url")}
            for k, e in json.load(open(path)).items()}


def poor_fits(solved):
    import solve as solve_step
    return {k for k, r in solved.items() if solve_step.poor_fit(r)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("out", help="the folder to write to")
    args = ap.parse_args()
    gen = photos.generated(args.sample)
    need = [os.path.join(gen, "prints", "prints.json"), os.path.join(gen, "solve", "solve.json"),
            os.path.join(gen, "read-serials", "serials.json"), os.path.join(gen, "restore", "index.html")]
    for f in need:
        if not os.path.exists(f):
            sys.exit(f"no {f}: run the steps before publish")
    prints = json.load(open(need[0]))
    solved = json.load(open(need[1]))["label_photos"]
    serials = json.load(open(need[2]))
    src = sources()
    titles = {r["id"]: r["title"] for r in json.load(open(serials_module.DATABASE))}
    poor = poor_fits(solved)
    out_dir = args.out
    os.makedirs(os.path.join(out_dir, "prints"), exist_ok=True)

    index = {"prints": {}, "label_photos": {}}
    copies = []
    frozen_entries = frozen.load()
    single, has_image = 0, set()
    for p in prints["prints"]:
        name = straighten.file_name(p["id"])
        if os.path.exists(os.path.join(gen, "restore", name)) or (p.get("frozen") in frozen_entries and os.path.exists(frozen.image_path(p["frozen"]))):
            has_image.add(p["id"])
        if len(p["keys"]) < 2:  # a single label photo: not published
            single += 1
            continue
        restored = os.path.join(gen, "restore", name)
        desc_file = restored[:-5] + ".json"
        desc = json.load(open(desc_file)) if os.path.exists(desc_file) else {}
        if p.get("frozen") in frozen_entries:  # the frozen image, as it is
            restored = frozen.image_path(p["frozen"])
            e = frozen_entries[p["frozen"]]
            desc = {"crop": e["crop"], "keys": e["restored_from"], "paper": e.get("paper")}
        image = None
        if os.path.exists(restored):
            image = "prints/" + name  # the id starts with the serial
            copies.append((restored, os.path.join(out_dir, image)))
        crop = desc.get("crop") or {}
        index["prints"][p["id"]] = {"serial": p["serial"], "release": p["release"], "title": titles.get(p["release"]),
                                    "shape": p["shape"], "image": image,
                                    "size": [crop["w"], crop["h"]] if image and crop else None,
                                    "paper": desc.get("paper") is not None if desc else None, "label_photos": p["keys"],
                                    "frozen": bool(p.get("frozen")), "restored_from": desc.get("keys")}
        for k in p["keys"]:
            sha1 = k.split("@")[0]
            s = src.get(sha1, {})
            index["label_photos"][k] = {"print": p["id"], "serial": (serials.get(k) or {}).get("serial"),
                                        "source": s.get("source"), "page_url": s.get("page_url"),
                                        "image_url": s.get("image_url"), "poor_fit": k in poor}

    for a, b in copies:
        shutil.copyfile(a, b)
    for step, f in LISTS:
        if os.path.exists(os.path.join(gen, step, f)):
            shutil.copyfile(os.path.join(gen, step, f), os.path.join(out_dir, f))
    steps.write_json(os.path.join(out_dir, "index.json"), index)
    differences = {}
    for name, tiles in prints_step.load_pairs(os.path.join(gen, "prints", "pairs.npz"), prints_step.comparison_version()).items():
        a, b = name.split("|")[:2]
        differences[a, b] = differences[b, a] = int(tiles.sum())
    releases = {r["id"]: r for r in json.load(open(serials_module.DATABASE))}
    wanted_list = wanted.entries(prints["prints"], has_image, solved, serials, releases, src, differences)
    steps.write_json(os.path.join(out_dir, "wanted.json"), wanted_list)
    wanted.page(out_dir, wanted_list)
    page(out_dir, index, len(wanted.games(wanted_list)))  # the rows of wanted.html: one per game and region group
    print(f"{single} prints of a single label photo left out")
    print(f"{len(copies)} prints, {len(index['label_photos'])} label photos listed ({len(poor & set(index['label_photos']))} poor fits)")
    print(f"{len(wanted_list)} prints wanted (wanted.html)")
    print(f"page: {os.path.join(out_dir, 'index.html')}")


PLATFORMS = [("dmg", "Game Boy"), ("cgb", "Game Boy Color"), ("agb", "Game Boy Advance")]
MIN_COLUMN = 260  # px: the grid's columns at least this wide, as many as fit, stretched to the page's width


def page(out_dir, index, wanted_count):
    """index.html: per platform (linked from the top, with its image count, and the total) the prints with an image, by game title
    (prints without one last, by serial), in a grid of as many columns as fit (MIN_COLUMN); each image at most half
    its pixel width wide, so it shows at 2x pixel density or more."""
    lp = index["label_photos"]
    used = lambda p: sum(1 for k in p["label_photos"] if not lp[k]["poor_fit"])  # poor fits aren't used
    shown = [p for p in index["prints"].values() if p["image"]]
    order = lambda p: (p["title"] is None, (p["title"] or "").casefold(), str(p["serial"] or p["release"] or ""))
    sections, links = [], []
    for shape, platform in PLATFORMS:
        ps = sorted((p for p in shown if p["shape"] == shape), key=order)
        figs = []
        for p in ps:
            sources = ", ".join(
                (f'<a href="{html.escape(lp[k]["page_url"] or lp[k]["image_url"])}">{html.escape(lp[k]["source"] or "?")}</a>'
                 if lp[k]["page_url"] or lp[k]["image_url"] else html.escape(lp[k]["source"] or "?"))
                + (' <span class="poor">(poor fit)</span>' if lp[k]["poor_fit"] else "") for k in p["label_photos"])
            w = (p.get("size") or [680])[0] / 2
            figs.append(f'<figure><img loading="lazy" src="{p["image"]}" style="max-width:{w:.0f}px">'
                        f'<figcaption><b>{html.escape(p["title"] or "(no title)")}</b><br>{html.escape(str(p["serial"] or p["release"] or "?"))}, '
                        f'Recreated from {used(p)} photo{"" if used(p) == 1 else "s"}'
                        f'<div class="src">{sources}</div></figcaption></figure>')
        links.append(f'<li><a href="#{shape}">{platform}</a>: {len(ps)} images</li>')
        sections.append(f'<h2 id="{shape}">{platform} ({len(ps)})</h2><div class="grid">{"".join(figs)}</div>')
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>publish</title>
<style>body{{font:14px system-ui;margin:16px;background:#333;color:#eee}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax({MIN_COLUMN}px,1fr));gap:16px;align-items:start}}
figure{{margin:0;min-width:0}} figure img{{display:block;width:100%;height:auto;margin:0 auto}} figcaption{{font-size:12px;margin:4px 0}}
.src{{font-size:11px;color:#bbb;margin-top:2px}} .poor{{color:#fa0}} a{{color:#9cf}} h2{{margin-top:32px}}</style>
<p><a href="wanted.html">Wanted photos</a>: help find photos of {wanted_count} cartridges</p>
<ul>{"".join(links)}<li>Total: {sum(1 for p in shown if p["shape"] in dict(PLATFORMS))} images</li></ul>
{"".join(sections)}""")


if __name__ == "__main__":
    main()
