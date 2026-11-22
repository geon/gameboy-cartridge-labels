# optimize: review-prints' Optimize tab's measures and would-be restores (the user, 2026-11-22). Not a step: run by
# review-prints in background processes, cached in <generated>/review-prints/optimize/ (no step reads or writes it).
# Per label photo of a restored print, against the restored image (generated/restore/<print>.avif), its straightened image
# cropped and masked as restore does, its colours evened to the restored image (restore.even_to):
#   - detail: how much of the restored image's fine detail (lightness, a difference of Gaussians of DETAIL_SIGMAS px)
#     the label photo carries: the gain of its fine detail projected on the restored image's, 0..1. Low resolution and
#     blur both lower it (the user: the distinction isn't meaningful, the effect is the same); noise and dirt don't
#     raise it, being uncorrelated with the restored image.
#   - divergence: the mean Oklab distance between it and the restored image, both blurred over DIVERGENCE_MM (so fine
#     misregistration and the print screen don't count): glare, dirt, stickers, another print.
#   - badness: (1 - detail) + min(1, divergence / DIVERGENCE_SCALE), 0..2. A label photo covering under MIN_COVER of
#     the crop, or with no straightened image, counts as 2.
# The proposal: the label photos restore can't use (a poor fit, another shape than the print's) left out, and of the
# others the worse half by badness, keeping at least restore.MIN_PHOTOS, restore.MIN_PRECISE of them not approximate
# cuts. A print's total badness: the sum over the label photos the proposal leaves out (the tab's order, the most first).
import hashlib, json, multiprocessing, os, sys, threading
import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import restore, straighten, cuts

DETAIL_SIGMAS = (1.0, 3.0)
DIVERGENCE_MM = 0.5
DIVERGENCE_SCALE = 0.08
MIN_COVER = 0.1
EDGE_PX = 6  # the valid area shrunk this much, so its border (filled, or the cut's edge) doesn't count
WORST = 2.0


def folder(gen):
    return os.path.join(gen, "review-prints", "optimize")


def badness(m):
    if m is None or m.get("detail") is None:
        return WORST
    return round((1 - min(1.0, max(0.0, m["detail"]))) + min(1.0, m["divergence"] / DIVERGENCE_SCALE), 3)


def measure(job):
    """(print id, {key: {"detail", "divergence", "cover"} or None}, the restored image's mtime) for job:
    (print id, restored image path, crop, shape, [(key, straightened image path, approximate)])."""
    pid, restored_path, crop, shape, keys = job
    mtime = os.path.getmtime(restored_path)
    R = cv2.imread(restored_path)
    if R is None:
        return pid, None, mtime
    R = R.astype(np.float32) / 255
    x0, y0, w, h = crop["x"], crop["y"], crop["w"], crop["h"]
    size, px_to_mm = straighten.canvas(shape)
    R_lab = restore.to_oklab(R)
    hp = lambda L: cv2.GaussianBlur(L, (0, 0), DETAIL_SIGMAS[0]) - cv2.GaussianBlur(L, (0, 0), DETAIL_SIGMAS[1])
    R_hp = hp(R_lab[..., 0])
    sigma = DIVERGENCE_MM * straighten.PX_PER_MM
    R_low = cv2.GaussianBlur(R_lab, (0, 0), sigma)
    out = {}
    for key, path, approximate in keys:
        img = cv2.imread(path)
        if img is None:
            out[key] = None
            continue
        if img.shape[:2] != (size[1], size[0]):  # straightened as another shape than the print's: restore can't use it
            out[key] = {"detail": None, "divergence": None, "cover": 0.0}
            continue
        valid = img.max(2) > 1
        cut = straighten.load_cut(os.path.dirname(os.path.dirname(path)), key)
        if cut is not None:
            valid &= cuts.mask(cut, shape, size, px_to_mm, cuts.INSET + (restore.APPROXIMATE_INSET if approximate else 0))
        img = img[y0:y0 + h, x0:x0 + w].astype(np.float32) / 255
        valid = valid[y0:y0 + h, x0:x0 + w]
        if img.shape != R.shape:
            out[key] = None
            continue
        inner = cv2.erode(valid.astype(np.uint8), np.ones((2 * EDGE_PX + 1, 2 * EDGE_PX + 1), np.uint8)) > 0
        cover = float(inner.mean())
        if cover < MIN_COVER:
            out[key] = {"detail": None, "divergence": None, "cover": round(cover, 3)}
            continue
        lab = restore.to_oklab(restore.even_to(restore.filled(img, valid), R, inner))
        I_hp = hp(lab[..., 0])
        denom = float((R_hp[inner] ** 2).sum())
        detail = float((I_hp[inner] * R_hp[inner]).sum()) / denom if denom > 0 else 0.0
        diff = np.linalg.norm(cv2.GaussianBlur(lab, (0, 0), sigma) - R_low, axis=2)
        out[key] = {"detail": round(detail, 3), "divergence": round(float(diff[inner].mean()), 4), "cover": round(cover, 3)}
    return pid, out, mtime


def proposal(keys, bad, usable, approximate):
    """The label photos the proposal keeps: of the usable ones, the better half by badness, at least restore.MIN_PHOTOS
    with restore.MIN_PRECISE not approximate cuts (all of them if there aren't that many)."""
    ranked = sorted((k for k in keys if k in usable), key=lambda k: (bad[k], k))
    n = max(restore.MIN_PHOTOS, (len(ranked) + 1) // 2)
    keep = ranked[:n]
    for k in ranked[n:]:
        if sum(1 for q in keep if q not in approximate) >= restore.MIN_PRECISE:
            break
        if k not in approximate:
            keep.append(k)
    return keep


def key_hash(keys):
    return hashlib.sha1(",".join(sorted(keys)).encode()).hexdigest()[:16]


def would_be(job):
    """restore.restore_print's job for these label photos, written to out_base (.avif, and .json: its description):
    (print id, the description, or None if too few label photos)."""
    pid, desc = restore.restore_print(job)
    out_base = job[-1]
    if desc is not None:
        tmp = out_base + ".json.tmp"
        with open(tmp, "w") as f:
            json.dump(desc, f)
        os.replace(tmp, out_base + ".json")
    return pid, desc


def nice():
    """The background processes' initializer: low priority, so a running make isn't slowed much."""
    try:
        os.nice(10)
    except OSError:
        pass
    cv2.setNumThreads(1)


def _would_be_child(job, conn):
    nice()
    try:
        conn.send(("ok", would_be(job)))
    except Exception as e:
        conn.send(("error", repr(e)))
    conn.close()


class Restore:
    """would_be(job) in a process of its own, so it can be killed when superseded (a process pool can't stop a running
    job: the user, 2026-11-22). Killed before it writes its .json, nothing partial is kept (would_be writes it last,
    via a temporary file). wait() -> would_be's answer; raises Superseded if killed."""
    class Superseded(Exception):
        pass

    def __init__(self, job):
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe(duplex=False)
        self.proc = ctx.Process(target=_would_be_child, args=(job, child), daemon=True)
        self.proc.start()
        child.close()  # the parent's copy: a killed child then reads as EOF
        self.done, self.answer = threading.Event(), None
        def reader():
            try:
                self.answer = parent.recv()
            except (EOFError, OSError):
                self.answer = ("superseded", None)
            parent.close()
            self.proc.join()
            self.done.set()
        threading.Thread(target=reader, daemon=True).start()

    def kill(self):
        if self.proc.is_alive():
            self.proc.kill()

    def wait(self):
        self.done.wait()
        kind, value = self.answer
        if kind == "ok":
            return value
        if kind == "superseded":
            raise Restore.Superseded()
        raise RuntimeError(value)
