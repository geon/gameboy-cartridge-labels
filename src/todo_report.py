# todo-report: a tool, not a step: the prints listed in todo.md restored with the current code as a named version,
# every version kept, and a page showing each listed print with the user's note and all its versions side by side, to
# see what a change did to the problems found.
#   todo.md (hand-written): blocks separated by blank lines; a block's first line names the problem's prints (a serial:
#     every print read as it; or a print's file name without its extension, as in generated/restore/), the rest is the
#     note. A first line "todo" is the title.
#   generated/todo-report/<n>-<name>/: a version: <print>.avif and .json as restore writes them, and version.json
#     ({"name", "note", "made", "commit"}). With --from-restore, the images are copied from generated/restore/ (what
#     the last run made) instead of restored anew.
#   generated/todo-report/index.html: per item, its note; per print, its versions in order, each with restore's
#     facts (paper found, label photos per band, pooled), then its label photos straightened (its own, then pooled).
# Usage: todo_report.py <name> [--note "what changed"] [--from-restore] [--workers N]; todo_report.py --page
import argparse, datetime, html, json, os, re, shutil, subprocess, sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import restore, steps, straighten

GEN = "generated"
OUT = os.path.join(GEN, "todo-report")
TODO = "todo.md"


def items():
    """[(the first line, the note)] from todo.md."""
    blocks = [b.strip().splitlines() for b in re.split(r"\n\s*\n", open(TODO, encoding="utf-8").read()) if b.strip()]
    return [(b[0].strip(), " ".join(l.strip() for l in b[1:])) for b in blocks if b[0].strip().lower() != "todo"]


def prints_of(name, result, serials):
    """The prints an item names: by its print file name, else every print one of whose label photos reads as it."""
    by_file = [p for p in result["prints"] if straighten.file_name(p["id"])[:-5] == name]
    return by_file or [p for p in result["prints"] if any((serials.get(k) or {}).get("serial") == name for k in p["keys"])]


def versions():
    if not os.path.isdir(OUT):
        return []
    found = [d for d in os.listdir(OUT) if os.path.isdir(os.path.join(OUT, d)) and re.match(r"\d+-", d)]
    return sorted(found, key=lambda d: int(d.split("-", 1)[0]))


def make_version(name, note, from_restore, workers):
    result = json.load(open(os.path.join(GEN, "prints", "prints.json"), encoding="utf-8"))
    solved = json.load(open(os.path.join(GEN, "solve", "solve.json"), encoding="utf-8"))["label_photos"]
    serials = json.load(open(os.path.join(GEN, "read-serials", "serials.json"), encoding="utf-8"))
    wanted = {p["id"]: p for item, _ in items() for p in prints_of(item, result, serials)}
    done = versions()
    folder = os.path.join(OUT, f"{int(done[-1].split('-', 1)[0]) + 1 if done else 0}-{re.sub(r'[^A-Za-z0-9_.-]+', '-', name)}")
    os.makedirs(folder)
    base = lambda pid: os.path.join(folder, straighten.file_name(pid)[:-5])
    if from_restore:
        for pid in wanted:
            src = os.path.join(GEN, "restore", straighten.file_name(pid)[:-5])
            for ext in (".avif", ".json"):
                if os.path.exists(src + ext):
                    shutil.copy2(src + ext, base(pid) + ext)
    else:
        jobs = restore.print_jobs(GEN, result, solved)
        with Pool(workers) as pool:
            for pid, desc in pool.imap_unordered(restore.restore_print, [jobs[pid] + (base(pid),) for pid in wanted if pid in jobs]):
                if desc is not None:
                    steps.write_json(base(pid) + ".json", desc)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src"], capture_output=True, text=True).stdout.strip()
    steps.write_json(os.path.join(folder, "version.json"), {"name": name, "note": note, "from_restore": from_restore,
                     "made": datetime.datetime.now().isoformat(timespec="minutes"), "commit": commit + (" + changes" if dirty else "")})
    print(f"{len(wanted)} prints into {folder}")


def facts(desc):
    if not desc:
        return "not restored"
    out = [f'{len(desc.get("keys", []))} own']
    if desc.get("pooled"):
        out.append(f'{len(desc["pooled"])} pooled')
    out.append("paper found" if desc.get("paper") else "no paper")
    out.append(f'bands {desc.get("bands")}')
    return ", ".join(out)


def page():
    result = json.load(open(os.path.join(GEN, "prints", "prints.json"), encoding="utf-8"))
    serials = json.load(open(os.path.join(GEN, "read-serials", "serials.json"), encoding="utf-8"))
    vs = versions()
    meta = {v: json.load(open(os.path.join(OUT, v, "version.json"), encoding="utf-8")) for v in vs}
    rel = os.path.relpath(os.path.join(GEN, "straighten"), OUT)
    head = "".join(f'<th>{html.escape(v)}<br><span class="m">{html.escape(meta[v].get("note") or "")}<br>{html.escape(meta[v]["made"])}, {html.escape(meta[v]["commit"])}</span></th>' for v in vs)
    rows = []
    for item, note in items():
        ps = prints_of(item, result, serials)
        rows.append(f'<tr><td colspan="{len(vs) + 1}" class="item"><b>{html.escape(item)}</b>: {html.escape(note)}'
                    f'{"" if ps else " <i>(no print found)</i>"}</td></tr>')
        for p in ps:
            b = straighten.file_name(p["id"])[:-5]
            cells, last = [], None
            for v in vs:
                f = os.path.join(OUT, v, b)
                desc = json.load(open(f + ".json", encoding="utf-8")) if os.path.exists(f + ".json") else None
                last = desc or last
                img = f'<img loading="lazy" src="{v}/{b}.avif">' if os.path.exists(f + ".avif") else '<div class="none">none</div>'
                cells.append(f'<td>{img}<div class="m">{html.escape(facts(desc))}</div></td>')
            c = (last or {}).get("crop") or restore.canonical_crop(p["shape"])
            (cw, ch), _ = straighten.canvas(p["shape"])
            scale = 90 / c["w"]
            src = lambda k, cls: (f'<div class="src {cls}" style="width:{c["w"] * scale:.0f}px;height:{c["h"] * scale:.0f}px" title="{html.escape(k)}">'
                                  f'<img loading="lazy" src="{rel}/{straighten.file_name(k)}" style="width:{cw * scale:.0f}px;'
                                  f'margin:{-c["y"] * scale:.0f}px 0 0 {-c["x"] * scale:.0f}px"></div>')
            sources = "".join(src(k, "own") for k in (last or {}).get("keys", p["keys"])) + "".join(src(k, "pooled") for k in (last or {}).get("pooled", []))
            rows.append(f'<tr><td class="p"><code>{html.escape(b)}</code><div class="sources">{sources}</div></td>{"".join(cells)}</tr>')
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>todo report</title>
<style>body{{font:13px system-ui;margin:16px;background:#333;color:#eee}} table{{border-collapse:collapse}} td,th{{vertical-align:top;padding:4px 6px;text-align:left}}
td img{{width:300px;display:block}} .m{{font-size:11px;color:#bbb;font-weight:normal;max-width:300px}} .item{{padding-top:18px;font-size:14px;border-top:1px solid #666}}
.p{{width:200px}} .p code{{font-size:10px;word-break:break-all}} .src{{display:inline-block;overflow:hidden;margin:2px;border:2px solid #6a6}} .src.pooled{{border-color:#c80}} .src img{{width:auto;display:block}}
.none{{width:300px;color:#999}}</style>
<h1>todo report</h1>
<p>The prints listed in todo.md, each version restored with the code of its time (left to right, oldest first). Under each print's name its label photos straightened, as the last version used them: green its own, orange pooled from other prints of its family.</p>
<table><tr><th>print</th>{head}</tr>{"".join(rows)}</table>""")
    print(f"page: {os.path.join(OUT, 'index.html')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--note", default="")
    ap.add_argument("--from-restore", action="store_true")
    ap.add_argument("--page", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    if not args.page:
        if not args.name:
            sys.exit("a version name, or --page")
        make_version(args.name, args.note, args.from_restore, args.workers)
    page()


if __name__ == "__main__":
    main()
