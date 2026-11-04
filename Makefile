# The steps from photos to label images, one target each. A target runs its step and nothing else: never another step
# first. Each step skips what it has already done; make clean-<step> deletes its output, to redo it.
#
#   make setup
#   Creates the Python environment, .venv/, with the packages in requirements.txt.
#
#   make add-photos
#   Files the photos left in save-new-images-here/ into photos/, each named by the serial read on its label (src/add_photos.py).
#
#   make read-text
#   Reads the text on every photo in photos/ into generated/read-text/<photo>.json: every line of text found, and where it is (src/read_text.py).
#
#   make fit-cartridge
#   Fits the cartridge's model (Game Boy, Game Boy Color only, Game Boy Advance) to every photo but those listed in special-shells.tsv, started from its text and from the outlines in the photo, the fit chosen by a score learned from your verdicts (make learn-choice), into fits.json: the pose of its plastic (the label is left for a later step), not yet reviewed; what it found on the way, with flags for review, into generated/fit-cartridge/<photo>.json; a plastic fit accepted or placed by hand is kept, not fitted again (src/fit_cartridge.py, src/cartridge.py, src/fits.py).
#
#   make fit-label
#   Fits the label in the recess of every photo whose plastic is accepted or placed by hand, into fits.json: its pose, as a homography from the label's model to the photo's pixels, not yet reviewed; its shift, turn and width into generated/fit-label/<photo>.json; a fit sticking out of the recess is rejected; a label accepted or placed by hand is kept (src/fit_label.py).
#
#   make fit-colors
#   Sets each photo's own colors (black, white, midtones, temperature, tint; src/color.py) into colors.json, for every photo but the fakes whose plastic is accepted or placed by hand: where its label is accepted or placed by hand, as learned from the colors set by hand (a linear model on the label's levels, learned afresh each run); else, as before: my own photos' and jnlgame's background made white, Hit-Japan's, yugiyahirano's and elrocinante's set by source, and for a source whose photos aren't lit alike, its label's white paper made neutral, as bright as the reference sources' (my own, Hit-Japan's, elrocinante's); settings placed by hand are kept. Its label images, straightened, into generated/fit-colors/labels/<photo>.png (src/fit_colors.py).
#
#   make render-labels
#   Renders each release's label, straightened and its colors set (colors.json, make fit-colors), stretched to its shell's canonical label size at 4.7 px per mm (DMG 42.5 x 37 mm, 200 x 174 px; CGB 41.5 x 37 mm, 195 x 174 px; AGB 43 x 22 mm, 202 x 103 px), into generated/render-labels/<release>.avif: from its preferred photo if that one's label is accepted or placed by hand, else the best one by source whose label is; releases without one get none (src/render.py).
#
#   make render-carts
#   Renders each release's cartridge front the same way, with 5 mm around it, at 20 px per mm (1340 x 1500 px, the AGB's 1400 x 890; off the photo transparent), the canonical images of the cartridges, into generated/render-carts/<release>.avif, from the photo chosen alike but by its plastic fit (src/render.py).
#
#   make label-page
#   A page of every release's label (from make render-labels) on an empty cartridge (templates/), the DMG ones on a gray or black one: black if gb-game-list marks it Game Boy Color enhanced, but for those in shell-colors.tsv; then the CGB ones on the clear CGB cartridge, and the AGB ones on a gray AGB cartridge drawn from its model, into generated/label-page/index.html, to open as a file (src/label_page.py).
#
#   make learn-choice
#   A tool, not a step: learns how fit-cartridge chooses among a photo's fits from the photos whose plastic is accepted or placed by hand, into src/choice.json (committed; fit-cartridge then fits again the photos not yet known to be right), and prints how many each choice gets right (src/learn_choice.py).
#
#   make adjust-colors
#   A tool, not a step: a local page for setting each photo's colors by hand, release by release, its photos' labels side by side, the reference sources' marked: black, white, midtones, temperature and tint sliders, saved to colors.json as placed by hand when let go; Auto puts back fit-colors' settings (src/adjust_colors.py).
#
#   make review-fits
#   A tool, not a step: a local page for judging the plastic's fits by eye, each drawn on its photo, flagged ones first; your verdicts are saved to fits.json (src/review_fits.py).
#
#   make review-labels
#   A tool, not a step: a local page for judging the label's fits by eye, each on its recess straightened, with 5 mm around it, all at one scale, those farthest from the recess's middle first; your verdicts are saved to fits.json; a plastic fit found off can be demoted to almost, rejecting its label (src/review_labels.py).
#
#   make fit-by-hand
#   A tool, not a step: a local page for placing the plastic and the label by hand where the fit is off, one photo at a time, those judged almost first: drag the recess's corners and the label into place; saved to fits.json as the photo's fit, placed by hand, which the steps keep (src/fit_by_hand.py).
#
#   make search-photos
#   A tool, not a step: a local page of searches (Google; for Japanese releases the eBay sellers elrocinante and Hit-Japan, and Jauce; for the others the eBay seller ASANOSHOP and GameStop; and Google Lens with the release's cartridge photo from game-boy-database.com or otakaraou photo) for photos of the Game Boy, Game Boy Color and Game Boy Advance releases not in photos/, or there only as fakes from emumovies or launchbox-abeezy1388 (those sold on Nintendo Power, and those from otakaraou alone, apart), into generated/search-photos/index.html (src/search_photos.py).
#
#   make name-photos
#   A tool, not a step: a local page for naming the photos whose serial isn't known, one at a time: type the serial on its label and press enter; the photo is renamed in photos/, its fits in fits.json with it; or delete it (src/name_photos.py).
#
#   make find-doubles
#   A tool, not a step: a local page listing every photo in photos/, one release per row, its photos sorted by their source's quality (Hit-Japan first, otakaraou the last real photos, the box-art fakes below), each marked with an orange check if its plastic is fitted, a green one if its label is too; each can be deleted, its fits with it, or renamed to a corrected serial, its fits following it; clicking a photo makes it its release's preferred one, saved to preferred.json (src/find_doubles.py).
#
#   make compare-labels
#   A tool, not a step: finds the photos whose labels look alike but which are of different releases with different serials, DMG only against DMG, CGB against CGB, AGB against AGB: their label images from make fit-colors (the label alone), compared in gray with the lighting evened out, shrunk to about 1.2 px per mm, by their correlation, the best of shifts up to about 1.7 mm; the scores kept by the photos' SHA-1s in generated/compare-labels/scores.json, so that a new photo is only compared with those already there; the pairs scoring at least 0.7, by score, into generated/compare-labels/matches.tsv, to review (src/compare_labels.py).
#
# Plain make lists these.

PYTHON := .venv/bin/python

.PHONY: help setup add-photos read-text clean-read-text fit-cartridge clean-fit-cartridge fit-label clean-fit-label fit-colors clean-fit-colors adjust-colors render-labels clean-render-labels render-carts clean-render-carts label-page learn-choice review-fits review-labels fit-by-hand search-photos name-photos find-doubles compare-labels
help:
	@awk '/^#   /{line = substr($$0, 5); if (line ~ /^make / && n++) print ""; print line}' Makefile

setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt

add-photos: | src/ocr
	$(PYTHON) src/add_photos.py

read-text: | src/ocr
	$(PYTHON) src/read_text.py

clean-read-text:
	rm -rf generated/read-text

fit-cartridge:
	$(PYTHON) src/fit_cartridge.py

clean-fit-cartridge:
	rm -rf generated/fit-cartridge

fit-label:
	$(PYTHON) src/fit_label.py

clean-fit-label:
	rm -rf generated/fit-label

fit-colors:
	$(PYTHON) src/fit_colors.py

clean-fit-colors:
	rm -rf generated/fit-colors

render-labels:
	$(PYTHON) src/render.py labels

clean-render-labels:
	rm -rf generated/render-labels

render-carts:
	$(PYTHON) src/render.py carts

clean-render-carts:
	rm -rf generated/render-carts

label-page:
	$(PYTHON) src/label_page.py

learn-choice:
	$(PYTHON) src/learn_choice.py

adjust-colors:
	$(PYTHON) src/adjust_colors.py

review-fits:
	$(PYTHON) src/review_fits.py

review-labels:
	$(PYTHON) src/review_labels.py

fit-by-hand:
	$(PYTHON) src/fit_by_hand.py

search-photos:
	$(PYTHON) src/search_photos.py

name-photos:
	$(PYTHON) src/name_photos.py

find-doubles:
	$(PYTHON) src/find_doubles.py

compare-labels:
	$(PYTHON) src/compare_labels.py

# The text recognition tool, built when missing (macOS).
src/ocr: src/ocr.swift
	swiftc -O $< -o $@
