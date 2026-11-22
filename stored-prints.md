# Stored prints are the truth

Decided by the user, 2026-11-22, after a make all merged dozens of prints of different serials (below). These rules are settled and very important: they override anything in persistent-prints.md, label-detection.md or the code that says otherwise. Built 2026-11-22 except what's listed under "Not yet built".

## The rules

1. **Every print is stored explicitly.** A print is a stored object: its id and its label photos. A run doesn't regroup the prints from scratch, and it doesn't rebuild them by replaying decisions. The stored prints are the truth, and the pipeline works from them.
2. **The user changes prints directly.** Join, split, delete and set serial in review-prints change the stored prints themselves. Nothing gets recorded for a later replay.
3. **A stored print only grows by a new label photo of its own serial, or of none.** A new label photo may be added to a stored print automatically only if its serial matches the print's, or if it has no serial at all (rule 6). Otherwise it isn't added. Pixels alone never add a label photo to a print of another serial, and never merge two stored prints.
4. **The serial is read from the straightened label photo only.** The serial used for adding a label photo to a print comes from the OCR of its straightened image. It never comes from reads in the whole photo (another cartridge's serial can be there), from the family's reads, or from a title guess.
5. **The serial must be there when joining.** If a label photo's serial hasn't been read yet when it would be added to a print, the pipeline steps are in the wrong order, and that's the bug to fix. Never add it before its straightened image has been read. A straightened image that has been read and gave no serial is different: that's rule 6.
6. **Pixels choose.** A new label photo whose serial several stored prints share goes into the one it matches best by pixels; if it matches none of them, it starts a new print. A new label photo whose straightened image gave no serial goes into the best-matching non-frozen print by pixels, whatever its serial, as if its missing serial matched any; it's assumed rightly grouped and restored with the print (the user, 2026-11-22).
7. **Frozen prints are never changed automatically.** Freezing means no step changes the print: no label photo is added, removed or moved, by pixels, by serial or by anything else. New label photos stay outside frozen prints, as if the frozen print didn't exist: joining one is for the user to do, if they want. Frozen prints need not be part of any pipeline step at all, which saves time. Never changing them automatically is crucial.
8. **Any change by hand unfreezes.** Joining into a frozen print, splitting it, deleting one of its label photos or setting another serial on it unfreezes it, with no warning or confirmation. Setting the serial it already has doesn't unfreeze it: it only updates the serials of its label photos (the user, 2026-11-22).
9. **Every label photo in a stored print keeps its pose and outline.** The store holds, for each label photo of each print, frozen or not, its outline in the photo (find's) and its pose (solve's: the fit, photo to ink, cut, shape). That's the point of storing prints. The pipeline may refine them for open prints and writes the refinement back, but never throws them away; a frozen print's are never changed (rule 7). This wasn't done before 2026-11-22, so the steps' caching may need revising to start from what's stored (the user, 2026-11-22).
10. **One interface for every change to a print.** Every change to the stored prints goes through one interface, from any step or tool. Each call says whether it's manual (the user, in a tool) or automatic (a step). An automatic call that would change a frozen print throws an error: the step is wrong, and nothing is changed. A manual one unfreezes it as rule 8 says. So the prints step doesn't have to expect a frozen print to lose or change a label photo: the interface makes it impossible (the user, 2026-11-22).
11. **A print of several serials is nonsense.** A print whose label photos' straightened serials differ (those without one don't count) must be fixed by hand, and isn't restored until it is. There's no "looked at" for it (the user, 2026-11-22).
12. **The photo's own reads only help the first fit.** find's reads of the whole photo help find a label photo and its first fit, nothing else: a label photo's serial comes from its straightened image only (the user, 2026-11-22).
13. **Matching new photos against frozen images is good.** A new label photo can be aligned to a frozen print through its image (solve's stage 3); it still doesn't join the frozen print (the user, 2026-11-22).

## Design (approved and built 2026-11-22)

**The store.** prints.json in the repo root (the user, 2026-11-22), one file for every print, frozen or not: `{"prints": {id: {"created", "serial", "frozen": true|false, "label_photos": {key: {"outline", "pose"}}}}, "gone": {...}}`. `frozen` is a boolean (the user: the only difference is a property). Each label photo keeps its outline and pose (rule 9): for a frozen print, what frozen-prints.json holds for it now; for an open one, find's outline and solve's record from the last run. A frozen print's image stays at frozen/<id>.avif (committed). It's print-ids.json renamed, with the label photos' outlines and poses added and frozen-prints.json's prints marked frozen, the file then deleted. Freezing sets `frozen` and writes the image; unfreezing clears it and keeps the image file, so Undo can freeze it again (freezing again overwrites it). A frozen print's own fields besides label photos (shape, `image`: SHA-1, crop, paper, restored_from; `photo_label_photos` for match; `frozen_at`) are kept on the print; src/frozen.py shows the frozen prints to the steps in frozen-prints.json's old shape. It's written only by the prints step (open prints only: adding new label photos, dropping gone ones, writing back refined outlines and poses) and by review-prints (the user's changes). Steps that read frozen-prints.json now read the frozen prints from it: find keeps a frozen label photo's key and outline from the store, so its key never changes. Size: solve's records are about 1.4 kB per label photo, so the file is some 35 MB for 25,000 label photos, committed; how to keep the diffs readable is to be worked out.

**The interface (rule 10).** One module (src/stored_prints.py) holds every change: make a print, add label photos, remove label photos, join, split, set serial, write back outlines and poses, freeze, unfreeze, mark gone. Each takes `manual` (true from review-prints and the other tools, false from the steps). With `manual` false, any change to a frozen print raises an error before anything is written. With `manual` true, a change to a frozen print clears `frozen` (rule 8), except setting the serial it already has, and Freeze itself. Every change is appended to the change log, with whether it was manual. Nothing else writes prints.json.

**A print's serial.** Stored in the print. It's set when the print is made, from its first label photos' serials. After that, only the user changes it (Set serial), never a run. Reads that later disagree are shown, not acted on.

**A label photo's serial (for joining).** read-serials gives each label photo a `straightened_serial`: the serial its straightened image's own exact OCR reads give. That's one serial, or none where they give none or several. It ignores the photo, the family and titles. The existing `serial` stays for display and the database. On the full set now: 22,757 of 25,260 label photos have one, 13 several, 155 only a near read, 2,335 none.

**The prints step, each run:**

1. Load the store. Frozen prints are left exactly as they are. Every open print's label photo must be in this run: find takes stored label photos as they are, keys included, and only the interface removes label photos (review-prints, fit-by-hand's Not a label, remove-photos, remove-low-resolution). One missing was removed outside it: the step stops, naming them and why. The label photos get this run's outline and pose written back. Nothing else in a stored print changes.
2. New label photos: current ones in no stored print (frozen or not).
3. Each new label photo with a `straightened_serial`: compared by pixels (the comparison as now: differing tiles, MIN_DIFF_TILES) with the label photos of the open stored prints of that serial. It goes into the one where most of the print's label photos are "same" and the mean differing tiles are fewest. Where none, it's left over.
4. The left-over new label photos of one serial are grouped among themselves by pixels (split_family as now), and each group becomes a new print of that serial.
5. Each new label photo without a `straightened_serial`: compared the same way with every open stored print holding label photos of its family (solve's: the pixel comparison needs one shape and ink coordinates, and that's where look-alikes are), whatever their serial. It goes into the best one by the same test, assumed rightly grouped (rule 6). Where none, it becomes a print of its own with no serial.
6. prints.json is written from the store (as now: id, keys, serial, release, shape, family) for restore and publish. The automatic grouping of whole families, automatic.json and the decisions replay all go away.

If a label photo's straightened serial isn't there when step 3 runs (read-serials older than straighten or solve), the step stops with an error naming the order. It doesn't guess.

**review-prints, revised to the store** (the user: the UI may need revising to match):

- Join, Split off, Delete label photo and Set serial change the store at once and save it. The page shows the store itself, not a forecast of the next run.
- Every change is appended to a change log in the store (`"log": [{kind, datetime, before, after}]`). A Recent changes tab replaces Decisions, with Undo on the latest changes.
- Tabs: Same serial (several stored prints of one serial: join or "all different"), Several serials (prints whose label photos' straightened serials differ: to be fixed, not restored until then; rule 11), No serial (prints with no serial: the label photos without a straightened serial that joined no print; join into a print or set serial), New (label photos the last run added, where they went), Every print, Search, Recent changes.
- Frozen prints: shown and changeable like any other. Any change unfreezes the print at once, with no warning or confirmation (rule 8). Freeze and Unfreeze set the property; Unfreeze no longer asks first.

**Migration, once:** the store is made from what review-prints shows now (the last run's grouping with the decisions applied, deterministic since 31b0634d). Each print whose label photos' straightened serials name different games is split into one print per serial; the label photos without a straightened serial stay with the most common serial. Then print-corrections.json is deleted. Its decisions are in the store, and the git history keeps the file.

**Later, separately:** frozen prints out of the pipeline steps (find, match, solve, restore, publish), and solve's stage 3 joining (rule 7).

## Why

The run of 2026-11-22 (make all after find's and solve's changes of 2026-11-22) made 82 merges. 44 of them came from no decision of the user's since the run before, and 38 of those joined different serials (AGB-A2SP-EUR into AGB-ASYP-EUR, AGB-A3AE-USA into AGB-AA2P-EUR, four games into the frozen AGB-AMKE-USA-kate, and more). There were three causes, all from rebuilding prints instead of storing them:

- **Old join decisions replayed on a new grouping.** A join named label photos, and on replay every current group holding any one of them joined in whole. When find or solve moved one of those label photos into another game's group, the whole group came along. Decision 912 joined ASYP prints, and its one label photo now grouped with 14 A2SP photos brought all 14 in.
- **The automatic grouping added label photos to frozen prints.** Pixels let other label photos of a family join a frozen print (AGB-AE7E-USA into AGB-AMKE-USA-kate, AGB-BG3E-USA into AGB-BRBE-USA-tom).
- **Random matching of old label photos.** An old label photo was matched to the first current outline holding its centre, in an order that changed per process. 25 old label photos lie in several outlines, so make prints and review-prints each grouped them by a different random pick. Fixed 2026-11-22 (31b0634d): those count as not found.

The wrong merges were reverted by hand on 2026-11-22: split decisions in print-corrections.json (150e3b91) and the merged-away ids restored in print-ids.json (adeee529).

## Built (2026-11-22)

- **read-serials:** `straightened_serial` per label photo (a serial set by hand counts as it).
- **The store and its interface:** prints.json, src/stored_prints.py (manual or automatic; FrozenError; change log with Undo; one label photo per line). frozen.STAMP (frozen/.changed, not committed) changes only with the frozen prints, so find and solve aren't redone each time a run writes the open prints.
- **Migration:** made from review-prints' grouping. Frozen prints are exactly their frozen label photos; 572 label photos that had joined frozen prints became prints of their own. 57 prints mixing games were split by straightened serial. print-ids.json, frozen-prints.json and print-corrections.json are deleted (git keeps them).
- **The prints step:** as designed above. It also leaves out label photos marked not a label or whose photo is deleted since solve ran (review-prints' Delete). On a copy, with 40 label photos taken out of their prints, 30 went back to their own print; the other 10 started new prints (or, one without a serial, joined another region's print): they were in their print by the user's joins, not by pixels.
- **review-prints:** as designed above. Undo of a deleted label photo also removes its not-labels mark (a photo deleted from photos/ can't be undone); Undo of Set serial also restores the label photos' serial corrections.
- **remove-low-resolution** skips photos of frozen prints; **remove-photos** takes a deleted photo's label photos out of their stored prints by hand (a frozen one unfreezes) and unfreezes without asking.

- **Several serials** (rule 11): prints.json's `several_serials`, restore skips those prints; review-prints' tab without Looked at.
- **read-serials** (rule 12): the serial and the title text from the straightened label photo's OCR only. On the full set 84 label photos lost their serial, 29 changed, 1 gained.
- **find and solve from the stored label photos** (rule 9): find takes every stored label photo as it is (key, stored cut as outline, area taken, never merged; found_by "stored" or "frozen"); solve takes an open print's stored pose as its stage 1 fit (no refitting, stages 2 and 3 refine; the stored poses are where stage 1's work is kept) and never merges two stored ones. Tried on 40 photos: all 41 stored label photos kept their keys and cuts. Stored label photos don't make find or solve run again: they're read when those run for their other inputs.
- **The prints step stops on a missing stored label photo** (rule 10), and remove-low-resolution (automatic) and fit-by-hand's Not a label (manual) go through the interface.

## Not yet built (as of 2026-11-22)

- **Frozen prints in the pipeline.** They still pass through find, match, solve, restore and publish (find and solve take their stored outlines and poses as they are). Frozen prints whose photos are gone (15 of 289, from before 2026-11-22) aren't checked.
- **The store's size.** prints.json is about 45 MB, committed.
- **Steps run on their own.** make all runs the steps in order and stops on the first failure, so read-serials always runs before prints there; make prints alone after a new solve stops with rule 5's error until make straighten read-serials have run.
