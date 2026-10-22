"""runner: does the work, inside the container or here with --local. For each package: check the disk, fork or mirror it
into the organisation, clone it shallow at its pinned commit, put it into every language with BURP (each language's quality
measured as it finishes), convert every language back and compare it with the original byte for byte, commit each exact
language on its own branch lang/<language>, add a paras branch with the report and what is still missing, push, confirm the
remote holds exactly what was pushed, clean up, and move on. Every step is logged; every failure is recorded with its cause.
© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI. Licensed under the MIT licence (see LICENSE)."""
import argparse, filecmp, json, os, shutil, signal, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from . import core

DATA = Path(__file__).parent / "data"
TIMEOUT = {"clone": 3600, "burp": 6 * 3600, "reverse": 3600, "push": 2 * 3600, "gh": 300}
MIN_FREE = float(os.environ.get("PARAS_MIN_FREE_GB", "2")) * 2**30   # the reserve kept free on the work disk
AUTHOR = ["-c", "user.name=Abhishek Choudhary", "-c", "user.email=obonac@users.noreply.github.com"]


class Run:
    def __init__(self, work, hindawi=None, org="hmnsq", langs="all", jobs=None, publish=False, allow_inexact=False):
        self.work = Path(work); self.tmp = self.work / "tmp"; self.rep = self.work / "reports"
        self.hindawi = Path(hindawi) if hindawi else self.work / "hindawi2026.10"
        self.burp = self.hindawi / "lang/hindawi/burp/burp.py"
        self.org, self.langspec, self.publish, self.allow_inexact = org, langs, publish, allow_inexact
        self.jobs = jobs or len(os.sched_getaffinity(0))
        self.state_path, self.progress_path = self.work / "state.json", self.work / "progress.json"
        self.state = core.read_json(self.state_path, {}) or {}
        self.events = core.Events(self.work)
        self.fork_base = os.environ.get("PARAS_FORK_BASE", "https://github.com")

    # ---- every command: shown, timed, recorded; never a shell string
    def sh(self, cmd, timeout, cwd=None, capture=False, stream=None):
        print("   $ " + " ".join(map(str, cmd)), flush=True)
        t0 = time.time()
        try:
            if stream:
                p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
                deadline = t0 + timeout
                for line in p.stdout:
                    stream(line.rstrip("\n"))
                    if time.time() > deadline:
                        p.kill(); raise subprocess.TimeoutExpired(cmd, timeout)
                p.wait(); rc, out = p.returncode, ""
            else:
                r = subprocess.run([str(c) for c in cmd], cwd=cwd, timeout=timeout, text=True, errors="replace",
                                   stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None)
                rc, out = r.returncode, (r.stdout or "")
        except subprocess.TimeoutExpired:
            self.events(step=cmd[0], status="timeout", seconds=int(time.time() - t0)); print(f"   timed out after {timeout} s", flush=True)
            return 124, ""
        except FileNotFoundError as e:
            self.events(step=cmd[0], status="missing", reason=str(e)); print(f"   {cmd[0]} is not installed: {e}", flush=True)
            return 127, ""
        return rc, out

    def setup(self):
        missing = [t for t in ("git", "gcc", "g++") + (("gh",) if self.publish and not os.environ.get("PARAS_NO_GH") else ()) if not shutil.which(t)]
        if missing:
            raise SystemExit(f"paras: {' '.join(missing)} missing here; inside the container paras installs them, here install them first")
        if (self.hindawi / ".git").exists() and not os.environ.get("PARAS_NO_UPDATE"):
            self.sh(["git", "-C", self.hindawi, "checkout", "-q", "--", "."], 60)
            self.sh(["git", "-C", self.hindawi, "pull", "-q", "--ff-only"], TIMEOUT["clone"])
        elif not self.hindawi.exists():
            rc, _ = self.sh(["git", "clone", "-q", "--depth", "1", "https://github.com/hindawiai/hindawi2026.10", self.hindawi], TIMEOUT["clone"])
            if rc:
                raise SystemExit("paras: the canonical Hindawi could not be cloned (network?)")
        shutil.copy(DATA / "burp/burp.py", self.burp)                        # the packaged BURP, laid over the canonical one
        for t in (DATA / "burp/glossary").glob("*.tsv"):
            shutil.copy(t, self.hindawi / "lang/hindawi/burp/glossary" / t.name)
        rc, head = self.sh(["git", "-C", self.hindawi, "rev-parse", "--short", "HEAD"], 30, capture=True)
        self.hindawi_rev = head.strip() if rc == 0 else "unknown"
        print(f"   Hindawi {self.hindawi_rev}, with paras's BURP and {len(list((DATA / 'burp/glossary').glob('*.tsv')))} dictionaries", flush=True)

    def languages(self):
        have = sorted({d.name for d in (self.hindawi / "lang/hindawi/languages").iterdir() if (d / "c2h.uhin").exists()} | {"hindi"})
        if self.langspec == "all":
            return have
        want = [l for l in self.langspec.split(",") if l]
        unknown = [l for l in want if l not in have]
        if unknown:
            raise SystemExit(f"paras: unknown languages: {', '.join(unknown)} (paras languages lists them)")
        return want

    def save(self):
        core.write_json(self.state_path, self.state)

    def progress(self, **kw):
        cur = core.read_json(self.progress_path, {}) or {}
        cur.update(kw); cur["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S"); cur["pid"] = os.getpid()
        core.write_json(self.progress_path, cur)

    def paused(self):
        while (core.read_json(self.work / "control.json", {}) or {}).get("pause"):
            self.progress(phase="paused"); time.sleep(2)

    # ---- one package
    def fork(self, p):
        dest = f"{self.org}/{p.name}"
        if os.environ.get("PARAS_NO_GH"):
            return True
        if self.sh(["gh", "repo", "view", dest], TIMEOUT["gh"], capture=True)[0] == 0:
            return True
        if "github.com/" in p.url:
            src = p.url.split("github.com/")[1].removesuffix(".git")
            self.sh(["gh", "repo", "fork", src, "--org", self.org, "--fork-name", p.name, "--clone=false"], TIMEOUT["gh"])
            for _ in range(30):                                              # GitHub makes forks in the background
                if self.sh(["gh", "repo", "view", dest], TIMEOUT["gh"], capture=True)[0] == 0:
                    return True
                time.sleep(6)
            return False
        if self.sh(["gh", "repo", "create", dest, "--public", "--description", f"Mirror of {p.url}, kept by paras; its licence travels with it"], TIMEOUT["gh"])[0]:
            return False
        m = self.tmp / "mirror.git"; shutil.rmtree(m, ignore_errors=True)
        ok = self.sh(["git", "clone", "-q", "--mirror", p.url, m], TIMEOUT["clone"])[0] == 0 and \
            self.sh(["git", "-C", m, "push", "-q", "--mirror", f"{self.fork_base}/{dest}.git"], TIMEOUT["push"])[0] == 0
        shutil.rmtree(m, ignore_errors=True)
        return ok

    def reverse(self, lang, out, scope):
        rv = self.tmp / "rev" / lang; shutil.rmtree(rv, ignore_errors=True)
        rc, _ = self.sh([sys.executable, self.burp, "reverse", out / lang, "--out", rv], TIMEOUT["reverse"], capture=True)
        files = [f for f in scope.rglob("*") if f.is_file() and ".git" not in f.parts]
        same = 0 if rc else sum(1 for f in files if (rv / f.relative_to(scope)).is_file() and filecmp.cmp(f, rv / f.relative_to(scope), shallow=False))
        shutil.rmtree(rv, ignore_errors=True)
        return lang, same, len(files)

    def one(self, p, langs, index, total):
        self.paused()
        name = p.name; t0 = time.time()
        publish = self.publish and p.mode == "ingest"
        print(f"\n\033[1m[{index} of {total}] layer {p.layer} · {name} · {p.url} · scope {p.scope} · {p.mode}\033[0m", flush=True)
        self.progress(package=name, layer=p.layer, index=index, total=total, phase="starting", languages={}, started=time.strftime("%Y-%m-%dT%H:%M:%S"))
        shutil.rmtree(self.tmp, ignore_errors=True); self.tmp.mkdir(parents=True)
        free = shutil.disk_usage(self.work).free
        if free < MIN_FREE:
            return {"status": f"skipped: less than {MIN_FREE / 2**30:g} GB free", "free_gb": round(free / 2**30, 1)}
        if publish and not self.fork(p):
            return {"status": "fork failed"}
        up = self.tmp / "up"
        ref = [] if p.ref == "-" else ["--branch", p.ref]
        self.progress(phase="cloning")
        local = Path(p.url[7:]) if p.url.startswith("file://") else None
        if local and local.is_dir() and not (local / ".git").exists():    # a plain folder: copied, and given a history of one commit
            shutil.copytree(local, up, symlinks=True)
            for cmd in (["git", "-C", up, "init", "-q"], ["git", "-C", up, "add", "-A"], ["git", "-C", up, *AUTHOR, "commit", "-q", "-m", "the folder as given"]):
                if self.sh(cmd, 600)[0]:
                    return {"status": "the folder could not be recorded in git"}
        elif self.sh(["git", "clone", "-q", "--depth", "1", *ref, p.url, up], TIMEOUT["clone"])[0]:
            return {"status": "clone failed"}
        pin = self.sh(["git", "-C", up, "rev-parse", "HEAD"], 30, capture=True)[1].strip()
        scope = up if p.scope == "-" else up / p.scope
        if not scope.is_dir():
            return {"status": f"scope {p.scope} is not in this tree", "pin": pin}
        size = sum(f.stat().st_size for f in scope.rglob("*") if f.is_file() and ".git" not in f.parts)
        use = langs if p.mode == "ingest" else langs[:1]
        need = size * len(use) * 2 + MIN_FREE
        if shutil.disk_usage(self.work).free < need:
            return {"status": f"skipped: needs {need / 2**30:.1f} GB free for {len(use)} languages", "pin": pin}
        out = self.tmp / "out"; quality = {}

        def burp_line(line):                     # BURP reports each language the moment it is done
            if line.startswith("BURP-PROGRESS "):
                d = json.loads(line[len("BURP-PROGRESS "):])
                q = core.Quality(lang=d["lang"], error=d.get("error", ""), **{k: d.get(k, 0) for k in
                                 ("files", "identifiers", "names_missing", "comments_translated", "comments_missing", "keywords_missing", "collisions", "unsupported")})
                quality[q.lang] = q
                self.progress(phase=f"ingesting ({len(quality)} of {len(use)} languages)", languages={k: v.to_dict() for k, v in quality.items()})
                print(f"   {q.lang:18} names {q.names_pct:5.1f}%  comments {q.comments_pct:5.1f}%  keywords missing {q.keywords_missing:3}  "
                      f"collisions {q.collisions:3}{'  ERROR ' + q.error if q.error else ''}", flush=True)
            elif not line.startswith("burp: "):
                print("     " + line, flush=True)
        tr = "glossary,llm" if os.environ.get("HINDAWI_LLM_URL") else "glossary"
        self.progress(phase=f"ingesting (0 of {len(use)} languages)")
        rc, _ = self.sh([sys.executable, self.burp, "ingest", scope, "--langs", ",".join(use), "--out", out, "--translators", tr,
                         "--jobs", self.jobs], TIMEOUT["burp"], stream=burp_line)
        done = [l for l in use if l in quality and not quality[l].error and (out / l).is_dir()]
        if not done:
            return {"status": "burp failed (no language finished)", "pin": pin, "rc": rc}
        rep = self.rep / name; rep.mkdir(parents=True, exist_ok=True)
        for f in ("GAPS.md", "GAPS.json"):
            if (out / f).exists():
                shutil.copy(out / f, rep / f)
        self.progress(phase="converting back")
        with ThreadPoolExecutor(max_workers=self.jobs) as pool:
            for lang, same, n in pool.map(lambda l: self.reverse(l, out, scope), done):
                quality[lang].exact, quality[lang].total = same, n
                self.progress(languages={k: v.to_dict() for k, v in quality.items()})
        exact = [l for l in done if quality[l].exact == quality[l].total]
        print(f"   {len(exact)} of {len(done)} languages convert back exactly", flush=True)
        gaps = core.read_json(out / "GAPS.json", {}) or {}
        result = {"status": "ingested", "pin": pin, "languages": len(done), "exact": len(exact), "hindawi": self.hindawi_rev,
                  "burp_sha256": __import__("hashlib").sha256((DATA / "burp/burp.py").read_bytes()).hexdigest()[:16],
                  "quality": {k: v.to_dict() for k, v in quality.items()},
                  "unsupported": gaps.get("files_in_languages_burp_cannot_read", {}), "seconds": int(time.time() - t0)}
        self.report(p, pin, quality, rep, out, gaps)
        if publish:
            result["status"] = self.publish_branches(p, up, scope, out, pin, done if self.allow_inexact else exact, rep)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return result

    def report(self, p, pin, quality, rep, out, gaps):
        """REPORT.md: what was done, what each measure means, and for every gap what to do about it and where."""
        from . import report
        (rep / "REPORT.md").write_text(report.render(p, pin, quality, out, gaps, f"the canonical Hindawi 2026.10 ({self.hindawi_rev}), with paras's BURP"),
                                       encoding="utf-8")

    def publish_branches(self, p, up, scope, out, pin, langs, rep):
        if not langs:
            return "not published: no language converts back exactly"
        fork = f"{self.fork_base}/{self.org}/{p.name}.git"
        self.sh(["git", "-C", up, "remote", "add", "fork", fork], 30)
        rel = "." if scope == up else p.scope
        self.progress(phase=f"committing {len(langs)} language branches")
        for l in langs:
            if self.sh(["git", "-C", up, "checkout", "-q", "-B", f"lang/{l}", pin], 300)[0]:
                return f"branch lang/{l} could not be made"
            shutil.copytree(out / l, scope, dirs_exist_ok=True, symlinks=True)
            self.sh(["git", "-C", up, "add", "-A", rel], 600)
            self.sh(["git", "-C", up, *AUTHOR, "commit", "-q", "--allow-empty", "-m", f"BURP {l}: {p.name} at {pin[:12]}, {rel} ingested"], 600)
        self.progress(phase="pushing")
        refs = "refs/heads/lang/*:refs/heads/lang/*"
        if self.sh(["git", "-C", up, "push", "-q", "-f", "fork", refs], TIMEOUT["push"])[0]:
            print("   the remote lacks the upstream history: fetching it, then pushing again", flush=True)
            self.sh(["git", "-C", up, "fetch", "-q", "--unshallow", "origin"], TIMEOUT["clone"])
            if self.sh(["git", "-C", up, "push", "-q", "-f", "fork", refs], TIMEOUT["push"])[0]:
                return "push failed"
        # the remote must hold exactly what was pushed
        rc, remote = self.sh(["git", "-C", up, "ls-remote", "fork", "refs/heads/lang/*"], 300, capture=True)
        held = {line.split()[1].removeprefix("refs/heads/"): line.split()[0] for line in remote.splitlines() if line.strip()}
        wrong = [l for l in langs if held.get(f"lang/{l}") != self.sh(["git", "-C", up, "rev-parse", f"lang/{l}"], 30, capture=True)[1].strip()]
        if rc or wrong:
            return f"pushed, but the remote does not match for {len(wrong)} branches: {' '.join(wrong[:5])}"
        self.sh(["git", "-C", up, "checkout", "-q", "--orphan", "paras"], 300)
        self.sh(["git", "-C", up, "rm", "-rqf", "."], 600)
        for f in ("REPORT.md", "GAPS.md", "GAPS.json"):
            if (rep / f).exists():
                shutil.copy(rep / f, up / ("README.md" if f == "REPORT.md" else f))
        self.sh(["git", "-C", up, "add", "-A"], 60)
        self.sh(["git", "-C", up, *AUTHOR, "commit", "-q", "-m", "paras: the report and what is still missing"], 60)
        if self.sh(["git", "-C", up, "push", "-q", "-f", "fork", "paras"], TIMEOUT["push"])[0]:
            return "language branches pushed and verified; the paras branch failed"
        if not os.environ.get("PARAS_NO_GH"):
            self.sh(["gh", "repo", "edit", f"{self.org}/{p.name}", "--default-branch", "paras"], TIMEOUT["gh"])
        return "published"

    def run(self, packages, redo=False):
        with core.Lock(self.work):
            self.setup()
            langs = self.languages()
            print(f"\033[1mparas: {len(packages)} packages × {len(langs)} languages · {self.jobs} cores · publish: "
                  f"{'yes, to ' + self.org if self.publish else 'no'}\033[0m", flush=True)
            self.events(step="run", status="start", packages=len(packages), languages=len(langs), publish=self.publish)

            def stop(sig, frame):
                self.progress(phase="interrupted"); self.events(step="run", status="interrupted", signal=sig); raise SystemExit(130)
            signal.signal(signal.SIGTERM, stop)
            for i, p in enumerate(packages, 1):
                st = self.state.get(p.name, {})
                if not redo and st.get("languages") and (st.get("status") == "published" or (st.get("status") == "ingested" and not self.publish)):
                    print(f"\n── {p.name}: {st['status']} in an earlier run, skipped", flush=True); continue
                try:
                    self.state[p.name] = self.one(p, langs, i, len(packages))
                except SystemExit:
                    raise
                except Exception as e:                                         # one package failing never stops the run
                    self.state[p.name] = {"status": f"error: {type(e).__name__}: {e}"}
                self.save(); self.events(step="package", name=p.name, status=self.state[p.name].get("status"))
                print(f"   → {self.state[p.name].get('status')}", flush=True)
            self.progress(phase="finished")
            self.summary(packages)

    def summary(self, packages):
        lines = ["# paras: where every package stands", "", "| Package | Layer | Status | Pinned at | Languages | Exact | Seconds |", "|---|---|---|---|---|---|---|"]
        for p in packages:
            s = self.state.get(p.name, {})
            lines.append(f"| {p.name} | {p.layer} | {s.get('status', 'not run')} | {s.get('pin', '')[:12]} | {s.get('languages', '')} | {s.get('exact', '')} | {s.get('seconds', '')} |")
        (self.work / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nSummary: {self.work / 'SUMMARY.md'} · what is missing: {self.rep}/<package>/GAPS.md", flush=True)


def package_for(target):
    """Any repository or folder named on the command line, as a package of its own."""
    t = target.rstrip("/")
    name = Path(t).name.removesuffix(".git") if not t.startswith("https://") else t.split("/")[-1].removesuffix(".git")
    url = t if t.startswith("https://") or t.startswith("file://") else "file://" + str(Path(t).resolve())
    return core.Package("99-target", name, url, "-", "-", "ingest")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="paras-runner")
    ap.add_argument("--work", default=os.environ.get("PARAS_WORK", "/work")); ap.add_argument("--hindawi")
    ap.add_argument("--target"); ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--only"); ap.add_argument("--from", dest="start"); ap.add_argument("--langs", default="all")
    ap.add_argument("--org", default="hmnsq"); ap.add_argument("--jobs", type=int); ap.add_argument("--redo", action="store_true")
    ap.add_argument("--allow-inexact", action="store_true")
    a = ap.parse_args(argv)
    publish = bool(os.environ.get("PARAS_CONSENT"))
    if a.target:
        pk = package_for(a.target)
        packages = [core.Package(pk.layer, pk.name, pk.url, pk.ref, pk.scope, "report" if a.report_only else "ingest")]
    else:
        packages = core.parse_manifest((DATA / "stack.tsv").read_text(encoding="utf-8"))
        if a.only:
            want = set(a.only.split(",")); unknown = want - {p.name for p in packages}
            if unknown:
                raise SystemExit(f"paras: not in the stack: {', '.join(sorted(unknown))}")
            packages = [p for p in packages if p.name in want]
        if a.start:
            names = [p.name for p in packages]
            if a.start not in names:
                raise SystemExit(f"paras: {a.start} is not in the stack")
            packages = packages[names.index(a.start):]
    Run(a.work, a.hindawi, a.org, a.langs, a.jobs, publish and not a.report_only, a.allow_inexact).run(packages, a.redo)


if __name__ == "__main__":
    main()
