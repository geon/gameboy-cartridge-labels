import contextlib, fcntl, json, os, cv2, numpy as np

# Each source's colors, as fit-colors sets them (src/fit_colors.py), for the sources that photograph every cartridge
# alike: my own photos and jnlgame's, on a plain white background, have it made white (that sets their exposure and
# white balance alike, as my hand correction of IMG_7324 did): settings making its white white (whitening); Hit-Japan's (eBay), washed out, get the levels of my hand corrections
# of nine of them
# (HITJAPAN); yugiyahirano's, likely one photographer's, the settings that brought them nearest the reference sources'
# labels of the same releases (YUGIYAHIRANO); elrocinante's (its background isn't white), levels as I set them by hand
# (ELROCINANTE). Judged by eye on the labels of all these
# sources' photos (2026-10-30).

# Where the background's white is measured: the frame's outer share on my photos (the cartridge photographed fills the
# middle, neighbouring ones the edges), the whole frame on jnlgame's. Against the band 2-6 mm around the fitted
# cartridge, the white measured so was within 3 % in brightness and 1.3 % in color on half my 187 photos, 10 % and
# 2.6 % on nine in ten; jnlgame's within 4.5 % and 2.1 % on half.
BORDERS = {"my-collection": 0.12, "jnlgame": None}
# My hand corrections of nine Hit-Japan photos (2026-10-30) averaged into one tone curve, the same on the three
# channels, brought them within ΔE 3.7 of my corrections (median, each left out of the average in turn); these settings
# come nearest that curve, weighted by how often each level is seen on Hit-Japan's labels: within 1.2 levels of 255 on
# average (2026-11-04).
HITJAPAN = {"black": 36.6, "white": 231.7, "midtones": 0.98, "temperature": 0, "tint": 0}
# Fitted on 122 of yugiyahirano's labels against the reference sources' of the same releases (the median of each
# photo's best settings; 2026-11-04): it took them from ΔE 18.8 to 12.1 (median, each release's photos with settings
# learned without them). Fitted as exposure and contrast; these levels come within 0.7 of 255 of them on average.
YUGIYAHIRANO = {"black": 14.0, "white": 217.2, "midtones": 1.17, "temperature": 0.22, "tint": -0.04}
# From my settings by hand (55 photos, 2026-11-04), what fit-colors does by default: a black point at 14 (I set it at
# 13 on my photos, 14 on elrocinante's, 17 on others', 11 on yugiyahirano's, medians; Hit-Japan's kept its 37), and a
# white point measured from a background or paper made WHITE_LOWER levels lower (I set it 14 below on my photos, 23 on
# others'); elrocinante's, left as they were, set alike (my 12: black 14, white 240, midtones 1.08, the white balance
# left alone on 9).
DEFAULT_BLACK = 14.0
WHITE_LOWER = 14.0
ELROCINANTE = {"black": 14.0, "white": 240.0, "midtones": 1.08, "temperature": 0.0, "tint": 0.0}
SOURCE_SETTINGS = {"ebay-hitjapan": HITJAPAN, "yugiyahirano": YUGIYAHIRANO, "ebay-elrocinante": ELROCINANTE}

_v = np.arange(256) / 255
LINEAR = np.where(_v <= 0.04045, _v / 12.92, ((_v + 0.055) / 1.055) ** 2.4).astype(np.float32)
LUMINANCE = np.array([0.0722, 0.7152, 0.2126], np.float32)  # B, G, R


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


# Each photo's own colors (colors.json), applied by render-labels and render-carts to the photo as it is: five
# settings, as in photo editors' Levels, with white balance before:
#   temperature: how much redder than blue white comes out, in stops (+: warmer);
#   tint: how much greener than red and blue's mean white comes out, in stops (+: greener, -: more magenta);
#   black: the level (0-255) that becomes black, and all below it;
#   white: the level (0-255) that becomes white, and all above it;
#   midtones: the levels between bent (1: straight; above 1 lighter, below darker), black and white kept.
# A pixel's channel c comes out as ((s - black) / (white - black)) ^ (1 / midtones), clipped to black and white, where
# s is the channel's level (sRGB, 0-255) after its gain in linear light, 2^k_c, set by temperature and tint (gains_of:
# their gains keep the brightness of a gray). So each channel goes through a curve of its own (curves_of).
# colors.json: by the photo's stem, {"sha1": its SHA-1, "colors": settings + {"source": "auto-generated" or
# "hand-placed"}}; settings made by make fit-colors (auto-generated) or set in make adjust-colors (hand-placed, which
# fit-colors keeps). An entry whose SHA-1 isn't its photo's is of another photo once under the same name: ignored.
FILE = "colors.json"
# The reference sources: photos lit alike within each (with their source's settings above), what the others are
# matched to.
# And the sources whose photos are lit alike, whose labels' white paper isn't used to set their colors (fit-colors):
# the references, jnlgame (on which it made the match with the references worse, ΔE 11.5 -> 15.7, 2026-11-04), and
# yugiyahirano (one photographer, likely).
# The reference sources' paper, as bright as fit-colors makes a photo's: the median of their labels' (color.paper),
# 0.88 of white, in linear light, with their settings (2026-11-04).
REFERENCES = ("my-collection", "ebay-hitjapan", "ebay-elrocinante")
LIT_ALIKE = REFERENCES + ("jnlgame", "yugiyahirano")
PAPER_BRIGHTNESS = 0.88
SETTINGS = ("black", "white", "midtones", "temperature", "tint")
NEUTRAL = {"black": 0.0, "white": 255.0, "midtones": 1.0, "temperature": 0.0, "tint": 0.0}


def encode(linear):
    """sRGB (0-1) of linear light, carried on above 1 by the same formula."""
    linear = np.asarray(linear, np.float64)
    return np.where(linear <= 0.0031308, 12.92 * linear, 1.055 * np.maximum(linear, 0) ** (1 / 2.4) - 0.055)


def gains_of(settings):
    """The gains of temperature and tint, in stops (B, G, R): red minus blue the temperature, green minus the mean of
    red and blue the tint, their luminance-weighted mean 0 (a gray stays as bright)."""
    t, n = settings["temperature"], settings["tint"]
    a = -LUMINANCE[1] * n - (LUMINANCE[2] - LUMINANCE[0]) * t / 2
    return np.array([a - t / 2, a + n, a + t / 2])


def curves_of(settings):
    """The per-channel curves (3 x 256, 8-bit sRGB in and out, B, G, R) of a photo's settings."""
    level = 255 * encode((2.0 ** gains_of(settings))[:, None] * LINEAR[None, :])
    black, white = settings["black"], max(settings["white"], settings["black"] + 1)
    out = np.clip((level - black) / (white - black), 0, 1) ** (1 / settings["midtones"])
    return (out * 255).round().astype(np.uint8)


def adjusted(photo, settings):
    """The photo with its own settings applied."""
    if settings is None or all(settings[k] == NEUTRAL[k] for k in SETTINGS):
        return photo
    curves = curves_of(settings)
    return np.dstack([cv2.LUT(photo[..., c], curves[c]) for c in range(3)])


def whitening(color, target=1.0):
    """The settings that make a color (linear, B, G, R) a neutral gray as bright as target (linear; 1: white), black
    kept black: temperature and tint making it neutral, then the white level set so that it comes out at target."""
    k = -np.log2(np.asarray(color, np.float64))
    settings = {"temperature": float(k[2] - k[0]), "tint": float(k[1] - (k[0] + k[2]) / 2)}
    seen = float(encode(color[1] * 2.0 ** gains_of(settings)[1]))  # all three channels alike now
    return settings | {"black": 0.0, "white": float(min(255, 255 * seen / float(encode(target)))), "midtones": 1.0}


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
