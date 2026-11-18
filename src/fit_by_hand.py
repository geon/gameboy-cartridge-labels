# fit-by-hand: a tool, not a step: a local page for placing labels by hand where the edge models were unsure, to train
# and test the label edge model on (the user, 2026-11-13). Main's fit-by-hand's label-alone mode (its page code taken
# over), on this branch's label photos: one shape's approximate cuts (solve.approximate_cut: the edge models found no
# plausible label), the lowest label confidence first (solve.json's edge.label_confidence). Each shown as straighten
# draws it (its ink coordinates, straighten.PX_PER_MM, straighten.MARGIN mm around the nominal label), with only the
# label's cut as a rectangle (cyan, corners rounded as main draws them), starting at solve's fitted cut (or the one saved
# before): its corners dragged freely (the perspective with them), the dots in its sides sliding one side; a magnifier
# shows 6 mm around the handle held. Saving writes the corners to HAND_FILE in the photo's own pixels (so a fit stays
# true whatever solve does later) and goes to the next; saved again, it replaces the one before. Next skips. "Not a
# label" (a button only: a key next to S was too easy to hit, the user) marks the area as not a label in find's
# NOT_LABELS: the fitted cut and find's outline of it, in the photo's pixels (the outline too: on about 15 % of the
# approximate cuts find's centre lies outside the fitted cut); find makes no label photo there on its next run, the photo
# and its other label photos stay. Its entry in HAND_FILE goes, and it leaves the list.
# No step reads HAND_FILE.
# Usage: fit_by_hand.py [shape] [port]   (shape: dmg, cgb or agb; cgb by default)
import json, os, sys, threading, urllib.parse, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, numpy as np
import photos
import solve as solve_step, straighten, cuts, shapes, steps, find as find_step

GEN = "generated"
HAND_FILE = "hand-fit-labels.json"  # {label photo key: {"corners": [[x, y] x 4: the cut's top left, top right, bottom right, bottom left, in the photo's pixels], "datetime"}}
lock = threading.Lock()
now = lambda: datetime.datetime.now().astimezone().isoformat(timespec="seconds")


PX_TO_MM = straighten.canvas("dmg")[1]  # a straightened image's px -> ink mm: the same for every shape (only the size differs)


def view_to_photo(photo_to_ink, pts):
    """Points in a straightened image's pixels -> the photo's pixels, through the fit it was drawn from."""
    H = np.linalg.inv(np.float64(photo_to_ink)) @ PX_TO_MM
    return cv2.perspectiveTransform(np.float64(pts).reshape(-1, 1, 2), H).reshape(-1, 2)


def photo_to_view(photo_to_ink, pts):
    H = np.linalg.inv(PX_TO_MM) @ np.float64(photo_to_ink)
    return cv2.perspectiveTransform(np.float64(pts).reshape(-1, 1, 2), H).reshape(-1, 2)


class Hand:
    def __init__(self, shape):
        self.shape = shape
        self.solved = json.load(open(os.path.join(GEN, "solve", "solve.json"), encoding="utf-8"))["label_photos"]
        self.hand = json.load(open(HAND_FILE, encoding="utf-8")) if os.path.exists(HAND_FILE) else {}
        conf = lambda r: (r.get("edge") or {}).get("label_confidence") or 0.0
        marked = json.load(open(find_step.NOT_LABELS, encoding="utf-8")) if os.path.exists(find_step.NOT_LABELS) else {}  # gone once find runs again
        keys = [k for k, r in self.solved.items() if r["shape"] == shape and solve_step.approximate_cut(r)
                and k not in marked and os.path.exists(self.base(k) + ".drawn.json")]
        self.order = sorted(keys, key=lambda k: (conf(self.solved[k]), k))
        self.conf = {k: conf(self.solved[k]) for k in keys}
        self.found = {lp["key"]: lp["outline"] for lp in json.load(open(os.path.join(GEN, "find", "label-photos.json"), encoding="utf-8"))["label_photos"]}

    def base(self, key):
        return os.path.join(GEN, "straighten", straighten.file_name(key)[:-5])

    def drawn(self, key):
        return json.load(open(self.base(key) + ".drawn.json", encoding="utf-8"))

    def item(self, key):
        r, d = self.solved[key], self.drawn(key)
        if key in self.hand:
            corners = photo_to_view(d["photo_to_ink"], self.hand[key]["corners"])
        else:  # solve's fitted cut, in the image as drawn (straighten.cut_inputs)
            ink = cuts.corners_in_ink(np.float64(d["photo_to_ink"]) @ np.float64(r["cut_to_photo"]), r["shape"], r.get("width_mm"), r.get("height_mm"))
            corners = cv2.perspectiveTransform(ink.reshape(-1, 1, 2), np.linalg.inv(PX_TO_MM)).reshape(-1, 2)
        w, h = shapes.LABEL_MM[r["shape"]]
        notes = [f"label confidence {self.conf[key]:.2f}", f"{solve_step.local_scale(np.array(r['cut_to_photo']), [0, 0, w, h]):.0f} px/mm in the photo",
                 f"family of {r['family_size']}"]
        if r.get("carried"):
            notes.append(f"pose carried from {r['carried']['from']}")
        if key in self.hand:
            notes.append(f"placed by hand {self.hand[key]['datetime']}")
        return {"key": key, "corners": np.round(corners, 2).tolist(), "label_mm": [w, h], "px_per_mm": straighten.PX_PER_MM, "notes": notes}

    def image(self, key):
        img = photos.imread(os.path.join(GEN, "straighten", straighten.file_name(key)))
        return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()

    def save(self, key, corners_view):
        corners = view_to_photo(self.drawn(key)["photo_to_ink"], corners_view)
        with lock:
            self.hand[key] = {"corners": np.round(corners, 2).tolist(), "datetime": now()}
            steps.write_json(HAND_FILE, self.hand)

    def not_a_label(self, key):
        r, found = self.solved[key], self.found.get(key)
        w, h = shapes.LABEL_MM[r["shape"]]
        area = cv2.perspectiveTransform(np.float64([[[0, 0]], [[w, 0]], [[w, h]], [[0, h]]]), np.float64(r["cut_to_photo"])).reshape(-1, 2)
        with lock:
            marked = json.load(open(find_step.NOT_LABELS, encoding="utf-8")) if os.path.exists(find_step.NOT_LABELS) else {}
            marked[key] = {"photo": r["photo"], "area": np.round(area, 1).tolist(), "found": found, "datetime": now()}
            steps.write_json(find_step.NOT_LABELS, marked)
            if self.hand.pop(key, None):
                steps.write_json(HAND_FILE, self.hand)
            self.order = [k for k in self.order if k != key]
            self.conf.pop(key, None)

    def listing(self):
        return {"items": [{"key": k, "conf": round(self.conf[k], 2), "placed": k in self.hand} for k in self.order],
                "placed": sum(k in self.hand for k in self.order)}


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fit labels by hand</title>
<style>
body{font:14px system-ui;margin:0;background:#f4f4f4;color:#222;display:flex;height:100vh}
#side{width:300px;flex:none;display:flex;flex-direction:column;gap:8px;background:#fff;padding:8px;box-sizing:border-box;border-right:1px solid #ddd}
#loupe{display:block;width:240px;height:240px;background:#000}
#summary{color:#555;font-variant-numeric:tabular-nums}
#list{flex:1;overflow:auto;min-height:0;font-variant-numeric:tabular-nums;font-size:12px}
#list a{display:block;color:#222;text-decoration:none;padding:2px 4px;border-radius:0.3em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#list a.cur{background:#dde}#list a::before{content:"\\2713  ";color:transparent}#list a.placed::before{color:#070}
#main{flex:1;display:flex;flex-direction:column;min-width:0}
header{background:#fff;padding:8px 16px;border-bottom:1px solid #ddd;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
#position{display:inline-block;width:12ch;text-align:center;font-variant-numeric:tabular-nums}
h2{font-size:14px;margin:0;width:30ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#notes,#help{flex-basis:100%;margin:0;font-size:12px;color:#555}
#stage{flex:1;position:relative;overflow:hidden;background:#333}
canvas#c{position:absolute;left:0;top:0}
button{font:inherit;padding:4px 10px;border:none;border-radius:0.3em}
button#save{background:#070;color:#fff}button#notlabel{background:#b00;color:#fff}
#status{display:inline-block;width:10ch;color:#070}
</style>
<div id="side"><span id="summary"></span><canvas id="loupe" width="240" height="240"></canvas><div id="list"></div></div>
<div id="main"><header>
<button id="prev">← prev</button><span id="position"></span><button id="next">next (skip) →</button>
<h2 id="title"></h2><button id="reset">Reset (R)</button><button id="save">Save (S)</button><button id="notlabel">Not a label</button><span id="status"></span>
<p id="notes"></p>
<p id="help">Drag the label's corners (squares) onto the sticker's; the dots slide a side. Tab: next handle; arrow keys: nudge 1 px (Shift: 10 px); wheel: zoom; drag elsewhere: pan; S: save and go to the next; N: next without saving. Not a label (no key): marks the area as not a label for find, and goes to the next.</p>
</header><div id="stage"><canvas id="c"></canvas></div></div>
<script>
const $ = id => document.getElementById(id);
const c = $("c"), ctx = c.getContext("2d"), lctx = $("loupe").getContext("2d");
let list = [], i = 0, item = null, img = new Image();
let corners = null, sel = 0, drag = -1, grab = null, startCorners = null, pan = null;
let scale = 1, ox = 0, oy = 0;
const apply = (H, [x, y]) => { const w = H[2][0] * x + H[2][1] * y + H[2][2]; return [(H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w]; };
function homography(src, dst) {
  const A = [], b = [];
  for (let k = 0; k < 4; k++) {
    const [x, y] = src[k], [u, v] = dst[k];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
  }
  for (let col = 0; col < 8; col++) {
    let p = col;
    for (let r = col + 1; r < 8; r++) if (Math.abs(A[r][col]) > Math.abs(A[p][col])) p = r;
    [A[col], A[p]] = [A[p], A[col]]; [b[col], b[p]] = [b[p], b[col]];
    for (let r = 0; r < 8; r++) if (r !== col) { const f = A[r][col] / A[col][col]; for (let k = col; k < 8; k++) A[r][k] -= f * A[col][k]; b[r] -= f * b[col]; }
  }
  const h = b.map((v, k) => v / A[k][k]);
  return [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1]];
}
// The label's own mm (its canonical rectangle) and the homography to the image's pixels through the handles.
const labelMm = () => { const [w, h] = item.label_mm; return [[0, 0], [w, 0], [w, h], [0, h]]; };
const toView = () => homography(labelMm(), corners), toMm = () => homography(corners, labelMm());
const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
// The label's outline with its corners rounded (1.4 mm, as main draws it), in its mm.
function roundedOutline(radius = 1.4, per = 6) {
  const [w, h] = item.label_mm, pts = [];
  [[radius, radius, Math.PI], [w - radius, radius, 1.5 * Math.PI], [w - radius, h - radius, 0], [radius, h - radius, 0.5 * Math.PI]].forEach(([cx, cy, a0]) => {
    for (let k = 0; k <= per; k++) { const t = a0 + k / per * Math.PI / 2; pts.push([cx + radius * Math.cos(t), cy + radius * Math.sin(t)]); }
  });
  return pts;
}
// Handles, in the image's pixels: 0-3 the label's corners, 4-7 the middle of its sides (top, right, bottom, left).
function handles() { const H = toView(), R = labelMm(); return corners.concat([0, 1, 2, 3].map(k => apply(H, mid(R[k], R[(k + 1) % 4])))); }
// Slides side k, from where it was at the start of the drag, to pass through the point q.
function slide(k, q, start) {
  const R = labelMm(), Hs = homography(R, start), m = apply(homography(start, R), q), s = mid(R[k], R[(k + 1) % 4]);
  const e = [R[(k + 1) % 4][0] - R[k][0], R[(k + 1) % 4][1] - R[k][1]], len = Math.hypot(...e), n = [e[1] / len, -e[0] / len];
  const d = (m[0] - s[0]) * n[0] + (m[1] - s[1]) * n[1];
  corners = start.map(p => p.slice());
  for (const j of [k, (k + 1) % 4]) corners[j] = apply(Hs, [R[j][0] + d * n[0], R[j][1] + d * n[1]]);
}
function move(h, q, startC) { if (h < 4) corners[h] = q; else slide(h - 4, q, startC); $("status").textContent = ""; }
async function start() { await showList(decodeURIComponent(location.hash.slice(1))); }
const showSummary = d => $("summary").textContent = `${d.items.length} label photos, ${d.placed} placed by hand`;
async function showList(key) {
  const data = await (await fetch("/list")).json();
  list = data.items; showSummary(data);
  i = Math.max(0, list.findIndex(p => p.key === key));
  showNames();
  if (list.length) show(); else $("title").textContent = "none";
}
function showNames() {
  $("list").innerHTML = list.map((p, k) => `<a href="#" data-k="${k}" class="${k === i ? "cur" : ""} ${p.placed ? "placed" : ""}">${p.conf.toFixed(2)} ${p.key}</a>`).join("");
  $("list").querySelector(".cur")?.scrollIntoView({block: "nearest"});
}
$("list").onclick = e => { const a = e.target.closest("a"); if (a) { e.preventDefault(); go(+a.dataset.k); } };
async function show() {
  const key = list[i].key;
  history.replaceState(null, "", "#" + encodeURIComponent(key));
  $("position").textContent = `${i + 1} / ${list.length}`;
  $("title").textContent = key; $("status").textContent = "";
  showNames();
  const it = await (await fetch("/item/" + encodeURIComponent(key))).json();
  const im = await new Promise(done => { const x = new Image(); x.onload = () => done(x); x.src = "/image/" + encodeURIComponent(key); });
  if (list[i].key !== key) return;
  item = it; img = im;
  $("notes").textContent = item.notes.join(" · ");
  frame(); reset();
}
function reset() { corners = item.corners.map(q => q.slice()); sel = 0; draw(); }
function frame() {
  const m = $("stage");
  c.width = m.clientWidth; c.height = m.clientHeight;
  scale = Math.min(c.width / img.width, c.height / img.height) * 0.95;
  ox = (c.width - img.width * scale) / 2; oy = (c.height - img.height * scale) / 2;
}
const toScreen = q => [ox + q[0] * scale, oy + q[1] * scale], viewAt = (x, y) => [(x - ox) / scale, (y - oy) / scale];
function stroke(g, pts, at) { g.beginPath(); pts.forEach((q, k) => { const [x, y] = at(q); k ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); g.stroke(); }
const outline = () => { const H = toView(); return roundedOutline().map(q => apply(H, q)); };
function draw() {
  ctx.clearRect(0, 0, c.width, c.height);
  ctx.drawImage(img, ox, oy, img.width * scale, img.height * scale);
  ctx.lineWidth = 1; ctx.strokeStyle = "#3cf"; stroke(ctx, outline(), toScreen);
  handles().forEach((q, k) => {
    const [x, y] = toScreen(q);
    ctx.fillStyle = k === sel ? "#ff0" : "#3cf";
    if (k < 4) ctx.fillRect(x - 4, y - 4, 8, 8); else { ctx.beginPath(); ctx.arc(x, y, 4, 0, 7); ctx.fill(); }
  });
  loupe(handles()[sel]);
}
// The magnifier: 6 x 6 mm around the handle.
function loupe(v) {
  const r = 3 * item.px_per_mm, z = 120 / r, at = p => [120 + (p[0] - v[0]) * z, 120 + (p[1] - v[1]) * z];
  lctx.imageSmoothingEnabled = false;
  lctx.fillStyle = "#000"; lctx.fillRect(0, 0, 240, 240);
  lctx.drawImage(img, v[0] - r, v[1] - r, 2 * r, 2 * r, 0, 0, 240, 240);
  lctx.strokeStyle = "#3cf"; stroke(lctx, outline(), at);
  lctx.strokeStyle = "#ff0"; lctx.strokeRect(117, 117, 6, 6);
}
c.onmousedown = e => {
  if (!corners) return;
  let best = -1, bd = 12 ** 2;
  handles().forEach((q, k) => { const [sx, sy] = toScreen(q), d = (sx - e.offsetX) ** 2 + (sy - e.offsetY) ** 2; if (d < bd) { bd = d; best = k; } });
  if (best < 0) { pan = [e.offsetX - ox, e.offsetY - oy]; return; }
  drag = sel = best;
  startCorners = corners.map(q => q.slice());
  const h = handles()[best], m = viewAt(e.offsetX, e.offsetY);
  grab = [h[0] - m[0], h[1] - m[1]];
  draw();
};
c.onmousemove = e => {
  if (pan) { ox = e.offsetX - pan[0]; oy = e.offsetY - pan[1]; return draw(); }
  if (drag < 0) return;
  const m = viewAt(e.offsetX, e.offsetY);
  move(drag, [m[0] + grab[0], m[1] + grab[1]], startCorners);
  draw();
};
window.onmouseup = () => { drag = -1; pan = null; };
c.onwheel = e => {
  e.preventDefault();
  const f = Math.exp(-e.deltaY / 500), [x, y] = [e.offsetX, e.offsetY];
  ox = x - (x - ox) * f; oy = y - (y - oy) * f; scale *= f;
  draw();
};
async function save() {
  if (!corners) return;
  const response = await fetch("/save", {method: "POST", body: JSON.stringify({key: item.key, corners})});
  if (!response.ok) return alert("Not saved: " + response.status);
  showSummary(await response.json());
  list[i].placed = true;
  if (i + 1 < list.length) go(i + 1); else { showNames(); $("status").textContent = "saved"; }
}
async function notLabel() {
  if (!item) return;
  const response = await fetch("/not-a-label", {method: "POST", body: JSON.stringify({key: item.key})});
  if (!response.ok) return alert("Not marked: " + response.status);
  const data = await response.json();
  list = data.items; showSummary(data);
  item = null; corners = null;
  if (!list.length) { $("title").textContent = "none"; return; }
  i = Math.min(i, list.length - 1); show();
}
const go = k => { if (k >= 0 && k < list.length) { i = k; show(); } };
$("prev").onclick = () => go(i - 1);
$("next").onclick = () => go(i + 1);
$("reset").onclick = () => reset();
$("save").onclick = () => save();
$("notlabel").onclick = () => notLabel();
document.onkeydown = e => {
  if (!corners) return;
  const step = e.shiftKey ? 10 : 1, d = {ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step]}[e.key];
  if (d) { const h = handles()[sel]; move(sel, [h[0] + d[0], h[1] + d[1]], corners.map(q => q.slice())); draw(); e.preventDefault(); }
  else if (e.key === "Tab") { const order = [0, 4, 1, 5, 2, 6, 3, 7]; sel = order[(order.indexOf(sel) + (e.shiftKey ? 7 : 1)) % 8]; draw(); e.preventDefault(); }
  else if (e.key === "s" || e.key === "S") save();
  else if (e.key === "n" || e.key === "N") go(i + 1);
  else if (e.key === "r" || e.key === "R") reset();
};
window.onresize = () => { if (img.width) { frame(); draw(); } };
start();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def send(self, body, kind="application/json"):
        body = json.dumps(body).encode() if kind == "application/json" else body
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parts = [urllib.parse.unquote(p) for p in self.path.split("?")[0].split("/")[1:]]
        if parts == [""]:
            self.send(PAGE.encode(), "text/html; charset=utf-8")
        elif parts == ["list"]:
            self.send(hand.listing())
        elif len(parts) == 2 and parts[0] == "item" and parts[1] in hand.conf:
            self.send(hand.item(parts[1]))
        elif len(parts) == 2 and parts[0] == "image" and parts[1] in hand.conf:
            self.send(hand.image(parts[1]), "image/jpeg")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ("/save", "/not-a-label"):
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/not-a-label":
            if data.get("key") not in hand.conf:
                return self.send_error(400)
            hand.not_a_label(data["key"])
            return self.send(hand.listing())
        if data.get("key") not in hand.conf or np.shape(data.get("corners")) != (4, 2):
            return self.send_error(400)
        hand.save(data["key"], data["corners"])
        self.send(hand.listing())

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    shape = sys.argv[1] if len(sys.argv) > 1 else "cgb"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8771
    hand = Hand(shape)
    print(f"{len(hand.order)} {shape.upper()} approximate cuts, {sum(k in hand.hand for k in hand.order)} placed by hand; "
          f"place them at http://localhost:{port}/ (ctrl-C to stop)")
    ThreadingHTTPServer(("localhost", port), Handler).serve_forever()
