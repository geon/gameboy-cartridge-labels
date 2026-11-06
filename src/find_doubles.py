import hashlib, json, os, sys, threading, urllib.parse, cv2
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fits, photos, render, serials
from cartridge import shell_of
from fit_cartridge import load

# find-doubles: a local page listing every photo in photos/, one release per row (the release its serial is filed
# under in gb-game-list, the region dropped if gb-game-list lacks it; else the serial itself), its photos sorted by
# their source's quality (photos.SOURCES, best first), each marked with an orange check if its plastic is fitted (accepted or
# placed by hand), a green one if its label is too. Each photo can be deleted (photos.delete), its fits with it, or
# renamed to a corrected serial (photos.rename: tidied, numbered if taken, moved to its system's folder), its fits
# following it. Clicking a photo makes it its release's preferred one (clicking it again unmakes it), saved in
# preferred.json: release id -> the photo's SHA-1, so a renamed photo stays preferred; an entry whose photo is no longer
# in its release (deleted, or renamed to another serial) is dropped on the next save. The fakes (photos.FAKES) are left
# out: never worth preferring. The preferred photo comes first. A photo whose plastic fit is accepted or placed by hand
# is shown cropped to it, as render-carts renders it.
# The rows can be narrowed to the releases with several photos (one and one from otakaraou count as one: photos.only), and to those with no preferred photo (a release given
# one stays shown until the rows are drawn again).
# Usage: find_doubles.py [port]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
lock = threading.Lock()


def plastic_of(known, name, sha1):
    """The photo's plastic fit if it's accepted or placed by hand, else None."""
    plastic = fits.of(known, photos.stem(name), sha1)["fit"].get("plastic")
    return plastic if fits.good(plastic) else None


def image(path, longest):
    """The photo, its longest side at most longest px, as WebP bytes; with an accepted or hand-placed
    plastic, cropped to it as render-carts does (render.cart_image: straightened, 5 mm around it, off the photo
    transparent)."""
    photo = load(path)
    name = os.path.basename(path)
    plastic = plastic_of(fits.load(), name, photos.sources(*path.split(os.sep)[1:3])[name].get("sha1"))
    if plastic:
        shell = shell_of(photos.serial_of(name)).name
        x0, y0, x1, y1 = render.cart_box(shell)
        small = render.cart_image(photo, shell, plastic["mm_to_photo"], longest / max(x1 - x0, y1 - y0))
    else:
        scale = min(1, longest / max(photo.shape[:2]))
        small = cv2.resize(photo, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return cv2.imencode(".webp", small, [cv2.IMWRITE_WEBP_QUALITY, 85])[1].tobytes()


def rows():
    """[{"release", "title", "photos": [{"path", "sha1", "source", "fitted": None, "plastic" or "label", "preferred",
    "version": its image's (image)}],
    "single": whether it counts as having one photo (photos.only)}], by release, the preferred photo first, then by source."""
    release_of = serials.releases_by_serial()
    known, preferred = fits.load(), photos.load_preferred()
    found = {}
    for source, system, name, entry in photos.all_sources():
        if source in photos.FAKES:
            continue
        key, release = serials.release_key(name, release_of)
        row = found.setdefault(key, {"release": key, "title": release["title"] if release else "(not in gb-game-list)", "photos": []})
        fit = fits.of(known, photos.stem(name), entry.get("sha1"))["fit"]
        fitted = "label" if fits.good(fit.get("label")) else "plastic" if fits.good(fit.get("plastic")) else None
        plastic = plastic_of(known, name, entry.get("sha1"))
        # The image's version: the photo, and the plastic it's cropped to.
        version = entry.get("sha1") + (hashlib.sha1(json.dumps(plastic["mm_to_photo"]).encode()).hexdigest()[:8] if plastic else "")
        row["photos"].append({"path": os.path.join(photos.ROOT, source, system, name), "sha1": entry.get("sha1"), "source": source,
                              "fitted": fitted, "preferred": preferred.get(key) == entry.get("sha1"), "version": version})
    for row in found.values():
        row["photos"].sort(key=lambda p: (not p["preferred"], photos.rank(p["source"]), p["path"]))
        row["single"] = photos.only([p["source"] for p in row["photos"]]) is not None
    return [found[k] for k in sorted(found)]


def prefer(path):
    """Makes the photo its release's preferred one, or unmakes it if it is; drops the entries whose photo is no longer
    in its release. Returns the release and its preferred photo's path (None if none)."""
    with lock:
        all_rows = rows()
        row = next(r for r in all_rows if any(p["path"] == path for p in r["photos"]))
        photo = next(p for p in row["photos"] if p["path"] == path)
        preferred = {r["release"]: p["sha1"] for r in all_rows for p in r["photos"] if p["preferred"]}
        if photo["preferred"]:
            del preferred[row["release"]]
        else:
            preferred[row["release"]] = photo["sha1"]
        photos.save_preferred(preferred)
        return row["release"], None if photo["preferred"] else path


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Find doubles</title>
<style>
body{font:14px system-ui;margin:0;background:#f4f4f4;color:#222}
header{position:sticky;top:0;z-index:1;background:#fff;padding:8px 16px;border-bottom:1px solid #ddd;display:flex;gap:16px;align-items:center}
#count{margin-left:auto;font-variant-numeric:tabular-nums}
.row{display:flex;gap:12px;padding:8px 16px;border-bottom:1px solid #e4e4e4;align-items:flex-start}
.release{width:180px;flex:none}.release b{display:block}.release span{color:#555}
.photos{display:flex;gap:8px;overflow-x:auto}
figure{margin:0;width:338px;flex:none;box-sizing:border-box;border:3px solid transparent;background:#fff;border-radius:0.3em;padding:6px;position:relative}
figure img{width:320px;height:320px;object-fit:contain;display:block}
figcaption{font-size:12px;color:#555;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin:4px 0}
.check{position:absolute;top:8px;right:8px;width:22px;height:22px;border-radius:50%;color:#fff;font-weight:700;text-align:center;line-height:22px}
.check.plastic{background:#e8830c}.check.label{background:#2a9d3a}
figure.preferred{border-color:#2a6fdb}figure img{cursor:pointer}
figcaption a{color:inherit}
button{font:inherit;padding:2px 8px;border:none;border-radius:0.3em}button.delete{color:#b00}
</style>
<header><b>Find doubles</b><label><input type="checkbox" id="doubles"> only releases with several photos</label>
<label><input type="checkbox" id="unpreferred"> only releases with no preferred photo</label>
<span><span class="check plastic" style="position:static;display:inline-block">✓</span> plastic fitted
<span class="check label" style="position:static;display:inline-block">✓</span> label fitted</span>
<span>click a photo to prefer it</span><span id="count"></span></header>
<main id="rows"></main>
<script>
const $ = id => document.getElementById(id);
const esc = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
let rows = [];
function render() {
  const shown = rows.filter(r => (!$("doubles").checked || !r.single) && (!$("unpreferred").checked || !r.photos.some(p => p.preferred)));
  $("count").textContent = `${shown.length} releases, ${shown.reduce((n, r) => n + r.photos.length, 0)} photos`;
  $("rows").innerHTML = shown.map(r => `<div class="row" data-release="${esc(r.release)}"><div class="release"><b>${esc(r.release)}</b><span>${esc(r.title)}</span></div><div class="photos">` +
    r.photos.map(p => `<figure data-path="${esc(p.path)}"${p.preferred ? ' class="preferred"' : ""}>${p.fitted ? `<span class="check ${p.fitted}" title="${p.fitted} fitted">✓</span>` : ""}` +
      `<img loading="lazy" data-action="prefer" data-path="${esc(p.path)}" src="/image?size=1000&v=${p.version}&path=${encodeURIComponent(p.path)}" alt="">` +
      `<figcaption title="${esc(p.path)}">${esc(p.source)} · <a href="/image?size=1600&v=${p.version}&path=${encodeURIComponent(p.path)}" target="_blank">open</a><br>${esc(p.path.split("/").pop())}</figcaption>` +
      `<button data-action="rename" data-path="${esc(p.path)}">Rename</button> <button class="delete" data-action="delete" data-path="${esc(p.path)}">Delete</button></figure>`).join("") + `</div></div>`).join("");
}
$("rows").onclick = async e => {
  const {action, path} = e.target.dataset || {};
  if (action === "rename") return rename(path);
  if (action === "prefer") return prefer(path);
  if (action !== "delete" || !confirm(`Delete ${path} from photos/?`)) return;
  const response = await fetch("/delete", {method: "POST", body: JSON.stringify({path})});
  if (!response.ok) return alert("Not deleted: " + await response.text());
  rows = await (await fetch("/rows")).json();  // afresh: a deletion can make a release count as having one photo
  render();
};
async function prefer(path) {
  const response = await fetch("/prefer", {method: "POST", body: JSON.stringify({path})});
  if (!response.ok) return alert("Not saved: " + await response.text());
  const {release, preferred} = await response.json();
  // In place, so the photos already shown aren't loaded again: the row's preferred photo marked, and moved first.
  const row = rows.find(r => r.release === release);
  for (const p of row.photos) p.preferred = p.path === preferred;
  row.photos.sort((a, b) => b.preferred - a.preferred);
  const div = [...document.querySelectorAll(".row")].find(d => d.dataset.release === release);
  if (!div) return;
  const strip = div.querySelector(".photos"), figures = [...strip.children];
  for (const p of row.photos) {
    const figure = figures.find(f => f.dataset.path === p.path);
    figure.classList.toggle("preferred", p.preferred);
    strip.appendChild(figure);
  }
}
async function rename(path) {
  const old = path.split("/").pop().replace(/\\.[^.]*$/, "").replace(/_\\d+$/, "");
  const name = (prompt(`The serial on the label of ${path}:`, old) || "").trim();
  if (!name || name === old) return;
  const response = await fetch("/rename", {method: "POST", body: JSON.stringify({path, name})});
  if (!response.ok) return alert("Not renamed: " + await response.text());
  rows = await (await fetch("/rows")).json();
  render();
}
$("doubles").onchange = $("unpreferred").onchange = render;
fetch("/rows").then(r => r.json()).then(r => { rows = r; render(); });
</script>
"""


def is_photo(path):
    """Whether path is a photo in photos/ (photos/<source>/<system>/<name>, with an entry in its sources.json)."""
    parts = path.split(os.sep)
    return len(parts) == 4 and parts[0] == photos.ROOT and ".." not in parts and parts[3] in photos.sources(parts[1], parts[2]) and os.path.isfile(path)


class Handler(BaseHTTPRequestHandler):
    def send(self, body, kind="application/json", status=200, cache=False):
        body = json.dumps(body).encode() if kind == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", kind)
        if cache:  # the URL carries the photo's SHA-1, so a photo given another's name isn't shown stale
            self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            self.send(PAGE.encode(), "text/html; charset=utf-8")
        elif url.path == "/rows":
            self.send(rows())
        elif url.path == "/image" and is_photo(path := query.get("path", [""])[0]):
            self.send(image(path, min(1600, int(query.get("size", ["1000"])[0]))), "image/webp", cache=True)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ("/delete", "/rename", "/prefer"):
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        path = data["path"]
        if not is_photo(path):
            return self.send(b"not a photo in photos/", "text/plain", 400)
        if self.path == "/prefer":
            release, preferred = prefer(path)
            print(f"{release}: {preferred or 'no photo'} preferred", flush=True)
            return self.send({"release": release, "preferred": preferred})
        if self.path == "/rename":
            try:
                new_path = photos.rename(path, data["name"])
            except ValueError as e:
                return self.send(str(e).encode(), "text/plain", 400)
            with fits.editing():
                pass  # its fits follow it (fits.reconcile)
            print(f"{path} -> {new_path}", flush=True)
            return self.send({"path": new_path})
        photos.delete(path)
        with fits.editing():
            pass  # its fits go with it (fits.reconcile)
        print(f"{path} deleted", flush=True)
        self.send({})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Photos by release at http://localhost:{PORT}/ (ctrl-C to stop)")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
