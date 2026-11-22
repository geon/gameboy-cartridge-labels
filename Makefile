# The steps from photos to label images, one target each. A target runs its step and nothing else: never another step
# first. Each step skips what it has already done; make clean-<step> deletes its output, to redo it. With SAMPLE=1 a
# step works on the photos in sample.txt only, into generated-sample/ instead of generated/.
#
#   make setup
#   Creates the Python environment, .venv/, with the packages in requirements.txt.
#
#   make test
#   Runs the unit tests (tests/).
#
#   make add-photos
#   Files the photos left in save-new-images-here/ into photos/ as <sha1>.<ext>, with where each came from (a
#   subfolder's name and listing.json) in photo-sources.json (src/add_photos.py).
#
#   make move-downloads
#   Moves the photos the eBay, Mercari and Yahoo (Jauce) downloaders saved in downloaded-photos/ to
#   save-new-images-here/, with their listing.json entries, for make add-photos (src/move_downloads.py).
#
#   make all
#   Runs every step below in order, remove-low-resolution through build (not add-photos or publish), each skipping what it has
#   already done.
#
#   make remove-low-resolution
#   Deletes from photos/ every photo whose label photos all have under 10 px per mm, by the last solve
#   (generated/solve/solve.json; nothing before the first), each recorded in
#   generated/remove-low-resolution/deleted.json. First, so a photo measured in one run is gone before the next run's
#   find and solve (src/remove_low_resolution.py).
#
#   make read-text
#   Reads the text on every photo (RapidOCR) into generated/read-text/<sha1>.json; the page generated/read-text/index.html.
#
#   make features
#   SIFT keypoints of every photo into generated/features/<sha1>.npz; the page generated/features/index.html.
#
#   make edges
#   Every straight line segment in every photo (LSD) into generated/edges/<sha1>.npz; the page generated/edges/index.html.
#
#   make match
#   Pairs of photos showing something alike, with their homographies, into generated/match/; the page
#   generated/match/index.html. Needs make features.
#
#   make find
#   The label photos in every photo, from serials read and matches, into generated/find/label-photos.json; the page
#   generated/find/index.html. Needs make read-text and make match.
#
#   make solve
#   Every label photo's homography into ink coordinates (the sticker's cut fitted to the edges, the linked sets aligned
#   by their matches) into generated/solve/solve.json; the page generated/solve/index.html. Needs make find and edges.
#
#   make straighten
#   Every solved label photo in ink coordinates (20 px/mm, 5 mm around the label) and its sticker's cut edges found in
#   it, into generated/straighten/; the pages generated/straighten/index.html and cuts.html. Needs make solve.
#
#   make read-serials
#   Every label photo's serial (OCR of the straightened label photos, settled within its family), the database's
#   entries with no label photo and the serials it doesn't know, into generated/read-serials/. Needs make straighten.
#
#   make prints
#   Each family's label photos split into prints by a tile comparison, into generated/prints/; the page generated/prints/index.html. Needs make read-serials.
#
#   make restore
#   An image of every print from its label photos (bands, the median), cropped 0.3 mm inside its family's cuts, paper white
#   where found, into generated/restore/; the page generated/restore/index.html. Needs make prints.
#
#   make select-visually-distinct
#   Of each game's prints, the ones that look different enough to browse: every pair of one game's restored prints
#   compared (the share of 2 mm tiles differing in colour or detail), a print left out when under 60 % differs from
#   one kept, into generated/select-visually-distinct/ (scores.json, selected.json); the page
#   generated/select-visually-distinct/index.html (src/select_visually_distinct.py). Needs make restore.
#
#   make build
#   The site, made anew in generated/publish/: prints/ (the restored prints), index.json (source and URLs from
#   photo-sources.json), the lists, the page generated/publish/index.html and wanted.html (the prints a photo or two
#   short of an image, best chances first: src/wanted.py) (src/publish.py). Needs make select-visually-distinct.
#
#   make publish
#   Not in make all: generated/publish/ as it is (make build) committed to the gh-pages branch, replacing all it held,
#   and pushed to origin (publish.sh).
#
#   make refreeze [ID=DMG-TS-USA-mike]
#   A tool, not a step: every frozen print (or the one given) restored again with today's restore, its frozen image
#   replaced; its label photos, poses and crop stay as accepted (src/refreeze.py). Then make all, to match the new images.
#
#   make review-prints
#   A tool, not a step: a local page for the stored prints (prints.json, stored-prints.md): joining, splitting, deleting
#   label photos, setting serials, freezing, changed in the store at once (then make restore publish): the serials of
#   several prints, prints of several serials, prints without a serial, the last run's new ones, every print worst
#   first, a search, and the recent changes to undo (src/review_prints.py).
#
#   make remove-photos
#   A tool, not a step: a local page for deleting photos from photos/ (the file and its record in photo-sources.json),
#   on three tabs: the unused photos, 20 at a time; every print's restored image to mark Good or Bad or freeze; every
#   print with its label photos, by print id, to delete one. Asks first if a photo holds label photos of other prints
#   (src/remove_photos.py).
#
#   make fit-by-hand SHAPE=cgb
#   A tool, not a step: a local page for placing labels by hand on one shape's approximate cuts (dmg, cgb or agb; cgb by
#   default), the lowest edge-model label confidence first, each straightened with its margin: drag the label's corners
#   onto the sticker's; saved to hand-fit-labels.json in the photo's pixels, for training and testing the label edge
#   model; no step reads it. Not a label: the area goes to not-labels.json, and make find makes no label photo there
#   (src/fit_by_hand.py).
#
#   make todo-report NAME=<name> NOTE="what changed"
#   A tool, not a step: the prints listed in todo.md restored with the current code as a new version
#   (generated/todo-report/<n>-<name>/, every version kept), and the page generated/todo-report/index.html: each listed
#   print with your note and all its versions side by side (src/todo_report.py). Without NAME, only the page.
#
# Plain make lists these.

PYTHON := .venv/bin/python
GENERATED := $(if $(SAMPLE),generated-sample,generated)
SAMPLE_FLAG := $(if $(SAMPLE),--sample,)

.PHONY: help setup test all todo-report add-photos move-downloads remove-low-resolution read-text clean-read-text features clean-features edges clean-edges match clean-match find clean-find solve clean-solve straighten clean-straighten read-serials clean-read-serials prints clean-prints restore clean-restore select-visually-distinct clean-select-visually-distinct build clean-build publish remove-photos review-prints refreeze fit-by-hand
help:
	@awk '/^#   /{line = substr($$0, 5); if (line ~ /^make / && n++) print ""; print line}' Makefile

setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest -q tests

add-photos:
	$(PYTHON) src/add_photos.py

move-downloads:
	$(PYTHON) src/move_downloads.py

todo-report:
	$(PYTHON) src/todo_report.py $(if $(NAME),$(NAME) --note "$(NOTE)",--page)

STEPS := remove-low-resolution read-text features edges match find solve straighten read-serials prints restore select-visually-distinct build

all:
	set -e; for step in $(STEPS); do $(MAKE) $$step; done

remove-low-resolution:
	$(PYTHON) src/remove_low_resolution.py $(SAMPLE_FLAG)

read-text:
	$(PYTHON) src/read_text.py $(SAMPLE_FLAG)

clean-read-text:
	rm -rf $(GENERATED)/read-text

features:
	$(PYTHON) src/features.py $(SAMPLE_FLAG)

clean-features:
	rm -rf $(GENERATED)/features

match:
	$(PYTHON) src/match.py $(SAMPLE_FLAG)

clean-match:
	rm -rf $(GENERATED)/match

find:
	$(PYTHON) src/find.py $(SAMPLE_FLAG)

clean-find:
	rm -rf $(GENERATED)/find

edges:
	$(PYTHON) src/edges.py $(SAMPLE_FLAG)

clean-edges:
	rm -rf $(GENERATED)/edges

solve:
	$(PYTHON) src/solve.py $(SAMPLE_FLAG)

clean-solve:
	rm -rf $(GENERATED)/solve

straighten:
	$(PYTHON) src/straighten.py $(SAMPLE_FLAG)

clean-straighten:
	rm -rf $(GENERATED)/straighten

read-serials:
	$(PYTHON) src/read_serials.py $(SAMPLE_FLAG)

clean-read-serials:
	rm -rf $(GENERATED)/read-serials

prints:
	$(PYTHON) src/prints.py $(SAMPLE_FLAG)

clean-prints:
	rm -rf $(GENERATED)/prints

restore:
	$(PYTHON) src/restore.py $(SAMPLE_FLAG)

clean-restore:
	rm -rf $(GENERATED)/restore

select-visually-distinct:
	$(PYTHON) src/select_visually_distinct.py $(SAMPLE_FLAG)

clean-select-visually-distinct:
	rm -rf $(GENERATED)/select-visually-distinct

build:
	rm -rf $(GENERATED)/publish
	$(PYTHON) src/publish.py $(SAMPLE_FLAG) $(GENERATED)/publish

clean-build:
	rm -rf $(GENERATED)/publish

publish:
	$(if $(SAMPLE),$(error make publish publishes generated/, not the sample),./publish.sh)

remove-photos:
	$(PYTHON) src/remove_photos.py

review-prints:
	$(PYTHON) src/review_prints.py

refreeze:
	$(PYTHON) src/refreeze.py $(SAMPLE_FLAG) $(ID)

SHAPE ?= cgb
fit-by-hand:
	$(PYTHON) src/fit_by_hand.py $(SHAPE)
