import json, os, sys, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import designs, fits, photos
from compare_labels import LABELS, SAME, SIMILAR, all_scores, compared_photos

# review-designs: a local page for telling the photos' label designs apart (src/designs.py, designs.json), from how
# alike their labels are (src/compare_labels.py, compared when the page starts: the photos whose label is accepted or
# placed by hand, with a current label image from make fit-colors). Three lists:
# What the comparison finds is listed as found, never rejected: it changes only as the comparison does.
#   - Similar designs, multiple serials: the photos with different serials whose labels score at least SIMILAR, but for
#     those expected alike (one game's stem and side, Japan or the rest of the world: designs.stem_of), and
#     those joined through them (A+B, B+C and C+D make A+B+C+D), by best score; confirmed when they're all one design
#     (hidden with "hide confirmed"), partly when some are. The photos are shown by design (the serials already linked
#     together), then by serial, each design with a checkbox, ticked to begin with (an unticked one stays so while the
#     page is open): "Same design" makes the ticked designs one (designs.merged); "Unlink" takes the ticked ones' serials
#     out of a design they share with others in the cluster (designs.unlinked: back to their releases' designs).
#     Variants of a game (Pokémon Gold and Silver) are simply left as they are.
#   - Different designs, one serial: the designs whose compared photos fall into separate groups (joined by pairs scoring
#     at least SAME). "Split off" makes a group a design of its own: by its serials (designs.split_off), or, where
#     it shares a serial with another group, by a note in its photos' names (DMG-MQ-UKV[ALT].jpg), asked for.
#   - Designs: the designs whose photos are of several serials, of the releases in designs.json (a family: the designs
#     sharing a release), their photos by serial. A serial can be split off into a design of its own, and a design in
#     designs.json dissolved (its serials back to their releases' designs). Designs are joined through "Same design".
# Each photo can be renamed to a corrected serial (photos.rename, as find-doubles does), its fits following it.
# Usage: review_designs.py [port]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8772
lock = threading.Lock()


def union(pairs):
    """Each item's group (item -> a representative) of the items joined through pairs."""
    parent = {}

    def root(s):
        while parent.setdefault(s, s) != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s
    for a, b in pairs:
        parent[root(a)] = root(b)
    return {s: root(s) for s in parent}


def groups_of(items, pairs):
    of = union(pairs)
    found = {}
    for x in items:
        found.setdefault(of.get(x, x), []).append(x)
    return list(found.values())


class Review:
    def __init__(self):
        self.current, stale = compared_photos()
        if stale:
            print(f"{len(stale)} photos with a good label but no current label image, left out: run make fit-colors first")
        self.scores = all_scores(self.current)
        self.shell = {s: shell for shell, (shas, _) in self.scores.items() for s in shas}
        self.index = {s: i for shas, _ in self.scores.values() for i, s in enumerate(shas)}
        # The pairs alike: (score, sha1, sha1).
        self.alike = []
        for shell, (shas, m) in self.scores.items():
            for i, j in zip(*((m >= SAME).nonzero())):
                if i < j:
                    self.alike.append((float(m[i, j]), shas[i], shas[j]))

    def score(self, a, b):
        """How alike two compared photos' labels are (of one shell)."""
        return float(self.scores[self.shell[a]][1][self.index[a], self.index[b]])

    def photos_now(self):
        """Every photo but the fakes, as named now: [{"sha1", "path", "name", "design", "release", "title", "part"}]."""
        by_design = designs.Designs()
        found = []
        for source, system, name, entry in photos.all_sources():
            if source in photos.FAKES or not entry.get("sha1"):
                continue
            design, _, release = by_design.design_of(name)
            found.append({"sha1": entry["sha1"], "path": os.path.join(photos.ROOT, source, system, name), "name": photos.stem(name),
                          "design": design, "release": release["id"] if release else None, "game": release["gameId"] if release else design,
                          "title": release["title"] if release else "(not in gb-game-list)", "part": designs.serial_part(name),
                          "compared": entry["sha1"] in self.current})
        return found, by_design

    def state(self):
        listed, by_design = self.photos_now()
        data = by_design.data
        info = {p["sha1"]: p for p in listed}

        # Similar designs, multiple serials.
        across = [(v, a, b) for v, a, b in self.alike if v >= SIMILAR and a in info and b in info
                  and photos.serial_of(info[a]["name"]) != photos.serial_of(info[b]["name"])
                  and (designs.stem_of(info[a]["name"]) is None or designs.stem_of(info[a]["name"]) != designs.stem_of(info[b]["name"]))]
        alike = []
        for shas in groups_of({s for _, a, b in across for s in (a, b)}, [(a, b) for _, a, b in across]):
            inside = set(shas)
            pairs = [(v, a, b) for v, a, b in across if a in inside]
            best = {}
            for v, a, b in pairs:
                for x, y in ((a, b), (b, a)):
                    if v > best.get(x, (-1, None))[0]:
                        best[x] = (v, y)
            linked = sum(info[a]["design"] == info[b]["design"] for _, a, b in pairs)
            alike.append({"score": max(v for v, _, _ in pairs), "shell": self.shell[shas[0]].upper(),
                          "confirmed": "yes" if len({info[x]["design"] for x in shas}) == 1 else "partly" if linked else None,
                          "same game": len({info[x]["game"] for x in shas}) == 1,
                          "photos": [dict(info[x], best=best[x][0], **{"with": info[best[x][1]]["name"]}) for x in sorted(shas, key=lambda x: info[x]["name"])]})
        alike.sort(key=lambda c: -c["score"])

        # Different designs, one serial.
        by = {}
        for p in listed:
            by.setdefault(p["design"], []).append(p)
        unalike = []
        for design, members in sorted(by.items()):
            compared = [p["sha1"] for p in members if p["compared"]]
            if len(compared) < 2:
                continue
            inside = set(compared)
            parts = groups_of(compared, [(a, b) for _, a, b in self.alike if a in inside and b in inside])
            if len(parts) < 2:
                continue
            groups = []
            for g in sorted(parts, key=lambda g: (-len(g), min(info[x]["name"] for x in g))):
                others = inside - set(g)
                groups.append({"photos": [dict(info[x], best=max((self.score(x, y) for y in others), default=-1)) for x in sorted(g, key=lambda x: info[x]["name"])]})
            unalike.append({"design": design, "title": members[0]["title"], "shell": self.shell[compared[0]].upper(), "groups": groups})

        # Designs, with their families.
        family_pairs = [("d:" + p["design"], "r:" + (p["release"] or p["design"])) for p in listed]
        family_pairs += [("d:" + by_design.names[i], "r:" + ((designs.release_of(part, by_design.release_of) or {}).get("id") or part))
                         for i, g in enumerate(data["designs"]) for part in g]
        of = union(family_pairs)
        families = {}
        for name in by_design.names:
            families.setdefault(of["d:" + name], set())
        for p in listed:
            root = of.get("d:" + p["design"])
            if root in families:
                families[root].add(p["design"])
        for i, name in enumerate(by_design.names):
            families[of["d:" + name]].add(name)
        listed_names = set(by_design.names)
        family_list = []
        for names in families.values():
            cards = []
            for name in sorted(names, key=lambda n: (n not in listed_names, n)):
                members = by.get(name, [])
                parts = data["designs"][by_design.names.index(name)] if name in listed_names else [name]
                serials_of = {}
                for p in sorted(members, key=lambda p: p["name"]):
                    serials_of.setdefault(p["part"], []).append(p)
                cards.append({"name": name, "listed": name in listed_names, "parts": parts,
                              "title": members[0]["title"] if members else "",
                              "serials": [{"part": k, "photos": v} for k, v in sorted(serials_of.items())]})
            family_list.append({"designs": cards})
        family_list.sort(key=lambda f: f["designs"][0]["name"])
        return {"alike": alike, "unalike": unalike, "families": family_list}

    def act(self, action, data):
        """Changes designs.json (or a photo's name) as the page asks; returns an error message, or None."""
        with lock:
            listed, by_design = self.photos_now()
            info = {p["sha1"]: p for p in listed}
            d = by_design.data
            shas = [s for s in data.get("shas", []) if s in info]
            if action == "merge":
                names = {info[s]["design"] for s in shas} | set(data.get("designs", []))
                if len(names) < 2:
                    return "not several designs"
                d = designs.merged(d, names, by_design)
            elif action == "unlink":
                # The ticked photos' parts, out of the designs they share with other photos of the cluster under another part.
                cluster = [s for s in data.get("cluster", []) if s in info]
                part = {s: by_design.part_of(info[s]["name"]) for s in cluster}
                parts = {part[s] for s in shas if part.get(s) is not None
                         and any(info[o]["design"] == info[s]["design"] and part[o] != part[s] for o in cluster)}
                if not parts:
                    return "none of the ticked photos shares a design with others in the cluster"
                d = designs.unlinked(d, parts)
            elif action == "split":
                design = data.get("design")
                group = set(shas)
                parts = {info[s]["part"] for s in group}
                rest = {p["part"] for p in listed if p["design"] == design and p["compared"] and p["sha1"] not in group}
                note = (data.get("note") or "").strip().upper()
                if parts & rest or not all(designs.is_serial(p) for p in parts):
                    if not note:
                        return "needs a note"
                    for s in group:
                        p = info[s]
                        photos.rename(p["path"], photos.serial_of(p["name"]) + f"[{note}]")
                    with fits.editing():
                        pass  # their fits follow them (fits.reconcile)
                    return None
                d = designs.split_off(d, parts)
            elif action == "split-serial":
                part = data.get("part", "")
                if not designs.is_serial(part):
                    return "not a serial with a region: give its photos a note instead (rename)"
                d = designs.split_off(d, [part])
            elif action == "dissolve":
                d = designs.dissolved(d, data.get("design"), by_design)
            elif action == "rename":
                p = next((p for p in listed if p["path"] == data.get("path")), None)
                if not p:
                    return "not a photo in photos/"
                try:
                    photos.rename(p["path"], data.get("name", ""))
                except ValueError as e:
                    return str(e)
                with fits.editing():
                    pass  # its fits follow it (fits.reconcile)
                return None
            else:
                return "unknown action"
            designs.save(d)
            return None


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Review designs</title>
<style>
body{font:14px system-ui;margin:0;background:#f4f4f4;color:#222}
header{position:sticky;top:0;z-index:1;background:#fff;padding:8px 16px;border-bottom:1px solid #ddd;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
nav button{background:#eee}nav button.on{background:#222;color:#fff}
#count{margin-left:auto;font-variant-numeric:tabular-nums}
main{display:flex;flex-direction:column;gap:12px;padding:12px 16px}
.item{background:#fff;border-radius:0.3em;padding:8px;border:3px solid transparent}
.item.yes{border-color:#2a9d3a}.item.partly{border-color:#9fd3a8}
.top{display:flex;gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap}
.score{font-weight:bold;font-variant-numeric:tabular-nums}.muted{color:#555}.game{color:#a60}
.top .state{margin-left:auto;color:#2a9d3a}
.photos{display:flex;gap:8px;flex-wrap:wrap}
.group{border:1px dashed #bbb;border-radius:0.3em;padding:6px;display:flex;flex-direction:column;gap:6px}
.design{border:1px solid #ddd;border-radius:0.3em;padding:6px;margin-bottom:8px}.design.listed{border-color:#2a6fdb}
.serial{display:flex;gap:8px;align-items:flex-start;margin:4px 0}.serial>b{width:150px;flex:none;font-weight:600}
figure{margin:0;width:240px}
figure img{width:240px;aspect-ratio:200/174;object-fit:contain;display:block;background:#eee}
figcaption{font-size:12px;color:#555;margin:4px 0;display:flex;gap:6px;align-items:flex-start}
figcaption div{overflow:hidden;flex:1;min-width:0}figcaption div span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
figcaption b{color:#222}
button{font:inherit;padding:2px 8px;border:none;border-radius:0.3em;cursor:pointer;background:#e4e4e4}
button.go{background:#2a9d3a;color:#fff}
</style>
<header><b>Review designs</b>
<nav><button data-tab="alike">Similar designs, multiple serials</button> <button data-tab="unalike">Different designs, one serial</button> <button data-tab="families">Designs</button></nav>
<label>shell <select id="shell"><option value="">all</option><option>DMG</option><option>CGB</option><option>AGB</option></select></label>
<label><input type="checkbox" id="hide" checked> hide confirmed</label>
<span id="count"></span></header>
<main id="items"></main>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
let state = {alike: [], unalike: [], families: []}, tab = location.hash.slice(1) || "alike";
const image = p => p.compared ? `/label?sha1=${p.sha1}` : `/photo?sha1=${p.sha1}`;
const figure = (p, extra = "") => `<figure><img loading="lazy" src="${image(p)}" alt="">` +
  `<figcaption><div><span title="${esc(p.path)}"><b>${esc(p.name)}</b> · ${esc(p.title)}</span>${extra}</div>` +
  `<button data-action="rename" data-path="${esc(p.path)}">Rename</button></figcaption></figure>`;
const shas = ps => ps.map(p => p.sha1).join(" ");
// The designs unticked in the clusters of similar designs, kept as the page is drawn again (after each change).
const unticked = new Set();
// Photos by serial (with its note): [[serial, photos]], in the order they come.
const bySerial = ps => Object.entries(ps.reduce((by, p) => ((by[p.part] ||= []).push(p), by), {}));
// Photos by design: [[design, photos]], in the order they come.
const byDesign = ps => Object.entries(ps.reduce((by, p) => ((by[p.design] ||= []).push(p), by), {}));
function render() {
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("on", b.dataset.tab === tab);
  const shell = $("shell").value, hide = $("hide").checked;
  let html = "", n = 0;
  if (tab === "alike") {
    const shown = state.alike.filter(c => (!shell || c.shell === shell) && (!hide || c.confirmed !== "yes"));
    n = shown.length;
    html = shown.map(c => `<div class="item ${c.confirmed || ""}" data-cluster="${shas(c.photos)}"><div class="top"><span class="score">${c.score.toFixed(3)}</span>` +
      `<span class="muted">${c.shell} · ${c.photos.length} photos</span>${c["same game"] ? '<span class="game">same game</span>' : ""}` +
      `<span class="state">${c.confirmed === "yes" ? "one design" : c.confirmed ? "partly one design" : ""}</span>` +
      (c.confirmed !== "yes" ? `<button class="go" data-action="merge">Same design</button>` : "") +
      (c.confirmed ? `<button data-action="unlink">Unlink</button>` : "") +
      `</div><div class="photos">` + byDesign(c.photos).map(([design, ps]) => { const serials = bySerial(ps); return `<div class="group">` +
        `<label><input type="checkbox" class="tick" data-key="${esc(design)}" data-shas="${shas(ps)}"${unticked.has(design) ? "" : " checked"}> ` +
        (serials.length > 1 ? `<b>${esc(design)}</b> <span class="muted">· ${serials.length} serials linked</span>` : `<b>${esc(serials[0][0])}</b> <span class="muted">· ${esc(design)}</span>`) + `</label>` +
        serials.map(([part, sps]) => (serials.length > 1 ? `<div class="muted">${esc(part)}</div>` : "") +
          `<div class="photos">${sps.map(p => figure(p, `<span>${p.best.toFixed(3)} with ${esc(p.with)}</span>`)).join("")}</div>`).join("") + `</div>`; }).join("") + `</div></div>`).join("");
  } else if (tab === "unalike") {
    const shown = state.unalike.filter(u => !shell || u.shell === shell);
    n = shown.length;
    html = shown.map(u => `<div class="item"><div class="top"><b>${esc(u.design)}</b><span class="muted">${esc(u.title)} · ${u.shell}</span></div><div class="photos">` +
      u.groups.map(g => `<div class="group"><div><button class="go" data-action="split" data-design="${esc(u.design)}" data-shas="${shas(g.photos)}">Split off</button></div>` +
        `<div class="photos">${g.photos.map(p => figure(p, `<span>best ${p.best.toFixed(3)} with the others</span>`)).join("")}</div></div>`).join("") + `</div></div>`).join("");
  } else {
    // The designs of several serials: one of a single serial has nothing to split off.
    const shown = state.families.map(f => f.designs.filter(d => d.serials.length > 1)).filter(ds => ds.length);
    n = shown.reduce((k, ds) => k + ds.length, 0);
    html = shown.map(ds => `<div class="item">` + ds.map(d => `<div class="design ${d.listed ? "listed" : ""}"><div class="top"><b>${esc(d.name)}</b>` +
      `<span class="muted">${esc(d.title)}${d.listed ? " · " + d.parts.map(esc).join(", ") : " · default"}</span>` +
      (d.listed ? `<button data-action="dissolve" data-design="${esc(d.name)}">Dissolve</button>` : "") + `</div>` +
      d.serials.map(s => `<div class="serial"><b>${esc(s.part)}<br><button data-action="split-serial" data-part="${esc(s.part)}">Split off</button></b>` +
        `<div class="photos">${s.photos.map(p => figure(p)).join("")}</div></div>`).join("") + `</div>`).join("") + `</div>`).join("");
  }
  $("count").textContent = `${n} shown`;
  $("items").innerHTML = html;
}
async function load() { state = await (await fetch("/state")).json(); render(); }
async function act(body) {
  const response = await fetch("/act", {method: "POST", body: JSON.stringify(body)});
  const text = await response.text();
  if (!response.ok) return text;
  await load();
  return null;
}
$("items").onclick = async e => {
  const d = e.target.dataset || {};
  if (!d.action || e.target.tagName === "SELECT") return;
  const item = e.target.closest("[data-cluster]");
  // In a cluster of similar designs: the ticked photos, and all of the cluster's.
  const list = item ? [...item.querySelectorAll("input.tick:checked")].flatMap(i => i.dataset.shas.split(" ")) : d.shas ? d.shas.split(" ") : [];
  const cluster = item ? item.dataset.cluster.split(" ") : [];
  if (d.action === "rename") {
    const old = d.path.split("/").pop().replace(/\\.[^.]*$/, "").replace(/_\\d+$/, "");
    const name = (prompt(`The serial on the label of ${d.path}:`, old) || "").trim();
    if (!name || name === old) return;
    const error = await act({action: "rename", path: d.path, name});
    if (error) alert("Not renamed: " + error);
    return;
  }
  let error = await act({action: d.action, shas: list, cluster, design: d.design, part: d.part});
  if (error === "needs a note") {
    const note = (prompt("These photos share a serial with the others: a note for their names, telling their design apart (e.g. ALT):") || "").trim();
    if (!note) return;
    error = await act({action: d.action, shas: list, design: d.design, note});
  }
  if (error) alert("Not saved: " + error);
};
$("items").onchange = e => {
  if (!e.target.matches("input.tick")) return;
  if (e.target.checked) unticked.delete(e.target.dataset.key); else unticked.add(e.target.dataset.key);
};
for (const b of document.querySelectorAll("nav button")) b.onclick = () => { tab = b.dataset.tab; location.hash = tab; render(); };
$("shell").onchange = $("hide").onchange = render;
load();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def send(self, body, kind="application/json", status=200, cache=False):
        body = json.dumps(body).encode() if kind == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", kind)
        if cache:  # by SHA-1: the label as compared when the page started
            self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        sha1 = urllib.parse.parse_qs(url.query).get("sha1", [""])[0]
        if url.path == "/":
            self.send(PAGE.encode(), "text/html; charset=utf-8")
        elif url.path == "/state":
            self.send(review.state())
        elif url.path == "/label" and sha1 in review.current:
            self.send(open(os.path.join(LABELS, review.current[sha1][0] + ".png"), "rb").read(), "image/png", cache=True)
        elif url.path == "/photo":
            path = next((os.path.join(photos.ROOT, s, sy, n) for s, sy, n, e in photos.all_sources() if e.get("sha1") == sha1), None)
            if not path:
                return self.send_error(404)
            import find_doubles
            self.send(find_doubles.image(path, 480), "image/webp", cache=True)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/act":
            return self.send_error(404)
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        error = review.act(data.get("action"), data)
        if error:
            return self.send(error.encode(), "text/plain", 409 if error == "needs a note" else 400)
        print(f"{data.get('action')}: {json.dumps({k: v for k, v in data.items() if k != 'action'}, ensure_ascii=False)}", flush=True)
        self.send({})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    review = Review()
    state = review.state()
    print(f"{len(review.current)} labels compared: {len(state['alike'])} clusters of similar designs with several serials, "
          f"{len(state['unalike'])} designs with different designs within, {len(state['families'])} families of designs; review them at http://localhost:{PORT}/ (ctrl-C to stop)")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
