# Plan

The goal: for each Game Boy and Game Boy Color cartridge release, a clean, straight-on image of its label, made from
photos of cartridges, and composited onto a clean cartridge of the right type. For the card images of the cartridge
database in [gb-game-list](../gb-game-list) (`database/releases.json`). Nothing runs unsupervised: every fit and every
image is reviewed before it's used.

## Sources, best first

Photos of a release from a better source replace those from a worse one, whenever one turns up.

1. Real photos: my own (`my-collection`), gbhwdb, and photos from listings and searches (eBay, Jauce, Mercari, Google…).
2. `otakaraou`: real photos, but small (median short side 800 px). Kept only for releases with no photo from (1).
3. `emumovies` and `launchbox-abeezy1388`: **the lowest quality. Not photos but fakes**: one rendered cartridge with a
   label made from box art pasted in. Kept only for releases with nothing else, and never a reason to delete a photo
   from (1) or (2). A release with only these still counts as missing a photo.
   - `launchbox-abeezy1388`: 193 images, one template (1000 × 1132 px, the label in (131, 333)–(868, 980)), so one
     hand fit (DMG-MH-USA_2's) is copied to them all.
   - `emumovies`: 356 images, three templates, each with one hand fit copied to the rest: 199 at 994 × 1132 px
     (DMG-A2BE-USA's), 155 at 878 × 1000 px (DMG-602-CHN's), 2 at 995 × 1132 px (DMG-AK-USA's).

## Steps

Done, run with `make` (see the Makefile): add-photos, read-text, fit-cartridge (the plastic), fit-label (the label in its
recess), fit-colors (each photo's color settings), render-labels and render-carts (one straightened image per release, src/render.py). Tools for judging and fixing fits: review-fits, review-labels, fit-by-hand; learn-choice (fit-cartridge's choice among its fits, learned from the verdicts: run it again as verdicts grow); adjust-colors (color settings by hand); for finding and naming photos:
search-photos, name-photos.

## Open work

- **Check fit-colors and adjust-colors** (built 2026-11-04, awaiting my check). fit-colors makes each label's white
  paper neutral, for the sources not lit alike. Settings learned per source were dropped: only a source lit alike
  could have one, and those are the references and jnlgame.
- **Check fit-label and review-labels** (built, awaiting my check).
- **Depth layers for the CGB shell**: built (cartridge.camera_of, seen_at; 2026-11-01) and tried; no clear gain
  (results in src/cartridge.py). The measured ridges are taken in flat (cgb_ridge_samples; not inside the recess):
  hard photos 11 -> 25 within 1 mm, accepted ones 57 -> 48 within 0.3 mm. CGB photos not yet refitted.
- Then: group the artwork. (Straightening the label and picking each release's photo: render-labels, render-carts.)
- **A tool comparing labels by their look against their serials**: similar labels with different serials (likely
  misreads: about 2 % of photos named by their text are wrong), and identical serials that look different (misnamed
  photos, or real variants such as reprints).
- **Photos named by release, not by their label** (on hold, 2026-11-02): 244 photos had no serial read, so
  add-photos kept the release the downloader searched for (e.g. jauce/dmg/DMG-A7CJ_2.jpg; no region in the name):
  otakaraou 115, gbhwdb 28, jauce 25, ebay-hitjapan 24, others 52. Another 242 have a full serial in the name but no
  serial_on_label in sources.json, so how they were named is unknown.
- **Verify photos against game-boy-database.com's scans**: parked. Built on the branch `verify-labels-gbdb` (make
  fetch-scans, watermark-mask, verify-labels; tested on one scan only), but it needs about 560 scans downloaded from
  their site, and I'd rather not crawl it.
- **gb-game-list's serials** are incomplete (AGB 47 %, serials without region): fix later.
- **Cleanup of the branch's history** (hand fits, fits.json redesign): later.
