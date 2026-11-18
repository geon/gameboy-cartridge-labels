# find: the label photos in every photo, from the evidence, into <generated>/find/label-photos.json:
#   {"label_photos": [{"key", "photo", "centre" [x, y], "radius", "outline" [[x, y]...] (the label's rectangle if
#                      placed, else the hull of the evidence: rough), "placed_by" (a detail or null), "shape", "found_by" ("serial", "near serial", "detail", "string and match", "match"),
#                      "strings": [{"text", "serial", "kind" (exact, near, unknown), "cost", "release", "corners"}],
#                      "details": [{"detail", "corners", "px_per_mm", "inliers"}],
#                      "matches": [{"to" (key), "inliers"}]}],
#    "sets": [[key...]] (label photos linked by matches),
#    "rejected": [{"photo", "centre", "strings", "why"}]}
# The evidence, in this order:
#   1. Seeds: the serial-looking strings each photo's text holds (read-text): exact serials the database knows, near
#      serials (serials.near) and strings it doesn't know; and the details found in it (src/details.py). Seeds of one
#      label (strings within MERGE line heights, details within DETAIL_REACH of a label's diagonal) are one candidate. A candidate
#      with an exact or near serial, or a detail, is a label photo; one with only unknown strings is one if a match
#      links it to a serial-looking string in another photo (possibly a new release).
#      Only serial-looking strings are used of the text. Other texts at fixed places on a layout might help, as seeds and
#      to place the label (the strip texts of US and European DMG labels: the serial down the left strip, MADE IN JAPAN
#      below it, THIS SIDE OUT up the right strip; the GAME BOY COLOR logo's text), but a test on the sample
#      (2026-11-09, label-detection.md) showed no improvement: as seeds 2 more photos found without serials and none
#      with them; as placement mostly wrong (MADE IN JAPAN and the strip serial sit elsewhere on other layouts).
#   2. Its area. Placed, if it has a detail at one place on every label of its shape (details/places.json: the GAME BOY
#      COLOR logos, KONAMI): the label's rectangle through the detail's homography is its outline, its circle just
#      around it, and the detail gives the shape; not if a serial's shape contradicts it (the white-background GAME
#      BOY COLOR logo is also on European CGB labels, elsewhere). Otherwise a circle of a label's diagonal around the seeds: RADIUS line heights of a string (the serial's line is
#      about 2.2 mm tall on DMG labels and sits anywhere on the label), or LABEL_DIAGONAL mm at a detail's scale (its
#      image is 20 px/mm, so its homography gives the photo's px/mm); the matched points inside it make the outline.
#   3. Spreading: a match whose points in one photo lie mostly inside a label photo's circle makes a label photo where
#      they lie in the other photo (its circle carried over through the match's homography; not a placed label's
#      rectangle: a match shows two areas alike, not one layout, and a shared template sits elsewhere on another
#      layout), or links the
#      one already there; repeated until nothing changes. A match that touches no label photo (a watermark, a
#      background, embossing) starts nothing.
#   4. Label photos of one photo whose outlines (the hull of their evidence) share MERGE_OVERLAP of the smaller are
#      one: spreading's circles are rough and may land a second label photo on one already there.
# Not labels: an area a person marked as not a label (NOT_LABELS, from make fit-by-hand: the fitted cut and find's
# outline of the label photo, in the photo's pixels) holds no label photo: a candidate whose centre lies in either is
# left out, from the seeds (rejected, with why) and from spreading (none is made there, so none spreads from it).
# Frozen label photos (src/frozen.py, persistent-prints.md stage 2): taken as they are (their keys, their cut as the
# outline, found_by "frozen"), never merged into another; their areas (the cut and find's outline when frozen) are
# taken: no other label photo is made there. Spreading reaches them as any label photo, so a new photo of a frozen
# print links to it.
# A match between a photo and a frozen print's image (match indexes them as photos) makes a label photo where the image
# lands in the photo, or tags the one already there (found_by "frozen print"; "frozen_print": the print's id,
# "frozen_match": the photo's pixels -> the image's): solve takes its pose from it.
# The shape is the serial's platform (DMG-, CGB-, AGB-); a label photo found by matching takes its linked ones' (most).
# Keys: <sha1>@<x>,<y>, the centre in whole percent of the photo's width and height.
# Done again when label-photos.json is older than this file or than any of its inputs (NOT_LABELS among them).
# With --no-strings, the text isn't used at all (details and matches only), into <generated>/find-no-strings/: to
# compare.
# Usage: find.py [--sample] [--no-strings]
import argparse, html, json, os, re, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos, serials, steps, match, details, shapes, frozen

MERGE = 12          # line heights: strings closer than this are one label's
RADIUS = 28         # line heights: a label's diagonal around its serial
LABEL_DIAGONAL = 60  # mm, a little over the DMG label's 56
DETAIL_REACH = 0.75  # of a label's diagonal: a detail and a serial at opposite ends of one label are one candidate
PLACED_RADIUS = 1.15  # a placed label's circle: its half diagonal, and a little
INSIDE = 0.5        # the share of a match's points that must lie in a label photo's circle for it to spread
MIN_POINTS = 15
MERGE_OVERLAP = 0.25  # label photos of one photo sharing this much of the smaller outline are one (the user: 25 %; was 50 %)


def seeds(lines, release_of, regions):
    """The serial-looking strings of a photo's lines: [{"text", "serial", "kind", "cost", "release", "corners",
    "centre", "height"}]."""
    out = []
    for line in lines:
        c = np.array(line["corners"], float)
        centre, height = c.mean(0), (np.hypot(*(c[3] - c[0])) + np.hypot(*(c[2] - c[1]))) / 2
        base = {"text": line["text"], "corners": line["corners"], "centre": centre.tolist(), "height": float(height),
                "reach": MERGE * float(height), "radius": RADIUS * float(height)}
        reads = serials.reads(line["text"])
        exact = [s for s in reads if serials.release(s, release_of)]
        for s in exact[:1]:
            out.append({**base, "serial": s, "kind": "exact", "cost": 0, "release": serials.release(s, release_of)["id"]})
        if exact:
            continue
        near = serials.near(line["text"], regions)
        for s, cost, _ in near[:1]:
            out.append({**base, "serial": s, "kind": "near", "cost": cost, "release": serials.release(s, release_of)["id"]})
        if not near and reads:
            out.append({**base, "serial": reads[0], "kind": "unknown", "cost": None, "release": None})
    return out


def detail_seeds(found):
    """A photo's detections as seeds: reach DETAIL_REACH of a label's diagonal, radius a whole one, at the detail's
    scale."""
    return [{**d, "reach": DETAIL_REACH * LABEL_DIAGONAL * d["px_per_mm"], "radius": LABEL_DIAGONAL * d["px_per_mm"], "kind": "detail"}
            for d in found]


def group(seeds):
    """Seeds of one label (within the larger one's reach of each other) as candidates: [[seed...]]."""
    reach = lambda s: s.get("reach", MERGE * s.get("height", 0))
    groups = []
    for s in seeds:
        near = [g for g in groups if any(np.hypot(*np.subtract(s["centre"], t["centre"])) < max(reach(s), reach(t)) for t in g)]
        merged = [s] + [t for g in near for t in g]
        groups = [g for g in groups if g not in near] + [merged]
    return groups


NOT_LABELS = "not-labels.json"  # {label photo key: {"photo", "area", "found" ([[x, y]...] in the photo's pixels), "datetime"}}


def load_not_labels(path=NOT_LABELS):
    """photo -> [polygons (float32)] marked not a label."""
    out = {}
    for e in (json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}).values():
        for poly in (e.get("area"), e.get("found")):
            if poly:
                out.setdefault(e["photo"], []).append(np.float32(poly))
    return out


def not_a_label(not_labels, photo, centre):
    return any(cv2.pointPolygonTest(p, (float(centre[0]), float(centre[1])), False) >= 0 for p in not_labels.get(photo, []))


def key(sha1, centre, size):
    return f"{sha1}@{int(centre[0] / size[0] * 100)},{int(centre[1] / size[1] * 100)}"


def inside(points, lp):
    return np.hypot(*(np.asarray(points) - lp["centre"]).T) < lp["radius"]


def shape_of(serial):
    m = re.match(r"(?:DIS-)?(DMG|CGB|AGB)", serial or "")
    return m.group(1).lower() if m else None


def outline(lp):
    """A placed label photo's rectangle; else the hull of its evidence: its matched points, its strings' and details'
    corners."""
    if lp.get("placed") is not None:
        return np.round(lp["placed"], 1).tolist()
    pts = [np.asarray(p) for p in lp["points"]] + [np.array(t["corners"], float) for t in lp["strings"] + lp.get("details", [])]
    pts = np.vstack(pts) if pts else lp["centre"].reshape(1, 2)
    return cv2.convexHull(pts.astype(np.float32)).reshape(-1, 2).round(1).tolist() if len(pts) >= 3 else pts.tolist()


def overlap(a, b):
    """The share of the smaller outline that the two outlines share."""
    pa, pb = np.float32(a).reshape(-1, 2), np.float32(b).reshape(-1, 2)
    if len(pa) < 3 or len(pb) < 3:
        return 0.0
    area, _ = cv2.intersectConvexConvex(pa, pb)
    smaller = min(cv2.contourArea(pa), cv2.contourArea(pb))
    return float(area / smaller) if smaller > 0 else 0.0


FOUND_BY = ["frozen", "frozen print", "serial", "near serial", "detail", "string and match", "match"]


def merge_overlapping(lps):
    """Label photos of one photo whose outlines share MERGE_OVERLAP of the smaller are merged: strings, points and
    links combined; the centre and circle of the one with strings (else the first); found by the strongest."""
    out, of_photo = [], {}  # of_photo: photo -> indices in out (by identity: == on these dicts compares numpy arrays)
    for lp in lps:
        here = of_photo.setdefault(lp["photo"], [])
        i = next((i for i in here if overlap(out[i]["outline"], lp["outline"]) >= MERGE_OVERLAP), None)
        if i is None:
            here.append(len(out))
            out.append(lp)
            continue
        same = out[i]
        if same.get("frozen_key") and lp.get("frozen_key"):  # two frozen label photos: never one
            here.append(len(out))
            out.append(lp)
            continue
        if same.get("frozen_key") or lp.get("frozen_key"):  # a frozen label photo stays as it is
            keep, other = (same, lp) if same.get("frozen_key") else (lp, same)
        else:
            keep, other = (same, lp) if same["strings"] or not lp["strings"] else (lp, same)
        keep["strings"] = keep["strings"] + other["strings"]
        keep["points"] = keep["points"] + other["points"]
        keep["details"] = keep.get("details", []) + other.get("details", [])
        if keep.get("placed") is None and other.get("placed") is not None:
            keep["placed"], keep["placed_by"] = other["placed"], other["placed_by"]
        keep["found_by"] = min(keep["found_by"], other["found_by"], key=FOUND_BY.index)
        for o, n in other.get("links", []):
            o["links"] = [(keep if x is other else x, m) for x, m in o["links"]]
        keep["links"] = [(o, n) for o, n in keep.get("links", []) + other.get("links", []) if o is not keep and o is not other]
        keep["outline"] = outline(keep)
        if keep is lp:
            out[i] = lp
    return out


def place(lp, places, photo_seeds=()):
    """Places a label photo by its best fixed-place detail (most inliers), if it has one: its rectangle, centre, a
    circle just around it, and its shape if no serial gave one. Not by a detail whose shape contradicts a serial of
    the label photo's or one within a label's diagonal of the detail (photo_seeds: the photo's seeds)."""
    def allowed(d):
        near = [t for t in photo_seeds if t.get("kind") in ("exact", "near") and
                np.hypot(*np.subtract(t["centre"], d["centre"])) < LABEL_DIAGONAL * d["px_per_mm"]]
        shapes_seen = {shape_of(t["serial"]) for t in list(lp["strings"]) + near if t["kind"] in ("exact", "near")}
        return not shapes_seen or places[d["detail"]]["shape"] in shapes_seen
    best = max((d for d in lp.get("details", []) if d["detail"] in places and allowed(d)), key=lambda d: d["inliers"], default=None)
    if best is None:
        return
    corners = details.placed_label(best, places, best["size"], shapes.LABEL_MM)
    lp["placed"], lp["placed_by"] = corners, best["detail"]
    lp["centre"] = corners.mean(0)
    lp["radius"] = PLACED_RADIUS * max(np.hypot(*(corners - lp["centre"]).T))
    lp["detail_shape"] = places[best["detail"]]["shape"]


def find(chosen, texts, matches, release_of, detections=None, use_strings=True, places=None, not_labels=None,
         frozen_lps=None, frozen_images=None):
    """The label photos, their sets and the rejected candidates, from the photos' texts (unless not use_strings), the
    details found in them (sha1 -> detections) and the matches; none in the areas not_labels marks (load_not_labels)."""
    not_labels = not_labels or {}
    # frozen label photos (src/frozen.py), as they are: key -> {"photo", "cut", "found", "shape"}; their areas taken
    taken = {}
    lps_frozen = []
    for fk, f in sorted((frozen_lps or {}).items()):
        if f["photo"] not in chosen:
            continue
        cut = np.float64(f["cut"])
        centre = cut.mean(0)
        lps_frozen.append({"photo": f["photo"], "centre": centre, "radius": float(np.max(np.hypot(*(cut - centre).T))),
                           "strings": [], "details": [], "points": [], "found_by": "frozen", "frozen_key": fk,
                           "placed": cut, "placed_by": None, "detail_shape": f["shape"]})
        for poly in (f["cut"], f.get("found")):
            if poly is not None and len(poly) >= 3:
                taken.setdefault(f["photo"], []).append(np.float32(poly))
    regions = serials.by_region(release_of)
    sizes = {s: texts[s]["size"] or [1, 1] for s in chosen}
    lps, rejected = [], []  # label photos: dicts with "photo", "centre" (array), "radius", "strings", "found_by"
    unknown = {}            # photo -> candidates with only unknown strings, decided after the matches are known
    for n, s in enumerate(chosen, 1):
        if n % 1000 == 0 or n == len(chosen):
            print(f"seeds found in {n} of {len(chosen)} photos", flush=True)
        found = (seeds(texts[s]["lines"], release_of, regions) if use_strings else []) + detail_seeds((detections or {}).get(s, []))
        for g in group(found):
            centre = np.mean([t["centre"] for t in g], 0)
            radius = max(t["radius"] for t in g)
            kinds = {t["kind"] for t in g}
            strings = [{k: t[k] for k in ("text", "serial", "kind", "cost", "release", "corners")} for t in g if t["kind"] != "detail"]
            found_details = [{k: t[k] for k in ("detail", "size", "corners", "centre", "px_per_mm", "inliers")} for t in g if t["kind"] == "detail"]
            cand = {"photo": s, "centre": centre, "radius": radius, "strings": strings, "details": found_details, "points": [],
                    "found_by": "serial" if "exact" in kinds else "near serial" if "near" in kinds else "detail" if "detail" in kinds else None}
            place(cand, places or {}, found)
            if not_a_label(not_labels, s, cand["centre"]):
                rejected.append({"photo": s, "centre": cand["centre"].tolist(), "strings": strings, "why": "in an area marked not a label"})
                continue
            if not_a_label(taken, s, cand["centre"]):
                rejected.append({"photo": s, "centre": cand["centre"].tolist(), "strings": strings, "why": "in a frozen label photo's area"})
                continue
            if cand["found_by"]:
                lps.append(cand)
            else:
                unknown.setdefault(s, []).append(cand)
    lps += lps_frozen
    # matches with frozen prints' images (frozen_images: image SHA-1 -> {"print", "crop", "shape"}): each makes a label
    # photo where it lands in the photo (or tags the one there) with the print and the match (photo -> image pixels)
    frozen_images = frozen_images or {}
    to_images, rest = [], []
    for a, b, H, inl in matches:
        if b in frozen_images and a in chosen:
            to_images.append((a, b, np.float64(H), inl[:, :2]))
        elif a in frozen_images and b in chosen:
            to_images.append((b, a, np.linalg.inv(np.float64(H)), inl[:, 2:]))
        elif a in chosen and b in chosen:
            rest.append((a, b, H, inl))
    matches = rest
    for a, img, H, pa in sorted(to_images, key=lambda m: -len(m[3])):
        f = frozen_images[img]
        w, h = f["crop"]["w"], f["crop"]["h"]
        corners = cv2.perspectiveTransform(np.float64([[[0, 0]], [[w, 0]], [[w, h]], [[0, h]]]), np.linalg.inv(H)).reshape(-1, 2)
        centre = corners.mean(0)
        here = [lp for lp in lps if lp["photo"] == a and inside([pa.mean(0)], lp)[0]]
        if here:
            lp = here[0]
            if lp.get("frozen_key") or lp.get("frozen_match") is not None:
                continue
        else:
            if not_a_label(not_labels, a, centre) or not_a_label(taken, a, centre):
                continue
            lp = {"photo": a, "centre": centre, "radius": float(np.max(np.hypot(*(corners - centre).T))), "strings": [],
                  "details": [], "points": [], "found_by": "frozen print", "detail_shape": f["shape"]}
            lps.append(lp)
        lp["frozen_print"], lp["frozen_match"] = f["print"], H
        lp["points"].append(pa)
    # the label photos per photo, kept as lps grows (a scan of lps per match was quadratic: an hour and more on 13k photos)
    of_photo = {}
    for lp in lps:
        of_photo.setdefault(lp["photo"], []).append(lp)
    def add(lp):
        lps.append(lp)
        of_photo.setdefault(lp["photo"], []).append(lp)
    by_photo = lambda s: list(of_photo.get(s, []))
    # both directions of every match: (photo a, photo b, a -> b, points in a, points in b)
    both = []
    for a, b, H, inl in matches:
        both.append((a, b, H, inl[:, :2], inl[:, 2:]))
        both.append((b, a, np.linalg.inv(H), inl[:, 2:], inl[:, :2]))
    # candidates with only unknown strings: a label photo if a match links them to a serial-looking string elsewhere
    for a, b, H, pa, pb in both:
        for cand in unknown.get(a, []):
            if cand["found_by"] or inside(pa, cand).mean() < INSIDE:
                continue
            others = by_photo(b) + unknown.get(b, [])
            if any(inside(pb, o).mean() >= INSIDE for o in others):
                cand["found_by"] = "string and match"
                add(cand)
    for cands in unknown.values():
        rejected += [{"photo": c["photo"], "centre": c["centre"].tolist(), "strings": c["strings"],
                      "why": "only strings the database doesn't know, and no match to a serial elsewhere"}
                     for c in cands if not c["found_by"]]
    # spreading, until nothing changes
    links = set()
    changed, passes = True, 0
    while changed:
        changed = False
        passes += 1
        for n, (a, b, H, pa, pb) in enumerate(both, 1):
            if n % 100000 == 0:
                print(f"spreading, pass {passes}: {n} of {len(both)} match directions", flush=True)
            for lp in by_photo(a):
                ins = inside(pa, lp)
                if ins.sum() < MIN_POINTS or ins.mean() < INSIDE:
                    continue
                qa, qb = pa[ins], pb[ins]
                there = [o for o in by_photo(b) if inside([qb.mean(0)], o)[0]]
                if there:
                    other = there[0]
                else:  # a new label photo where the match lands, its circle carried over
                    centre = cv2.perspectiveTransform(lp["centre"].reshape(1, 1, 2), H).reshape(2)
                    edge = cv2.perspectiveTransform((lp["centre"] + [lp["radius"], 0]).reshape(1, 1, 2), H).reshape(2)
                    w, h = sizes[b]
                    if not (0 <= centre[0] < w and 0 <= centre[1] < h):
                        centre = qb.mean(0)
                    radius = float(np.hypot(*(edge - centre)))
                    # it must hold where the match lands, or the next pass doesn't find it and adds it again, every
                    # pass, forever (the full set, 2026-11-12: one more per pass from the third on, 342 passes and on)
                    if not np.hypot(*(qb.mean(0) - centre)) < radius:
                        centre, radius = qb.mean(0), max(radius, 1.0)
                    if not_a_label(not_labels, b, centre) or not_a_label(taken, b, centre):
                        continue
                    other = {"photo": b, "centre": centre, "radius": radius, "strings": [],
                             "details": [], "points": [], "found_by": "match"}
                    add(other)
                    changed = True
                link = (id(lp), id(other)) if id(lp) < id(other) else (id(other), id(lp))
                if link not in links:
                    links.add(link)
                    lp.setdefault("links", []).append((other, len(qa)))
                    other.setdefault("links", []).append((lp, len(qa)))
                    lp["points"].append(qa)
                    other["points"].append(qb)
        print(f"spreading, pass {passes} done: {len(lps)} label photos, {len(links)} links", flush=True)
    # outlines; label photos of one photo whose outlines mostly overlap are one (spreading's circles are rough)
    for lp in lps:
        lp["outline"] = outline(lp)
    lps = merge_overlapping(lps)
    for lp in lps:
        lp["outline"] = outline(lp)
        lp["key"] = lp.get("frozen_key") or key(lp["photo"], lp["centre"], sizes[lp["photo"]])
    for lp in lps:
        own = [shape_of(t["serial"]) for t in lp["strings"] if t["kind"] != "unknown"]
        lp["shape"] = max(set(own), key=own.count) if own else lp.get("detail_shape")
        if lp.get("frozen_key"):
            lp["shape"] = lp["detail_shape"]
    for _ in range(len(lps)):  # shapes spread along links
        moved = False
        for lp in lps:
            if lp["shape"] is None:
                linked = [o["shape"] for o, _ in lp.get("links", []) if o["shape"]]
                if linked:
                    lp["shape"] = max(set(linked), key=linked.count)
                    moved = True
        if not moved:
            break
    parent = {id(lp): id(lp) for lp in lps}
    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for lp in lps:
        for o, _ in lp.get("links", []):
            parent[root(id(lp))] = root(id(o))
    sets = {}
    for lp in lps:
        sets.setdefault(root(id(lp)), []).append(lp["key"])
    out = [{"key": lp["key"], "photo": lp["photo"], "centre": np.round(lp["centre"], 1).tolist(),
            "radius": round(float(lp["radius"]), 1), "outline": lp["outline"], "shape": lp["shape"],
            "found_by": lp["found_by"], "placed_by": lp.get("placed_by"), "strings": lp["strings"], "details": lp.get("details", []),
            "matches": [{"to": o["key"], "inliers": n} for o, n in lp.get("links", [])],
            **({"frozen_print": lp["frozen_print"], "frozen_match": np.round(lp["frozen_match"] / lp["frozen_match"][2, 2], 9).tolist()}
               if lp.get("frozen_match") is not None else {})} for lp in lps]
    return {"label_photos": out, "sets": sorted(sets.values(), key=len, reverse=True), "rejected": rejected}


def page(out_dir, chosen, result, texts):
    lps = result["label_photos"]
    by_photo = {}
    for lp in lps:
        by_photo.setdefault(lp["photo"], []).append(lp)
    none = [s for s in chosen if s not in by_photo]
    several = [s for s in chosen if len(by_photo.get(s, [])) > 1]
    counts = {}
    for lp in lps:
        counts[lp["found_by"]] = counts.get(lp["found_by"], 0) + 1
    shapes = {}
    for lp in lps:
        shapes[lp["shape"]] = shapes.get(lp["shape"], 0) + 1
    rel = os.path.relpath(".", out_dir)
    colours = {"frozen": "#05f", "frozen print": "#5af", "serial": "#2a2", "near serial": "#6c2", "detail": "#a3c", "string and match": "#c80", "match": "#28c"}

    def figure(s):
        w, h = texts[s]["size"] or [1, 1]
        shapes_svg = ""
        for lp in by_photo.get(s, []):
            pts = " ".join(f"{x},{y}" for x, y in lp["outline"])
            c = colours[lp["found_by"]]
            shapes_svg += (f'<circle cx="{lp["centre"][0]}" cy="{lp["centre"][1]}" r="{lp["radius"]}" fill="none" stroke="{c}" stroke-dasharray="8 8" stroke-width="{max(w, h) / 300}"/>'
                           f'<polygon points="{pts}" fill="{c}" fill-opacity="0.15" stroke="{c}" stroke-width="{max(w, h) / 200}"/>')
        label = "<br>".join(html.escape(f'{lp["found_by"]}: {", ".join(t["serial"] for t in lp["strings"]) or "-"}{"; " + ", ".join(d["detail"][:-4] for d in lp.get("details", [])) if lp.get("details") else ""} ({lp["shape"]}, {len(lp["matches"])} links{", placed by " + lp["placed_by"] if lp.get("placed_by") else ""})') for lp in by_photo.get(s, []))
        return (f'<figure><div class="ph"><img loading="lazy" src="{rel}/{chosen[s]}"><svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">{shapes_svg}</svg></div>'
                f'<figcaption><code>{s[:10]}</code><br>{label}</figcaption></figure>')

    rejected = "".join(f'<li><code>{r["photo"][:10]}</code>: {html.escape(", ".join(t["text"] for t in r["strings"]))}</li>' for r in result["rejected"])
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>find</title>
<style>body{{font:14px system-ui;margin:16px}} figure{{display:inline-block;margin:6px;vertical-align:top;width:260px}}
.ph{{position:relative;display:inline-block}} .ph img{{max-width:260px;max-height:260px;display:block}} .ph svg{{position:absolute;inset:0;width:100%;height:100%}}
figcaption{{font-size:12px}}</style>
<h1>find</h1>
<p>{len(chosen)} photos, {len(lps)} label photos (found by: {", ".join(f"{k} {v}" for k, v in counts.items())}; shapes: {", ".join(f"{k} {v}" for k, v in shapes.items())}), {len(result["sets"])} linked sets (largest {len(result["sets"][0]) if result["sets"] else 0}). Photos with no label photo: {len(none)}; with several: {len(several)}.</p>
<p>Filled: the hull of the evidence (or the label placed by a logo); dashed: the circle the evidence was looked for in. The colour says how the label photo was found:</p>
{steps.legend([(c, k) for k, c in colours.items()])}
<h2>No label photo ({steps.shown(len(none))})</h2>{"".join(figure(s) for s in steps.few(none))}
<h2>Several label photos ({steps.shown(len(several))})</h2>{"".join(figure(s) for s in steps.few(several))}
<h2>Rejected candidates ({len(result["rejected"])})</h2><ul>{rejected}</ul>
<h2>One label photo ({steps.shown(len(chosen) - len(none) - len(several))})</h2>{"".join(figure(s) for s in steps.few(s for s in chosen if s in by_photo and s not in several))}
""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--no-strings", action="store_true")
    args = ap.parse_args()
    chosen = photos.chosen(args.sample)
    gen = photos.generated(args.sample)
    out_dir = os.path.join(gen, "find-no-strings" if args.no_strings else "find")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "label-photos.json")
    text_files = {s: os.path.join(gen, "read-text", s + ".json") for s in chosen}
    match_files = [os.path.join(gen, "match", s + ".npz") for s in chosen]
    missing = [p for p in list(text_files.values()) + match_files if not os.path.exists(p)]
    if missing:
        sys.exit(f"{len(missing)} inputs missing: run make read-text and make match first")
    found = details.detections(gen, chosen)
    detail_files = [os.path.join(gen, "details", s + ".json") for s in chosen]
    places_file = os.path.join(details.DETAILS, details.PLACES)
    newest = max(os.path.getmtime(p) for p in list(text_files.values()) + match_files + detail_files + [places_file]
                 + [f for f in (NOT_LABELS, frozen.FILE) if os.path.exists(f)])
    texts = {s: json.load(open(p, encoding="utf-8")) for s, p in text_files.items()}
    if steps.stale(out, __file__) or os.path.getmtime(out) < newest:
        result = find(chosen, texts, match.read_matches(os.path.join(gen, "match"), list(chosen), frozen.images()), serials.load_database(),
                      found, use_strings=not args.no_strings, places=details.load_places(), not_labels=load_not_labels(),
                      frozen_images={e["image"]: {"print": pid, "crop": e["crop"], "shape": e["shape"]} for pid, e in frozen.load().items()},
                      frozen_lps={k: {"photo": r["photo"], "cut": frozen.cut_corners(r), "found": r.get("found"), "shape": r["shape"]}
                                  for k, (pid, r) in frozen.label_photos(frozen.load()).items()})
        steps.write_json(out, result)
    result = json.load(open(out, encoding="utf-8"))
    page(out_dir, chosen, result, texts)
    print(f"{len(result['label_photos'])} label photos; page: {os.path.join(out_dir, 'index.html')}")


if __name__ == "__main__":
    main()
