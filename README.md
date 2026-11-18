# Game Boy labels

Clean, straight-on images of Game Boy cartridge labels, made from photos of cartridges: my own, and ones found online.

## Setup

Needs Python 3. Run `make setup` once: it creates the Python environment, `.venv/`, with the packages in
`requirements.txt`. Run `make` to list the steps.

### Windows

The steps from `add-photos` to `build` run on Windows 11 (tried there with a few hundred photos). `make publish`, `remove-photos`,
`review-prints` and `fit-by-hand` haven't been tried on Windows.

1. Install Python 3.13 from python.org (tick "Add python.exe to PATH") and Git for Windows.
2. In PowerShell, in the project folder, without `make`:

   ```
   python run.py setup
   python run.py test
   python run.py all
   ```

   `run.py` takes the same targets as the Makefile, with the same options: `python run.py read-text SAMPLE=1`,
   `python run.py refreeze ID=DMG-TS-USA-mike`, `python run.py clean-prints`. `python run.py` lists them.
3. If you prefer `make`, install it (`winget install ezwinports.make`, or `scoop install make`) and use Git Bash: `make`
   then works as on Linux. `make publish` (publish.sh) needs Git Bash either way.

Put new photos in `save-new-images-here/` and run `python run.py add-photos`; they are filed in `photos/` (HEIC works
through `pillow-heif`). Text files are read and written as UTF-8 with LF line
endings on every system, so the JSON files are the same ones as on other systems; `.gitattributes` keeps Git from
turning them into CRLF.
