import json, os, sys, urllib.parse, cv2
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fits, photos
from fit_cartridge import load

# name-photos: a local page for naming the photos in photos/ whose serial isn't known (in a source's unknown/ folder),
# one at a time: type the serial on its label and press enter (or Rename), and the next one is shown. The photo is
# renamed in photos/ (photos.rename: tidied, numbered if taken, moved to its system's folder), and its verdicts in
# fits.json go with it (fits.reconcile). A photo not worth keeping can be deleted instead (photos.delete), its fits
# with it.
# Usage: name_photos.py [port]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8768


def image(path, longest=1600):
    """The photo, its longest side at most longest px, as JPEG bytes."""
    photo = load(path)
    scale = min(1, longest / max(photo.shape[:2]))
    small = cv2.resize(photo, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()


class Naming:
    """The photos still to name, read when the tool starts."""

    def __init__(self):
        self.entries = {os.path.join(photos.ROOT, s, system, n): e for s, system, n, e in photos.all_sources() if system == "unknown"}
        self.todo = sorted(self.entries)

    def current(self):
        if not self.todo:
            return {"left": 0}
        path = self.todo[0]
        entry = self.entries[path]
        return {"left": len(self.todo), "path": path, "about": entry.get("title_on_page") or entry.get("original_name") or ""}

    def rename(self, path, name):
        new_path = photos.rename(path, name)
        with fits.editing():
            pass  # its fits follow it (fits.reconcile)
        self.todo.remove(path)
        return new_path

    def delete(self, path):
        photos.delete(path)
        with fits.editing():
            pass  # its fits go with it
        self.todo.remove(path)


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Name photos</title>
<style>
body{font:14px system-ui;margin:0;background:#f4f4f4;color:#222;height:100vh;display:flex;flex-direction:column}
header{background:#fff;padding:8px 16px;border-bottom:1px solid #ddd;display:flex;gap:12px;white-space:nowrap;overflow:hidden}
#path{font-weight:600}#about{color:#555;overflow:hidden;text-overflow:ellipsis}#left{margin-left:auto;font-variant-numeric:tabular-nums}
main{flex:1;min-height:0;padding:12px 16px}
main img{width:100%;height:100%;object-fit:contain;display:block}
form{background:#fff;padding:8px 16px;border-top:1px solid #ddd;display:flex;gap:6px}
input{flex:1;font:inherit;padding:4px 8px}
button{font:inherit;padding:4px 10px;border:none;border-radius:0.3em}
button.delete{color:#b00}
</style>
<header><span id="path"></span><span id="about"></span><span id="left"></span></header>
<main><img id="photo" alt=""></main>
<form id="form"><input id="name" placeholder="The serial on its label, e.g. DMG-A8-JPN" autocomplete="off" autofocus><button>Rename</button><button type="button" class="delete" id="delete">Delete photo</button></form>
<script>
const $ = id => document.getElementById(id);
let current = null;
async function show() {
  current = await (await fetch("/current")).json();
  $("left").textContent = `${current.left} left`;
  $("path").textContent = current.path || "All named.";
  $("about").textContent = current.about || "";
  $("photo").src = current.path ? "/image?path=" + encodeURIComponent(current.path) : "";
  $("name").value = "";
  $("name").focus();
}
$("form").onsubmit = async e => {
  e.preventDefault();
  const name = $("name").value.trim();
  if (!name || !current.path) return;
  const response = await fetch("/rename", {method: "POST", body: JSON.stringify({path: current.path, name})});
  if (!response.ok) return alert("Not renamed: " + await response.text());
  show();
};
$("delete").onclick = async () => {
  if (!current.path || !confirm(`Delete ${current.path} from photos/?`)) return;
  const response = await fetch("/delete", {method: "POST", body: JSON.stringify({path: current.path})});
  if (!response.ok) return alert("Not deleted: " + await response.text());
  show();
};
show();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def send(self, body, kind="application/json", status=200):
        body = json.dumps(body).encode() if kind == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/":
            self.send(PAGE.encode(), "text/html; charset=utf-8")
        elif url.path == "/current":
            self.send(naming.current())
        elif url.path == "/image" and (path := urllib.parse.parse_qs(url.query).get("path", [""])[0]) in naming.todo:
            self.send(image(path), "image/jpeg")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ("/rename", "/delete"):
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if data["path"] not in naming.todo:
            return self.send(b"not a photo to name", "text/plain", 400)
        if self.path == "/delete":
            naming.delete(data["path"])
            print(f"{data['path']} deleted", flush=True)
            return self.send({})
        try:
            new_path = naming.rename(data["path"], data["name"])
        except ValueError as e:
            return self.send(str(e).encode(), "text/plain", 400)
        print(f"{data['path']} -> {new_path}", flush=True)
        self.send({"path": new_path})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    naming = Naming()
    print(f"{len(naming.todo)} photos to name; name them at http://localhost:{PORT}/ (ctrl-C to stop)")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
