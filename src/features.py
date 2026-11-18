# features: SIFT keypoints of every photo, nothing specific to labels, for any later step, into
# <generated>/features/<sha1>.npz:
#   size (w, h of the photo), scale (the photo's pixels per pixel SIFT saw),
#   points (n x 2, the photo's pixels, its EXIF turn applied), sizes and angles (in the photo's pixels and degrees),
#   responses (strength), descriptors (n x 128, uint8).
# SIFT sees the photo at most MAX_SIDE px on its long side (never scaled up) and keeps at most MAX_KEYPOINTS, the
# strongest; the keypoints are stored in the full photo's pixels.
# Also of every frozen print's image (src/frozen.py), named by the image's SHA-1: match indexes them as if they were
# photos (persistent-prints.md stage 2).
# A photo is done again when its file is missing or older than this file. Files of photos no longer there are removed.
# The page, <generated>/features/index.html: the counts, the photos with the fewest keypoints first.
# Usage: features.py [--sample] [--workers N]
import argparse, os, sys
import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, steps, frozen

MAX_SIDE = 2000
MAX_KEYPOINTS = 8000


def features(image, max_side=MAX_SIDE, max_keypoints=MAX_KEYPOINTS):
    """SIFT keypoints of a BGR image: a dict of the arrays stored (points etc. in the image's own pixels)."""
    h, w = image.shape[:2]
    scale = max(1.0, max(w, h) / max_side)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if scale > 1:
        gray = cv2.resize(gray, (round(w / scale), round(h / scale)), interpolation=cv2.INTER_AREA)
    kp, des = cv2.SIFT_create(nfeatures=max_keypoints).detectAndCompute(gray, None)
    if des is None:
        kp, des = [], np.zeros((0, 128), np.float32)
    # pixel centres: a point x in the small image is at (x + 0.5) * scale - 0.5 in the photo
    pts = np.float32([k.pt for k in kp]).reshape(-1, 2)
    return {"size": np.int32([w, h]), "scale": np.float32(scale),
            "points": ((pts + 0.5) * scale - 0.5).astype(np.float32),
            "sizes": np.float32([k.size * scale for k in kp]), "angles": np.float32([k.angle for k in kp]),
            "responses": np.float32([k.response for k in kp]),
            "descriptors": np.clip(np.round(des), 0, 255).astype(np.uint8)}


def empty():
    return {"size": np.int32([0, 0]), "scale": np.float32(1), "points": np.zeros((0, 2), np.float32),
            "sizes": np.zeros(0, np.float32), "angles": np.zeros(0, np.float32), "responses": np.zeros(0, np.float32),
            "descriptors": np.zeros((0, 128), np.uint8)}


def do_photo(job):
    sha1, path, out = job
    image = photos.load(path)
    steps.write_npz(out, **(features(image) if image is not None else empty()))
    return sha1


def page(out_dir, chosen):
    counts = []
    for sha1, path in chosen.items():
        f = np.load(os.path.join(out_dir, sha1 + ".npz"))
        counts.append((len(f["points"]), sha1, path, tuple(f["size"])))
    counts.sort()
    n = np.array([c[0] for c in counts]) if counts else np.zeros(1)
    rel = os.path.relpath(".", out_dir)
    rows = "\n".join(f'<tr><td>{c}</td><td><code>{s[:10]}</code><br>{w} x {h}</td>'
                     f'<td><a href="{rel}/{p}"><img loading="lazy" src="{rel}/{p}"></a></td></tr>'
                     for c, s, p, (w, h) in steps.few(counts))
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>features</title>
<style>body{{font:14px system-ui;margin:16px}} img{{max-width:240px;max-height:240px}} td{{vertical-align:top;padding:4px 8px;border-top:1px solid #ccc}}</style>
<h1>features</h1>
<p>{len(counts)} photos. Keypoints per photo: fewest {int(n.min())}, 10 % below {int(np.percentile(n, 10))}, median {int(np.median(n))}, most {int(n.max())}; {int((n >= MAX_KEYPOINTS).sum())} photos at the cap of {MAX_KEYPOINTS}. SIFT sees at most {MAX_SIDE} px across.</p>
<h2>Fewest keypoints (100)</h2><table><tr><th>keypoints</th><th>photo</th><th></th></tr>{rows}</table>
""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    chosen = photos.chosen(args.sample)
    out_dir = os.path.join(photos.generated(args.sample), "features")
    os.makedirs(out_dir, exist_ok=True)
    images = {s: path for s, (_, path) in frozen.images().items()}  # frozen prints' images, matched as photos
    steps.remove_orphans(out_dir, {**chosen, **images}, ".npz")
    jobs = [(s, p, os.path.join(out_dir, s + ".npz")) for s, p in {**chosen, **images}.items()]
    steps.run(do_photo, [j for j in jobs if steps.stale(j[2], __file__)], args.workers, what="features of")
    page(out_dir, chosen)
    print(f"page: {os.path.join(out_dir, 'index.html')}")


if __name__ == "__main__":
    main()
