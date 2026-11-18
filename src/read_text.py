# read-text: the text on every photo, read by RapidOCR (PP-OCR's models as ONNX; better than Apple Vision on the sample,
# label-detection.md), into <generated>/read-text/<sha1>.json:
#   {"size": [w, h], "engine": "rapidocr <version>",
#    "lines": [{"text", "confidence", "corners": [[x, y] x 4]}]}
# The corners are in the photo's pixels (its EXIF turn applied), in reading order: where the text starts at its top,
# then along the text, so they also give its turn. RapidOCR's own boxes don't (always the box's top left first), so its
# 180° classifier is run on each line once more: a line taller than wide (as RapidOCR crops it) reads top down unless
# the classifier turns it.
# A photo is read again when its file is missing or older than this file. Files of photos no longer there are removed.
# The page, <generated>/read-text/index.html: the photos with no serial-looking string first, then those whose serials
# the database doesn't know.
# Usage: read_text.py [--sample] [--workers N]
import argparse, html, json, os, sys
from importlib.metadata import version
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, serials, steps

CLS_THRESHOLD = 0.9  # RapidOCR's own (Cls.cls_thresh): below it, a line isn't turned
_engine = None


def engine(threads=None):
    global _engine
    if _engine is None:
        from rapidocr import RapidOCR
        params = {"Global.log_level": "warning"}
        if threads:
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = threads
        _engine = RapidOCR(params=params)
    return _engine


def reading_order(box, turned):
    """A box's corners (top left, top right, bottom right, bottom left, as RapidOCR gives them) in reading order: a box
    wider than tall reads left to right, one at least 1.5 times as tall as wide (RapidOCR's own rule for turning a crop)
    top down; turned (by the 180° classifier), the other way."""
    box = [list(map(float, p)) for p in box]
    w = max(np.hypot(*np.subtract(box[1], box[0])), np.hypot(*np.subtract(box[2], box[3])))
    h = max(np.hypot(*np.subtract(box[3], box[0])), np.hypot(*np.subtract(box[2], box[1])))
    start = (1 if h >= 1.5 * w else 0) + (2 if turned else 0)
    return box[start:] + box[:start]


def read(image, eng=None):
    """The lines of text on an image (BGR): [{"text", "confidence", "corners"}]."""
    from rapidocr.utils.process_img import get_rotate_crop_image
    eng = eng or engine()
    r = eng(image)
    if r.txts is None or r.boxes is None:
        return []
    crops = [get_rotate_crop_image(image, np.float32(b)) for b in r.boxes]
    classes = eng._load_cls_model()(crops).cls_res
    return [{"text": t, "confidence": round(float(c), 4),
             "corners": [[round(x, 1), round(y, 1)] for x, y in reading_order(b, label == "180" and score > CLS_THRESHOLD)]}
            for t, c, b, (label, score) in zip(r.txts, r.scores, r.boxes, classes)]


def read_photo(job):
    sha1, path, out = job
    image = photos.load(path)
    result = {"size": None, "engine": f"rapidocr {version('rapidocr')}", "lines": []}
    if image is not None:
        result["size"] = [image.shape[1], image.shape[0]]
        result["lines"] = read(image)
    steps.write_json(out, result)
    return sha1


def init_worker(threads):
    engine(threads)


def page(out_dir, chosen, release_of):
    """index.html: the counts, then the photos with no serial-looking string, then those with none the database knows."""
    none, unknown, known = [], [], 0
    for sha1, path in chosen.items():
        lines = json.load(open(os.path.join(out_dir, sha1 + ".json"), encoding="utf-8"))["lines"]
        found = [s for l in lines for s in serials.reads(l["text"])]
        if not found:
            none.append((sha1, path, lines, found))
        elif not any(serials.release(s, release_of) for s in found):
            unknown.append((sha1, path, lines, found))
        else:
            known += 1
    rel = os.path.relpath(".", out_dir)

    def rows(items):
        out = []
        for sha1, path, lines, found in steps.few(items):
            texts = "<br>".join(html.escape(l["text"]) for l in lines) or "<i>no text</i>"
            out.append(f'<tr><td><a href="{rel}/{path}"><img loading="lazy" src="{rel}/{path}"></a></td>'
                       f'<td><code>{sha1[:10]}</code><br>{html.escape(", ".join(found))}</td><td>{texts}</td></tr>')
        return "\n".join(out)

    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>read-text</title>
<style>body{{font:14px system-ui;margin:16px}} img{{max-width:240px;max-height:240px}} td{{vertical-align:top;padding:4px 8px;border-top:1px solid #ccc}}</style>
<h1>read-text</h1>
<p>{len(chosen)} photos: a serial the database knows on {known}; serial-looking strings, none known, on {len(unknown)}; no serial-looking string on {len(none)}.</p>
<h2>No serial-looking string ({steps.shown(len(none))})</h2><table>{rows(none)}</table>
<h2>Serial-looking strings the database doesn't know ({steps.shown(len(unknown))})</h2><table>{rows(unknown)}</table>
""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    chosen = photos.chosen(args.sample)
    out_dir = os.path.join(photos.generated(args.sample), "read-text")
    os.makedirs(out_dir, exist_ok=True)
    steps.remove_orphans(out_dir, chosen, ".json")
    jobs = [(s, p, os.path.join(out_dir, s + ".json")) for s, p in chosen.items()]
    jobs = [j for j in jobs if steps.stale(j[2], __file__)]
    threads = max(1, (os.cpu_count() or 4) // args.workers)
    steps.run(read_photo, jobs, args.workers, init_worker, (threads,), "read")
    page(out_dir, chosen, serials.load_database())
    print(f"page: {os.path.join(out_dir, 'index.html')}")


if __name__ == "__main__":
    main()
