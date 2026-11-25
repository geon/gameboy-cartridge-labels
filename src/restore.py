# restore: an image of every print from its label photos, into <generated>/restore/:
#   <print>.avif: the restored print at straighten's PX_PER_MM, cropped to its family's cut (cuts.crop: the median of
#     each side of the stickers' cuts found by straighten, INSET mm inward, whole pixels; the same for every print of
#     the family); its colours scaled so its paper is white (see paper_white) where paper is found, else the label
#     photos' evened to their median (the user: one image per print)
#   <print>.json: {"crop" (cuts.crop's: x, y, w, h px in the straightened images, mm), "keys" (its label photos used),
#     "approximate" (those of them with an approximate cut), "screen_peaks" (how many print-screen peaks descreen removed),
#     "bands" (how many label photos count in each band, finest first), "paper" (the paper's colour found, or null)}
# The label photos: the print's own only, poor fits left out (solve.poor_fit); a print with fewer than MIN_PHOTOS of
# them, or fewer than MIN_PRECISE that aren't approximate cuts (solve.approximate_cut), gets no image (the user,
# 2026-11-12: only prints of three or more label photos restored; one used as it is and two averaged were removed).
# An approximate cut's label photo counts only APPROXIMATE_INSET mm further inside its cut (the cut found by
# straighten around the nested fit's: 0.16 mm from it at the median, 0.41 at 90 %, against 0.04 and 0.14 for the edge
# models' cuts; the edge models moved the nested fit's label 0.49 mm at the median, 1.31 at 90 %). (Pooling the
# label photos of the family's other prints where they matched the print's own was removed, 2026-11-11: the user found
# it very broken.) Each straightened label photo's colours evened per channel to the
# median of the print's own (a scale and offset), then split into frequency bands in Oklab (a Laplacian pyramid, halving until
# the image is under 8 px across). Per band and pixel, a label photo counts unless the band is finer than its own
# photo's resolution (the fit's photo pixels per mm), its straightened image is empty there (off the photo), it lies
# outside its own sticker's cut moved cuts.INSET mm inward (plastic, and the highlight or shadow on the cut's edge); in
# coarser bands, a pixel partly where it counts counts by the part (its weight). Outside where it counts, each is filled
# from its nearest pixel that counts before it's split into bands (so neither black nor plastic leaks into the coarse
# bands). Before combining, the label photos are registered finely at full resolution (register). Combined per band by
# the weighted median (weighted_median).
# (Was, until 2026-11-25: in coarser bands only where the whole pixel counts. At a label's edge, where few label photos
# reach it (approximate cuts stop 1 mm further in), no band pixel 0.8-1.6 mm tall was whole there, so those bands had no
# detail; the coarsest band's blur of the design 1-3 mm in was no longer cancelled by them and showed as a coloured
# smear along the edge (the user: AGB-AEVE-USA-ivan, its photos black at the edge).)
# (Tried: weighting by each band's local energy, as in focus stacking, with Tukey's biweight: the user found the plain
# median removes noise better; noise and dirt have high local energy too. To experiment with later: energy only to
# leave out clearly blurred regions. Tried 2026-11-15: before the median, each label photo's band fitted per Oklab
# channel to the band's median where both count (photo ≈ g · median, the residual + an offset), divided by g, capped
# 0.5-2x; gains 0.7-1.3 in the fine bands, ±5 % in the coarse; on 20 prints chosen to show it most (few label photos
# of mixed resolution and sources) the user found the difference imperceptible: not worth doing. Test script:
# generated/band-gain/make.py.)
# Last, after the paper white, the print screen (halftone) removed from the restored print (src/descreen.py: a notch at
# the screen's peaks, then a 1.5 px weighted median; the user, 2026-11-14: on the restored print, not on each label
# photo before).
# A frozen print (src/frozen.py) isn't restored: its image is the one frozen (publish copies it); make refreeze
# (src/refreeze.py) restores it again. Nor is an open print of a serial and tag some frozen print has (the user,
# 2026-11-23: the frozen one is done; review-prints' Same serial tab hides them too); an untagged open print is held
# back by any frozen print of its serial.
# Done again when an image is older than this file, cuts.py, descreen.py, prints.json, solve.json or its family's straightened
# images and cuts.
# Usage: restore.py [--sample] [--workers N]
import argparse, html, json, os, sys
import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, steps, straighten, shapes, cuts, descreen, prints as prints_step
from scipy import ndimage

QUALITY = 90
MIN_PHOTOS = 3         # a print with fewer label photos isn't restored
MIN_PRECISE = 2        # nor one with fewer label photos that aren't approximate cuts
APPROXIMATE_INSET = 1.0  # mm, an approximate cut moved this much further inward than cuts.INSET
MAX_PHOTOS = 30        # the sharpest kept, if a print has more


# sRGB <-> Oklab (Björn Ottosson's), on float images in 0..1 (BGR in and out, as OpenCV's)
_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])


def to_oklab(bgr):
    rgb = bgr[..., ::-1]
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    lms = np.cbrt(lin @ _M1.T)
    return (lms @ _M2.T).astype(np.float32)


def from_oklab(lab):
    lms = (lab @ np.linalg.inv(_M2).T) ** 3
    lin = np.clip(lms @ np.linalg.inv(_M1).T, 0, 1)
    rgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return rgb[..., ::-1].astype(np.float32)


def pyramid(img):
    """A Laplacian pyramid: [band 0 (finest), ..., the residual]."""
    levels, cur = [], img
    while min(cur.shape[:2]) >= 16:
        down = cv2.pyrDown(cur)
        up = cv2.pyrUp(down, dstsize=(cur.shape[1], cur.shape[0]))
        levels.append(cur - up)
        cur = down
    levels.append(cur)
    return levels


def collapse(levels):
    cur = levels[-1]
    for band in reversed(levels[:-1]):
        cur = cv2.pyrUp(cur, dstsize=(band.shape[1], band.shape[0])) + band
    return cur


def even_to(img, ref, valid):
    """img's colours evened per channel to ref (a scale and offset, fitted on valid pixels, the best 80 %)."""
    out = img.copy()
    for c in range(3):
        x, y = img[..., c][valid], ref[..., c][valid]
        if len(x) < 100:
            continue
        A = np.c_[x, np.ones_like(x)]
        coef = np.linalg.lstsq(A, y, rcond=None)[0]
        r = np.abs(A @ coef - y)
        ok = r <= np.percentile(r, 80)  # <=: with residuals all zero (a photo evened to itself), < kept none
        coef = np.linalg.lstsq(A[ok], y[ok], rcond=None)[0]
        out[..., c] = img[..., c] * coef[0] + coef[1]
    return np.clip(out, 0, 1)


# Fine registration at full resolution: solve aligns a print's label photos by their pixels at 5 px/mm, which leaves
# 0.4-1.8 px (at 20 px/mm) between them, most at the label's top and bottom, enough to blur small text in a median.
# Each label photo (lighting-evened gray) is aligned to the print's median by a homography (ECC), the median rebuilt,
# REGISTER_ROUNDS times; then by a smooth local correction: dense optical flow (DIS) against the median, smoothed over
# FLOW_SMOOTH_MM and limited to FLOW_MAX_PX, so a gentle bend or lens distortion is followed, not a detail (dirt isn't
# pulled into place).
# A print joined across families (by the user in review-prints, or by the prints step) has label photos posed by separate
# fits, up to about 1 mm (20 px) apart: each is first shifted onto the one with the most of the label on it by phase
# correlation (accepted when its peak is at least COARSE_RESPONSE and the shift at most COARSE_MAX_MM).
REGISTER_ROUNDS = 2
COARSE_RESPONSE = 0.05
COARSE_MAX_MM = 3.0
FLOW_SMOOTH_MM = 2.0
FLOW_MAX_PX = 3.0


def evened_gray(img, valid):
    g = cv2.cvtColor((img * 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
    P = straighten.PX_PER_MM
    m = cv2.GaussianBlur(g, (0, 0), P / 2)
    s = np.sqrt(cv2.GaussianBlur((g - m) ** 2, (0, 0), P / 2)) + 2
    return np.where(valid, (g - m) / s, 0).astype(np.float32)


WARP_INTERPOLATION = cv2.INTER_LANCZOS4


def warp(img, M, flow=None, nearest=False, interpolation=None):
    """img resampled once: out(x) = img(M (x + flow(x))) (M: out px -> img px). One resampling, with a sharp kernel:
    a homography and then the flow, each bilinear, had softened every label photo (DMG-KYJ's sharpest: 0.57 -> 0.38 of
    its detail measure) and so every restored print."""
    h, w = img.shape[:2]
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    if flow is not None:
        gx, gy = gx + flow[..., 0], gy + flow[..., 1]
    pts = cv2.perspectiveTransform(np.dstack([gx, gy]).reshape(-1, 1, 2).astype(np.float64), np.float64(M)).reshape(h, w, 2)
    inter = cv2.INTER_NEAREST if nearest else (interpolation if interpolation is not None else WARP_INTERPOLATION)
    return cv2.remap(img, pts[..., 0].astype(np.float32), pts[..., 1].astype(np.float32), inter,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=0)


ECC_CRITERIA = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)


def homography_to(ref, gray, valid, M):
    """M refined (ECC) so gray, warped by it, lies on ref; M as it was if ECC fails."""
    try:
        return cv2.findTransformECC(ref, gray, M, cv2.MOTION_HOMOGRAPHY, ECC_CRITERIA, valid, 5)[1]
    except cv2.error:
        return M


def warped_onto(ref, entry, gray, M):
    """entry (image, valid, px/mm) resampled onto ref: its homography M, then a smooth local correction (optical flow
    against ref, smoothed over FLOW_SMOOTH_MM, limited to FLOW_MAX_PX)."""
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    to8 = lambda x: np.clip(x * 40 + 128, 0, 255).astype(np.uint8)
    flow = dis.calc(to8(ref), to8(warp(gray, M)), None)        # ref px -> where it is in the aligned photo
    flow = cv2.GaussianBlur(flow, (0, 0), FLOW_SMOOTH_MM * straighten.PX_PER_MM)
    mag = np.linalg.norm(flow, axis=2, keepdims=True)
    flow = (flow * np.minimum(1, FLOW_MAX_PX / np.maximum(mag, 1e-6))).astype(np.float32)
    return (warp(entry[0], M, flow), warp(entry[1].astype(np.uint8), M, flow, nearest=True) > 0, entry[2])


def coarse_shifts(grays, valids):
    """Per label photo, a translation (as a homography: out px -> its px) putting it on the one with the most valid
    pixels (phase correlation), or none where the correlation is weak or the shift too large."""
    ref = int(np.argmax([v.sum() for v in valids]))
    window = cv2.createHanningWindow(grays[ref].shape[::-1], cv2.CV_32F)
    Ms = []
    for i, g in enumerate(grays):
        M = np.eye(3, dtype=np.float32)
        if i != ref:
            (dx, dy), response = cv2.phaseCorrelate(grays[ref] * window, g * window)
            if response >= COARSE_RESPONSE and np.hypot(dx, dy) <= COARSE_MAX_MM * straighten.PX_PER_MM:
                M[0, 2], M[1, 2] = dx, dy
        Ms.append(M)
    return Ms


def register(entries, joined=False):
    """A print's own label photos (image, valid, px/mm) aligned to their median: a homography each, then a smooth
    local correction. joined: a print joined across families: first coarse_shifts."""
    valids = [e[1].astype(np.uint8) for e in entries]
    grays = [evened_gray(e[0], v > 0) for e, v in zip(entries, valids)]
    Ms = coarse_shifts(grays, valids) if joined else [np.eye(3, dtype=np.float32) for _ in entries]
    for _ in range(REGISTER_ROUNDS):
        ref = np.median(np.stack([warp(g, M) for g, M in zip(grays, Ms)]), 0)
        Ms = [homography_to(ref, g, v, M) for g, v, M in zip(grays, valids, Ms)]
    ref = np.median(np.stack([warp(g, M) for g, M in zip(grays, Ms)]), 0)
    return [warped_onto(ref, e, g, M) for e, g, M in zip(entries, grays, Ms)]


def finest_band(photo_px_per_mm):
    """The finest band (0 = straighten's full resolution) a photo with this many pixels per mm carries: band k holds
    detail about 2^k pixels of straighten's across, which needs about as many of the photo's per mm."""
    ratio = straighten.PX_PER_MM / max(photo_px_per_mm, 1e-6)
    return max(0, int(np.floor(np.log2(max(ratio, 1.0)))))


# Local sharpness: a label photo blurred in places (out of focus, motion, a soft lens corner) has little detail there in
# the fine bands, and the median of crisp and blurred photos is soft (DMG-KYJ: six label photos of 16-44 px/mm, all
# counting in the finest band by their resolution, two of them clearly soft). Per band and pixel, a label photo's
# local detail is its band's lightness magnitude averaged over SHARP_MM; it counts only where that is at least
# SHARP_SHARE of the second most detailed label photo's there (the second: dirt or noise on one photo has detail too,
# and mustn't push the others out). Only to leave out what's clearly blurred, never to favour the most detailed (the
# energy-weighted median favoured noise and dirt). With two, which is blurred and which is dirty can't be told; so
# per pixel, a label photo is left out only where three or more still count (a
# watermark on one of three came through where the softest was left out: 1b32d2a69c…_68_34, 2026-11-10).
SHARP_MM = 1.0
SHARP_SHARE = 0.5


def sharp_enough(L, counts, lv):
    """n x H x W: whether each label photo is sharp enough at each pixel of band lv (L: the band's lightness; counts:
    where each label photo counts at all)."""
    sigma = max(1.0, SHARP_MM * straighten.PX_PER_MM / 2 ** lv)
    detail = np.stack([cv2.GaussianBlur(np.abs(l).astype(np.float32), (0, 0), sigma) for l in L]) * counts
    second = np.sort(detail, axis=0)[-2]
    return detail >= SHARP_SHARE * second


def weighted_median(vals, W):
    """Per pixel and channel, the median of vals (n x H x W x C) weighted by W (n x H x W); where two halves weigh
    the same, the mean of the values on either side (so equal weights give np.median's). 0 where nothing weighs."""
    order = np.argsort(vals, axis=0)
    v = np.take_along_axis(vals, order, 0)
    w = np.take_along_axis(np.broadcast_to(W[..., None], vals.shape), order, 0)
    cum = np.cumsum(w, 0)
    half = cum[-1:] / 2
    eps = 1e-6 * np.maximum(cum[-1:], 1e-12)
    lo = np.minimum((cum < half - eps).sum(0, keepdims=True), len(vals) - 1)
    hi = np.minimum((cum <= half + eps).sum(0, keepdims=True), len(vals) - 1)
    # hi past lo only on a tie; skip zero-weight values there
    hi = np.maximum(hi, lo)
    out = (np.take_along_axis(v, lo, 0) + np.take_along_axis(v, hi, 0))[0] / 2
    return np.where(cum[-1] > 0, out, 0)


def filled(img, where):
    """img with the pixels outside where set to their nearest pixel inside (img as it is if where is empty)."""
    if where.all() or not where.any():
        return img
    idx = ndimage.distance_transform_edt(~where, return_distances=False, return_indices=True)
    return img[idx[0], idx[1]]


def restore_print(job):
    """Restores one print: (print id, the result's description)."""
    pid, shape, own, px_per_mm, approximate, crop, joined, out_base = job
    P = straighten.PX_PER_MM
    x0, y0, w, h = crop["x"], crop["y"], crop["w"], crop["h"]
    size, px_to_mm = straighten.canvas(shape)

    def load(key, path):  # (image 0..1 BGR cropped, valid mask, px/mm) or None
        img = cv2.imread(path)
        if img is None:
            return None
        valid = img.max(2) > 1    # straighten's border outside the photo is black
        cut = straighten.load_cut(os.path.dirname(os.path.dirname(path)), key)
        if cut is not None:
            valid &= cuts.mask(cut, shape, size, px_to_mm, cuts.INSET + (APPROXIMATE_INSET if key in approximate else 0))
        img = img[y0:y0 + h, x0:x0 + w].astype(np.float32) / 255
        return img, valid[y0:y0 + h, x0:x0 + w], px_per_mm.get(key, P)

    loaded = [(k, load(k, path)) for k, path in own]
    loaded = [(k, e) for k, e in loaded if e is not None]
    if len(loaded) < MIN_PHOTOS or sum(k not in approximate for k, _ in loaded) < MIN_PRECISE:
        return pid, None
    if len(loaded) > MAX_PHOTOS:
        loaded = sorted(loaded, key=lambda ke: -ke[1][2])[:MAX_PHOTOS]
    own_keys = [k for k, _ in loaded]
    entries = register([e for _, e in loaded], joined)
    ref = np.median(np.stack([e[0] for e in entries]), 0)
    evened = [even_to(e[0], ref, e[1]) for e in entries]
    valids = [e[1] for e in entries]
    pyrs = [pyramid(to_oklab(filled(img, v))) for img, v in zip(evened, valids)]
    levels = len(pyrs[0])
    out_levels, out_median, counts = [], [], []
    for lv in range(levels):
        vals = np.stack([p[lv] for p in pyrs])                                   # n x H x W x 3
        hh, ww = vals.shape[1:3]
        weights = []
        for e, p in zip(entries, pyrs):
            # where it counts (on the photo, inside its cut): by the part of the pixel that does
            wgt = cv2.resize(e[1].astype(np.float32), (ww, hh), interpolation=cv2.INTER_AREA)
            wgt[wgt < 1e-3] = 0
            if lv < levels - 1 and lv < finest_band(e[2]):
                wgt[:] = 0
            weights.append(wgt)
        W = np.stack(weights)
        if lv < levels - 1:
            sharp = W * sharp_enough(vals[..., 0], W > 0, lv)
            # only where three or more still count: with two left, the dirty one isn't outvoted (a watermark on one
            # of three came through at half strength where the third, softest, was left out)
            W = np.where(((sharp > 0).sum(0) >= 3)[None], sharp, W)
        total = W.sum(0)
        counts.append(int(np.median((W > 0).sum(0))))
        est = weighted_median(vals, W)
        # where nothing counts in this band (finer than every photo): no detail
        est = np.where((total > 1e-12)[..., None], est, 0 if lv < levels - 1 else vals.mean(0))
        out_levels.append(est.astype(np.float32))
    result = np.clip(from_oklab(collapse(out_levels)), 0, 1)
    paper, white = paper_white(result)
    final, screen = descreen.descreen(to_oklab(white if white is not None else result))
    write_avif(out_base + ".avif", np.clip(from_oklab(final), 0, 1))
    for old in (out_base + "-median.avif", out_base + "-paper.avif"):
        if os.path.exists(old):
            os.remove(old)
    return pid, {"crop": crop, "keys": own_keys, "approximate": [k for k in own_keys if k in approximate], "bands": counts,
                 "paper": None if paper is None else [round(float(v), 3) for v in paper], "screen_peaks": len(screen)}


def canonical_crop(shape):
    """The canonical label at ink coordinates' origin, as cuts.crop gives a crop (when no cut was found at all)."""
    P, M = straighten.PX_PER_MM, straighten.MARGIN
    lw, lh = shapes.LABEL_MM[shape]
    x, y = int(round(M * P)), int(round(M * P))
    return {"x": x, "y": y, "w": int(round(lw * P)), "h": int(round(lh * P)), "mm": [0.0, 0.0, lw, lh]}


def write_avif(path, img):
    tmp = path + ".tmp.avif"
    cv2.imwrite(tmp, (np.clip(img, 0, 1) * 255).round().astype(np.uint8), [cv2.IMWRITE_AVIF_QUALITY, QUALITY])
    os.replace(tmp, path)


# Paper white: the paper is the restored image's brightest near-neutral pixels (Oklab chroma under PAPER_CHROMA, in the
# top PAPER_TOP of the lightness among those), at least PAPER_MIN_TOP of the label, their median lightness at least
# PAPER_LIGHT; each channel scaled in linear light so the paper at its PAPER_WHITE quantile of lightness becomes white:
# only the brightest of the paper clips (the user: the paper's median made white, 5 % over, clipped far too much). A
# label with too little near-neutral area (PAPER_MIN) or such paper isn't done. The top tenth, not half (2026-11-10):
# halftoned greys and tints aren't resolved into dots at this resolution, so a dark label's near-neutral pixels are
# mostly mid greys, and their lighter half was no paper (832 of 5589 prints got none; AGB-BRKE-USA's white came out at
# 84 %, the user's 85 % by hand).
# Black point, likewise (the user: the printed solid black's texture crushed, that's the point): the ink is the
# near-neutral pixels darker than INK_MAX lightness, at least INK_MIN of the label; black is where their histogram's
# peak falls to half its height on its light side (the solid black's texture, crushed), but at most INK_ABOVE_DARKEST
# above their INK_BLACK quantile (a peak well above the darkest ink is a grey: DMG-NM-NOE was too dark), the colour of
# the ink at that lightness (or its neutral grey if none is), taken off per channel in linear light so the black is
# neutral too. A label with too little such ink keeps its blacks as they are. (Tried: a cap at 15 % sRGB: no gain on
# clean labels, too little on glary ones, which need the higher black.)
# A dark colour isn't black ink (2026-11-22, the user: AGB-AGSP-EUR-jill's dark green background clipped to black): dark
# colours have little Oklab chroma, so they pass as near-neutral ink, the histogram's peak is the colour and taking its
# colour off makes it black. Where the ink at that lightness has a hue (its median a,b at least INK_HUE from neutral;
# real black ink's noise averages out, median 0.014 on 273 prints, 17 % at INK_HUE or more), the black is neutral
# instead, at the ink's INK_BLACK quantile of lightness: the darkest go black, the colour gets darker but stays a colour.
# (Tried: an ink chroma limit of 0.02: much of the green is under it too, no change; no black point at all: washed out.)
PAPER_CHROMA = 0.04
PAPER_TOP = 0.1
PAPER_MIN = 0.03
PAPER_MIN_TOP = 0.01
PAPER_LIGHT = 0.6
PAPER_WHITE = 0.9
INK_MAX = 0.4
INK_MIN = 0.01
INK_BLACK = 0.1
INK_ABOVE_DARKEST = 0.1
INK_BINS = 40
INK_HUE = 0.025


def paper_white(bgr):
    """(the paper's colour BGR 0..1, the image with paper white and, where there's ink enough, ink black) or (None, None)."""
    lab = to_oklab(bgr)
    L = lab[..., 0]
    neutral = np.hypot(lab[..., 1], lab[..., 2]) < PAPER_CHROMA
    if neutral.mean() < PAPER_MIN:
        return None, None
    paper = neutral & (L >= np.quantile(L[neutral], 1 - PAPER_TOP))
    if paper.mean() < PAPER_MIN_TOP or np.median(L[paper]) < PAPER_LIGHT:
        return None, None
    lin = np.where(bgr <= 0.04045, bgr / 12.92, ((bgr + 0.055) / 1.055) ** 2.4)
    brightest = paper.copy()
    brightest[paper] = L[paper] >= np.quantile(L[paper], PAPER_WHITE)
    white_lin = np.median(lin[brightest], axis=0)  # the colour of the paper's brightest tenth, so its hue stays even
    ink = neutral & (L < INK_MAX)
    black_lin = np.zeros(3)
    if ink.mean() >= INK_MIN:
        black_lin = ink_black(L[ink], lin[ink], lab[..., 1][ink], lab[..., 2][ink])
    out = np.clip((lin - black_lin) / np.maximum(white_lin - black_lin, 1e-3), 0, 1)
    out = np.where(out <= 0.0031308, out * 12.92, 1.055 * np.power(out, 1 / 2.4) - 0.055)
    return np.median(bgr[paper], axis=0), out.astype(np.float32)


def ink_black(L, lin, a, b):
    """The black point (linear BGR) of the ink's lightness L, colours lin and Oklab a, b (see above)."""
    edges = np.linspace(0, INK_MAX, INK_BINS + 1)
    h = np.convolve(np.histogram(L, edges)[0], np.ones(3) / 3, "same")
    peak = int(np.argmax(h))
    side = peak + next((i for i, v in enumerate(h[peak:]) if v < h[peak] / 2), len(h) - peak)
    level = min(edges[min(side, INK_BINS)], np.quantile(L, INK_BLACK) + INK_ABOVE_DARKEST)
    near = np.abs(L - level) < INK_MAX / INK_BINS / 2
    if near.any() and np.hypot(np.median(a[near]), np.median(b[near])) >= INK_HUE:  # a colour, not black ink
        return np.full(3, np.quantile(L, INK_BLACK) ** 3)
    return np.median(lin[near], axis=0) if near.any() else np.full(3, level ** 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    gen = photos.generated(args.sample)
    prints_file, solve_file = os.path.join(gen, "prints", "prints.json"), os.path.join(gen, "solve", "solve.json")
    for p in (prints_file, solve_file):
        if not os.path.exists(p):
            sys.exit(f"{p} missing: run make prints first")
    result = json.load(open(prints_file))
    solved = json.load(open(solve_file))["label_photos"]
    out_dir = os.path.join(gen, "restore")
    os.makedirs(out_dir, exist_ok=True)
    base = lambda pid: os.path.join(out_dir, straighten.file_name(pid)[:-5])
    newest = max(os.path.getmtime(p) for p in (prints_file, solve_file, __file__, cuts.__file__, descreen.__file__))
    mtime = lambda f: os.path.getmtime(f) if os.path.exists(f) else 0
    jobs, wanted = [], set()
    for pid, job in print_jobs(gen, result, solved).items():
        wanted |= {os.path.basename(base(pid)) + s for s in (".avif", ".json")}
        inputs = max([newest] + [max(mtime(f), mtime(straighten.cut_file(f))) for _, f in job[2]])
        if not os.path.exists(base(pid) + ".avif") or os.path.getmtime(base(pid) + ".avif") < inputs:
            jobs.append(job + (base(pid),))
    for f in os.listdir(out_dir):
        if f not in wanted and f != "index.html":
            os.remove(os.path.join(out_dir, f))
    import multiprocessing
    with multiprocessing.Pool(args.workers) as pool:
        for n, (pid, desc) in enumerate(pool.imap_unordered(restore_print, jobs), 1):
            if desc is not None:
                steps.write_json(base(pid) + ".json", desc)
            if n % 20 == 0 or n == len(jobs):
                print(f"restored {n} of {len(jobs)} prints", flush=True)
    page(out_dir, result, gen)
    print(f"page: {os.path.join(out_dir, 'index.html')}")


def print_jobs(gen, result, solved):
    """print id -> restore_print's job but its output path: (id, shape, own [(key, image)], px per mm {key: ...},
    the approximate cuts {key}, crop, joined across families). Poor fits are left out; a print with fewer than MIN_PHOTOS others, or
    MIN_PRECISE that aren't approximate cuts, isn't restored at all (the user: fewer prints, all of them good, rather
    than bad ones among them)."""
    info = fit_info(gen, solved)
    _, poor, approximate, _, _ = info
    by_family = {}
    for p in result["prints"]:
        by_family.setdefault(p["family"], []).append(p)
    crops = {}
    for fam, ps in by_family.items():
        # the crop from the precise cuts where there are any
        keys = ([k for p in ps for k in p["keys"] if k not in poor and k not in approximate]
                or [k for p in ps for k in p["keys"] if k not in poor] or [k for p in ps for k in p["keys"]])
        found = [c for c in (straighten.load_cut(gen, k) for k in keys) if c is not None]
        crops[fam] = (cuts.crop(found, ps[0]["shape"], straighten.PX_PER_MM, straighten.MARGIN) if found
                      else canonical_crop(ps[0]["shape"]))
    frozen_tags = {}  # serial -> the tags of its frozen prints ("" for none)
    for p in result["prints"]:
        if p.get("frozen") and p.get("serial"):
            frozen_tags.setdefault(p["serial"], set()).add(p.get("tag") or "")
    jobs = {}
    for p in result["prints"]:
        if p.get("frozen"):  # its image is the frozen one (src/frozen.py): restored again only by make refreeze
            continue
        if p.get("several_serials"):  # its label photos read several serials: to be fixed by hand first (stored-prints.md)
            continue
        tags = frozen_tags.get(p.get("serial"))
        if tags and (not p.get("tag") or p["tag"] in tags):  # a frozen print of its serial and tag is done (the user,
            continue                                          # 2026-11-23); an untagged print is any print of its serial
        job = job_of(p, info, crops[p["family"]])
        if job:
            jobs[p["id"]] = job
    return jobs


def fit_info(gen, solved):
    """(px per mm {key: the photo's pixels per mm at the label, from the fit}, poor fits {key}, approximate cuts {key},
    key -> its straightened image, the shape each was fitted as {key: shape})."""
    import solve as solve_step
    px_per_mm = {}
    for k, r in solved.items():
        lw, lh = shapes.LABEL_MM[r["shape"]]
        px_per_mm[k] = solve_step.local_scale(np.array(r["cut_to_photo"]), [0, 0, lw, lh])
    poor = {k for k, r in solved.items() if solve_step.poor_fit(r)}
    approximate = {k for k, r in solved.items() if solve_step.approximate_cut(r)}
    return (px_per_mm, poor, approximate, lambda k: os.path.join(gen, "straighten", straighten.file_name(k)),
            {k: r["shape"] for k, r in solved.items()})


def job_of(p, info, crop):
    """A print's job for restore_print but its output path, or None if it has too few label photos to restore."""
    px_per_mm, poor, approximate, image, shape_of = info
    # a label photo fitted as another shape than the print's (joined by hand: a CGB label fitted as DMG, 2026-11-14)
    # is straightened to another size and can't be combined: left out, like a poor fit
    other = [k for k in p["keys"] if shape_of.get(k) != p["shape"]]
    if other:
        print(f"{p['id']}: left out, fitted as another shape than the print's {p['shape']}: "
              + ", ".join(f"{k} ({shape_of.get(k)})" for k in other), flush=True)
    own = [(k, image(k)) for k in p["keys"] if k not in poor and k not in other]
    if len(own) < MIN_PHOTOS or sum(k not in approximate for k, _ in own) < MIN_PRECISE:
        return None
    return (p["id"], p["shape"], own, px_per_mm, approximate & {k for k, _ in own}, crop, len(p.get("families", [])) > 1)


def page(out_dir, result, gen):
    """index.html: per print, the restored image (paper white where found, else median colours), and its label photos
    straightened (the same crop)."""
    P, M = straighten.PX_PER_MM, straighten.MARGIN
    rel = os.path.relpath(os.path.join(gen, "straighten"), out_dir)
    figs = []
    for p in sorted(result["prints"], key=lambda p: -len(p["keys"])):
        b = straighten.file_name(p["id"])[:-5]
        if not os.path.exists(os.path.join(out_dir, b + ".avif")):
            continue
        desc = json.load(open(os.path.join(out_dir, b + ".json"))) if os.path.exists(os.path.join(out_dir, b + ".json")) else {}
        c = desc.get("crop") or canonical_crop(p["shape"])
        (cw, ch), _ = straighten.canvas(p["shape"])
        # a straightened label photo cropped by CSS: the image scaled so the crop is 160 px wide
        scale = 160 / c["w"]
        crop = lambda k: (f'<div class="src" style="width:{c["w"] * scale:.0f}px;height:{c["h"] * scale:.0f}px">'
                          f'<img loading="lazy" src="{rel}/{straighten.file_name(k)}" style="width:{cw * scale:.0f}px;'
                          f'margin:{-c["y"] * scale:.0f}px 0 0 {-c["x"] * scale:.0f}px"></div>')
        sources = "".join(crop(k) for k in desc.get("keys", [])[:steps.PAGE_SOURCES]) + steps.more(len(desc.get("keys", [])))
        figs.append(f'<figure><div class="pair"><img loading="lazy" src="{b}.avif"></div>'
                    f'<figcaption><b>{html.escape(str(p["serial"] or p["release"] or "?"))}</b>: {len(desc.get("keys", []))} label photos ({len(desc.get("approximate", []))} approximate cuts)'
                    f'{"" if desc.get("paper") else "; no paper found: median colours"}; label photos per band, finest first: {desc.get("bands")}</figcaption>'
                    f'<div class="sources">{sources}</div></figure>')
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>restore</title>
<style>body{{font:14px system-ui;margin:16px;background:#333;color:#eee}} figure{{display:block;margin:12px 0 24px}} .pair img{{width:340px;margin-right:6px}}
figcaption{{font-size:12px;margin:4px 0}} .src{{display:inline-block;overflow:hidden;margin:2px}} .src img{{display:block}}</style>
<h1>restore</h1>
<p>{steps.shown(len(figs))} restored prints, the most label photos first. The restored print: the median of its label photos per band, their colours evened to their median, then its paper made white (clipping a little) where paper is found. Below: its label photos straightened, the same crop.</p>
{"".join(steps.few(figs))}""")


if __name__ == "__main__":
    main()
