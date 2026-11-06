# Game Boy labels

Clean, straight-on images of Game Boy cartridge labels, made from photos of cartridges: my own, and ones found online.

## Setup

Needs macOS (for text recognition), Python 3, and [gb-game-list](../gb-game-list) checked out next to this repository.
Run `make setup` once: it creates the Python environment, `.venv/`, with the packages in `requirements.txt`.

## Where things are

- `save-new-images-here/`: drop off new photos here, in a subfolder named after where they came from.
- `photos/`: every photo of a cartridge, `photos/<source>/<system>/<serial>[_<n>].<ext>`, with a `sources.json` per folder
  saying where each photo came from. A photo is named by the serial printed on its label; to correct one, rename it.
- `special-shells.tsv`: the cartridges whose shell isn't the usual one (rumble, tilt sensor, infrared…), left out of the
  fitting. Edited by hand.
- `split-by-region.tsv`: the releases in gb-game-list (one per ROM) whose regions' labels differ, each region a release
  of its own here (CGB-AW8A-JPN). Edited by hand.
- `colors.json`: each photo's own color settings (black, white, midtones, temperature, tint), made by `make fit-colors`,
  or set by hand in `make adjust-colors`.
- `src/`: the scripts.
- `reviews/fits.json`: my verdicts on the fits (`make review-fits`), each with the fit it judged.
- `generated/`: everything made from the photos (not committed).

## Steps

Run `make` to list them. Each step is one target, and runs only that step.
