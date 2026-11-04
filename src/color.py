import contextlib, fcntl, json, os, cv2, numpy as np

import photos

# The photos' colors, evened out as they're read (fit_cartridge.load), for the sources that photograph every cartridge
# alike: my own photos and jnlgame's, on a plain white background, have it made white (that sets their exposure and
# white balance alike, as my hand correction of IMG_7324 did); Hit-Japan's (eBay), washed out, get the contrast of my
# hand corrections of nine of them. Other sources' photos are left as they are: elrocinante's background isn't white,
# and one setting for all its photos made them no nearer mine of the same releases. Judged by eye on the labels of all
# these sources' photos (2026-10-30).

# Where the background's white is measured: the frame's outer share on my photos (the cartridge photographed fills the
# middle, neighbouring ones the edges), the whole frame on jnlgame's. Against the band 2-6 mm around the fitted
# cartridge, the white measured so was within 3 % in brightness and 1.3 % in color on half my 187 photos, 10 % and
# 2.6 % on nine in ten; jnlgame's within 4.5 % and 2.1 % on half.
BORDERS = {"my-collection": 0.12, "jnlgame": None}
# What goes above white is rolled off rather than clipped: a pixel's brightest channel, in linear light, compressed
# above KNEE so that TOP times the white comes out white, its channels scaled alike (its hue kept).
KNEE, TOP = 0.8, 1.6
# My hand corrections of nine Hit-Japan photos (2026-10-30), averaged: one tone curve, the same on the three channels,
# sRGB in (the middle of 32 equal steps) to out, 0-255. It darkens the shadows (a black point near 30) and lifts the
# highlights a little; it brought them within ΔE 3.7 of my corrections (median, each left out of the average in turn).
HITJAPAN_CURVE = [7, 7, 8, 8, 10, 15, 22, 30, 39, 49, 60, 70, 81, 92, 102, 113, 124, 134, 145, 155, 165, 176, 187, 197, 208, 219, 229, 239, 246,
                  250, 252, 252]
HITJAPAN = np.interp(np.arange(256), (np.arange(32) + 0.5) * 8, HITJAPAN_CURVE).round().astype(np.uint8)

_v = np.arange(256) / 255
LINEAR = np.where(_v <= 0.04045, _v / 12.92, ((_v + 0.055) / 1.055) ** 2.4).astype(np.float32)
_v = np.arange(4096) / 4095
SRGB = (255 * np.where(_v <= 0.0031308, 12.92 * _v, 1.055 * _v ** (1 / 2.4) - 0.055)).round().astype(np.uint8)
LUMINANCE = np.array([0.0722, 0.7152, 0.2126], np.float32)  # B, G, R


def source_of(path):
    """The source of a photo in photos/, from its path; None for one elsewhere."""
    rel = os.path.relpath(path, photos.ROOT)
    return None if rel.startswith("..") else rel.split(os.sep)[0]


def white(photo, border=None):
    """The background's white, linear (B, G, R): the median of the brighter half of the photo's pixels (shrunk to
    400 px), of those in the frame's outer border share only if given."""
    scale = 400 / max(photo.shape[:2])
    small = cv2.resize(photo, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    if border is not None:
        h, w = small.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        small = small[(xx < w * border) | (xx >= w * (1 - border)) | (yy < h * border) | (yy >= h * (1 - border))]
    pixels = LINEAR[small.reshape(-1, 3)]
    y = pixels @ LUMINANCE
    return np.median(pixels[y >= np.median(y)], 0)


def through(photo, curves, roll_off=True, rows=512):
    """The photo through per-channel curves (3 x 256: an 8-bit sRGB value -> linear light, B, G, R), back to 8-bit sRGB;
    what goes above white rolled off from KNEE (roll_off) or else scaled down to white, its hue kept either way; a few
    rows at a time (a photo is large)."""
    out = np.empty_like(photo)
    T = (TOP - KNEE) / (1 - KNEE)
    curves = np.asarray(curves, np.float32)
    for r in range(0, photo.shape[0], rows):
        p = photo[r:r + rows]
        x = np.stack([curves[c][p[..., c]] for c in range(3)], -1)
        m = np.maximum(x.max(2, keepdims=True), 1e-6)
        t = np.maximum(m - KNEE, 0) / (1 - KNEE)
        rolled = np.where(m > KNEE, KNEE + (1 - KNEE) * t * (1 + t / T ** 2) / (1 + t), m) if roll_off else m
        out[r:r + rows] = SRGB[np.clip(x * (np.minimum(rolled, 1) / m) * 4095 + 0.5, 0, 4095).astype(np.int32)]
    return out


def made_white(photo, white):
    """The photo with its white made white, what goes above it rolled off."""
    return through(photo, LINEAR[None, :] / np.asarray(white, np.float32)[:, None])


def corrected(photo, path):
    """The photo (as read from path) with its colors evened out, if its source is one of those above."""
    source = source_of(path)
    if source in BORDERS:
        return made_white(photo, white(photo, BORDERS[source]))
    if source == "ebay-hitjapan":
        return cv2.LUT(photo, HITJAPAN)
    return photo


# Each photo's own colors (colors.json), applied after its source's evening out above, by render-labels and
# render-carts: four settings, in plain terms:
#   brightness: how much brighter white comes out, in stops (+1: twice as bright, in linear light);
#   contrast: the power on linear light, pivoted at white (1: unchanged; 1.2: a gray at half of white's brightness comes
#     out at 0.5^1.2 = 0.44 of it): above 1 darkens the shadows and leaves white as it is;
#   temperature: how much redder than blue white comes out, in stops (+: warmer);
#   tint: how much greener than red and blue's mean white comes out, in stops (+: greener, -: more magenta).
# A pixel's channel c (linear light, 0-1) comes out as 2^k_c * x^contrast, k the channel's gain in stops at white, set
# by brightness, temperature and tint (gains_of); a pixel going above white is scaled down to it, its hue kept.
# colors.json: by the photo's stem, {"sha1": its SHA-1, "colors": settings + {"source": "auto-generated" or
# "hand-placed"}}; settings made by make fit-colors (auto-generated) or set in make adjust-colors (hand-placed, which
# fit-colors keeps). An entry whose SHA-1 isn't its photo's is of another photo once under the same name: ignored.
FILE = "colors.json"
# The reference sources: photos lit alike within each (after the evening out above), what every other source's are
# matched to (make learn-colors). And the sources whose photos are lit alike, so that a photo's own white paper isn't
# trusted over its source's settings: the references and jnlgame (on which the paper made the match worse, ΔE 11.6 ->
# 15.7, 2026-11-04).
REFERENCES = ("my-collection", "ebay-hitjapan", "ebay-elrocinante")
LIT_ALIKE = REFERENCES + ("jnlgame",)
SETTINGS = ("brightness", "contrast", "temperature", "tint")
NEUTRAL = {"brightness": 0.0, "contrast": 1.0, "temperature": 0.0, "tint": 0.0}


def gains_of(settings):
    """The gains at white, in stops (B, G, R), of brightness, temperature and tint: the luminance-weighted mean is the
    brightness, red minus blue the temperature, green minus the mean of red and blue the tint."""
    b, t, n = settings["brightness"], settings["temperature"], settings["tint"]
    a = b - LUMINANCE[1] * n - (LUMINANCE[2] - LUMINANCE[0]) * t / 2
    return np.array([a - t / 2, a + n, a + t / 2])


def settings_of(gains, contrast):
    """The settings of gains at white (stops, B, G, R) and a contrast: gains_of's inverse."""
    k = np.asarray(gains, np.float64)
    return {"brightness": float(k @ LUMINANCE), "contrast": float(contrast), "temperature": float(k[2] - k[0]),
            "tint": float(k[1] - (k[0] + k[2]) / 2)}


def curves_of(settings):
    """The per-channel curves (3 x 256, sRGB -> linear) of a photo's settings."""
    return (2.0 ** gains_of(settings))[:, None] * LINEAR[None, :] ** settings["contrast"]


def adjusted(photo, settings):
    """The photo (already evened out by its source) with its own settings applied."""
    if settings is None or all(settings[k] == NEUTRAL[k] for k in SETTINGS):
        return photo
    return through(photo, curves_of(settings), roll_off=False)


def load_colors():
    return json.load(open(FILE)) if os.path.exists(FILE) else {}


def save_colors(colors):
    """One line per photo, so that the file's history reads as settings changed."""
    lines = [f"{json.dumps(name)}: {json.dumps(entry)}" for name, entry in sorted(colors.items())]
    open(FILE + ".tmp", "w").write("{\n" + ",\n".join(lines) + "\n}\n" if lines else "{}\n")
    os.replace(FILE + ".tmp", FILE)


@contextlib.contextmanager
def editing_colors():
    """colors.json, read afresh under a lock, saved when the block ends without an error."""
    with open(FILE + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        colors = load_colors()
        yield colors
        save_colors(colors)


def colors_of(colors, name, sha1):
    """The photo's settings (with their source), or None: none, or of another photo once under that name."""
    entry = colors.get(name)
    return entry["colors"] if entry and entry.get("sha1") == sha1 else None


# White paper on a label, for the settings fit-colors makes (src/fit_colors.py): of the label's brightest pixels
# (PAPER_TOP share) where it's flat (brightness changing less than PAPER_FLAT across 3 px), the connected regions;
# in each, the pixels within PAPER_TOLERANCE (stops, any channel) of its median color; the region with the most of
# them, times their brightness, if they're at least PAPER_SHARE of the label and no channel is off their brightness
# by more than PAPER_CAST stops (a red label's brightest part isn't paper). Measured on the labels of my photos,
# Hit-Japan's and elrocinante's: found on about half the labels.
PAPER_TOP, PAPER_FLAT, PAPER_TOLERANCE, PAPER_SHARE, PAPER_CAST = 0.25, 0.15, 0.04, 0.02, 0.35
PAPER_MARGIN = 6  # px of a 200 px wide label left out at its edges (the fit's error, the recess's shadow)


def paper(label):
    """White paper's color on a label image (BGR, 8-bit sRGB, the label alone, straightened), linear (B, G, R); or
    None if there's none."""
    m = PAPER_MARGIN
    lin = cv2.GaussianBlur(LINEAR[label[m:-m, m:-m]], (0, 0), 1.0)
    y = lin @ LUMINANCE + 1e-6
    chroma = np.log2(np.maximum(lin, 1e-4) / y[..., None])
    flat = cv2.morphologyEx(y, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) / y < PAPER_FLAT
    bright = (y >= np.quantile(y, 1 - PAPER_TOP)) & flat
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bright.astype(np.uint8), connectivity=4)
    best = None
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < PAPER_SHARE * y.size:
            continue
        x0, y0, w, h = stats[i, :4]
        box = (slice(y0, y0 + h), slice(x0, x0 + w))
        region = labels[box] == i
        c = np.median(chroma[box][region], 0)
        near = region & (np.abs(chroma[box] - c).max(2) < PAPER_TOLERANCE)
        if near.sum() < PAPER_SHARE * y.size:
            continue
        color = np.median(lin[box][near], 0)
        if np.abs(np.log2(color / (color @ LUMINANCE))).max() > PAPER_CAST:
            continue
        score = near.sum() * (color @ LUMINANCE)
        if best is None or score > best[0]:
            best = (score, color)
    return None if best is None else best[1]
