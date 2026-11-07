# Label consensus from several photos

Ideas and first results (2026-11-07). Nothing here is built into the tools yet; the experiments' scripts are throw-away.

## Background

SIFT on straightened labels identifies a cart from a photo alone and registers its print precisely, which makes
combining several photos of one print possible. Experiments on photos/ and the accepted label fits:

| Experiment | Result |
| --- | --- |
| Label correlation (review-designs' score), 100 test photos, label placed from the plastic fit | 100 % right design; 92 % when the label is off by about 2 mm SD |
| SIFT against all references (2170 accepted labels, 1196 designs), 100 test photos | 100 % right design; median 134 distinct inliers against 4 for the best other design |
| SIFT speed, all 1398 DMG designs in one FLANN index | about 0.2 s per photo, after a one-off minute of reference SIFT on 10 cores |
| Print against cut | the print sits a median 0.29 mm (90 %: 0.69 mm) differently from the cut between copies |
| Print angle against cut, 1194 pairs | about 0.11° SD per label; the label fits' own angle error about 0.074° |

Labels are printed with overflow and cut sloppily, so registering photos by their print, not their cut edges, is what
lines them up. Some SIFT poses were seen off by about 0.5 mm: pose quality was never measured directly, and pooling a
design's references into one RANSAC is the suspected cause.

## The idea

With 3 or more photos of one print, registered to each other by the print, a consensus label keeps what the photos
agree on and drops what only one shows.

- Scratches, dirt, specks and stickers appear in one photo only, so a median-like rule discards them.
- Glare sits in a different place in each photo, so it's outvoted too, except when every photo has it in the same
  place (shiny black labels under the same lamp).
- Focus: where a photo is partly out of focus, the sharp photos supply the detail.
- Not removed: defects in the same place on every copy, such as wear where carts are gripped.

## Method

Combine the photos band by band, as in multiband blending for photo stitching (Burt and Adelson's Laplacian
pyramid), with a different rule per band.

1. Register every photo's label to one reference by its print: SIFT, then a dense refinement (such as OpenCV's ECC)
   for sub-pixel alignment, which the finest bands need.
2. Convert to Oklab. Its L is a cube root of luminance, so a brighter photo has proportionally stronger detail. Use a
   ratio pyramid (each detail band divided by the band below it) so that photos with different lighting compare
   band by band.
3. Combine per band:
    - lowest band: from one chosen photo, or the median of all (next section);
    - middle bands: the median; scratches, dirt and specks mostly live here;
    - finest bands: the strongest coefficients among those agreeing with the median, or weighted by each photo's
      measured sharpness. A plain median blurs a sharp photo with softer ones.
4. Mask what a photo can't contribute (stickers, tears, clipped highlights): its weight is 0 there, the mask blurred
   per band as in stitching, so it fades out over a wider area in coarser bands.
5. Clipped highlights stay white as wanted, but carry no detail, so they're masked out of the fine bands.

The split between the lowest band and the rest sits just above the size of glare patches, probably a few mm. It can be
measured: below it the photos disagree because of lighting, above it only where there are defects.

## The lowest band

The lowest band carries the overall tone and lighting, so it needs its own choice: the preferred photo
(preferred.json) is chosen for other reasons.

| What matters | For the preferred photo | For the lowest band |
| --- | --- | --- |
| Resolution | yes | no: only coarse tone, a few mm and up |
| Small damage (scratches, dirt) | yes | no: the finer bands come from the consensus |
| Even lighting, no glare | some | the main thing |
| Right colors | yes | yes |
| Large-scale fading or discoloration | some | yes: it would carry over |

- Default: the median of all photos' lowest bands, after matching their exposure. With 3 or more photos it often
  removes glare by itself.
- Suggestion: the photo whose lowest band is closest to that median, and smoothest.
- Manual choice per design where every photo has glare in the same place. It needs its own record, separate from
  preferred.json; format to be agreed before building.

## Only two photos

With two photos there's no majority, so a rule decides where they disagree: prefer the photo with less fine detail in
that spot. It works for some defects and fails for others.

| Kind of defect | What it does | Prefer the smoother photo |
| --- | --- | --- |
| Scratches, dust, specks, dirt, JPEG noise | adds fine detail | works |
| Wear, scuffed print, faded spots | removes fine detail | fails: picks the damaged one |
| Glare | lowers contrast | fails |
| One photo out of focus | less detail everywhere | fails, everywhere |

1. Match sharpness first: blur the sharper photo to the softer one's overall sharpness, then look for differences.
   Only real local differences remain, and the rule applies only there; the output keeps the sharper photo's detail
   elsewhere.
2. Use the sign of the difference: something added (a bright scratch on black, a dark speck on white): take the photo
   without it; something taken away (lower contrast, softer print edges): take the photo that has the detail.
3. Show the rest for a manual decision, such as a mark that could be dirt or print. A third photo settles most of them.

## Automatic grading

How much a copy differs from the clean consensus, outside real print differences, measures its wear. Each photo gets a
grade without anyone looking at it.

- Difference map: per pixel, the photo's registered label against the consensus, in the middle and fine bands (the
  lowest band is lighting, not condition).
- Kinds of damage from the map's shape and sign: thin bright lines (scratches), dark specks (dirt), large areas of
  lost contrast (wear, fading), straight-edged blocks (stickers, tears).
- Grade: the share of the label's area that differs beyond the photos' normal noise, perhaps weighted by kind;
  thresholds to be calibrated against copies graded by eye.
- Not condition: glare, blur and JPEG noise also differ from the consensus. They must be told apart (glare is smooth
  and bright, blur is lost detail everywhere), or the grade measures the photo instead of the cart.
- Uses: choosing photos (the cleanest copy), a collector's catalogue, the phone app showing a scanned cart's
  condition.

## More applications

| Application | How |
| --- | --- |
| Clean labels for render-labels | render each design from the consensus print instead of one photo |
| Stickers, tears, price tags | mask the region where one copy disagrees over an area; fill it from the others |
| Real print differences | after registration, copies differ only where the print does (rating mark, revision, language, print run): a sharper signal for review-designs, showing where |
| Reproductions | a reprint differs from the consensus in sharpness, color and small details |
| Photo quality | each photo's sharpness and noise against the consensus ranks photos by measurement, not source, for choose-photos |
| Text reading | read-text on the consensus instead of single photos |
| Canonical label position | place labels by their print, not their cut: straight, centered print; keep the cut's spread as statistics |
| Phone app | identify by SIFT, show the clean label beside the photo, highlight wear, stickers, or a variant not yet in the library |

Hosting the search: a server at home behind a Cloudflare Tunnel, the Worker forwarding the shrunk photo; SIFT could
later move into the browser.

## Fitting from the print

Prints that recur across photos could replace most hand fitting: the photos whose automatic fit is good locate the
print in the others, and the print straightens their whole cartridge face.

1. Group the photos by print: SIFT on every photo, one index of all descriptors, each photo's candidates checked with
   RANSAC; linked photos are one print. This finds designs, misnamed photos and variants by itself, and RANSAC run
   repeatedly (each fit's inliers removed) finds several labels in one photo.
2. Confirm fits: photos whose automatic label fit is good (about 20 %) register to each other by the print; the
   inliers in the recess agree with the fits.
3. Locate the print in the failed photos by RANSAC against the confirmed ones: a full homography from hundreds of
   inliers.
4. The label is flat in the cartridge face, so that homography straightens the whole face. The plastic is then a 2D
   problem: a shift and a turn within the label's room in the recess (about 1.5 mm and 2°).
5. Fit from there: the start goes into fits.json's "start" (as fit-by-hand's "Save for refit"), which fit-cartridge
   fits from alone.

- Not a consensus of the plastic: labels are stuck on shifted and turned per copy, so faces lined up by their print
  blur the plastic's edges. Fit each photo in its straightened face; a plastic consensus needs the faces lined up by
  the plastic instead.
- Recess depth: the label lies behind the face, so at an angle the face is straightened with a small, almost uniform
  offset (about 0.5 mm at 25° for a 1 mm deep recess), absorbed by the 2D fit's shift.
- Cut edges: what recurs is the print, not the label's cut; the label's outline comes from the model once the print is
  registered. Hand fitting would only remain for the real cut edges, if wanted.
- Konsolenkost's badly cut-out labels register too: whatever part of the print shows. Their template cartridge photos
  give no plastic fit.
- Designs with no confirmed fit need the shell's template elements (logo strip, borders, side strips) as the anchor,
  less precisely.

### A plastic consensus

The plastic matters on its own: an image of each actual cartridge gives context when researching the photos later, and
proves there is a real photo, not a synthetic image. The consensus is a tool for fitting; each photo keeps its own
straightened cartridge image.

- Scale comes from the plastic: the print's scale varies between copies by about 0.46 % (SD), about 0.2 mm across a
  label. The mm frame is set by the plastic, the print registered within it.
- One consensus per mold, shared by every photo of that shell: thousands for the DMG. Random errors shrink with the
  square root of the number of photos (1000 photos: about 3 % of one photo's noise), and their different sub-pixel
  offsets resolve the shell more finely than any one photo. The limit is how alike real shells are.
- Built like an average template in medical imaging: straighten each face through its print; line the faces up by the
  current plastic fits and average; re-align every face to the average and repeat until it settles; anchor the
  absolute scale once to the calipers (56.8 mm wide). The 4500 photos with a plastic fit at least "almost" are enough
  to start.
- Aligned by edges and gradients, not brightness: plastic is smooth (little for SIFT) and its brightness is mostly
  shading and reflections. Shell color then doesn't matter.
- Fitting becomes registration to a nearly perfect template that includes the bevels, the embossed arrow, the recess
  walls and the notch, not just the outline. Precision is then limited by each photo's sharpness; to be measured
  (today's fits agree with hand fits to about 0.3 mm), by leaving a photo out of the consensus, or with two photos of
  the same physical cart.
- Outliers stand out: wrong fits, worn or damaged shells, reproduction shells.
- Mold variants found, not assumed: group the photos by where they differ from the consensus (embossing, arrow, screw
  hole, notch), one consensus per group.
- Measured shells as a by-product: recess, bevels, arrow position from thousands of photos.
- Mold cavities: a multi-cavity mold makes several shells per shot, each with tiny repeatable differences. Each
  photo's difference from the consensus may carry its cavity's signature; grouping those could find the cavities and
  assign shells to them, if the cavities differ more than noise and wear. Photos of a shell's inside, if it carries a
  cavity number, could confirm the groups.

### One joint fit

Within each print, the print matches pin down the plane of every photo's cartridge face; together with the plastic
consensus, everything can be fitted at once, like bundle adjustment.

| | Per photo | Shared |
| --- | --- | --- |
| Unknowns | the face's plane (a homography, 8 numbers); where this cart's label sits on its plastic (shift and turn, 3) | one print per design; one plastic shape per mold |
| Constraints | hundreds of print matches to the other photos of the print; the whole plastic face against its consensus | all photos of the print; thousands of photos of the mold |

- The plane comes almost entirely from the print: a homography from hundreds of inliers (rotation between two prints
  measured to 0.008°). The plastic only settles the label's offset against an extremely precise template.
- The recess depth is one small extra unknown per photo, or a camera focal length: the label's plane is parallel to
  the face, a known distance behind it.
- The same cart photographed more than once (a relisting, or own photos) shares its label offset; such repeats show
  as identical offsets and wear, and constrain the fit further.

Unlike the starts tried on 2026-11-04 (label art from fakes and other releases: no new fits; joint plastic and label
fit: no gain), the match here is the same print in other real photos, and the plane comes from the print's homography,
not an edge fit. It targets the fits never found (93 hand-placed DMG photos had no candidate within 1 mm), not the
choice between candidates.

Test with known answers: photos with hand-placed plastics treated as unfitted, each one's start derived from its print
via the design's other photos, fit-cartridge run from it, compared with the hand fit (within 0.3 and 0.5 mm).

## First trial: DMG-APSJ-JPN

On 10 photos with accepted labels, registration by the print works, but the consensus is softer than the sharpest
photo, and the grades mix photo quality with condition.

- Registration: SIFT homography, then ECC refinement (which moved it a further 0.1–0.9 px). ECC correlation
  0.98–0.995 for 9 photos; DMG-APSJ-JPN_8 only 0.906.
- Sharpness: the consensus's fine detail is 0.0049, against 0.0114 for the sharpest photo (DMG-APSJ-JPN_3) and
  0.0020–0.0075 for the rest. The sharpness-weighted median lands mid-way; the rule "strongest coefficient among those
  agreeing with the median" is needed.
- Lowest band: rendered both ways (the median of all, and from DMG-APSJ-JPN_3) for comparison by eye.

| Photo | Source | px/mm | Sharpness | Differs from consensus |
| --- | --- | --- | --- | --- |
| DMG-APSJ-JPN | gbhwdb | 20.3 | 0.0080 | 11.6 % |
| DMG-APSJ-JPN_3 | gbhwdb | 22.7 | 0.0172 | 13.7 % |
| DMG-APSJ-JPN_5 | gbhwdb | 17.8 | 0.0115 | 15.1 % |
| DMG-APSJ-JPN_9 | gbhwdb | 13.5 | 0.0107 | 16.3 % |
| DMG-APSJ-JPN_10 | gbhwdb | 15.4 | 0.0039 | 20.6 % |
| DMG-APSJ-JPN_6 | gbhwdb | 14.4 | 0.0043 | 20.9 % |
| DMG-APSJ-JPN_7 | gbhwdb | 19.5 | 0.0087 | 22.0 % |
| DMG-APSJ-JPN_11 | yugiyahirano | 21.7 | 0.0064 | 22.6 % |
| DMG-APSJ-JPN_8 | gbhwdb | 21.3 | 0.0070 | 26.0 % |
| DMG-APSJ-JPN_2 | gbhwdb | 14.2 | 0.0126 | 27.2 % |

"Differs" is the share of the label whose detail differs from the consensus by more than 4× the median difference.
The sharpest photo differs partly because the consensus is softer, and the soft photos because they lack detail: the
difference maps, not these numbers, show which is wear.

Open: the agreeing-strongest rule for the fine bands; telling blur and glare apart from damage before grading; whether
the lowest band defaults to the median of all photos or to a manual pick.
