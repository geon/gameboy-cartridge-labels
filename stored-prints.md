# Stored prints are the truth

Decided by the user, 2026-11-22, after a make all merged dozens of prints of different serials (below). These rules are settled and very important: they override anything in persistent-prints.md, label-detection.md or the code that says otherwise. Where the code doesn't follow them yet, that's listed under "Not yet built".

## The rules

1. **Every print is stored explicitly.** A print is a stored object: its id and its label photos. A run doesn't regroup the prints from scratch, and it doesn't rebuild them by replaying decisions. The stored prints are the truth, and the pipeline works from them.
2. **The user changes prints directly.** Join, split, delete and set serial in review-prints change the stored prints themselves. Nothing gets recorded for a later replay.
3. **A stored print only grows by a new label photo of its own serial.** A new label photo may be added to a stored print automatically only if its serial matches the print's. Otherwise it isn't added. Pixels alone never add a label photo to a print of another serial, and never merge two stored prints.
4. **The serial is read from the straightened label photo only.** The serial used for adding a label photo to a print comes from the OCR of its straightened image. It never comes from reads in the whole photo (another cartridge's serial can be there), from the family's reads, or from a title guess.
5. **The serial must be there when joining.** If a label photo's serial isn't available when it would be added to a print, the pipeline steps are in the wrong order, and that's the bug to fix. Never add it without one.
6. **Frozen prints are never changed automatically.** Freezing means no step changes the print: no label photo is added, removed or moved, by pixels, by serial or by anything else. Only the user changes a frozen print, by hand. Frozen prints need not be part of any pipeline step at all, which saves time. Never changing them automatically is crucial.

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
