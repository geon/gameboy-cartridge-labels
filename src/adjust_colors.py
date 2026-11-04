import json, os, sys, threading, urllib.parse, cv2, numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import color, photos, serials
from fit_colors import LABELS, auto, candidates
from review_fits import FILTERS_JS, facet_counts, filters_of, matching

# adjust-colors: a local page for setting each photo's colors by hand (src/color.py: brightness, contrast,
# temperature, tint), release by release, its photos' labels side by side, so that they can be made to match; the
# reference sources' (color.REFERENCES: lit alike, what the others are matched to) marked. Each label is shown as
# render-labels makes it (its image from make fit-colors, with its settings applied as color.adjusted does), and
# changes as its sliders move; let go of one, and the photo's settings are saved to colors.json as placed by hand,
# which fit-colors keeps. "Auto" puts back the settings fit-colors would make. Releases with the most photos first.
# Needs make fit-colors first (the label images, and the settings to start from).
# Usage: adjust_colors.py [port]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8771
PER_PAGE = 8
# The sliders' ranges and steps, by setting.
RANGES = {"brightness": (-1.5, 1.5, 0.01), "contrast": (0.5, 2.0, 0.01), "temperature": (-1.0, 1.0, 0.01), "tint": (-0.5, 0.5, 0.01)}


class Adjust:
    def __init__(self):
        found = candidates()
        self.source = {stem: f[0] for stem, f in found.items() if os.path.exists(os.path.join(LABELS, stem + ".png"))}
        self.sha1 = {stem: found[stem][2] for stem in self.source}
        release_of = serials.releases_by_serial()
        self.photos = {}
        for stem in sorted(self.source, key=lambda s: (photos.rank(self.source[s]), s)):
            self.photos.setdefault(serials.release_key(stem, release_of)[0], []).append(stem)
        self.order = sorted(self.photos, key=lambda r: (-len(self.photos[r]), r))
        self.lock = threading.Lock()
        colors = color.load_colors()
        self.facets = {
            "source": {s: {r for r in self.order if any(self.source[p] == s for p in self.photos[r])}
                       for s in sorted(set(self.source.values()), key=photos.rank)},
            "reference": {"with a reference": {r for r in self.order if any(self.source[p] in color.REFERENCES for p in self.photos[r])},
                          "without": {r for r in self.order if not any(self.source[p] in color.REFERENCES for p in self.photos[r])}},
            "photos": {"several": {r for r in self.order if len(self.photos[r]) > 1}, "one": {r for r in self.order if len(self.photos[r]) == 1}},
        }
        hand = {r for r in self.order if any((color.colors_of(colors, p, self.sha1[p]) or {}).get("source") == "hand-placed" for p in self.photos[r])}
        self.facets["by hand"] = {"some": hand, "none": set(self.order) - hand}

    def settings(self, colors, stem):
        found = color.colors_of(colors, stem, self.sha1[stem])
        if found is None:
            return dict(color.NEUTRAL, source=None)
        return {k: found[k] for k in color.SETTINGS} | {"source": found.get("source")}

    def page(self, filters, number):
        chosen = matching(self.order, self.facets, filters)
        colors = color.load_colors()
        releases = [{"release": r, "photos": [{"name": p, "source": self.source[p], "reference": self.source[p] in color.REFERENCES,
                                               "settings": self.settings(colors, p)} for p in self.photos[r]]}
                    for r in chosen[number * PER_PAGE:(number + 1) * PER_PAGE]]
        return {"releases": releases, "pages": max(1, -(-len(chosen) // PER_PAGE)), "count": len(chosen)}

    def save(self, stem, settings, source):
        clean = {k: round(float(settings[k]), 4) for k in color.SETTINGS}
        with color.editing_colors() as colors:
            colors[stem] = {"sha1": self.sha1[stem], "colors": clean | {"source": source}}
        return clean | {"source": source}

    def auto(self, stem):
        label = cv2.imread(os.path.join(LABELS, stem + ".png"))
        return self.save(stem, auto(self.source[stem], color.paper(label)), "auto-generated")


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Adjust colors</title>
<style>
body{font:14px system-ui;margin:0;background:#f4f4f4;color:#222}
header{position:sticky;top:0;background:#fff;padding:8px 16px;border-bottom:1px solid #ddd;display:flex;gap:12px;align-items:center;flex-wrap:wrap;z-index:1}
#position{display:inline-block;width:12ch;text-align:center;font-variant-numeric:tabular-nums}
#filters{display:flex;gap:12px}#count{color:#555;font-variant-numeric:tabular-nums}
main{padding:12px 16px;display:flex;flex-direction:column;gap:16px}
.release h2{font-size:14px;margin:0 0 6px}
.row{display:flex;gap:12px;overflow-x:auto;padding-bottom:4px}
section{background:#fff;border-radius:6px;padding:8px;display:flex;flex-direction:column;gap:4px;flex:none;width:400px}
section.reference{outline:2px solid #07a}
.top{display:flex;gap:6px;align-items:center}
h3{flex:1;font-size:13px;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.state{width:9ch;font-size:12px;color:#555;text-align:right}.state.hand{color:#070}
canvas{width:400px;height:348px;display:block;background:#eee}
label.slider{display:grid;grid-template-columns:11ch 1fr 7ch;align-items:center;font-size:12px;gap:6px}
label.slider span:last-child{text-align:right;font-variant-numeric:tabular-nums}
input[type=range]{width:100%}
button{font:inherit;padding:4px 10px;border:none;border-radius:0.3em}
</style>
<header>
<span id="filters"></span><span id="count"></span>
<button id="prev">← prev</button><span id="position"></span><button id="next">next →</button>
<span style="color:#555">Blue outline: a reference source.</span>
</header>
<main id="entries"></main>
<script>
const RANGES = %RANGES%, NAMES = Object.keys(RANGES), LUM = [0.0722, 0.7152, 0.2126];
let page = 0, pages = 1;
const $ = id => document.getElementById(id);
const esc = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
%FILTERS_JS%
const LIN = Array.from({length: 256}, (_, i) => { const v = i / 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
const SRGB = Array.from({length: 4096}, (_, i) => { const v = i / 4095; return Math.round(255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055)); });
// As color.gains_of and color.adjusted: per channel (B, G, R) 2^k * x^contrast; above white scaled down, its hue kept.
function gains(s) {
  const a = s.brightness - LUM[1] * s.tint - (LUM[2] - LUM[0]) * s.temperature / 2;
  return [a - s.temperature / 2, a + s.tint, a + s.temperature / 2];
}
const originals = {};
function draw(section) {
  const canvas = section.querySelector("canvas"), source = originals[section.dataset.name];
  if (!source) return;
  const s = settingsOf(section), k = gains(s);
  const curves = [2, 1, 0].map(c => LIN.map(x => 2 ** k[c] * x ** s.contrast));  // R, G, B (canvas order)
  const out = new ImageData(source.width, source.height), a = source.data, b = out.data;
  for (let i = 0; i < a.length; i += 4) {
    let r = curves[0][a[i]], g = curves[1][a[i + 1]], bl = curves[2][a[i + 2]];
    const m = Math.max(r, g, bl);
    if (m > 1) { r /= m; g /= m; bl /= m; }
    b[i] = SRGB[Math.round(r * 4095)]; b[i + 1] = SRGB[Math.round(g * 4095)]; b[i + 2] = SRGB[Math.round(bl * 4095)]; b[i + 3] = 255;
  }
  canvas.getContext("2d").putImageData(out, 0, 0);
}
const settingsOf = section => Object.fromEntries(NAMES.map(n => [n, parseFloat(section.querySelector(`input[name=${n}]`).value)]));
const shown = (name, v) => name === "contrast" ? v.toFixed(2) : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2);
function setSettings(section, s) {
  for (const n of NAMES) { section.querySelector(`input[name=${n}]`).value = s[n]; section.querySelector(`[data-value=${n}]`).textContent = shown(n, s[n]); }
  const state = section.querySelector(".state");
  state.textContent = s.source === "hand-placed" ? "by hand" : s.source === "auto-generated" ? "auto" : "none";
  state.classList.toggle("hand", s.source === "hand-placed");
  draw(section);
}
async function load() {
  const data = await (await fetch("/list")).json(), hash = fromHash();
  showFilters(data.facets, hash);
  page = Math.max(0, (parseInt(hash.page) || 1) - 1);
  show();
}
async function show() {
  const data = await (await fetch(`/page/${page}?${filterQuery()}`)).json();
  pages = data.pages;
  if (page >= pages) { page = pages - 1; return show(); }
  setHash({page: page + 1});
  $("count").textContent = `${data.count} releases`;
  $("position").textContent = `page ${page + 1} / ${pages}`;
  $("entries").innerHTML = data.releases.map(r => `<div class="release"><h2>${esc(r.release)}</h2><div class="row">` + r.photos.map(p => `
    <section data-name="${esc(p.name)}" class="${p.reference ? "reference" : ""}">
      <div class="top"><h3 title="${esc(p.source)}">${esc(p.name)} · ${esc(p.source)}</h3><span class="state"></span><button class="auto">Auto</button></div>
      <canvas width="200" height="174"></canvas>
      ${NAMES.map(n => `<label class="slider"><span>${n}</span><input type="range" name="${n}" min="${RANGES[n][0]}" max="${RANGES[n][1]}" step="${RANGES[n][2]}"><span data-value="${n}"></span></label>`).join("")}
    </section>`).join("") + "</div></div>").join("");
  const all = data.releases.flatMap(r => r.photos);
  for (const section of document.querySelectorAll("section")) {
    const p = all.find(p => p.name === section.dataset.name);
    setSettings(section, p.settings);
    const image = new Image();
    image.onload = () => {
      const c = document.createElement("canvas"); c.width = image.width; c.height = image.height;
      const ctx = c.getContext("2d"); ctx.drawImage(image, 0, 0);
      originals[p.name] = ctx.getImageData(0, 0, image.width, image.height);
      draw(section);
    };
    image.src = `/label/${encodeURIComponent(p.name)}`;
  }
  window.scrollTo(0, 0);
}
$("entries").oninput = e => {
  if (e.target.type !== "range") return;
  const section = e.target.closest("section");
  section.querySelector(`[data-value=${e.target.name}]`).textContent = shown(e.target.name, parseFloat(e.target.value));
  draw(section);
};
async function post(path, body) {
  const response = await fetch(path, {method: "POST", body: JSON.stringify(body)});
  if (!response.ok) { alert("Not saved: " + await response.text()); return null; }
  return response.json();
}
$("entries").onchange = async e => {
  if (e.target.type !== "range") return;
  const section = e.target.closest("section");
  const saved = await post("/colors", {name: section.dataset.name, settings: settingsOf(section)});
  if (saved) setSettings(section, saved);
};
$("entries").onclick = async e => {
  if (!e.target.matches("button.auto")) return;
  const section = e.target.closest("section");
  const saved = await post("/auto", {name: section.dataset.name});
  if (saved) setSettings(section, saved);
};
const go = p => { if (p >= 0 && p < pages) { page = p; show(); } };
$("filters").onchange = () => { page = 0; show(); };
$("prev").onclick = () => go(page - 1);
$("next").onclick = () => go(page + 1);
document.onkeydown = e => {
  if (e.target.tagName === "SELECT" || e.target.type === "range") return;
  if (e.key === "ArrowLeft") go(page - 1);
  if (e.key === "ArrowRight") go(page + 1);
};
load();
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
            self.send(PAGE.replace("%FILTERS_JS%", FILTERS_JS).replace("%RANGES%", json.dumps(RANGES)).encode(), "text/html; charset=utf-8")
        elif parts == ["list"]:
            self.send({"facets": facet_counts(adjust.facets)})
        elif len(parts) == 2 and parts[0] == "page" and parts[1].isdigit():
            self.send(adjust.page(filters_of(self.path), int(parts[1])))
        elif len(parts) == 2 and parts[0] == "label" and parts[1] in adjust.source:
            self.send(open(os.path.join(LABELS, parts[1] + ".png"), "rb").read(), "image/png")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ("/colors", "/auto"):
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if data.get("name") not in adjust.source:
            return self.send_error(400)
        if self.path == "/auto":
            return self.send(adjust.auto(data["name"]))
        settings = data.get("settings", {})
        if any(not isinstance(settings.get(k), (int, float)) or not RANGES[k][0] <= settings[k] <= RANGES[k][1] for k in color.SETTINGS):
            return self.send_error(400)
        self.send(adjust.save(data["name"], settings, "hand-placed"))

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    adjust = Adjust()
    print(f"{len(adjust.order)} releases, {len(adjust.source)} photos with a label; adjust them at http://localhost:{PORT}/ (ctrl-C to stop)")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
