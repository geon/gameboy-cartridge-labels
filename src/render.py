import concurrent.futures, hashlib, io, json, os, re, sys, cv2, numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import color, fits, photos, serials
from cartridge import SHELLS, project, shell_of
from fit_cartridge import load

# render-labels and render-carts: one image per release, straightened (perspective removed through its fits) and with
# its colors set by its own settings (src/color.py; colors.json, make fit-colors, make adjust-colors), as AVIF:
#   labels: generated/render-labels/<release>.avif, the label alone, stretched to its shell's canonical label
#     size at LABEL_PX_PER_MM (the labels' size varies a few tenths of a mm: their fits' model corners are mapped to the
#     image's corners);
#   carts: generated/render-carts/<release>.avif, the cartridge's front with CART_MARGIN mm around it, at
#     CART_PX_PER_MM: meant as the canonical images of the cartridges; where the margin runs off the photo, transparent.
# The release's photo: its preferred one (preferred.json, chosen in find-doubles) if the fit the image needs (the label
# for labels, the plastic for carts) is accepted or placed by hand, else the best one by source (photos.SOURCES) whose
# fit is; the fakes (photos.FAKES) never. A release with no such photo gets no image. So a release's label and cart
# come from different photos while its preferred photo's label isn't accepted. Each step's made.json records what each image was made from (the photo's
# SHA-1, the fits, its color settings, this code's version); an image is made again when any of it changes, and those of releases no
# longer rendered are removed.
# Usage: render.py labels|carts
# The labels' scale: 4.7 px per mm, the same for both shells, so that their images keep the labels' sizes to each other.
# Each label is rendered at its shell's canonical label size (cartridge.LABEL, CGB_LABEL), rounded to whole pixels:
# DMG 42.5 x 37 mm -> 200 x 174 px (199.75 x 173.9), CGB 41.5 x 37 -> 195 x 174 (195.05 x 173.9). Chosen to put the
# DMG's at 200 px wide with little rounding: no scale near it gives both shells whole pixels (only even px per mm do:
# 4, 170 x 148 and 166 x 148, too small; 6, 255 x 222, too big).
LABEL_PX_PER_MM = 4.7
CART_MARGIN = 5.0
# The cartridge images' scale: 20 px per mm, 1340 x 1500 px. Measured on the photos render-carts uses (1402,
# 2026-11-03): the cartridge is seen at a median 18 px per mm (Hit-Japan 20, jnlgame 19, my own 43, otakaraou 10);
# 33 % have 20 or more, 61 % 15, 82 % 10. So the best sources keep their detail; the others are enlarged.
CART_PX_PER_MM = 20
# AVIF through Pillow, not OpenCV: OpenCV's encoder always halves the color's resolution (4:2:0), which smears colored
# text at this size, whatever the quality (ΔE 99th percentile about 14 at quality 95). Measured on 16 labels against
# lossless (2026-11-02), 4:4:4: quality 80 13.6 KB, ΔE median 2.1, 99th percentile 8.2; 90 18.6 KB, 1.7, 6.1;
# 95 25.8 KB, 1.3, 4.3.
# On 8 cartridge images (1340 x 1500 px, 2026-11-03): quality 75 159 KB, ΔE 1.2, 3.8; 80 189 KB, 1.1, 3.6; 90 302 KB, 1.0, 3.1.
QUALITY = 90
# Drawn at SUPERSAMPLE times the scale, from the photo shrunk to at most twice that, then shrunk by area: every output
# pixel the mean of the photo under it, not a sample of it. Less for the carts, whose image is large.
SUPERSAMPLE = {"labels": 4, "carts": 2}
OUT = {"labels": "generated/render-labels", "carts": "generated/render-carts"}
CODE = hashlib.sha1(b"".join(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f), "rb").read()
                             for f in ("render.py", "color.py"))).hexdigest()


def chosen(kind):
    """Each release's photo to render for kind (labels or carts): release id -> (stem, path, sha1, shell name, plastic and
    label homographies; the label None for carts)."""
    release_of, known, preferred, colors = serials.releases_by_serial(), fits.load(), photos.load_preferred(), color.load_colors()
    candidates = {}
    for source, system, name, entry in photos.all_sources():
        if source in photos.FAKES:
            continue
        stem, sha1 = photos.stem(name), entry.get("sha1")
        fit = fits.of(known, stem, sha1)["fit"]
        if not fits.good(fit.get("plastic")) or kind == "labels" and not fits.good(fit.get("label")):
            continue
        serial = photos.serial_of(name)
        release = serials.release_key(name, release_of)[0]
        candidates.setdefault(release, []).append((preferred.get(release) != sha1, photos.rank(source), name, stem,
                                                   os.path.join(photos.ROOT, source, system, name), sha1, shell_of(serial).name,
                                                   fit["plastic"]["mm_to_photo"], fit["label"]["mm_to_photo"] if kind == "labels" else None,
                                                   settings_of(colors, stem, sha1)))
    return {release: min(c)[3:] for release, c in candidates.items()}


def settings_of(colors, stem, sha1):
    """A photo's color settings (without their source), or None."""
    found = color.colors_of(colors, stem, sha1)
    return {k: found[k] for k in color.SETTINGS} if found else None


def frame(H, box, size, supersample):
    """The photo's pixels, H mapping mm to them, rendered for box (x0, y0, x1, y1, mm) into size (w, h px): a homography
    from the supersampled image's pixels to the photo's."""
    (x0, y0, x1, y1), (w, h) = box, size
    sx, sy = (x1 - x0) / (w * supersample), (y1 - y0) / (h * supersample)
    return np.asarray(H, np.float64) @ np.array([[sx, 0, x0 + sx / 2], [0, sy, y0 + sy / 2], [0, 0, 1]])


def rendered(photo, M, size, supersample, alpha=False):
    """The photo seen through M (the supersampled image's pixels -> the photo's), size px (w, h); with alpha, its
    pixels off the photo transparent (BGRA)."""
    w, h = size[0] * supersample, size[1] * supersample
    c = project(M, [[w / 2, h / 2], [w / 2 + 1, h / 2], [w / 2, h / 2 + 1]])
    (ax, ay), (bx, by) = c[1] - c[0], c[2] - c[0]
    photo_px = np.sqrt(abs(ax * by - ay * bx))  # photo px per supersampled px, at the middle
    if photo_px > 2:
        shrink = 2 / photo_px
        photo = cv2.resize(photo, None, fx=shrink, fy=shrink, interpolation=cv2.INTER_AREA)
        M = np.array([[shrink, 0, (shrink - 1) / 2], [0, shrink, (shrink - 1) / 2], [0, 0, 1]]) @ M
    if alpha:
        photo = np.dstack([photo, np.full(photo.shape[:2], 255, np.uint8)])
    big = cv2.warpPerspective(photo, M, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return cv2.resize(big, size, interpolation=cv2.INTER_AREA)


def label_image(photo, shell, label_H):
    model = SHELLS[shell].label
    size = (round((model[2] - model[0]) * LABEL_PX_PER_MM), round((model[3] - model[1]) * LABEL_PX_PER_MM))
    return rendered(photo, frame(label_H, model, size, SUPERSAMPLE["labels"]), size, SUPERSAMPLE["labels"])


def cart_image(photo, shell, plastic_H):
    w, h = SHELLS[shell].body
    box = (-CART_MARGIN, -CART_MARGIN, w + CART_MARGIN, h + CART_MARGIN)
    size = (round((box[2] - box[0]) * CART_PX_PER_MM), round((box[3] - box[1]) * CART_PX_PER_MM))
    return rendered(photo, frame(plastic_H, box, size, SUPERSAMPLE["carts"]), size, SUPERSAMPLE["carts"], alpha=True)


def render(kind, release, path, shell, plastic_H, label_H, settings, out):
    photo = color.adjusted(load(path), settings)
    image = label_image(photo, shell, label_H) if kind == "labels" else cart_image(photo, shell, plastic_H)
    data = io.BytesIO()
    Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA if image.shape[2] == 4 else cv2.COLOR_BGR2RGB)).save(
        data, "AVIF", quality=QUALITY, subsampling="4:4:4", speed=4)
    open(out + ".tmp", "wb").write(data.getvalue())
    os.replace(out + ".tmp", out)
    return release


def file_of(release):
    return re.sub(r"[^A-Za-z0-9._()\[\]-]", "_", release) + ".avif"


def main(kind):
    folder = OUT[kind]
    os.makedirs(folder, exist_ok=True)
    made_path = os.path.join(folder, "made.json")
    made = json.load(open(made_path)) if os.path.exists(made_path) else {}
    photo_of = chosen(kind)
    want = {release: {"photo": stem, "sha1": sha1, "shell": shell, "pose": plastic_H if kind == "carts" else label_H, "colors": settings, "code": CODE}
            for release, (stem, path, sha1, shell, plastic_H, label_H, settings) in photo_of.items()}
    for release in set(made) - set(want):
        if os.path.exists(os.path.join(folder, file_of(release))):
            os.remove(os.path.join(folder, file_of(release)))
        del made[release]
    todo = [r for r in sorted(want) if made.get(r) != want[r] or not os.path.exists(os.path.join(folder, file_of(r)))]
    print(f"{len(want)} releases, {len(todo)} to render into {folder}/")
    with concurrent.futures.ProcessPoolExecutor() as pool:
        jobs = [pool.submit(render, kind, r, *photo_of[r][1:2], *photo_of[r][3:], os.path.join(folder, file_of(r))) for r in todo]
        for n, job in enumerate(concurrent.futures.as_completed(jobs), 1):
            try:
                release = job.result()
                made[release] = want[release]
            except Exception as e:
                print(f"  failed: {e}")
            if n % 100 == 0 or n == len(jobs):
                print(f"  {n}/{len(jobs)}")
                open(made_path, "w").write(json.dumps(made, indent=0, sort_keys=True))
    open(made_path, "w").write(json.dumps(made, indent=0, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in OUT:
        sys.exit("Usage: render.py labels|carts")
    main(sys.argv[1])
