import csv, re, warnings, cv2, numpy as np

# The models of the Game Boy cartridges' shells, and fitting one to a photo, for fit-cartridge (src/fit_cartridge.py):
# started from the text read on the photo (or from the outlines in it), points on the model's edges look along their
# normals for the strongest change, and the model's pose (mm -> photo pixels) is fitted to them. Three shells (Shell): the Game Boy's (DMG), which
# Game Boy Color games that also play on a Game Boy came in too, the clear Game Boy Color only cartridge's (CGB,
# serials CGB-...), and the Game Boy Advance's (AGB, serials AGB-...). In millimetres on the cartridge's front (origin top left of the body, x right, y down): the DMG's
# body 57 x 65, recess 44 x 39 inset 6.5 from the sides and 18 from the top, label 42.5 x 37 (a canonical size, LABEL)
# centered in the recess.
# Only the plastic's pose is fitted: labels are stuck on a little shifted and turned, so their edges only help to get
# close.

BODY = (57.0, 65.0)
RECESS = (6.5, 18.0, 50.5, 57.0)
# The label: a canonical size, as the labels all differ (on 20 hand-placed ones 41.7 to 42.5 wide, median about 42.15,
# and 36.8 to 37.2 high): 42.5 x 37, round numbers, centered in the recess, 0.75 from its sides and 1 from its top and
# bottom.
LABEL = (7.25, 19.0, 49.75, 56.0)
# The recess's corners' radius: an arc and two straight sides fitted to the wall at each corner, warped to mm through a
# good fit (IMG_7477: 0.95 to 1.15 mm).
RECESS_RADIUS = 1.05


# Cartridges whose shell isn't this one (rumble, tilt sensor, infrared...), listed by hand: game code -> shell.
SPECIAL_SHELLS = "special-shells.tsv"


def special_shell(serial):
    """What is special about the shell of the cartridge with this serial or release id (special-shells.tsv), or None."""
    rows = csv.DictReader((l for l in open(SPECIAL_SHELLS) if not l.startswith("#")), delimiter="\t")
    return next((r["shell"] for r in rows if re.match(re.escape(r["code"]) + r"[A-Z]?(-|$)", serial)), None)


def corners_of(rect):
    x1, y1, x2, y2 = rect
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], np.float64)


# The embossed "Nintendo GAME BOY™" in the pill, as macOS's text recognition boxes the line (tools/ocr.swift): through
# 72 unflagged fits of my photos (2026-10-22) it was found in all, its box's corners within 0.15 mm (middle half) of
# x 10.7 to 46.5 and y 8.5 to 12.5 mm, though the text is read garbled ("NinteendeGAME BOYT"). The line's left end moves
# when label text beside it is read into it ("しれてたしさしたさにGAIME BOY TT"), so starts use its right end (the ™):
# the middle of its right edge at 46.48, 10.57 (10 to 90 %: x 46.26 to 46.75, y 10.36 to 10.79), and its height, 3.95
# mm (10 to 90 %: 3.81 to 4.34).
EMBOSS = (10.68, 8.5, 46.47, 12.5)
EMBOSS_RIGHT = (46.48, 10.57)
EMBOSS_HEIGHT = 3.95


def emboss_lines(lines, count=3):
    """Of the OCR's lines ({"text", "quad"}), the few most like the embossed "Nintendo GAME BOY", best first: other lines
    can read alike (e.g. "©1993 Nintendo MADE IN JAPAN"), so each is tried as a start. Lines with "COLOR" are left out:
    on black cartridges the embossing is often too faint to read, and the label's "GAME BOY COLOR" (along its left
    side, turned 90 degrees) was taken for it."""
    import difflib, re
    letters = lambda t: re.sub(r"[^A-Za-z]", "", t).upper()
    score = lambda t: difflib.SequenceMatcher(None, letters(t), "NINTENDOGAMEBOY").ratio()
    lines = [l for l in lines if "COLO" not in letters(l["text"]) and "OLOR" not in letters(l["text"])]
    return sorted((l for l in lines if score(l["text"]) >= 0.4), key=lambda l: -score(l["text"]))[:count]


def emboss_start(line, scale=1.0, dy=0.0):
    """A start for the fit from the embossed line's quadrilateral (top left, top right, bottom right, bottom left): a
    similarity taking EMBOSS_RIGHT to the middle of its right edge, turned along its top edge, EMBOSS_HEIGHT to the right
    edge's length times scale, and shifted dy mm down."""
    q = np.array(line["quad"], np.float64)
    u = (q[1] - q[0]) / np.linalg.norm(q[1] - q[0])
    n = np.array([-u[1], u[0]])  # down the text
    s = np.linalg.norm(q[2] - q[1]) / EMBOSS_HEIGHT * scale
    A = s * np.c_[u, n]
    t = (q[1] + q[2]) / 2 - A @ (np.array(EMBOSS_RIGHT) + [0, dy])
    return np.vstack([np.c_[A, t], [0, 0, 1]])


# "GAME BOY COLOR" along the left side of the labels of cartridges that also play on a Game Boy Color (often black ones,
# whose embossing is too faint to read): read upward, so the text's box (top left, top right, bottom right, bottom left
# as it reads) lies at these corners, through 13 unflagged fits of my photos (2026-10-22; 10 to 90 % within about 1 mm,
# as labels are stuck on a little shifted).
COLOR_TEXT = np.array([[8.77, 53.32], [8.9, 21.75], [13.11, 21.75], [13.08, 53.35]])


def color_lines(lines):
    """Of the OCR's lines, those reading "GAME BOY COLOR"."""
    import re
    letters = lambda t: re.sub(r"[^A-Za-z]", "", t).upper()
    return [l for l in lines if ("COLO" in letters(l["text"]) or "OLOR" in letters(l["text"])) and ("BOY" in letters(l["text"]) or "GAME" in letters(l["text"]))]


def color_start(line, scale=1.0, dy=0.0, angle=0.0, text=COLOR_TEXT):
    """A start for the fit from a "GAME BOY COLOR" line: the similarity (least squares) taking the text's corners in mm
    (COLOR_TEXT on DMG cartridges) to its quadrilateral, scaled by scale and turned by angle (degrees) about the text's
    center, and shifted dy mm down."""
    mm = np.asarray(text) - [0, dy]
    c = mm.mean(axis=0)
    a = np.radians(angle)
    mm = c + (mm - c) @ np.array([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]]) * scale
    return similarity(mm, line["quad"])


def similarity(mm, photo):
    """The similarity (least squares) taking points in mm to points in the photo, as a homography."""
    mm, q = np.asarray(mm, np.float64), np.asarray(photo, np.float64)
    n = len(mm)
    # x' = a x - b y + tx, y' = b x + a y + ty
    A = np.vstack([np.c_[mm[:, 0], -mm[:, 1], np.ones(n), np.zeros(n)], np.c_[mm[:, 1], mm[:, 0], np.zeros(n), np.ones(n)]])
    a, b, tx, ty = np.linalg.lstsq(A, np.r_[q[:, 0], q[:, 1]], rcond=None)[0]
    return np.array([[a, -b, tx], [b, a, ty], [0, 0, 1]])


def turn(H):
    """The turn of a similarity (or a near one), in degrees."""
    return float(np.degrees(np.arctan2(H[1, 0], H[0, 0])))


# Texts along the label's grey side strips (US and European labels), as read on 111 unflagged fits of my photos
# (2026-10-22): the text's box (as it reads) at these corners. Across the strip they lie within about 0.5 mm (10 to
# 90 %), along it within 3 to 7 mm, as the texts differ in length; they fix where the label's sides are, and its turn.
# "MADE IN JAPAN" also stands anywhere, level, on Japanese labels, so it is only used running down (turned 90 degrees
# from the embossed line, when that is read). "THIS SIDE OUT" was read on only 6 of about 15 labels with it.
STRIP_TEXTS = {
    # Down the left strip: the serial with its region (DMG-ASWP-EUR, DMG-ML-SCN).
    "serial": np.array([[10.61, 21.59], [10.65, 34.15], [8.83, 34.15], [8.87, 21.58]]),
    # Down the left strip, below the serial.
    "made in japan": np.array([[10.74, 39.7], [10.68, 54.04], [9.06, 54.03], [9.12, 39.61]]),
    # Up the right strip.
    "this side out": np.array([[45.58, 53.11], [45.43, 44.49], [46.65, 44.48], [46.81, 53.12]]),
}


def strip_lines(lines):
    """Of the OCR's lines, those reading one of STRIP_TEXTS, as (kind, line)."""
    import difflib, re
    letters = lambda t: re.sub(r"[^A-Za-z]", "", t).upper()
    sim = lambda a, b: difflib.SequenceMatcher(None, a, b).ratio()
    found = []
    for l in lines:
        t = letters(l["text"])
        if re.match(r"DMG[A-Z0-9]{1,5}(NOE|USA|EUR|UKV|SCN|FRG|FAH|ESP|ITA|GPS|AUS|EUU|HOL|FRA|CAN|SWE)", t):
            found.append(("serial", l))
        elif sim(t, "MADEINJAPAN") >= 0.7:
            found.append(("made in japan", l))
        elif sim(t, "THISSIDEOUT") >= 0.6:
            found.append(("this side out", l))
    return found


def text_starts(lines, shell, scales=(0.92, 1.0, 1.08), dys=(-0.5, 0.0, 0.5)):
    """Starts for the fit from the OCR's lines, each at a few scales and shifts: the embossed "Nintendo GAME BOY" (the
    few lines most like it); "GAME BOY COLOR", also turned a little (its box's turn was several degrees off on black
    cartridges); and, only when no embossed line is read, the strip texts. Strip texts as starts beside the embossed
    line (also one similarity through all their points) found no better fits, only rivals a few mm away that flagged
    good fits as ambiguous: on my photos 111 -> 113 unflagged, on those found online 41 -> 41, and the excellent
    DMG-CJ_2 lost. A strip text's start is dropped when it turns the cartridge over 45 degrees from upright: read
    upside down, or "MADE IN JAPAN" standing level on a Japanese label. On the CGB's shell only "GAME BOY COLOR", where
    it lies on that shell's label: the others aren't measured there. On the AGB's the embossed "GAME BOY ADVANCE" (the
    few lines most like it), at wider scales and shifts, as its size and place are rough."""
    if shell.name == "agb":
        return [agb_logo_start(l, s, d) for l in agb_logo_lines(lines)[:3] for s in (0.85, 1.0, 1.15) for d in (-1.0, 0.0, 1.0)]
    if shell.name == "cgb":
        return [color_start(l, s, d, a, shell.color_text) for l in color_lines(lines) for s in scales for d in dys for a in (-6, -3, 0, 3, 6)]
    emboss = emboss_lines(lines)
    starts = [emboss_start(l, s, d) for l in emboss for s in scales for d in dys]
    starts += [color_start(l, s, d, a) for l in color_lines(lines) for s in scales for d in dys for a in (-6, -3, 0, 3, 6)]
    if not emboss:
        for kind, l in strip_lines(lines):
            mm = STRIP_TEXTS[kind]
            if abs((turn(similarity(mm, l["quad"])) + 180) % 360 - 180) >= 45:
                continue
            c = mm.mean(axis=0)
            starts += [similarity(c + (mm - c) * s - [0, d], l["quad"]) for s in scales for d in (-2.0, 0.0, 2.0)]
    return starts


def edges_of(rect):
    x1, y1, x2, y2 = rect
    # (start, end, outward normal) per side: top, right, bottom, left.
    return [((x1, y1), (x2, y1), (0, -1)), ((x2, y1), (x2, y2), (1, 0)), ((x2, y2), (x1, y2), (0, 1)), ((x1, y2), (x1, y1), (-1, 0))]


# The edges of the cartridge's front face, the plane the label lies in: the top edge left of the notch (5 mm wide and
# 3 mm deep at the top right), the sides, and the bottom edge between the rounded corners. Along the lower 38 mm (below
# 27 mm, the part that goes into the Game Boy) the sides step in by 0.3 mm and are bevelled, the bevel's inner edge
# about 1.7 mm in from the upper side. That inner edge is in the face, but it is faint in photos, and fitting it
# instead of the outer edge was less precise (at 1.7 mm in: 32 instead of 40 fits within 0.3 mm, both 50 within 1 mm); leaving the lower sides out was
# much worse. So the lower sides are the outer edge: through the hand-placed recesses it was found within 0.02 mm of
# there (median), on these nearly head-on photos. The notch's edges made the fits a little worse (33 instead of 36
# within 0.3 mm), so they are left out.
FACE_RUNS = [
    ((2.0, 0.0), (50.0, 0.0), (0, -1)),
    ((56.85, 4.0), (56.85, 25.0), (1, 0)),
    ((56.55, 29.0), (56.55, 62.0), (1, 0)),
    ((54.0, 64.85), (3.0, 64.85), (0, 1)),
    ((0.3, 62.0), (0.3, 29.0), (-1, 0)),
    ((0.0, 25.0), (0.0, 4.0), (-1, 0)),
]


# The embossed arrow below the label, pointing at the slot: a triangle with rounded corners, its top edge 1 mm below
# the recess (8.3 mm wide where visible, measured with calipers), its tip 87 degrees (game-boy-database.com scans lined up
# on it). As sharp lines: the top edge and the two diagonals, sampled away from the
# rounded corners. Steps: the arrow's walls are lit or shaded.
ARROW_TOP = 58.0
ARROW_HALF_WIDTH = 4.9  # at the top edge, sharp corners (the visible 8.3 mm less the rounding)
ARROW_HALF_ANGLE = np.radians(43.5)
ARROW_TIP = (28.5, ARROW_TOP + ARROW_HALF_WIDTH / np.tan(ARROW_HALF_ANGLE))
ARROW_EDGES = [
    ((28.5 - ARROW_HALF_WIDTH, ARROW_TOP), (28.5 + ARROW_HALF_WIDTH, ARROW_TOP), (0, -1)),
    ((28.5 + ARROW_HALF_WIDTH, ARROW_TOP), ARROW_TIP, (np.cos(ARROW_HALF_ANGLE), np.sin(ARROW_HALF_ANGLE))),
    (ARROW_TIP, (28.5 - ARROW_HALF_WIDTH, ARROW_TOP), (-np.cos(ARROW_HALF_ANGLE), np.sin(ARROW_HALF_ANGLE))),
]


# The pill-shaped cavity with the embossed "Nintendo GAME BOY" above the label: 44.2 x 12 mm, its top 4 mm below the
# body's top and its bottom 2 mm above the recess (calipers), centered like the recess; the ends are half circles
# (checked against game-boy-database.com scans). Sampled as steps along its outline, the text inside left out.
PILL = (28.5 - 22.1, 4.0, 28.5 + 22.1, 16.0)
PILL_RADIUS = 6.0


def pill_samples():
    """Points on the pill's outline (mm) and their outward normals: the straight top and bottom, and the ends."""
    x1, y1, x2, y2 = PILL
    cy = (y1 + y2) / 2
    points, normals = [], []
    for x in np.linspace(x1 + PILL_RADIUS + 1, x2 - PILL_RADIUS - 1, 16):
        points += [(x, y1), (x, y2)]
        normals += [(0, -1), (0, 1)]
    for cx, angles in ((x1 + PILL_RADIUS, np.radians(np.linspace(110, 250, 6))), (x2 - PILL_RADIUS, np.radians(np.linspace(-70, 70, 6)))):
        for a in angles:
            points.append((cx + PILL_RADIUS * np.cos(a), cy + PILL_RADIUS * np.sin(a)))
            normals.append((np.cos(a), np.sin(a)))
    return np.array(points), np.array(normals)


# The grooves beside the pill, 5 on each side: 2 mm apart, centered on the pill's middle (10 mm down), 1.2 mm wide;
# each runs from the face's side edge to 1 mm from the pill's half circle. From 20 hand-placed edges on each side of
# three photos (experiments: pitch 2.01 mm, centre 9.87, width 1.15, gap to the pill 0.99, median).
GROOVE_PITCH, GROOVE_WIDTH, GROOVE_GAP = 2.0, 1.2, 1.0


def groove_edges():
    """The grooves' edges in mm: [(outer end, inner end)] x 20, top edge then bottom edge, left side's grooves first."""
    cy = (PILL[1] + PILL[3]) / 2
    r = PILL_RADIUS + GROOVE_GAP
    edges = []
    for outer_x, center_x, sign in ((0.0, PILL[0] + PILL_RADIUS, -1), (56.85, PILL[2] - PILL_RADIUS, 1)):
        for k in range(-2, 3):
            for y in (cy + k * GROOVE_PITCH - GROOVE_WIDTH / 2, cy + k * GROOVE_PITCH + GROOVE_WIDTH / 2):
                inner_x = center_x + sign * np.sqrt(r * r - (y - cy) ** 2)
                edges.append((np.array([outer_x, y]), np.array([inner_x, y])))
    return edges


def build_samples(recess=RECESS, label=LABEL, arrow_edges=ARROW_EDGES, pill=True, grooves=True, face_runs=FACE_RUNS, face_points=None,
                  recess_radius=RECESS_RADIUS):
    """Sample points (mm), their outward normals, and their kind: "recess" (a thin line: plastic on both sides of the
    wall), "label", "arrow", "pill", "groove" or "face" (steps; face_points: more of them, (points, normals)). By default
    the DMG's.
    The label's sides are sampled along their middle 70 %, clear of its rounded corners. With recess_radius, the
    recess's sides run to within 1.5 mm of its corners, as densely, and each rounded corner has 3 samples of its own
    (radial, as on the pill's ends); without, its middle 70 % too. On the photos with a fit placed by hand (2026-10-29),
    that brought 90 of 142 fits within 0.3 mm of it instead of 70 (108 within 1 mm instead of 88), and 122 of 278 known
    good photos unflagged instead of 55. On the CGB's shell it didn't help (its corners' radius isn't measured), nor did
    the bevel line along the DMG's lower sides as more samples (66 within 0.3 mm)."""
    samples = []
    for a, b, n in edges_of(label):
        for t in np.linspace(0.15, 0.85, 18):
            samples.append(((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), n, "label"))
    for a, b, n in edges_of(recess):
        length = np.hypot(b[0] - a[0], b[1] - a[1])
        ends, count = (1.5 / length, round((length - 3.0) * 18 / (0.7 * 44.0))) if recess_radius else (0.15, 18)
        for t in np.linspace(ends, 1 - ends, count):
            samples.append(((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), n, "recess"))
    if recess_radius:
        x1, y1, x2, y2 = recess
        r = recess_radius
        for (cx, cy), a0 in (((x1 + r, y1 + r), np.pi), ((x2 - r, y1 + r), 1.5 * np.pi), ((x2 - r, y2 - r), 0.0), ((x1 + r, y2 - r), 0.5 * np.pi)):
            for t in np.linspace(a0 + np.pi / 8, a0 + 3 * np.pi / 8, 3):
                samples.append(((cx + r * np.cos(t), cy + r * np.sin(t)), (np.cos(t), np.sin(t)), "recess"))
    for a, b, n in arrow_edges:
        for t in np.linspace(0.3, 0.7, 8):
            samples.append(((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), n, "arrow"))
    for point, n in zip(*pill_samples()) if pill else ():
        samples.append((tuple(point), tuple(n), "pill"))
    for a, b in groove_edges() if grooves else ():
        # Steps across each edge, away from the ends (the search looks both ways, so the normal's sign doesn't matter).
        for t in np.linspace(0.15, 0.75, 4):
            samples.append((tuple(a + (b - a) * t), (0, -1), "groove"))
    for a, b, n in face_runs:
        count = max(6, int(np.hypot(b[0] - a[0], b[1] - a[1]) / 2.5))
        for t in np.linspace(0, 1, count):
            samples.append(((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), n, "face"))
    for point, n in zip(*face_points) if face_points is not None else ():
        samples.append((tuple(point), tuple(n), "face"))
    points = np.array([s[0] for s in samples], np.float64)
    normals = np.array([s[1] for s in samples], np.float64)
    kinds = np.array([s[2] for s in samples])
    return points, normals, kinds


# The clear Game Boy Color only (CGB) cartridge, as measured with calipers on one on 2026-10-16: the body 57 wide and
# 65 high in the middle, but its top bowed, 64.2 high at the corners (taken as an arc); the recess 38.5 high, 21.5 from
# the top (in the middle) and 5 from the bottom, and 43 wide, centered (measured 44.5 then, 43.7 and 43.0 on
# 2026-11-01; hard to measure; the DMG's is 44). The label, as placed by hand on 11 photos (2026-10-23): 42.9 x 37.0
# (widths 42.84 to 43.15; wider than DMG labels), centered in the recess within 0.4 mm and 0.5 degrees. Its "GAME BOY
# COLOR" down the left edge lies within about 0.8 mm of CGB_COLOR_TEXT on all of them. Both were found through fits
# made with the recess 44.5 wide, so their widths are scaled to the 43 mm recess (x 43 / 44.5 about the middle: the
# labels 41.40 to 41.70 wide, median 41.45); the top corners' radius below too, but it's left as found.
# The shell's other features aren't measured (see the arrow below).
# The body is 56.8 wide (calipers, 2026-11-04, on all three shells: 57 before), its middle at 28.5 as the recess's: its
# sides at CGB_LEFT and CGB_LEFT + 56.8. On the 209 CGB photos placed by hand, fit-cartridge's fit within 0.3 / 0.5 mm of
# the hand fit: 28 / 100 with the sides 57 apart, 47 / 111 at 56.8.
CGB_BODY = (56.8, 65.0)
CGB_LEFT = 28.5 - CGB_BODY[0] / 2
CGB_BODY_CORNER_DROP = 0.8
# The top corners' radius: 2.7 mm, the median of 66 corners on 33 photos whose fit was accepted or placed by hand
# (2026-10-29; middle half 2.6 to 2.8): a rounded corner fitted to the shell's edge against the background. The fitting
# samples stay clear of the corners, so it only shapes the outline drawn.
CGB_TOP_CORNER_RADIUS = 2.7
# The top and the sides are bevelled, 2 mm deep (measured, 2026-11-01): there the body's outline (CGB_BODY, the widest
# extent) lies 2 mm behind the front face (the bottom edge is in it), and the face ends inside it, where the bevel starts: on the sides
# about 2 mm in (the bevel looks about 45 degrees), on the top about 3 mm down (judged by eye; hard to make out).
# The bevels' inner edge as fitting samples (steps 2 mm in on the sides, 3 mm down on the top) made fits
# worse (2026-11-01, against 58 hand-placed and 108 accepted fits: within 1 mm 25 -> 21 and 79 -> 63), and in place of
# the outline's top and sides much worse.
CGB_BEVEL_DEPTH = 2.0
CGB_BEVEL_SIDE = 2.0
CGB_BEVEL_TOP = 3.0  # not drawn either: the inner edge didn't help to judge fits by eye
CGB_RECESS = (7.0, 21.5, 50.0, 60.0)
CGB_OLD_TO_43 = 43.0 / 44.5  # the label's and its text's widths, found with the recess 44.5 wide
# The label: a canonical size, as on the DMG (LABEL), as the labels differ: 41.5 x 37, round numbers within the
# scaled widths above (0.05 from their median), centered in the recess, 0.75 from all its sides.
CGB_LABEL = (7.75, 22.25, 49.25, 59.25)
# "GAME BOY COLOR" on the label: its box (top left, top right, bottom right, bottom left as it reads), median.
CGB_COLOR_TEXT = np.array([[8.18, 56.69], [8.32, 24.5], [12.85, 25.05], [12.33, 56.99]]) * [CGB_OLD_TO_43, 1] + [28.5 * (1 - CGB_OLD_TO_43), 0]
# The arrow below the recess, smaller and flatter than the DMG's. Measured with calipers (2026-11-01): its visible
# size, the rounded corners included, 6 wide and 3 tall, its top edge 1 mm below the recess. Before, judged by eye on
# photos (2026-10-23): 7 x 3, 1.2 mm below the recess. The visible size is what's measured; the sharp triangle the
# fitter samples (its sides meeting at imaginary corners) is derived from it through the corners' radii, which are
# only judged by eye (the top corners barely rounded, the tip a little more) and so the less certain part.
CGB_ARROW_VISIBLE = (6.0, 3.0)
CGB_ARROW_TOP_RADIUS = 0.15
CGB_ARROW_TIP_RADIUS = 0.25
CGB_ARROW_TOP = CGB_RECESS[3] + 1.0  # the top edge: the top corners' rounding doesn't move it


def sharp_arrow(visible_width, visible_height, top_radius, tip_radius):
    """The sharp triangle (width, height) whose corners, rounded to these radii, give this visible width and height.
    A top corner rounded by r loses r / tan(a / 2) - r of the half width (a: its angle), the tip
    r / sin(b / 2) - r of the height (b: its angle)."""
    half, height = visible_width / 2, visible_height
    for _ in range(50):
        a, b = np.arctan2(height, half), 2 * np.arctan2(half, height)
        half = visible_width / 2 + top_radius * (1 / np.tan(a / 2) - 1)
        height = visible_height + tip_radius * (1 / np.sin(b / 2) - 1)
    return 2 * half, height


CGB_ARROW_WIDTH, CGB_ARROW_HEIGHT = sharp_arrow(*CGB_ARROW_VISIBLE, CGB_ARROW_TOP_RADIUS, CGB_ARROW_TIP_RADIUS)


def cgb_top(xs):
    """The CGB body's top at xs (mm): bowed up by CGB_BODY_CORNER_DROP in the middle, a circular arc through the
    (sharp) top corners."""
    w, drop = CGB_BODY[0], CGB_BODY_CORNER_DROP
    r = ((w / 2) ** 2 + drop ** 2) / (2 * drop)
    return np.c_[xs, r - np.sqrt(r * r - (np.asarray(xs) - 28.5) ** 2)]


def cgb_corner():
    """The CGB body's top left corner's arc: its center (mm) and its angles from the side to the top (radians, y down),
    tangent to the side and to the top's tangent at the corner. The top right one is its mirror image."""
    r = CGB_TOP_CORNER_RADIUS
    slope = (cgb_top([CGB_LEFT])[0, 1] - cgb_top([CGB_LEFT + 0.01])[0, 1]) / 0.01  # the top rises toward the middle
    center = np.array([CGB_LEFT + r, CGB_BODY_CORNER_DROP - slope * r + r * np.hypot(1, slope)])  # r from the side and the top
    return center, np.pi, np.arctan2(-1, -slope) + 2 * np.pi


def cgb_body_outline(per_top=24, per_corner=8):
    """The CGB body's outline in mm, clockwise from the top left: the bowed top, its corners rounded to
    CGB_TOP_CORNER_RADIUS (cgb_corner), the sides and the bottom straight."""
    w, h, r, l = CGB_BODY[0], CGB_BODY[1], CGB_TOP_CORNER_RADIUS, CGB_LEFT
    center, a0, a1 = cgb_corner()
    left = [center + r * np.array([np.cos(t), np.sin(t)]) for t in np.linspace(a0, a1, per_corner)]
    right = [(57.0 - x, y) for x, y in left[::-1]]  # mirrored about the middle, 28.5
    return np.vstack([left, cgb_top(np.linspace(left[-1][0], 57.0 - left[-1][0], per_top)), right, [[l + w, h], [l, h]]])


def cgb_outline_points():
    """The CGB body's outline, closed, in mm, and each point's depth behind the face: its top and sides
    (cgb_body_outline) CGB_BEVEL_DEPTH behind it; its bottom edge in it, CGB_BEVEL_SIDE in from the sides (the bevels
    end there), joined to the sides' bottom ends."""
    (w, h), l = CGB_BODY, CGB_LEFT
    outline = cgb_body_outline()[:-2]  # from the left side's top round to the right side's top: without the bottom
    back = dense_line(np.vstack([[[l, h]], outline, [[l + w, h]]]))
    bottom = dense_line([[l + w - CGB_BEVEL_SIDE, h], [l + CGB_BEVEL_SIDE, h]])
    return np.vstack([back, bottom]), np.r_[np.full(len(back), CGB_BEVEL_DEPTH), np.zeros(len(bottom))]


def cgb_outline_seen(camera):
    """The CGB body's outline (cgb_outline_points) as seen in the face from the camera (camera_of)."""
    points, depths = cgb_outline_points()
    seen = points.copy()
    back = depths > 0
    seen[back] = seen_at(points[back], CGB_BEVEL_DEPTH, camera, wall=0.0, n=1.0)
    return seen


def cgb_handles():
    """The CGB's ridges' outer corners in mm (where the outer edges of the side ridges meet those of the top and bottom
    ridges): fit-by-hand's handles held them for a while (2026-11-01); unused for now, as they're seen behind the face."""
    x1, y1, x2, y2 = CGB_RIDGES_INNER
    top = y1 - CGB_RIDGE_TOP + cgb_top([x1 - CGB_RIDGE_SIDE])[0, 1] - cgb_top([28.5])[0, 1]
    return (x1 - CGB_RIDGE_SIDE, top, x2 + CGB_RIDGE_SIDE, y2 + CGB_RIDGE_TOP)


def dense_line(points, closed=False, per_mm=2):
    """Points along a polyline (mm) every 1 / per_mm mm or closer, so that it bends as it should when seen at depth."""
    points = np.asarray(points, np.float64)
    ends = np.vstack([points[1:], points[:1]]) if closed else points[1:]
    parts = [np.linspace(a, b, max(2, int(np.linalg.norm(b - a) * per_mm) + 1), endpoint=False) for a, b in zip(points, ends)]
    return np.vstack(parts + ([] if closed else [points[-1:]]))


def cgb_corner_samples(count=5, clear=np.radians(15)):
    """Points on the CGB body's rounded top corners (mm) and their outward normals, as on the pill's ends: along the
    arc, clear of its ends, where the side and the top have samples of their own."""
    center, a0, a1 = cgb_corner()
    r = CGB_TOP_CORNER_RADIUS
    points, normals = [], []
    for t in np.linspace(a0 + clear, a1 - clear, count):
        n = np.array([np.cos(t), np.sin(t)])
        points += [center + r * n, [57.0 - (center + r * n)[0], (center + r * n)[1]]]
        normals += [n, [-n[0], n[1]]]
    return np.array(points), np.array(normals)


def cgb_arrow_edges():
    """The CGB's arrow as sharp edges (top, right, left), for sampling."""
    half = CGB_ARROW_WIDTH / 2
    left, right, tip = (28.5 - half, CGB_ARROW_TOP), (28.5 + half, CGB_ARROW_TOP), (28.5, CGB_ARROW_TOP + CGB_ARROW_HEIGHT)
    a = np.arctan2(half, CGB_ARROW_HEIGHT)
    return [(left, right, (0, -1)), (right, tip, (np.cos(a), np.sin(a))), (tip, left, (-np.cos(a), np.sin(a)))]


def cgb_ridge_samples():
    """The internal ridges' edges as steps (mm, outward normals), seen flat (as if in the front face; seeing them
    through the wall made no clear difference, see below): the side ridges' outer edges from 6 to 50 mm down, the top
    ridge's both edges beside and between its gaps (following the bowed top), and the bottom ridge's both edges where
    they aren't behind the label (only beside the recess; the label hides the rest). The side ridges' inner edges are
    left out: on the photos placed by hand they were found about 0.5 mm further out than measured."""
    x1, y1, x2, y2 = CGB_RIDGES_INNER
    side, top = CGB_RIDGE_SIDE, CGB_RIDGE_TOP
    points, normals = [], []
    def add(pts, n):
        points.extend(np.asarray(pts, np.float64)); normals.extend([n] * len(pts))
    ys = np.linspace(6.0, 50.0, 12)
    add(np.c_[np.full(12, x1 - side), ys], (-1.0, 0.0))
    add(np.c_[np.full(12, x2 + side), ys], (1.0, 0.0))
    xs = np.r_[np.linspace(x1 + 1.0, CGB_RIDGE_GAPS[0][0] - 1.0, 3), np.linspace(CGB_RIDGE_GAPS[0][1] + 1.0, CGB_RIDGE_GAPS[1][0] - 1.0, 6),
               np.linspace(CGB_RIDGE_GAPS[1][1] + 1.0, x2 - 1.0, 3)]
    bow = cgb_top(xs)[:, 1] - cgb_top([28.5])[0, 1]  # the top ridge follows the bowed top; measured in the middle
    add(np.c_[xs, y1 - top + bow], (0.0, -1.0))
    add(np.c_[xs, y1 + bow], (0.0, 1.0))
    clear = 0.3  # from the side ridge and from the recess's wall
    xb = np.r_[np.linspace(x1 + clear, CGB_RECESS[0] - clear, 3), np.linspace(CGB_RECESS[2] + clear, x2 - clear, 3)]
    add(np.c_[xb, np.full(6, y2)], (0.0, -1.0))
    add(np.c_[xb, np.full(6, y2 + top)], (0.0, 1.0))
    return np.array(points), np.array(normals, np.float64)


def cgb_ridge_lines(per_mm=2):
    """The internal ridges' visible edges as open polylines in mm, for drawing: both edges of the side ridges, of the
    top ridge (closed off at its gaps) and of the bottom ridge beside the recess (the label hides the rest)."""
    x1, y1, x2, y2 = CGB_RIDGES_INNER
    side, top = CGB_RIDGE_SIDE, CGB_RIDGE_TOP
    outer_x1, outer_x2, outer_y1, outer_y2 = x1 - side, x2 + side, y1 - top, y2 + top
    bow = lambda xs: cgb_top(xs)[:, 1] - cgb_top([28.5])[0, 1]
    run = lambda a, b: np.linspace(a, b, max(2, int(abs(b - a) * per_mm) + 1))
    curve = lambda a, b, y: (lambda xs: np.c_[xs, y + bow(xs)])(run(a, b))
    (g0a, g0b), (g1a, g1b) = CGB_RIDGE_GAPS
    lines = []
    for a, b in ((outer_x1, g0a), (g0b, g1a), (g1b, outer_x2)):
        lines.append(curve(a, b, outer_y1))
    for a, b in ((x1, g0a), (g0b, g1a), (g1b, x2)):
        lines.append(curve(a, b, y1))
    for g in (g0a, g0b, g1a, g1b):  # the gaps' ends
        lines.append(np.array([[g, outer_y1 + bow([g])[0]], [g, y1 + bow([g])[0]]]))
    for x, y_top, y_bottom in ((outer_x1, outer_y1, outer_y2), (outer_x2, outer_y1, outer_y2), (x1, y1, y2), (x2, y1, y2)):
        lines.append(np.c_[np.full(2, x), [y_top + bow([x])[0], y_bottom]])
    for y, a, b in ((outer_y2, outer_x1, CGB_RECESS[0]), (y2, x1, CGB_RECESS[0]), (outer_y2, CGB_RECESS[2], outer_x2), (y2, CGB_RECESS[2], x2)):
        lines.append(np.c_[run(a, b), np.full(len(run(a, b)), y)])
    return lines


def cgb_face_points():
    """The CGB's extra face samples: its top corners' and the ridges'."""
    corners, ridges = cgb_corner_samples(), cgb_ridge_samples()
    return np.vstack([corners[0], ridges[0]]), np.vstack([corners[1], ridges[1]])


def cgb_face_runs():
    """The CGB body's edges as runs for sampling: the straight sides and bottom, and the bowed top as short chords."""
    (w, h), l = CGB_BODY, CGB_LEFT
    runs = [((l + w, 8.0), (l + w, 58.0), (1, 0)), ((l + 3.0, h), (l + w - 3.0, h), (0, 1)), ((l, 58.0), (l, 8.0), (-1, 0))]
    top = cgb_top(np.linspace(l, l + w, 9))
    runs += [(tuple(a), tuple(b), (0, -1)) for a, b in zip(top[1:-2], top[2:-1])]
    return runs


# Tried on the clear CGB shell, and left out (2026-10-29, against the fits accepted or placed by hand): what shows
# through it (the board's sides, 51.0 mm apart, as in MouseBiteLabs' KiCad replica of the original outline; its 32
# contacts below the label; its top edge; the CR1616 battery at 37.5, 16.9 mm) and the shell's internal wall (a dark
# band through the lines placed by hand: the sides at 28.5 +- 25.9 mm, the bottom at 54.25, the top 2.3 mm below the
# bowed top, with gaps from 7.2 to 19.4 mm either side of the middle). None clearly helped; all lie behind the front
# face, so on photos taken close or at an angle they show away from where the front's fit puts them (parallax).
# The depth model (camera_of, seen_at, 2026-11-01) was then tried against that: the measured ridges (as steps at their
# edges, 1.4 mm deep) and the board (its top edge and contacts, 6.3 mm deep) added to the CGB's samples, flat or seen
# through the wall, compared with the good fits (58 placed by hand, 86 accepted; within 1 mm / within 0.3 mm):
#   none (as now)               hand 11 / 2, accepted 58 / 57
#   ridges, flat                hand 23 / 2, accepted 60 / 50
#   ridges, camera 40 cm away   hand 23 / 3, accepted 57 / 47
#   ridges + board, flat        hand 24 / 2, accepted 54 / 41
#   ridges + board, 40 cm       hand 22 / 3, accepted 54 / 38   (25 cm: hand 20)
#   board, flat / 40 cm         hand 15 / 2, accepted 54 / 50  /  hand 17 / 4, accepted 43 / 38
# Seeing them through the wall made no clear difference: the ridges' shift (0.1 to 0.25 mm) is within the hand fits'
# error, and where the camera is can't be told well from the fit (camera_of, with the photo's center as the view's
# center, put it on average 74 mm below the cartridge, and lined the features up worse than taking it straight in
# front). The ridges themselves (flat) help the hard photos, at a cost on the accepted ones: taken in (cgb_ridge_samples; as built: hand 25 / 3,
# accepted 57 / 48).
# Scripts: ../gameboy-labels-archive/tools-2026-11-01/.

# The CGB shell's internal ridges, measured with calipers (2026-11-01; to 0.1 mm), in mm on the front as above: a
# rectangle of ridges, the sides 1.2 thick (outer 52.4 apart, inner 50.0, centered), the top and bottom 1.4 thick (outer
# 53.2 apart in the middle, inner 50.4). Where it lies vertically was hard to measure: the top's inner edge 3.5 below
# the body's top, the bottom's 11.5 above its bottom, which leaves 50.0 between them, not 50.4. The bottom is kept and
# the top moved up: the hand-placed band (below) had the bottom ridge's middle at 54.25 (here 54.2) and the top's at
# 2.3 (here 2.4; 2.8 had the top been kept). The top ridge has two 12 mm gaps, 14 apart in the middle, starting 7 from
# the side ridges' outer edges (7 + 12 + 14 + 12 + 7 = 52.0 of the 52.4; taken centered: 7 to 19 from the middle).
# The hand-placed band lies within 0.5 mm of all of it (sides 25.9 from the middle, gaps 7.2 to 19.4 from the middle).
CGB_RIDGE_SIDE = 1.2
CGB_RIDGE_TOP = 1.4
CGB_RIDGES_INNER = (28.5 - 25.0, 53.5 - 50.4, 28.5 + 25.0, 53.5)  # x1, y1, x2, y2 of the ridges' inner edges
CGB_RIDGE_GAPS = [(28.5 - 19.0, 28.5 - 7.0), (28.5 + 7.0, 28.5 + 19.0)]  # x ranges of the top ridge's gaps
# Depths behind the front face (mm). The shell is 8.5 thick, front face to back, its walls 1.4 thick; the board
# (0.8 thick) lies on the back wall, so its front (the contacts' plane) is 2.2 from the back: 6.3 behind the face. The
# ridges show where they meet the front wall's inside: 1.4 behind the face. The recess is 0.2 deep (the DMG's too).
# These are true depths; seen through the front wall they look shallower (refraction, worked out 2026-11-01): straight
# on, a feature behind the 1.4 mm wall looks 1.4 / n deep instead (n about 1.5 to 1.6 for clear plastic), so both the
# ridges (about 0.9) and the board (about 5.8) look about 0.5 mm shallower than they are. At an angle that moves them in
# the photo by about 0.5 x tan(angle): 0.1 mm at 10 degrees, 0.2 at 20, 0.3 at 30 (as much as a good fit's error), so
# it is worth modelling; which plastic barely matters (acrylic 1.49 or polycarbonate 1.585: under 0.05 mm apart at 30
# degrees). Plan: give each feature its depth, fit a real camera pose (rotation, translation, focal length) instead of a
# homography, and bend each line of sight through the 1.4 mm front wall by Snell's law, n = 1.5.
CGB_REFRACTIVE_INDEX = 1.5
CGB_THICKNESS = 8.5
CGB_WALL = 1.4
CGB_BOARD_DEPTH = CGB_THICKNESS - CGB_WALL - 0.8
CGB_RIDGE_DEPTH = CGB_WALL
RECESS_DEPTH = 0.2


# The Game Boy Advance (AGB) cartridge (agb-shell.md), by hand with calipers (2026-11-04): the body 56.8 wide (as the
# DMG's and CGB's) and 34.5 high, with a shoulder sticking out 1.6 on each side along its top (60.0 wide there: x from
# -1.5 to 58.5; the body's middle at 28.5, as the recess's, so its sides at 0.1 and 56.9: AGB_LEFT); its top, sides and shoulders bevelled, 2 mm (AGB_BEVEL). The
# recess 44 x 23 (calipers at 44.5 don't fit in, 44.0 and 23 are a bit tight, 22.5 has room), centered. The rest
# measured on 51 photos whose recess I placed by hand (2026-11-04; edges in the photos straightened through that fit,
# medians; the middle half of the photos within about 0.1 mm), in the recess's frame:
#   - the outline (behind the face, at the bevel's back) looks 1.3 to 1.5 % smaller than 56.8 x 34.5 and 60 at the
#     shoulders (56.06 x 34.0, 59.30; the DMG's, whose face runs to its edge, 56.78 x 64.71 on 60 photos placed by
#     hand): seen from about 13 to 15 cm (2 mm deep), as 37 of them are otakaraou's close-ups. Fitted at that size
#     (AGB_OUTLINE_SEEN, 0.987, their mean): on the 51, 42 fits within 0.3 mm of the hand fit (median 0.14), against
#     15 at full size (0.34) and 4 without the outline (with 57 wide and 1.5 shoulders: 39 at 0.985);
#   - the recess's top 7.65 below the body's top, its bottom 3.85 above its bottom (7.43 and 3.57 to the outline as
#     seen, made 1.5 % larger about the body's middle; by hand: "looks like 7.5", and 3.5);
#   - the shoulders 1.6 out on each side (by hand too);
#   - the shoulders' undersides 6.7 below the top (by hand 7);
#   - the label 43 x 22 (42.8 x 21.8 measured; by hand 43 x 22), centered across, 0.4 below the recess's top and 0.6
#     above its bottom (measured 0.48 and 0.72);
#   - the grip above the recess: two creases bowing upward, taken as circular arcs, meeting in sharp points 2.4 above
#     the recess's top (by hand 2), straight above its sides; the upper one's top 1.8 below the body's top, the lower
#     one's 2.9 (by hand 2 and 2.5; the strongest lines there, rough: a straight line 1.45 below the top runs across
#     too, maybe the top bevel's inner edge).
# The embossed "GAME BOY ADVANCE" logo between the creases and the recess, about 28 wide. Not measured: the corners'
# radii, the logo's height and place (AGB_LOGO).
AGB_BODY = (56.8, 34.5)
AGB_LEFT = 28.5 - AGB_BODY[0] / 2  # the body's left side: its middle at 28.5, as the recess's and the other shells'
AGB_SHOULDER = 1.6
AGB_SHOULDER_HEIGHT = 6.7
AGB_BEVEL = 2.0
AGB_OUTLINE_SEEN = 0.987  # the outline's size as fitted, about the body's middle
AGB_RECESS = (6.5, 7.65, 50.5, 30.65)
AGB_LABEL = (7.0, 8.05, 50.0, 30.05)
AGB_CREASE_END = AGB_RECESS[1] - 2.4
AGB_CREASE_TOPS = (1.8, 2.9)  # the upper crease's, the lower one's
# The logo as macOS's text recognition boxes it: 28 wide, as high as the boxes of its reads with 12 or more letters
# (width over height 8.4, median of 92 reads on AGB photos, 2026-11-04: 3.33 mm), its middle taken halfway between the
# lower crease (about 3.5 mm down at the logo's ends) and the recess: a guess, which the starts allow for (agb_logo_start).
AGB_LOGO = (28.5 - 14.0, 5.55 - 28.0 / 8.4 / 2, 28.5 + 14.0, 5.55 + 28.0 / 8.4 / 2)


def agb_outline(scale=1.0):
    """The AGB body's outline in mm, clockwise from the top left: the shoulders, the sides and the bottom (corners sharp:
    their radii aren't measured); scaled about the body's middle (AGB_OUTLINE_SEEN: as fitted and seen)."""
    w, h, s, sh, l = *AGB_BODY, AGB_SHOULDER, AGB_SHOULDER_HEIGHT, AGB_LEFT
    points = np.array([(-s, 0), (w + s, 0), (w + s, sh), (w, sh), (w, h), (0, h), (0, sh), (-s, sh)], np.float64) + (l, 0)
    return (28.5, h / 2) + (points - (28.5, h / 2)) * scale


def agb_crease(top, count=48):
    """One crease in mm, left to right: the circular arc from the left point to the right one through (28.5, top)."""
    half, sag = (AGB_RECESS[2] - AGB_RECESS[0]) / 2, AGB_CREASE_END - top
    r = (half * half + sag * sag) / (2 * sag)
    xs = np.linspace(AGB_RECESS[0], AGB_RECESS[2], count)
    return np.c_[xs, top + r - np.sqrt(r * r - (xs - 28.5) ** 2)]


def agb_face_runs():
    """The AGB body's edges as runs for sampling, clear of the corners by 1 mm or more: the top, the shoulders' sides,
    the body's sides below them and the bottom. The shoulders' undersides (1.6 mm) are left out. The creases aren't
    sampled: their measurements are rough (half a mm) and the fit's last bands are 0.4. At the outline's size as seen
    (AGB_OUTLINE_SEEN)."""
    w, h, s, sh, l = *AGB_BODY, AGB_SHOULDER, AGB_SHOULDER_HEIGHT, AGB_LEFT
    k = AGB_OUTLINE_SEEN
    seen = lambda p: (28.5 + (p[0] + l - 28.5) * k, h / 2 + (p[1] - h / 2) * k)
    return [(seen(a), seen(b), n) for a, b, n in (((-s + 1.0, 0.0), (w + s - 1.0, 0.0), (0, -1)),
            ((w + s, 1.0), (w + s, sh - 1.0), (1, 0)), ((w, sh + 1.5), (w, h - 1.5), (1, 0)),
            ((w - 2.0, h), (2.0, h), (0, 1)),
            ((0.0, h - 1.5), (0.0, sh + 1.5), (-1, 0)), ((-s, sh - 1.0), (-s, 1.0), (-1, 0)))]


def agb_logo_lines(lines):
    """Of the OCR's lines, those reading "GAME BOY ADVANCE" whole enough to place: 12 or more letters, mostly alike
    (read garbled, as "CAMEBOYADVANEE"), best first. "FOR GAME BOY ADVANCE" is left out: printed on labels."""
    import difflib, re
    letters = lambda t: re.sub(r"[^A-Za-z]", "", t).upper()
    score = lambda t: difflib.SequenceMatcher(None, letters(t), "GAMEBOYADVANCE").ratio()
    found = [l for l in lines if len(letters(l["text"])) >= 12 and score(l["text"]) >= 0.6 and not letters(l["text"]).startswith("FOR")]
    return sorted(found, key=lambda l: -score(l["text"]))


def agb_logo_start(line, scale=1.0, dy=0.0):
    """A start for the fit from the logo's line: the similarity taking AGB_LOGO's corners, scaled by scale about its
    middle and shifted dy mm down, to its quadrilateral."""
    mm = corners_of(AGB_LOGO)
    c = mm.mean(axis=0)
    return similarity(c + (mm - c) * scale - [0, dy], line["quad"])


class Shell:
    """A cartridge's front, as the fitter sees it: the body (w, h), the recess and the label (x1, y1, x2, y2), the
    samples, the plain band below the recess for Fitter.band_line (the recess's bottom line's rows, the band's rows, and
    its columns beside the arrow), where "GAME BOY COLOR" lies on the label (its box's corners; None: not measured), and
    the box around the whole front (x1, y1, x2, y2; the body's unless given: the AGB's shoulders stick out)."""

    def __init__(self, name, body, recess, label, samples, recess_line_rows, band_rows, band_columns, color_text, box=None):
        self.name, self.body, self.recess, self.label = name, body, recess, label
        self.box = box or (0.0, 0.0) + tuple(body)
        self.points, self.normals, self.kinds = samples
        self.recess_line_rows, self.band_rows, self.band_columns, self.color_text = recess_line_rows, band_rows, band_columns, color_text


DMG = Shell("dmg", BODY, RECESS, LABEL, build_samples(), (56.5, 57.5), (58.2, 63.8),
            np.r_[np.arange(5.0, 22.0, 0.25), np.arange(35.0, 52.0, 0.25)], COLOR_TEXT)
# Its pill, grooves and embossing aren't measured, so they take no part; "GAME BOY COLOR" lies where it does on DMG
# labels relative to the label, which is 3.25 mm lower here.
CGB = Shell("cgb", CGB_BODY, CGB_RECESS, CGB_LABEL,
            build_samples(CGB_RECESS, CGB_LABEL, cgb_arrow_edges(), pill=False, grooves=False, face_runs=cgb_face_runs(),
                          face_points=cgb_face_points(), recess_radius=None),
            (59.5, 60.5), (60.6, 64.6), np.r_[np.arange(5.0, 24.0, 0.25), np.arange(33.0, 52.0, 0.25)], CGB_COLOR_TEXT,
            box=(CGB_LEFT, 0.0, CGB_LEFT + CGB_BODY[0], CGB_BODY[1]))
# No arrow on its front: the band below the recess runs across the whole recess. No "GAME BOY COLOR" on its labels.
AGB = Shell("agb", AGB_BODY, AGB_RECESS, AGB_LABEL,
            build_samples(AGB_RECESS, AGB_LABEL, [], pill=False, grooves=False, face_runs=agb_face_runs(), recess_radius=None),
            (30.15, 31.15), (31.35, 33.6), np.arange(7.0, 50.0, 0.25), None, box=(AGB_LEFT - AGB_SHOULDER, 0.0, AGB_LEFT + AGB_BODY[0] + AGB_SHOULDER, AGB_BODY[1]))
SHELLS = {"dmg": DMG, "cgb": CGB, "agb": AGB}


def shell_of(serial):
    """The shell of the cartridge with this serial or release id: CGB- ones are Game Boy Color only, AGB- ones (and
    release ids like agb-0014) Game Boy Advance."""
    prefix = serial[:4].upper()
    return CGB if prefix == "CGB-" else AGB if prefix == "AGB-" else DMG


def project(H, pts):
    p = np.c_[pts, np.ones(len(pts))] @ np.asarray(H).T
    return p[:, :2] / p[:, 2:]


# The photos are taken 20 to 100 cm from the cartridge. A fit (mm on the front -> the photo's pixels) can only come from
# a camera that far away if, seen from the camera, its two axes are equally scaled and perpendicular: a pinhole camera
# at distance Z shows the cartridge at s = f / Z pixels per mm, f its constant in pixels, so each distance gives f = Z s;
# the camera's center is taken anywhere in the photo, as photos found online are cropped. The inconsistency: the axes'
# scale difference (%) plus 4 x how far from perpendicular they are (degrees), at the distance and center that make it
# least. On the fits accepted or placed by hand (2026-10-29) it was at most 0.30 on my own photos' hand fits and at
# most 5.05 on the accepted ones (all but one under 5; online, 4 of 70 hand fits over 5, all CGB placements on jauce's
# photos), while 193 of 795 rejected online fits were over 5. Above DISTANCE_TOLERANCE a fit is impossible.
DISTANCES = (200.0, 1000.0)
DISTANCE_TOLERANCE = 5.0


def camera_distance(H, size, steps=40, grid=9):
    """How far a fit (mm -> the photo's pixels, the photo size (w, h) pixels) is from what a camera 20 to 100 cm away
    could see, and the range of distances (mm) within DISTANCE_TOLERANCE of it (None if none is): (inconsistency,
    (nearest, farthest))."""
    H = np.asarray(H, np.float64)
    H = H / H[2, 2]
    c = project(H, [[28.5, 32.5]])[0]
    J = np.array([project(H, [[28.6, 32.5]])[0] - c, project(H, [[28.5, 32.6]])[0] - c]) / 0.1
    s = np.sqrt(abs(np.linalg.det(J)))  # pixels per mm at the cartridge's middle
    z = np.geomspace(*DISTANCES, steps)[:, None, None]
    cx = np.linspace(0, size[0], grid)[None, :, None]
    cy = np.linspace(0, size[1], grid)[None, None, :]
    f = z * s
    # The axes as the camera sees them: K^-1 H's first two columns, K the camera with constant f and center (cx, cy).
    a = np.stack(np.broadcast_arrays((H[0, 0] - cx * H[2, 0]) / f, (H[1, 0] - cy * H[2, 0]) / f, H[2, 0] + 0 * f), -1)
    b = np.stack(np.broadcast_arrays((H[0, 1] - cx * H[2, 1]) / f, (H[1, 1] - cy * H[2, 1]) / f, H[2, 1] + 0 * f), -1)
    na, nb = np.linalg.norm(a, axis=-1), np.linalg.norm(b, axis=-1)
    angle = 90 - np.degrees(np.arccos(np.clip(np.abs((a * b).sum(-1)) / na / nb, 0, 1)))
    error = np.abs(np.log(na / nb)) * 100 + 4 * angle
    least = error.min(axis=(1, 2))
    fits = z[least <= DISTANCE_TOLERANCE, 0, 0]
    return float(least.min()), ((float(fits.min()), float(fits.max())) if len(fits) else None)


# Depth: features behind the front face (the CGB's ridges and board, seen through its clear front wall) show in the
# photo where the line of sight to them crosses the face, which depends on where the camera is. The camera, in mm on
# the face (x, y, and its height above the face), comes from the fit, which dictates it: a pinhole camera with square
# pixels, its center at the photo's center (photos found online may be cropped, and then it's off), and the focal
# length that makes the fit's two axes most nearly equal and perpendicular; however near or far that puts the camera
# (DISTANCES only judge whether a fit fit-cartridge made is plausible). A fit without perspective (or with none a
# camera could give) puts it infinitely far, straight in front: depth then shifts nothing. The line of sight bends
# where it enters and leaves the front wall (Snell's law; see the depths above).


def camera_of(H, center):
    """The camera that sees the front face as H (mm -> pixels) shows it, the center of its view at pixel center:
    (x, y, height) in mm, the face's x and y and the height above it (infinite: no perspective to tell)."""
    H = np.asarray(H, np.float64)
    H = H / H[2, 2]
    A = H[:2, 0] - np.array(center) * H[2, 0]
    B = H[:2, 1] - np.array(center) * H[2, 1]
    # 1 / f^2 from the axes' perpendicularity and their equal length (each linear in it), by least squares, each
    # equation scaled to the size of its terms.
    rows = [(A @ B, -H[2, 0] * H[2, 1]), (A @ A - B @ B, H[2, 1] ** 2 - H[2, 0] ** 2)]
    num = sum(a * b for a, b in rows)
    den = sum(a * a for a, b in rows)
    g = num / den if den > 0 else 0.0  # 1 / f^2
    if not g > 0:
        return np.array([28.5, 32.5, np.inf])
    f = 1 / np.sqrt(g)
    K = np.array([[f, 0, center[0]], [0, f, center[1]], [0, 0, 1]])
    M = np.linalg.inv(K) @ H
    scale = 2 / (np.linalg.norm(M[:, 0]) + np.linalg.norm(M[:, 1]))
    r1, r2, t = M[:, 0] * scale, M[:, 1] * scale, M[:, 2] * scale
    if t[2] < 0:
        r1, r2, t = -r1, -r2, -t
    r3 = np.cross(r1, r2)
    C = -np.linalg.solve(np.c_[r1, r2, r3 / np.linalg.norm(r3)], t)  # as fit_by_hand's page does it
    return np.array([C[0], C[1], abs(C[2])])


def seen_at(points, depth, camera, wall=CGB_WALL, n=CGB_REFRACTIVE_INDEX):
    """Where on the front face points (mm) depth mm behind it are seen from the camera (camera_of): the line of sight
    from the camera to the face, bent through the front wall (wall mm thick, refractive index n) and straight again
    behind it. Points at depth 0 stay where they are."""
    points = np.asarray(points, np.float64)
    if depth <= 0 or not np.isfinite(camera[2]):
        return points
    foot, height = camera[:2], camera[2]
    away = points - foot
    target = np.linalg.norm(away, axis=1)
    glass, air = min(depth, wall), max(0.0, depth - wall)
    r = target * height / (height + depth)  # straight lines first
    for _ in range(8):  # Newton's method on r + offset(r) = target
        tan = r / height
        sin = tan / np.sqrt(1 + tan * tan)
        sin_r = sin / n
        tan_r = sin_r / np.sqrt(1 - sin_r * sin_r)
        offset = glass * tan_r + air * tan
        # d offset / d r: through d tan = dr / height, d tan_r / d tan = (cos^3 / n) / cos_r^3
        cos, cos_r = 1 / np.sqrt(1 + tan * tan), np.sqrt(1 - sin_r * sin_r)
        slope = (glass * cos ** 3 / n / cos_r ** 3 + air) / height
        r = r - (r + offset - target) / (1 + slope)
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(target > 1e-9, r / target, 1.0)
    return foot + away * k[:, None]


def tilt(H):
    """How far a fit turns the cartridge's up from the photo's up, in degrees. Of the 2,326 fits accepted or placed by
    hand (2026-11-01), all but 4 were within 45 degrees of upright."""
    a, b = project(H, [[28.5, 10.0], [28.5, 55.0]])
    d = b - a
    return float(np.degrees(np.arctan2(-d[0], d[1])))


MAX_TILT = 50.0


def outline_quads(photo, max_side=1000):
    """Four-sided outlines in the photo (in its pixels, clockwise from the top left one), for starts where no text is
    read: the convex hulls of the contours of edges (Canny at three thresholds) and of light/dark, red/green,
    yellow/blue and saturated/grey regions (Otsu), each as a quadrilateral where one simplifies to four corners, and as
    its least rotated rectangle; those covering under 1 % of the photo left out, near-duplicates (corners within 1.5 % of
    its size) once. The label, the recess and the body each turn up among them on most photos (as the photo is found
    online: one cartridge on a plain background)."""
    h, w = photo.shape[:2]
    s = min(1.0, max_side / max(h, w))
    small = cv2.resize(photo, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (0, 0), 1.2)
    lab, hsv = cv2.cvtColor(small, cv2.COLOR_BGR2LAB), cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    maps = [cv2.dilate(cv2.Canny(gray, lo, hi), np.ones((3, 3), np.uint8)) for lo, hi in ((20, 60), (40, 120), (80, 200))]
    for channel in (lab[..., 0], lab[..., 1], lab[..., 2], hsv[..., 1]):
        _, m = cv2.threshold(cv2.GaussianBlur(channel, (0, 0), 2), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        maps += [m, 255 - m]
    found = []
    for m in maps:
        for c in cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]:
            hull = cv2.convexHull(c)
            if not 0.01 * sh * sw <= cv2.contourArea(hull) <= 0.98 * sh * sw:
                continue
            perimeter = cv2.arcLength(hull, True)
            for eps in (0.015, 0.03):
                simple = cv2.approxPolyDP(hull, eps * perimeter, True)
                if len(simple) == 4:
                    found.append(simple.reshape(4, 2).astype(np.float64))
                    break
            found.append(cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float64))
    quads = []
    for q in found:
        c = q.mean(axis=0)
        q = q[np.argsort(np.arctan2(q[:, 1] - c[1], q[:, 0] - c[0]))]
        q = np.roll(q, -int(np.argmin(q.sum(axis=1))), axis=0)
        if not any(np.abs(q - o).max() < 0.015 * max(sh, sw) for o in quads):
            quads.append(q)
    return [q / s for q in quads]


def outline_starts(quads, shell, size, tolerance=0.15):
    """Starts for the fit from outline_quads: each quadrilateral taken for the label, the recess or the body (its box,
    with the AGB's shoulders), in each of
    its four turns whose proportions are within tolerance (log of the ratio) of that rectangle's and that keep the
    cartridge within MAX_TILT of upright; a start putting the body partly outside the photo (by over 10 % of its size)
    or covering under 3 % of it is left out. As (homography, quad index, what)."""
    w, h = size
    sides = lambda q: np.linalg.norm(np.roll(q, -1, axis=0) - q, axis=1)
    body = corners_of(shell.box)
    starts = []
    for i, q in enumerate(quads):
        for what, rect in (("label", shell.label), ("recess", shell.recess), ("body", shell.box)):
            mm = corners_of(rect)
            ms = sides(mm)
            for k in range(4):
                qk = np.roll(q, -k, axis=0)
                qs = sides(qk)
                if abs(np.log((qs[0] + qs[2]) / (qs[1] + qs[3]) / ((ms[0] + ms[2]) / (ms[1] + ms[3])))) > tolerance:
                    continue
                H = cv2.getPerspectiveTransform(mm.astype(np.float32), qk.astype(np.float32)).astype(np.float64)
                H /= H[2, 2]
                b = project(H, body)
                if abs(tilt(H)) > MAX_TILT or (b < [-0.1 * w, -0.1 * h]).any() or (b > [1.1 * w, 1.1 * h]).any() or cv2.contourArea(b.astype(np.float32)) < 0.03 * w * h:
                    continue
                starts.append((H, i, what))
    return starts


class Fitter:
    """Fits a shell's model (the DMG's by default) to one photo."""

    def __init__(self, photo, shell=DMG):
        self.shell = shell
        self.photo = photo
        self.ph, self.pw = photo.shape[:2]
        # Working copy: about 900 px wide, in Lab, slightly blurred.
        self.work = min(1.0, 900 / self.pw)
        small = cv2.resize(photo, None, fx=self.work, fy=self.work, interpolation=cv2.INTER_AREA)
        self.lab = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32), (0, 0), 1.0)
        self.sh, self.sw = self.lab.shape[:2]
        self.points, self.normals, self.kinds = shell.points, shell.normals, shell.kinds
        self.is_line = self.kinds == "recess"

    def subset(self, kinds):
        """The same photo with only some sample kinds, e.g. ("recess",)."""
        other = object.__new__(Fitter)
        other.__dict__.update(self.__dict__)
        keep = np.isin(self.kinds, kinds)
        other.points, other.normals, other.kinds = self.points[keep], self.normals[keep], self.kinds[keep]
        other.is_line = other.kinds == "recess"
        return other

    def without_side(self, side):
        """The same photo without the recess's and the label's samples on one side (0 top, 1 right, 2 bottom, 3 left):
        for refitting when label art along that side was taken for the recess's line."""
        other = object.__new__(Fitter)
        other.__dict__.update(self.__dict__)
        normal = np.array(edges_of(self.shell.recess)[side][2], np.float64)
        keep = ~(np.isin(self.kinds, ("recess", "label")) & (np.abs(self.normals - normal).sum(axis=1) < 1e-9))
        other.points, other.normals, other.kinds = self.points[keep], self.normals[keep], self.kinds[keep]
        other.is_line = other.kinds == "recess"
        return other

    def sample_lab(self, xy):
        mx, my = xy[..., 0].astype(np.float32), xy[..., 1].astype(np.float32)
        return cv2.remap(self.lab, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def search(self, H, band, step=0.04):
        """For each sample, the offset along its normal (mm) with the strongest edge within +-band, and its strength."""
        # Sampled 0.35 mm beyond the band, so a line near the band's end can still be compared with both its sides.
        margin = 0.36
        offsets = np.arange(-band - margin, band + margin + step / 2, step)
        grid = self.points[:, None, :] + self.normals[:, None, :] * offsets[None, :, None]
        xy = project(H, grid.reshape(-1, 2)).reshape(len(self.points), len(offsets), 2) * self.work
        values = self.sample_lab(xy)
        # Steps lie between two offsets; lines at an offset. Both as strength per position, with positions in mm.
        step_strength = np.linalg.norm(np.diff(values, axis=1), axis=2)
        step_at = offsets[:-1] + step / 2
        # A thin line: the color differs from both sides, 0.35 mm out, and the two sides match each other.
        w = max(1, int(round(0.35 / step)))
        center = values[:, w:-w]
        before, after = values[:, : -2 * w], values[:, 2 * w :]
        line = np.linalg.norm(center - (before + after) / 2, axis=2) * np.exp(-np.linalg.norm(before - after, axis=2) / 8)
        line_at = offsets[w:-w]
        inside_xy = (xy[..., 0] > 1) & (xy[..., 1] > 1) & (xy[..., 0] < self.sw - 2) & (xy[..., 1] < self.sh - 2)
        found = np.zeros(len(self.points))
        strength = np.zeros(len(self.points))
        for is_line, positions, strengths, inside in (
            (True, line_at, line, inside_xy[:, w:-w] & inside_xy[:, : -2 * w] & inside_xy[:, 2 * w :]),
            (False, step_at, step_strength, inside_xy[:, :-1] & inside_xy[:, 1:]),
        ):
            rows = self.is_line == is_line
            if not rows.any():
                continue
            within = np.broadcast_to(np.abs(positions) <= band + 1e-9, (rows.sum(), len(positions)))
            candidates = np.where(inside[rows] & within, strengths[rows], 0)
            best = candidates.argmax(axis=1)
            found[rows] = positions[best]
            strength[rows] = candidates[np.arange(rows.sum()), best]
        return found, strength

    def update(self, H, found, weights, projective):
        """One point-to-line step: the correction M (in mm) that moves each sample across its edge by its found offset,
        leaving it free to slide along the edge, by weighted least squares. Returns H @ M. Affine unless projective."""
        x, y = self.points[:, 0] / 30.0, self.points[:, 1] / 30.0  # scaled for conditioning
        nx, ny = self.normals[:, 0], self.normals[:, 1]
        # dp = (d0 x + d1 y + d2 - x (d6 x + d7 y), d3 x + d4 y + d5 - y (d6 x + d7 y)) in scaled units; n . dp = found / 30.
        columns = [nx * x, nx * y, nx, ny * x, ny * y, ny]
        if projective:
            columns += [-(nx * x + ny * y) * x, -(nx * x + ny * y) * y]
        A = np.stack(columns, axis=1) * np.sqrt(weights)[:, None]
        b = found / 30.0 * np.sqrt(weights)
        d = np.linalg.lstsq(A, b, rcond=None)[0]
        d = np.concatenate([d, np.zeros(8 - len(d))])
        S = np.diag([30.0, 30.0, 1.0])
        M = np.array([[1 + d[0], d[1], d[2]], [d[3], 1 + d[4], d[5]], [d[6], d[7], 1.0]])
        return H @ (S @ M @ np.linalg.inv(S))

    def fit(self, H0, bands=(3.0, 2.0, 1.4, 1.0, 0.7, 0.5, 0.4, 0.4), fine_kinds=("recess", "face", "arrow", "pill", "groove"), iterations=3,
            late_kinds={"pill": 1.4, "groove": 0.5}, kind_weights=None):
        """Refines H0 with shrinking bands, by point-to-line steps with robust (Tukey) weights; returns the homography
        and its quality. Bands of 1 mm and less use only fine_kinds: the label isn't placed exactly in the recess, so its
        edges only help to get close. late_kinds take part only from the given band down: the pill's bottom
        edge is 2 mm above the recess's top, which a wider search finds instead. kind_weights scale each kind's samples
        (default 1)."""
        kind_weight = np.array([(kind_weights or {}).get(k, 1.0) for k in self.kinds])
        H = np.asarray(H0, np.float64).copy()
        for band in bands:
            use = np.isin(self.kinds, fine_kinds) if fine_kinds and band <= 1.0 else np.ones(len(self.kinds), bool)
            for kind, start in late_kinds.items():
                use &= ~((self.kinds == kind) & (band > start))
            for _ in range(iterations):
                found, strength = self.search(H, band)
                strong = use & (strength > np.percentile(strength[use], 30))
                # Edges on both axes, or the correction is underdetermined.
                if (strong & (np.abs(self.normals[:, 0]) > 0.5)).sum() < 6 or (strong & (np.abs(self.normals[:, 1]) > 0.5)).sum() < 6:
                    return H, 0.0
                weights = strong * kind_weight
                for _ in range(3):
                    Hn = self.update(H, found, weights, projective=band <= 1.0)
                    # Residual across the edges after the step, in mm, for the robust weights.
                    moved = project(np.linalg.inv(Hn) @ H, self.points + self.normals * found[:, None]) - self.points
                    residual = np.abs((moved * self.normals).sum(axis=1))
                    scale = max(0.05, 1.4826 * np.median(residual[strong]))
                    u = residual / (4.685 * scale)
                    weights = np.where(strong & (u < 1), (1 - u * u) ** 2, 0.0) * kind_weight
                H = Hn
        return H, self.quality(H)

    def line_continuity(self, H, band=0.4, step=0.25):
        """How unbroken the recess's line is on each side (top, right, bottom, left): sampled every step mm (ends 1 mm
        in), the strongest thin line within +-band of each sample, and the share of samples on one straight line
        (within 0.12 mm). The real wall runs the whole side; label art that a fit mistakes for it gives short pieces.
        On the hand-placed recesses the median side was 95 to 98 % on the line (see line_continuity.py)."""
        points, normals, side_of = [], [], []
        for k, (a, b, n) in enumerate(edges_of(self.shell.recess)):
            a, b = np.array(a, float), np.array(b, float)
            length = np.linalg.norm(b - a)
            for d in np.arange(1.0, length - 1.0 + 1e-9, step):
                points.append(a + (b - a) * d / length)
                normals.append(n)
                side_of.append(k)
        f = self.subset(("recess",))
        f.points, f.normals, side_of = np.array(points), np.array(normals, float), np.array(side_of)
        f.kinds, f.is_line = np.array(["recess"] * len(points)), np.ones(len(points), bool)
        found, _ = f.search(H, band)
        shares = []
        for k in range(4):
            off = found[side_of == k]
            t = np.arange(len(off)) * step
            keep = np.ones(len(t), bool)
            for _ in range(3):
                b, a = np.polyfit(t[keep], off[keep], 1)
                keep = np.abs(off - (a + b * t)) < 0.12
                if keep.sum() < 4:
                    break
            shares.append(float(keep.mean()))
        return shares

    def band_line(self, H):
        """The strongest horizontal line in the plain band below the recess (on the DMG 58.2 to 63.8 mm down, beside the arrow),
        relative to the recess's bottom line: the rows' medians across the band's width, so that lines running across
        it count and the frosted texture doesn't. Apart from the arrow's top there should be none; a fit that slid
        vertically puts the recess's wall or the face's bottom edge there."""
        xs = self.shell.band_columns
        (l0, l1), (b0, b1) = self.shell.recess_line_rows, self.shell.band_rows
        ys = np.arange(l0 - 1.0, min(b1 + 1.8, self.shell.body[1] + 0.6), 0.05)
        grid = np.stack(np.meshgrid(xs, ys), -1).reshape(-1, 2)
        xy = (project(H, grid) * self.work).reshape(len(ys), len(xs), 2).astype(np.float32)
        inside = (xy[..., 0] > 1) & (xy[..., 1] > 1) & (xy[..., 0] < self.sw - 2) & (xy[..., 1] < self.sh - 2)
        if inside.mean() < 0.5:
            return 0.0
        L = np.where(inside, self.sample_lab(xy)[..., 0], np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # rows wholly outside the photo
            profile = np.nanmedian(L, axis=1)
        steps = np.abs(profile[6:] - profile[:-6])  # across 0.3 mm
        at = ys[3:-3]
        recess_line = np.nanmax(steps[(at > l0) & (at < l1)])
        band = np.nanmax(steps[(at > b0) & (at < b1)])
        return float(band / (recess_line + 1e-9)) if np.isfinite(band) and np.isfinite(recess_line) else 0.0

    def recess_strength(self, H):
        """The mean strength of the recess's line within 0.12 mm of where H puts it: the most reliable edge (see
        old experiments), so the best measure for choosing among fits from different starts."""
        found, strength = self.subset(("recess",)).search(H, 0.12)
        return float(np.mean(strength))

    def features(self, H):
        """What fit-cartridge's choice among fits weighs, of one fit: for each kind of sample, the share with a strong
        edge within 0.12 mm (near), their mean strength there (str) and the median offset of the strongest edge within
        0.4 mm (offset); the recess's strength, the band's line, the quality, and the recess line's continuity (least
        and mean side)."""
        found, strength = self.search(H, 0.4)
        median = np.median(strength)
        f = {}
        for kind in ("recess", "label", "face", "arrow", "pill", "groove"):
            m = self.kinds == kind
            near = np.abs(found[m]) < 0.12
            f[f"{kind}_near"] = float((near & (strength[m] > median * 0.5)).mean()) if m.any() else 0.0
            f[f"{kind}_str"] = float(np.mean(strength[m] * near)) if m.any() else 0.0
            f[f"{kind}_offset"] = float(np.median(np.abs(found[m]))) if m.any() else 0.0
        continuity = self.line_continuity(H)
        return f | {"recess_strength": self.recess_strength(H), "band_line": self.band_line(H), "quality": self.quality(H),
                    "cont_min": float(min(continuity)), "cont_mean": float(np.mean(continuity))}

    def quality(self, H):
        """The share of samples with a strong edge within 0.12 mm of the place H puts them."""
        found, strength = self.search(H, 0.4)
        return float(((np.abs(found) < 0.12) & (strength > np.median(strength) * 0.5)).mean())
