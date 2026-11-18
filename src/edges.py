# edges: every straight line segment and outline quadrilateral in every photo, nothing specific to labels (which are
# a cut, a recess or the body is decided later), into <generated>/edges/<sha1>.npz:
#   size (w, h of the photo), scale (the photo's pixels per pixel LSD saw),
#   segments (n x 4: x1, y1, x2, y2 in the photo's pixels, its EXIF turn applied; the darker side on the right as it
#   runs, with y down), widths (in the photo's pixels), strength (-log10 of LSD's number of false alarms: higher is
#   surer), quads (m x 4 x 2: outline quadrilaterals, src/outlines.py, ported from main).
# OpenCV's LSD (line segment detector, refined), on the photo at most MAX_SIDE px on its long side (as features);
# segments shorter than MIN_LENGTH px there are left out.
# A photo is done again when its file is missing or older than this file. Files of photos no longer there are removed.
# The page, <generated>/edges/index.html: the counts, and the longest segments drawn on some photos.
# Usage: edges.py [--sample] [--workers N]
import argparse, os, sys
import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, steps, outlines

MAX_SIDE = 2000
MIN_LENGTH = 10


def segments(image, max_side=MAX_SIDE, min_length=MIN_LENGTH):
    """LSD's segments of a BGR image: a dict of the arrays stored (in the image's own pixels)."""
    h, w = image.shape[:2]
    scale = max(1.0, max(w, h) / max_side)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if scale > 1:
        gray = cv2.resize(gray, (round(w / scale), round(h / scale)), interpolation=cv2.INTER_AREA)
    lines, widths, _, nfa = cv2.createLineSegmentDetector(cv2.LSD_REFINE_ADV).detect(gray)
    if lines is None:
        return empty((w, h), scale)
    lines, widths, nfa = lines.reshape(-1, 4), widths.ravel(), nfa.ravel()
    keep = np.hypot(lines[:, 2] - lines[:, 0], lines[:, 3] - lines[:, 1]) >= min_length
    return {"size": np.int32([w, h]), "scale": np.float32(scale),
            "segments": ((lines[keep] + 0.5) * scale - 0.5).astype(np.float32),
            "widths": (widths[keep] * scale).astype(np.float32), "strength": nfa[keep].astype(np.float32)}


def empty(size=(0, 0), scale=1.0):
    return {"size": np.int32(size), "scale": np.float32(scale), "segments": np.zeros((0, 4), np.float32),
            "widths": np.zeros(0, np.float32), "strength": np.zeros(0, np.float32)}


def do_photo(job):
    sha1, path, out = job
    image = photos.load(path)
    if image is None:
        steps.write_npz(out, **empty(), quads=np.zeros((0, 4, 2), np.float32))
        return sha1
    quads = outlines.outline_quads(image)
    steps.write_npz(out, **segments(image), quads=np.float32(quads).reshape(-1, 4, 2))
    return sha1


def page(out_dir, chosen, drawn=steps.PAGE_FIGURES):
    counts = []
    for sha1, path in chosen.items():
        f = np.load(os.path.join(out_dir, sha1 + ".npz"))
        counts.append((len(f["segments"]), sha1, path))
    n = np.array([c[0] for c in counts]) if counts else np.zeros(1)
    rel = os.path.relpath(".", out_dir)
    figures = []
    for _, sha1, path in counts[:drawn]:
        f = np.load(os.path.join(out_dir, sha1 + ".npz"))
        w, h = f["size"]
        seg = f["segments"]
        longest = seg[np.argsort(-np.hypot(seg[:, 2] - seg[:, 0], seg[:, 3] - seg[:, 1]))[:300]]
        lines = "".join(f'<line x1="{a:.0f}" y1="{b:.0f}" x2="{c:.0f}" y2="{d:.0f}"/>' for a, b, c, d in longest)
        figures.append(f'<figure><div class="ph"><img loading="lazy" src="{rel}/{path}"><svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
                       f'<g stroke="#f0f" stroke-width="{max(w, h) / 400:.1f}">{lines}</g></svg></div><figcaption><code>{sha1[:10]}</code> {len(seg)} segments</figcaption></figure>')
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"""<!doctype html><meta charset="utf-8"><title>edges</title>
<style>body{{font:14px system-ui;margin:16px}} figure{{display:inline-block;margin:6px;vertical-align:top}}
.ph{{position:relative;display:inline-block}} .ph img{{max-width:300px;max-height:300px;display:block}} .ph svg{{position:absolute;inset:0;width:100%;height:100%}}</style>
<h1>edges</h1>
<p>{len(counts)} photos. Segments per photo: fewest {int(n.min())}, median {int(np.median(n))}, most {int(n.max())}. LSD sees at most {MAX_SIDE} px across; segments under {MIN_LENGTH} px there left out.</p>
<h2>The 300 longest segments of {min(drawn, len(counts))} photos</h2>{"".join(figures)}
""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    chosen = photos.chosen(args.sample)
    out_dir = os.path.join(photos.generated(args.sample), "edges")
    os.makedirs(out_dir, exist_ok=True)
    steps.remove_orphans(out_dir, chosen, ".npz")
    jobs = [(s, p, os.path.join(out_dir, s + ".npz")) for s, p in chosen.items()]
    steps.run(do_photo, [j for j in jobs if steps.stale(j[2], __file__)], args.workers, what="edges of")
    page(out_dir, chosen)
    print(f"page: {os.path.join(out_dir, 'index.html')}")


if __name__ == "__main__":
    main()
