"""paras: put any software into your language, and prove it still works. Paras on SHAKTI is Parashakti.
© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI. Licensed under the MIT licence (see LICENSE)."""
import argparse, os, shutil, subprocess, sys
from pathlib import Path
from . import __version__, NOTICE, core, tui

PKG = Path(__file__).parent; DATA = PKG / "data"
IMAGE, CONTAINER = f"paras-ilm:{__version__}", "paras-ilm"
TOOLS = "git python3 gh ca-certificates gcc g++"

HELP = """paras: put any software into your language, and prove it still works.

  paras ingest <repository>     into every supported language: checked, one branch per language
  paras report <repository>     ingest and check only, and say what is still to be translated
  paras stack                   the whole sovereign stack, layer by layer, silicon to distribution
  paras top                     watch a run: cores, progress, and every language's quality

  <repository> is any Git URL (GitHub, GitLab, your own server) or a folder on this machine.

Options, when you need them:
  --langs urdu,tamil    only these languages        --publish [ORG]   publish to ORG (default hmnsq), asking once
  --only xv6,linux      only these stack packages   --from linux      start the stack from a package
  --cpus 0-5            run only on these cores     --local           run here, without a container
  --work DIR            where work and reports go (default ./paras-work)

Also: paras list · paras status · paras stop · paras doctor · paras prove <repository> --run CMD --expect TEXT
Everything runs inside one container, made once and kept; nothing is installed on this machine."""


def say(t):
    print(f"\033[1m{t}\033[0m", flush=True)


def docker(*args, capture=True):
    return subprocess.run(["docker", *args], capture_output=capture, text=True)


def ensure_container(work, cpus):
    if not shutil.which("docker"):
        sys.exit("paras: Docker is not installed. Install Docker, or run with --local.")
    if docker("info").returncode:
        sys.exit("paras: Docker is installed but not reachable by this user (is the daemon running? are you in the docker group?)")
    if docker("image", "inspect", IMAGE).returncode:
        say(f"Building the paras container image once ({IMAGE}); every step is shown")
        if docker("build", "-t", IMAGE, "-f", str(DATA / "Dockerfile"), str(DATA), capture=False).returncode:
            sys.exit("paras: the image did not build (see above)")
    r = docker("inspect", "-f", "{{range .Mounts}}{{.Source}}={{.Destination}};{{end}}", CONTAINER)
    if r.returncode:
        say(f"Creating the container {CONTAINER} once; it is kept between runs")
        args = ["create", "--name", CONTAINER, "-v", f"{work}:/work", "-v", f"{PKG}:/opt/paras/paras_ilm:ro"] + (["--cpuset-cpus", cpus] if cpus else []) + [IMAGE, "sleep", "infinity"]
        if docker(*args, capture=False).returncode:
            sys.exit("paras: the container could not be created (see above)")
    else:
        mounts = dict(m.split("=", 1)[::-1] for m in r.stdout.strip().strip(";").split(";") if "=" in m)
        if mounts.get("/work") != str(work) or mounts.get("/opt/paras/paras_ilm") != str(PKG):
            sys.exit(f"paras: the container {CONTAINER} belongs to another work folder ({mounts.get('/work')}) or another paras install "
                     f"({mounts.get('/opt/paras/paras_ilm')}). Run paras from that folder, or remove it: docker rm -f {CONTAINER}")
        if cpus:
            docker("update", "--cpuset-cpus", cpus, CONTAINER, capture=False)
    if docker("inspect", "-f", "{{.State.Running}}", CONTAINER).stdout.strip() != "true":
        docker("start", CONTAINER, capture=False)
    missing = docker("exec", CONTAINER, "bash", "-c", "for t in git python3 gh gcc g++; do command -v $t >/dev/null || echo $t; done").stdout.split()
    if missing:
        say(f"Installing inside the container: {' '.join(missing)}")
        if docker("exec", CONTAINER, "bash", "-c", f"export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y {TOOLS}", capture=False).returncode:
            sys.exit("paras: installing inside the container failed (see above)")


def consent(what):
    say(what)
    try:
        line = input("   Type YES and a reason, once; nothing else will ask.\n   > ")
    except EOFError:
        line = ""
    if line.strip().split(" ")[0].upper().strip(",:;.") != "YES":
        say("nothing done"); sys.exit(0)
    return "PUSH " + (line.strip()[3:].strip(" ,:;.") or "paras")


def run_inside(work, args, publish_note, local):
    env = {}
    if publish_note:
        token = os.environ.get("GH_TOKEN", "")
        if not token and shutil.which("gh"):
            token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
        if not token:
            sys.exit("paras: publishing needs a GitHub login here (gh auth login), or GH_TOKEN set")
        env["GH_TOKEN"] = token
        env["PARAS_CONSENT"] = consent(publish_note)
    for k in ("HINDAWI_LLM_URL", "HINDAWI_LLM_MODEL"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    if local:
        os.environ.update(env)
        from . import runner
        return runner.main(["--work", str(work), *args])
    flags = sum((["-e", f"{k}={v}"] for k, v in env.items()), [])
    tty = ["-it"] if sys.stdin.isatty() else ["-i"]
    setup = "gh auth setup-git >/dev/null 2>&1 || true; " if publish_note else ""
    cmd = ["docker", "exec", *tty, *flags, "-e", "PYTHONPATH=/opt/paras", CONTAINER, "bash", "-c",
           setup + 'exec python3 -m paras_ilm.runner --work /work "$@"', "_", *args]
    os.execvp("docker", cmd)


def main(argv=None):
    import signal
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)      # piped into head or less, it ends quietly, as Unix tools do
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(HELP); print(); print(NOTICE); return 0
    if argv[0] in ("--version", "-V", "version"):
        print(NOTICE); return 0
    ap = argparse.ArgumentParser(prog="paras", add_help=False)
    ap.add_argument("verb"); ap.add_argument("target", nargs="?")
    ap.add_argument("--langs", default="all"); ap.add_argument("--publish", nargs="?", const="hmnsq")
    ap.add_argument("--only"); ap.add_argument("--from", dest="start"); ap.add_argument("--cpus"); ap.add_argument("--local", action="store_true")
    ap.add_argument("--work", default=os.environ.get("PARAS_WORK", str(Path.cwd() / "paras-work"))); ap.add_argument("--jobs", type=int)
    ap.add_argument("--redo", action="store_true"); ap.add_argument("--allow-inexact", action="store_true"); ap.add_argument("--once", action="store_true")
    ap.add_argument("--run"); ap.add_argument("--expect"); ap.add_argument("--build")
    a = ap.parse_args(argv)
    work = Path(a.work).resolve(); work.mkdir(parents=True, exist_ok=True)
    if a.cpus:
        try:
            tui.parse_cpus(a.cpus)
        except ValueError as e:
            sys.exit(f"paras: {e}")
    if a.verb == "list":
        for p in core.parse_manifest((DATA / "stack.tsv").read_text(encoding="utf-8")):
            print(f"{p.layer:12} {p.name:16} {p.mode:7} {p.scope:28} {p.url}")
        return 0
    if a.verb == "top":
        return tui.once(work) if a.once or not sys.stdout.isatty() else tui.run(work)
    if a.verb == "status":
        prog = core.read_json(work / "progress.json", {}) or {}
        print(f"{prog.get('package', 'no run')} · {prog.get('phase', '-')} · updated {prog.get('updated', '-')}")
        print((work / "SUMMARY.md").read_text(encoding="utf-8") if (work / "SUMMARY.md").exists() else "no summary yet"); return 0
    if a.verb == "stop":
        if a.local or tui.container_cpus() is None:
            pid = (core.read_json(work / "progress.json", {}) or {}).get("pid")
            if pid:
                os.kill(pid, 15)
        else:
            docker("exec", CONTAINER, "pkill", "-TERM", "-f", "paras_ilm.runner", capture=False)
        say("asked the run to stop; it records where it was, and a rerun carries on from there"); return 0
    if a.verb == "doctor":
        for t in ("docker", "gh", "git", "python3"):
            print(f"   {t:8} {'found' if shutil.which(t) else 'MISSING'}")
        print(f"   disk     {shutil.disk_usage(work).free >> 30} GB free in {work}")
        print(f"   cores    {os.cpu_count()}; the container uses: {tui.container_cpus() or 'no container yet'}")
        return 0
    if a.verb == "prove":
        if not a.target:
            sys.exit("paras: prove needs a repository")
        eng = ["bash", str(DATA / "engine/prove.sh"), "--no-ui", "--url", a.target, "--langs", a.langs] + \
              sum(([f"--{k}", v] for k, v in (("run", a.run), ("expect", a.expect), ("build", a.build)) if v), [])
        if a.local:
            return subprocess.call(eng, cwd=work)
        ensure_container(work, a.cpus)
        os.execvp("docker", ["docker", "exec", "-it" if sys.stdin.isatty() else "-i", "-w", "/work", CONTAINER, "bash", "/opt/paras/paras_ilm/data/engine/prove.sh",
                             *eng[2:]])
    if a.verb not in ("ingest", "report", "stack"):
        sys.exit(f"paras: I do not know {a.verb!r} (paras --help)")
    if a.verb in ("ingest", "report") and not a.target:
        sys.exit(f"paras: {a.verb} needs a repository (a Git URL or a folder)")
    args = ["--langs", a.langs] + (["--org", a.publish] if a.publish else []) + (["--jobs", str(a.jobs)] if a.jobs else []) + \
           (["--redo"] if a.redo else []) + (["--allow-inexact"] if a.allow_inexact else [])
    if a.verb == "stack":
        args += (["--only", a.only] if a.only else []) + (["--from", a.start] if a.start else [])
        note = f"This run forks the stack's packages into github.com/{a.publish} and pushes, for each, one branch per language that converts back exactly." if a.publish else ""
    else:
        target = a.target
        if not target.startswith(("https://", "file://")):
            p = Path(target).resolve()
            if not p.is_dir():
                sys.exit(f"paras: {target} is neither a Git URL nor a folder")
            if not a.local:                       # a local folder is copied into the work folder, which the container sees
                dest = work / "inputs" / p.name; shutil.rmtree(dest, ignore_errors=True); shutil.copytree(p, dest, symlinks=True)
                target = f"/work/inputs/{p.name}"
            else:
                target = str(p)
        args += ["--target", target] + (["--report-only"] if a.verb == "report" else [])
        note = (f"This run forks {a.target} into github.com/{a.publish} and pushes one branch per language that converts back exactly."
                if a.publish and a.verb == "ingest" else "")
    if not a.local:
        ensure_container(work, a.cpus)
    return run_inside(work, args, note, a.local)


if __name__ == "__main__":
    sys.exit(main())
