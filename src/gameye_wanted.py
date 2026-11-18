"""The wanted prints a collector's cartridges could give photos of, from the collector's GameEye export.

A GameEye export (.ged) is a zip holding ownership_database.db (SQLite): table ownership, one row per item, with
title, platform_id (4 Game Boy, 39 Game Boy Color, 5 Game Boy Advance) and country_id (1 USA, 15 Europe, 3 Japan: from
the titles seen in one export, 2026-11-16). GameEye has no serials, so cartridges are matched to wanted.json by system
and title (case, accents, punctuation, "&"/"and" and "the" ignored; ALIAS for titles GameEye spells otherwise). A print
is only counted when one of its serials is from the cartridge's country: a USA cartridge is no photo of a EUR print of
the same game.

    python3 src/gameye_wanted.py <export.ged> <out.md>

Writes a Markdown list of the cartridges to ask photos of, one per line, those that complete a print with one photo
first, then by wanted.html's rank; a game with several wanted prints (different print runs) is one line.
"""
import collections, json, os, re, sqlite3, sys, tempfile, unicodedata, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WANTED = os.path.join(ROOT, "generated", "publish", "wanted.json")
SYSTEM = {4: "dmg", 39: "cgb", 5: "agb"}
SYSTEM_NAME = {"dmg": "Game Boy", "cgb": "Game Boy Color", "agb": "Game Boy Advance"}
COUNTRY_SUFFIXES = {1: {"USA"}, 3: {"JPN"}, 15: None}  # None: Europe, any suffix but USA and JPN
ALIAS = {  # GameEye title -> wanted.json title, checked by hand (2026-11-16)
    "Tony Hawk's Pro Skater 2": "Tony Hawk Pro Skater 2",
    "Shaun Palmers Pro Snowboarder": "Shaun Palmer's Pro Snowboader",
    "Disney Piglet's Big Game": "Piglet's Big Game",
    "Nickelodeon SpongeBob SquarePants: Creature from the Krusty Krab": "SpongeBob SquarePants - Creature from the Krusty Krab",
    "Donald Duck Adv@nce!*#": "Donald Duck Advance",
    "Spirit: Stallion of the Cimarron": "Spirit - Stallion of the Cimarron - Search for Homeland",
    "The Hobbit": "Hobbit, The - The Prelude to the Lord of the Rings",
}


def norm(title):
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().casefold().replace("&", " and ")
    return " ".join(w for w in re.sub(r"[^a-z0-9]+", " ", t).split() if w != "the")


def owned(ged):
    with tempfile.TemporaryDirectory() as d:
        with zipfile.ZipFile(ged) as z:
            path = z.extract("ownership_database.db", d)
        con = sqlite3.connect(path)
        rows = con.execute("select title, platform_id, country_id from ownership").fetchall()
        con.close()
    return [(t, SYSTEM[p], c) for t, p, c in rows if p in SYSTEM]


def matches(rows, wanted):
    rank = {e["print"]: i + 1 for i, e in enumerate(wanted)}
    by_game = collections.defaultdict(list)
    for e in wanted:
        by_game[(e["system"], norm(e["title"]))].append(e)
    carts = collections.defaultdict(list)
    for title, system, country in rows:
        want = COUNTRY_SUFFIXES.get(country, set())
        for e in by_game.get((system, norm(ALIAS.get(title, title))), []):
            suffixes = {s.rsplit("-", 1)[-1] for s in e["serials"]}
            if (suffixes & want) if want is not None else (suffixes - {"USA", "JPN"}):
                carts[(title, system)].append({**e, "rank": rank[e["print"]]})
    return sorted(carts.items(), key=lambda kv: (min(e["needed"] for e in kv[1]), min(e["rank"] for e in kv[1])))


def markdown(carts, ged):
    n_prints = sum(len(es) for _, es in carts)
    out = [f"# Photos to ask for: {os.path.basename(ged)}", "",
           f"{len(carts)} of the collector's cartridges are games with wanted prints of their region ({n_prints} prints; src/gameye_wanted.py from generated/publish/wanted.json). A front photo of the label is what's wanted. First the cartridges where one photo completes a print, then by rank on wanted.html. Where a game has several wanted prints (print runs), the collector's copy is one of them, or another.", ""]
    for (title, system), es in carts:
        es.sort(key=lambda e: e["rank"])
        prints = ", ".join(f"{e['print']} (needs {e['needed']}, rank {e['rank']})" for e in es)
        out.append(f"- {title} ({SYSTEM_NAME[system]}): {prints}")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ged, out = sys.argv[1:3]
    carts = matches(owned(ged), json.load(open(WANTED, encoding="utf-8")))
    open(out, "w", encoding="utf-8", newline="\n").write(markdown(carts, ged))
    print(f"{len(carts)} cartridges -> {out}")
