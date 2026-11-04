import json, os, sys, threading, urllib.parse, cv2
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fits, photos, serials
from compare_labels import SCORES, THRESHOLD
from fit_colors import LABELS, OUT as COLORS_OUT

# review-matches: a local page listing the clusters of photos compare-labels found alike: the pairs scoring at least
# its THRESHOLD that are of different releases with different serials, as the photos are named now (so a pair renamed
# into one release no longer joins them), and the photos joined through them (A+B, B+C and C+D make A+B+C+D), by their
# best score, their labels side by side, each with its best score in the cluster. Each photo can be renamed to a
# corrected serial (photos.rename, as find-doubles does), its fits following it. A cluster can be confirmed: photos of
# labels alike, saved in label-clusters.json as its pairs, by the photos' SHA-1s, so that renaming keeps them; it is
# confirmed when its photos are all joined through confirmed pairs, partly when some are. Unconfirming drops the
# confirmed pairs among its photos. The confirmed clusters can be hidden.
# Needs make compare-labels first.
# Usage: review_matches.py [port]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8772
CLUSTERS = "label-clusters.json"
lock = threading.Lock()


def load_confirmed():
    """The confirmed pairs: a set of (sha1, sha1), sorted within."""
    return {tuple(p) for p in json.load(open(CLUSTERS))} if os.path.exists(CLUSTERS) else set()


def save_confirmed(pairs):
    """One pair per line, so that the file's history reads as pairs confirmed and unconfirmed."""
    lines = [json.dumps(list(p)) for p in sorted(pairs)]
    open(CLUSTERS + ".tmp", "w").write("[\n" + ",\n".join(lines) + "\n]\n" if lines else "[]\n")
    os.replace(CLUSTERS + ".tmp", CLUSTERS)


def clusters(pairs):
    """Each photo's cluster (sha1 -> a representative sha1) of the photos joined through pairs."""
    parent = {}

    def root(s):
        while parent.setdefault(s, s) != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s
    for a, b in pairs:
        parent[root(a)] = root(b)
    return {s: root(s) for s in parent}


def current_photos():
    """sha1 -> (path, stem) of the photos in photos/ now."""
    return {e["sha1"]: (os.path.join(photos.ROOT, source, system, name), photos.stem(name))
            for source, system, name, e in photos.all_sources() if e.get("sha1")}


def pairs_alike():
    """The pairs to review, as the photos are named now: [(score, sha1, sha1)]; and sha1 -> {"sha1", "path", "name",
    "release", "title", "game", "shell"} of their photos."""
    kept = json.load(open(SCORES)) if os.path.exists(SCORES) else {"compared": {}, "scores": {}}
    now, release_of = current_photos(), serials.releases_by_serial()
    info, found = {}, []
    for key, score in kept["scores"].items():
        if score < THRESHOLD or not all(s in now for s in key.split()):
            continue
        a, b = key.split()
        for s in (a, b):
            if s not in info:
                k, r = serials.release_key(now[s][1], release_of)
                info[s] = {"sha1": s, "path": now[s][0], "name": now[s][1], "release": k, "game": r["gameId"] if r else k,
                           "title": r["title"] if r else "(not in gb-game-list)", "shell": kept["compared"][s]["shell"].upper()}
        if info[a]["release"] != info[b]["release"] and photos.serial_of(info[a]["name"]) != photos.serial_of(info[b]["name"]):
            found.append((score, a, b))
    return found, info


def groups():
    """The clusters to review: [{"score": the best, "shell", "confirmed": "yes", "partly" or None, "same game": all of
    one game, "photos": [{... as pairs_alike, "best": its best score in the cluster, "with": that photo's name}]}],
    by best score."""
    found, info = pairs_alike()
    confirmed = load_confirmed()
    of = clusters([(a, b) for _, a, b in found])
    joined = clusters(confirmed)
    members = {}
    for s, root in of.items():
        members.setdefault(root, []).append(s)
    result = []
    for shas in members.values():
        inside = set(shas)
        best = {}
        for score, a, b in found:
            if a in inside:
                for x, y in ((a, b), (b, a)):
                    if score > best.get(x, (-1, None))[0]:
                        best[x] = (score, y)
        whole = len({joined.get(x, x) for x in shas}) == 1
        some = any(a in inside and b in inside for a, b in confirmed)
        result.append({"score": max(v for v, _ in best.values()), "shell": info[shas[0]]["shell"],
                       "confirmed": "yes" if whole else "partly" if some else None,
                       "same game": len({info[x]["game"] for x in shas}) == 1,
                       "photos": [dict(info[x], best=best[x][0], **{"with": info[best[x][1]]["name"]})
                                  for x in sorted(shas, key=lambda x: info[x]["name"])]})
    return sorted(result, key=lambda g: -g["score"])


def confirm(shas):
    """Confirms the cluster of these photos (its pairs alike), or, if it is confirmed, unconfirms it (drops the
    confirmed pairs among them). Returns whether it is confirmed now."""
    inside = set(shas)
    with lock:
        found, _ = pairs_alike()
        pairs = load_confirmed()
        joined = clusters(pairs)
        if len({joined.get(x, x) for x in inside}) == 1:
            pairs = {p for p in pairs if not (p[0] in inside and p[1] in inside)}
        else:
            pairs |= {tuple(sorted((a, b))) for _, a, b in found if a in inside and b in inside}
        save_confirmed(pairs)
        return len({clusters(pairs).get(x, x) for x in inside}) == 1


label_cache, cache_lock = {}, threading.Lock()


def label(sha1):
    """The photo's label as compared (its label fit then), straightened, as PNG bytes: fit-colors' image if it is of
    that fit, else rendered from the photo (as for a photo renamed since)."""
    with cache_lock:
        if sha1 in label_cache:
            return label_cache[sha1]
    compared = json.load(open(SCORES))["compared"][sha1]
    path, stem = current_photos()[sha1]
    made_path = os.path.join(COLORS_OUT, "made.json")
    made = (json.load(open(made_path)) if os.path.exists(made_path) else {}).get(stem, {})
    png = os.path.join(LABELS, stem + ".png")
    if made.get("sha1") == sha1 and made.get("label") == compared["label"] and os.path.exists(png):
        image = cv2.imread(png)
    else:
        import render
        from fit_cartridge import load
        image = render.label_image(load(path), compared["shell"], compared["label"])
    data = cv2.imencode(".png", image)[1].tobytes()
    with cache_lock:
        label_cache[sha1] = data
    return data


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Review matches</title>
<style>
body{font:14px system-ui;margin:0;background:#f4f4f4;color:#222}
header{position:sticky;top:0;z-index:1;background:#fff;padding:8px 16px;border-bottom:1px solid #ddd;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
#count{margin-left:auto;font-variant-numeric:tabular-nums}
main{display:flex;flex-direction:column;gap:12px;padding:12px 16px}
.cluster{background:#fff;border-radius:0.3em;padding:8px;border:3px solid transparent}
.cluster.yes{border-color:#2a9d3a}.cluster.partly{border-color:#9fd3a8}
.top{display:flex;gap:8px;align-items:center;margin-bottom:6px}
.score{font-weight:bold;font-variant-numeric:tabular-nums;width:3.5em}.shell{color:#555;width:2.5em}.size{color:#555;width:5em}.game{color:#a60}
.top .state{margin-left:auto;color:#2a9d3a;width:9em;text-align:right}
.photos{display:flex;gap:8px;flex-wrap:wrap}
figure{margin:0;width:300px}
figure img{width:300px;aspect-ratio:200/174;object-fit:contain;display:block;background:#eee}
figcaption{font-size:12px;color:#555;margin:4px 0;display:flex;gap:6px;align-items:flex-start}
figcaption div{overflow:hidden;flex:1;min-width:0}figcaption div span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
figcaption b{color:#222}
button{font:inherit;padding:2px 8px;border:none;border-radius:0.3em;cursor:pointer}
button.confirm{background:#2a9d3a;color:#fff;width:7em}.cluster.yes button.confirm{background:#ddd;color:#222}
</style>
<header><b>Review matches</b>
<label>shell <select id="shell"><option value="">all</option><option>DMG</option><option>CGB</option><option>AGB</option></select></label>
<label><input type="checkbox" id="hide" checked> hide confirmed</label>
<label><input type="checkbox" id="games"> only different games</label>
<span>labels alike, of different releases: rename a photo to its label's serial, or confirm the cluster</span>
<span id="count"></span></header>
<main id="clusters"></main>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
let clusters = [];
function render() {
  const shown = clusters.filter(c => (!$("shell").value || c.shell === $("shell").value) && (!$("hide").checked || c.confirmed !== "yes") && (!$("games").checked || !c["same game"]));
  $("count").textContent = `${shown.length} of ${clusters.length} clusters, ${shown.reduce((n, c) => n + c.photos.length, 0)} photos`;
  $("clusters").innerHTML = shown.map((c, i) => `<div class="cluster ${c.confirmed || ""}">` +
    `<div class="top"><span class="score">${c.score.toFixed(3)}</span><span class="shell">${c.shell}</span><span class="size">${c.photos.length} photos</span>` +
    `${c["same game"] ? '<span class="game">same game</span>' : ""}` +
    `<span class="state">${c.confirmed === "yes" ? "confirmed" : c.confirmed ? "partly confirmed" : ""}</span>` +
    `<button class="confirm" data-action="confirm" data-shas="${c.photos.map(p => p.sha1).join(" ")}">${c.confirmed === "yes" ? "Unconfirm" : "Confirm"}</button></div>` +
    `<div class="photos">` + c.photos.map(p => `<figure><img loading="lazy" src="/label?sha1=${p.sha1}" alt="">` +
      `<figcaption><div><span title="${esc(p.path)}"><b>${esc(p.name)}</b> · ${esc(p.title)}</span>` +
      `<span>${p.best.toFixed(3)} with ${esc(p.with)}</span></div>` +
      `<button data-action="rename" data-path="${esc(p.path)}">Rename</button></figcaption></figure>`).join("") +
    `</div></div>`).join("");
}
async function load() { clusters = await (await fetch("/clusters")).json(); render(); }
$("clusters").onclick = async e => {
  const {action, path, shas} = e.target.dataset || {};
  if (action === "confirm") {
    const response = await fetch("/confirm", {method: "POST", body: JSON.stringify({shas: shas.split(" ")})});
    if (!response.ok) return alert("Not saved: " + await response.text());
    return load();
  }
  if (action !== "rename") return;
  const old = path.split("/").pop().replace(/\\.[^.]*$/, "").replace(/_\\d+$/, "");
  const name = (prompt(`The serial on the label of ${path}:`, old) || "").trim();
  if (!name || name === old) return;
  const response = await fetch("/rename", {method: "POST", body: JSON.stringify({path, name})});
  if (!response.ok) return alert("Not renamed: " + await response.text());
  load();
};
$("shell").onchange = $("hide").onchange = $("games").onchange = render;
load();
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
        if cache:  # by SHA-1, and the label as compared: the same image as long as the scores are
            self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            self.send(PAGE.encode(), "text/html; charset=utf-8")
        elif url.path == "/clusters":
            self.send(groups())
        elif url.path == "/label":
            sha1 = query.get("sha1", [""])[0]
            try:
                self.send(label(sha1), "image/png", cache=True)
            except KeyError:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path not in ("/rename", "/confirm"):
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/confirm":
            known = json.load(open(SCORES))["compared"]
            shas = data.get("shas") or []
            if len(set(shas)) < 2 or not all(x in known for x in shas):
                return self.send(b"not a cluster of compared photos", "text/plain", 400)
            now = confirm(shas)
            print(f"{' '.join(shas)} {'confirmed' if now else 'unconfirmed'}", flush=True)
            return self.send({"confirmed": now})
        path = data["path"]
        if not is_photo(path):
            return self.send(b"not a photo in photos/", "text/plain", 400)
        try:
            new_path = photos.rename(path, data["name"])
        except ValueError as e:
            return self.send(str(e).encode(), "text/plain", 400)
        with fits.editing():
            pass  # its fits follow it (fits.reconcile)
        print(f"{path} -> {new_path}", flush=True)
        self.send({"path": new_path})


if __name__ == "__main__":
    if not os.path.exists(SCORES):
        sys.exit("no scores: run make compare-labels first")
    print(f"{len(groups())} clusters to review at http://localhost:{PORT}/ (ctrl-C to stop)")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
