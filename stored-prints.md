# Stored prints are the truth

Decided by the user, 2026-11-22, after a make all merged dozens of prints of different serials (below). These rules are settled and very important: they override anything in persistent-prints.md, label-detection.md or the code that says otherwise. Where the code doesn't follow them yet, that's listed under "Not yet built".

## The rules

1. **Every print is stored explicitly.** A print is a stored object: its id and its label photos. A run doesn't regroup the prints from scratch, and it doesn't rebuild them by replaying decisions. The stored prints are the truth, and the pipeline works from them.
2. **The user changes prints directly.** Join, split, delete and set serial in review-prints change the stored prints themselves. Nothing gets recorded for a later replay.
3. **A stored print only grows by a new label photo of its own serial.** A new label photo may be added to a stored print automatically only if its serial matches the print's. Otherwise it isn't added. Pixels alone never add a label photo to a print of another serial, and never merge two stored prints.
4. **The serial is read from the straightened label photo only.** The serial used for adding a label photo to a print comes from the OCR of its straightened image. It never comes from reads in the whole photo (another cartridge's serial can be there), from the family's reads, or from a title guess.
5. **The serial must be there when joining.** If a label photo's serial isn't available when it would be added to a print, the pipeline steps are in the wrong order, and that's the bug to fix. Never add it without one.
6. **Pixels choose among prints of one serial.** A new label photo whose serial several stored prints share goes into the one it matches best by pixels; if it matches none of them, it starts a new print (the user, 2026-11-22).
7. **Frozen prints are never changed automatically.** Freezing means no step changes the print: no label photo is added, removed or moved, by pixels, by serial or by anything else. Only the user changes a frozen print, by hand. Frozen prints need not be part of any pipeline step at all, which saves time. Never changing them automatically is crucial.

## Proposed design (for the user's yes, 2026-11-22; not built)

**The store.** print-ids.json becomes the store of open prints: `{"prints": {id: {"created", "serial", "keys": [...]}}, "gone": {...}}`, as now plus each print's own `serial`. Written only by the prints step (adding new label photos, dropping gone ones) and by review-prints (the user's changes). Frozen prints stay in frozen-prints.json and are not in it. Freezing moves a print from the store to frozen-prints.json, and unfreezing moves it back.

**A print's serial.** Stored in the print. It's set when the print is made, from its first label photos' serials. After that, only the user changes it (Set serial), never a run. Reads that later disagree are shown, not acted on.

**A label photo's serial (for joining).** read-serials gives each label photo a `straightened_serial`: the serial its straightened image's own exact OCR reads give. That's one serial, or none where they give none or several. It ignores the photo, the family and titles. The existing `serial` stays for display and the database. On the full set now: 22,757 of 25,260 label photos have one, 13 several, 155 only a near read, 2,335 none.

**The prints step, each run:**

1. Load the store. Match each stored key to a current label photo (print_ids.same_label_photo: the same key, else the one current outline holding its centre; not found where none or several do). Drop keys not found. A print left empty becomes gone ("no label photo left"). Nothing else in a stored print changes.
2. New label photos: current ones in no stored print and no frozen print.
3. Each new label photo with a `straightened_serial`: compared by pixels (the comparison as now: differing tiles, MIN_DIFF_TILES) with the label photos of the stored prints of that serial. It goes into the one where most of the print's label photos are "same" and the mean differing tiles are fewest. Where none, it's left over.
4. The left-over new label photos of one serial are grouped among themselves by pixels (split_family as now), and each group becomes a new print of that serial.
5. A new label photo without a `straightened_serial` joins nothing. It becomes a print of its own with no serial, for the user (below).
6. prints.json is written from the store (as now: id, keys, serial, release, shape, family) for restore and publish. The automatic grouping of whole families, automatic.json and the decisions replay all go away.

If a label photo's straightened serial isn't there when step 3 runs (read-serials older than straighten or solve), the step stops with an error naming the order. It doesn't guess.

**review-prints, revised to the store** (the user: the UI may need revising to match):

- Join, Split off, Delete label photo and Set serial change the store at once and save it. The page shows the store itself, not a forecast of the next run.
- Every change is appended to a change log in the store (`"log": [{kind, datetime, before, after}]`). A Recent changes tab replaces Decisions, with Undo on the latest changes.
- Tabs: Same serial (several stored prints of one serial: join or "all different"), Several serials (prints whose label photos' straightened serials differ), No serial (prints of label photos without a straightened serial: join into a print or set serial), New (label photos the last run added, where they went), Every print, Search.
- Frozen prints: shown, not changeable, as now.

**Migration, once:** the store is made from what review-prints shows now (the last run's grouping with the decisions applied, deterministic since 31b0634d). Each print whose label photos' straightened serials name different games is split into one print per serial; the label photos without a straightened serial stay with the most common serial. Then print-corrections.json is deleted. Its decisions are in the store, and the git history keeps the file.

**Later, separately:** frozen prints out of the pipeline steps (find, match, solve, restore, publish), and solve's stage 3 joining (rule 7).

## Why

The run of 2026-11-22 (make all after find's and solve's changes of 2026-11-22) made 82 merges. 44 of them came from no decision of the user's since the run before, and 38 of those joined different serials (AGB-A2SP-EUR into AGB-ASYP-EUR, AGB-A3AE-USA into AGB-AA2P-EUR, four games into the frozen AGB-AMKE-USA-kate, and more). There were three causes, all from rebuilding prints instead of storing them:

- **Old join decisions replayed on a new grouping.** A join named label photos, and on replay every current group holding any one of them joined in whole. When find or solve moved one of those label photos into another game's group, the whole group came along. Decision 912 joined ASYP prints, and its one label photo now grouped with 14 A2SP photos brought all 14 in.
- **The automatic grouping added label photos to frozen prints.** Pixels let other label photos of a family join a frozen print (AGB-AE7E-USA into AGB-AMKE-USA-kate, AGB-BG3E-USA into AGB-BRBE-USA-tom).
- **Random matching of old label photos.** An old label photo was matched to the first current outline holding its centre, in an order that changed per process. 25 old label photos lie in several outlines, so make prints and review-prints each grouped them by a different random pick. Fixed 2026-11-22 (31b0634d): those count as not found.

The wrong merges were reverted by hand on 2026-11-22: split decisions in print-corrections.json (150e3b91) and the merged-away ids restored in print-ids.json (adeee529).

## Not yet built (as of 2026-11-22)

- **The prints step.** It regroups each family by pixels and replays print-corrections.json, then names the result from print-ids.json. Under the rules it should load the stored prints, drop label photos that no longer exist, and add new label photos by rule 3. print-ids.json holds each print's label photos already, but only as a name registry.
- **review-prints.** It records decisions in print-corrections.json instead of changing the stored prints. The decisions file goes away once the stored prints take its place.
- **read-serials.** A label photo's serial is decided from the straightened OCR, find's reads in the photo, its family's reads and title guesses. For rule 4, the serial used for joining must come from the straightened label photo alone.
- **Frozen prints in the pipeline.** Match and solve match new photos against frozen prints' images and add them (persistent-prints.md, stage 3), and the prints step lets label photos of a family join a frozen print. Both go against rule 6. Frozen prints still pass through find, match, solve, prints, restore and publish.
- **Pipeline order.** In solve, a new photo joins a frozen print before straighten and read-serials have run. Under rule 5 that's the wrong order.
