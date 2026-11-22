# Persistent prints and freezing (design, for review)

**Superseded where they differ by stored-prints.md (the user, 2026-11-22): every print is stored and is the truth; a print grows only by a new label photo of its own serial, read from the straightened label photo; frozen prints are never changed automatically (no stage 3 joining).**

Status: stage 1 built 2026-11-13 (src/print_ids.py, print-ids.json; the prints step's pair cache with it); stage 2 built 2026-11-13 (src/frozen.py; Freeze in remove-photos; features, match, find, solve, prints, restore, publish), tried on the sample only: a frozen print kept its id, label photos, poses and image; two of its photos held out of the freezing were matched against its image (pose from the match within 0.15 and 0.20 mm of their own fit) and joined it. Match's fingerprint is unchanged: nothing is matched again. The user's idea: a print the user is happy with needn't be fitted or restored again, its label photos needn't be matched again, and prints should keep their ids between runs.

## Why

- **Work.** Every run recomputes everything from the photos: solve takes hours, restore redoes every print whose inputs changed. A print the user has accepted gains nothing from that.
- **Verdicts that stick.** print-marks.json marks an image by its SHA-1: a rerun that changes the image unmarks it. Of the 233 prints marked Good on 2026-11-12, 153 are still the current image a day later.
- **Something stable to point at.** A print's id is the smallest key among its label photos, within a run only; todo.md, the marks and any later hand input can't refer to a print reliably.
- **Accepted fits help the rest.** A frozen print's restored image is a clean, straightened reference: a new photo matched to it gets its pose in ink coordinates from the match itself, with no edge fitting (as solve's stage 3 carries a pose from a precise label photo).

## Terms

- **print id:** a print's persistent name, made once and kept while the print exists.
- **open print:** a print the pipeline computes as now.
- **frozen print:** a print the user accepted: its label photos, their poses and its image are fixed and no step recomputes them.
- **taken area:** where a frozen label photo is in its photo; find makes no other label photo there (as not-labels.json's areas).

## Changes to settled rules (label-detection.md, Architecture and Data structures)

These go against rules marked settled, so they need the user's yes first:

1. "Print id: the smallest key among its label photos (within a run only, never in hand files)" becomes: a persistent id, kept between runs, usable in hand files.
2. "Keys aren't remembered between runs" stays for open label photos; a frozen label photo's key is fixed in frozen-prints.json.
3. "A step owns its output … no step's output feeds an earlier step": the prints step must read the ids it gave last run to keep them. That's a step reading its own earlier output, not an earlier step reading a later one's, so the one-way flow holds; but the ids must survive make clean-prints, so they live in a committed file the prints step writes (print-ids.json, below), a new kind of file: neither hand input nor generated.
4. Frozen prints are hand input (written by a tool on the user's say, like not-labels.json) that find, match, solve, prints, restore and publish read. That's allowed (hand input may be read by any step), but it's the first hand input holding images.

## Stage 1: persistent print ids

**The id:** the serial as printed on the label, a hyphen, and a short English first name: `DMG-APSJ-JPN-lisa` (the user, 2026-11-13: names imply no order or hierarchy, unlike numbers, and are easy to remember). The name is picked at random from the list below, among those not yet used with that serial (in print-ids.json, gone ones included: never reused), so two prints of one serial differ by their names. The serial is the one read-serials settled when the print got its id; the name part is always lowercase letters, the serial never is, so the two can't be confused.

The names (50; a serial with more prints than names gets two names: `-lisa-bob`):

alex
amy
ann
beth
bob
carl
dan
dave
dora
ella
emma
eve
frank
fred
gina
greg
hugo
ivan
jack
jane
jeff
jill
joe
john
karl
kate
kim
lee
lisa
lucy
luke
mark
mary
max
meg
mike
nick
nora
paul
pete
rick
rose
ruth
sara
ted
tess
tina
tom
vera
zoe

- **No serial read:** the release read instead if any (`DMG-APSJ-jeff`), else `UNKNOWN-jeff`.
- **The serial read differently later** (a misread corrected): the id is corrected (the user, 2026-11-13): the print gets the corrected serial with its name kept if free there (else another), and the old id goes to "gone" with "renamed" and the new id, so anything pointing at it can follow.

**The file:** print-ids.json, in the repo root, written by the prints step only, committed like the data files:

```
{"prints": {"DMG-APSJ-JPN-lisa": {"keys": ["<sha1>@48,55", …], "created": "<datetime>"}},
 "gone": {"DMG-APSJ-JPN-bob": {"why": "merged", "into": "DMG-APSJ-JPN-lisa", "datetime": "<datetime>"}}}
```

**How a run keeps them:** after the tile comparison, each of this run's prints is matched to last run's by the label photos they share (a label photo is the same between runs when it's in the same photo and its centre lies in last run's outline, as keys work now):

- shares label photos with exactly one old print, and that one with no other new print: it keeps the id;
- shares with none: a new id;
- **merge:** shares with two or more old prints: it takes the id of the one with the most shared label photos; the others go to "gone" with "merged" and the id they went into, so anything pointing at them can follow;
- **split:** an old print's label photos now in two or more new prints: the one with the most of them keeps the id, the others get new ids, recorded with "split from";
- **shrink:** an old print with no label photo left (photos deleted, areas marked not a label, links lost): its id goes to "gone" with why;
- a false positive (a link that later proves wrong) shows up as a split.

**Who uses the ids:** prints.json, restore's and publish's file names, publish's index.json, print-marks.json (by id and image SHA-1), todo.md. A restored print's file becomes:

generated/restore/DMG-APSJ-JPN-lisa.avif

**Measured before keeping:** over two consecutive runs with nothing changed, every id kept; after the 2026-11-13 not-labels and hand fits, how many merges, splits and gone, each listed on the prints page for the user to look at.

## Stage 2: freezing

**How a print is frozen:** a Freeze button on remove-photos' Restored prints tab (and Unfreeze). Only a print with an image can be frozen.

**What's kept:**

frozen-prints.json, in the repo root, hand input:

```
{"DMG-APSJ-JPN-lisa": {"datetime": "<datetime>",
         "serial": "DMG-APSJ-JPN", "shape": "dmg",
         "image": "<sha1 of the image>",
         "crop": {…, as restore's},
         "restored_from": ["<sha1>@48,55", …],
         "label_photos": {"<sha1>@48,55": {"photo_to_ink": [[…]], "cut": [[x, y] × 4, the photo's pixels]}}}}
```

the image itself, copied from restore:

frozen/DMG-APSJ-JPN-lisa.avif

The images are committed (the user, 2026-11-13: the repository will hold them anyway once published); about 130 KB each. "restored_from" lists the label photos the image was restored from (restore's "keys"); "label_photos" holds the print's label photos when frozen, with their poses.

**What each step does with a frozen print:**

- **match:** a photo all of whose label photos are frozen leaves matching (it's neither looked up nor in the index); a photo with any open label photo stays. Each frozen print's image joins the index as if it were a photo (its own SHA-1), so a new photo of that print matches it. Existing match files stay as written.
- **find:** frozen label photos are taken from frozen-prints.json as they are, not searched for; their areas are taken. A match from a photo to a frozen print's image makes a label photo there (found_by "frozen print"), as spreading does now.
- **solve:** frozen label photos are copied (photo_to_ink, cut), not fitted, and not in stage 2. A label photo matched to a frozen print's image gets its photo_to_ink from that match (the image is in ink coordinates), checked by the pixel test of stage 2.
- **straighten, read-serials:** skip frozen label photos (their serial is the one frozen).
- **prints:** a frozen print keeps its id and its label photos. A new label photo matched to it is compared with its image by the tile comparison: the same print, or another print (a variant), as now. The same print: it joins the print (in prints.json and publish's index.json, with the print's other label photos), but the image stays as frozen (the user, 2026-11-13): the print's label photos can be more than the image's "restored_from".
- **restore:** skips frozen prints.
- **publish:** copies the frozen image as it is.

**Unfreezing** deletes the entry and its image: the next run treats the print as open, from its label photos.

## Stage 3: new photos against frozen prints

Built into stage 2's match and solve (above); listed apart because it's measured apart: on photos held out (some frozen print's own photos, left out of its freezing), how often the match to the frozen image finds them, and how far the pose from the match is from their solved one.

## Decided (the user, 2026-11-13)

- A new photo of a frozen print joins the print; the image stays as frozen; the image records which label photos it was restored from.
- The frozen images are committed.
- A wrong serial in an id is corrected (renamed, the old id followed through "gone").
- The 153 prints marked Good whose image is still current are not frozen as a batch: not that good.

## Open questions for the user

1. **May anything change a frozen print?** For example a better colour method later. Not decided yet.

## Order of work

1. Stage 1 alone (prints step, print-ids.json, the steps using ids); measured as above; committed.
2. Stage 2 for restore and publish only (the cheap part: frozen prints' images kept); then for find and solve; then match.
3. Stage 3's measurement.
