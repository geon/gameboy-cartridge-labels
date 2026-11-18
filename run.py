"""The Makefile's targets for where there is no make (plain Windows): python run.py <target> [SAMPLE=1] [ID=..] [SHAPE=..]
[NAME=..] [NOTE=..]. python run.py lists them.
python run.py py <script> [arguments] runs any script of the project in the .venv environment. Same steps, same scripts; `make publish` (publish.sh) needs Git Bash."""
import os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = ["remove-low-resolution", "read-text", "features", "edges", "match", "find", "solve", "straighten",
         "read-serials", "prints", "restore", "build"]
CLEANABLE = ["read-text", "features", "edges", "match", "find", "solve", "straighten", "read-serials", "prints",
             "restore", "build"]
TOOLS = {"add-photos": "add_photos", "move-downloads": "move_downloads", "remove-photos": "remove_photos",
         "review-prints": "review_prints"}
VENV_PYTHON = os.path.join(HERE, ".venv", "Scripts" if os.name == "nt" else "bin", "python" + (".exe" if os.name == "nt" else ""))


def python():
    return VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable


def run(*args):
    done = subprocess.run([python(), *args], cwd=HERE)
    if done.returncode:
        sys.exit(done.returncode)


def step(name, v):
    gen = "generated-sample" if v.get("SAMPLE") else "generated"
    flag = ["--sample"] if v.get("SAMPLE") else []
    script = lambda s: os.path.join("src", s.replace("-", "_") + ".py")
    if name == "setup":
        subprocess.run([sys.executable, "-m", "venv", os.path.join(HERE, ".venv")], check=True)
        run("-m", "pip", "install", "-r", "requirements.txt")
    elif name == "test":
        run("-m", "pytest", "-q", "tests")
    elif name == "all":
        for s in STEPS:
            step(s, v)
    elif name == "build":
        shutil.rmtree(os.path.join(HERE, gen, "publish"), ignore_errors=True)
        run(script("publish"), *flag, gen + "/publish")
    elif name == "todo-report":
        run(script(name), *([v["NAME"], "--note", v.get("NOTE", "")] if v.get("NAME") else ["--page"]))
    elif name == "refreeze":
        run(script(name), *flag, *([v["ID"]] if v.get("ID") else []))
    elif name == "fit-by-hand":
        run(script(name), v.get("SHAPE", "cgb"))
    elif name in TOOLS:
        run(os.path.join("src", TOOLS[name] + ".py"))
    elif name in STEPS:
        run(script(name), *flag)
    elif name.startswith("clean-") and name[6:] in CLEANABLE:
        shutil.rmtree(os.path.join(HERE, gen, name[6:]), ignore_errors=True)
    elif name == "publish":
        sys.exit("publish.sh is a bash script: run make publish from Git Bash")
    elif name == "help":
        print("targets:", *["setup", "test", "all", "todo-report", "refreeze", "fit-by-hand", "publish", *TOOLS, *STEPS,
                            *("clean-" + c for c in CLEANABLE)])
    else:
        sys.exit(f"unknown target {name!r}; targets: " + ", ".join(
            ["setup", "test", "all", "todo-report", "refreeze", "fit-by-hand", "publish", *TOOLS, *STEPS,
             *("clean-" + c for c in CLEANABLE)]))


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "py":  # python run.py py src/tradera_photos.py download ...: any script, in the environment
        run(*args[1:])
        sys.exit(0)
    v = dict(a.split("=", 1) for a in args if "=" in a)
    names = [a for a in args if "=" not in a]
    step(names[0] if names else "help", v)
