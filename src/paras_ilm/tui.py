"""tui: paras top. A live display in the manner of htop, read from the work folder while a run goes on.
© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI. Licensed under the MIT licence (see LICENSE)."""
import os, re, shutil, subprocess, time
from pathlib import Path
from . import core, __version__

DATA = Path(__file__).parent / "data"
CONTAINER = "paras-ilm"


def cpu_times():
    out = {}
    for line in Path("/proc/stat").read_text().splitlines():
        if re.match(r"^cpu\d+ ", line):
            f = line.split(); v = list(map(int, f[1:9]))
            out[int(f[0][3:])] = (sum(v), v[3] + v[4])
    return out


def cpu_load(prev, cur):
    return {c: (0.0 if (cur[c][0] - prev[c][0]) <= 0 else 100.0 * (1 - (cur[c][1] - prev[c][1]) / (cur[c][0] - prev[c][0]))) for c in cur if c in prev}


def mem():
    m = {l.split(":")[0]: int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines() if l.split()[1:]}
    total, avail = m.get("MemTotal", 1), m.get("MemAvailable", 0)
    return 100.0 * (total - avail) / total, total / 1048576


def parse_cpus(spec):
    """'0-5', '0,2,4', '0-3,8-11' into a set of cores; anything else is refused with the reason."""
    if not re.fullmatch(r"\d+(-\d+)?(,\d+(-\d+)?)*", spec or ""):
        raise ValueError(f"{spec!r}: cores are written like 0-5 or 0,2,4")
    cores = set()
    for part in spec.split(","):
        a, _, b = part.partition("-"); a = int(a); b = int(b) if b else a
        if b < a:
            raise ValueError(f"{part}: the range runs backwards")
        cores |= set(range(a, b + 1))
    n = os.cpu_count() or 1
    if max(cores) >= n:
        raise ValueError(f"this machine has cores 0 to {n - 1}")
    return cores


def container_cpus():
    if not shutil.which("docker"):
        return None
    r = subprocess.run(["docker", "inspect", "-f", "{{.HostConfig.CpusetCpus}}", CONTAINER], capture_output=True, text=True)
    return (r.stdout.strip() or "all") if r.returncode == 0 else None


def set_cores(spec, work):
    """Move the work onto these cores: the container's cpuset, or, without a container, the runner and its children."""
    cores = parse_cpus(spec)
    if container_cpus() is not None:
        r = subprocess.run(["docker", "update", "--cpuset-cpus", spec, CONTAINER], capture_output=True, text=True)
        return f"the container now runs on cores {spec}" if r.returncode == 0 else f"docker update failed: {r.stderr.strip()[:80]}"
    pid = (core.read_json(Path(work) / "progress.json", {}) or {}).get("pid")
    if not pid or not Path(f"/proc/{pid}").exists():
        return "no run is going on here"
    moved = 0
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                stat = (d / "stat").read_text().split(")")[-1].split()
                if int(d.name) == pid or int(stat[1]) == pid:
                    os.sched_setaffinity(int(d.name), cores); moved += 1
            except (OSError, ValueError, IndexError):
                pass
    return f"{moved} processes now run on cores {spec}"


def snapshot(work, load=None, cols=120, sort="score"):
    """The display as lines of (text, colour), so the same content draws on a terminal or prints plainly."""
    work = Path(work)
    prog = core.read_json(work / "progress.json", {}) or {}
    state = core.read_json(work / "state.json", {}) or {}
    stack = core.parse_manifest((DATA / "stack.tsv").read_text(encoding="utf-8"))
    L = []
    L.append((f"paras {__version__} · {prog.get('package', 'idle')} ({prog.get('layer', '-')}) · {prog.get('phase', 'no run')} · "
              f"package {prog.get('index', 0)} of {prog.get('total', 0)} · updated {prog.get('updated', '-')}", "title"))
    if load:
        cur = container_cpus()
        used = parse_cpus(cur) if cur and cur != "all" else set(load)
        cells = []
        for c in sorted(load):
            n = int(load[c] / 10)
            cells.append((f"{c:>2}{'*' if c in used else ' '}[{'|' * n}{' ' * (10 - n)}{load[c]:4.0f}%]", "hot" if load[c] > 80 else "ok"))
        per = max(1, cols // 22)
        for i in range(0, len(cells), per):
            L.append(("  ".join(t for t, _ in cells[i:i + per]), "bar"))
        pct, gb = mem()
        L.append((f"Mem[{'|' * int(pct / 5)}{' ' * (20 - int(pct / 5))}{pct:4.0f}% of {gb:.1f} GB]   * marks the cores the work may use", "bar"))
    pub = sum(1 for s in state.values() if s.get("status") == "published")
    ing = sum(1 for s in state.values() if s.get("status") == "ingested")
    bad = sum(1 for s in state.values() if s.get("status") not in ("published", "ingested", None))
    done = pub + ing + bad; width = 40; filled = int(width * done / max(1, len(stack)))
    L.append((f"Stack [{'#' * filled}{'.' * (width - filled)}] {done} of {len(stack)} · published {pub} · ingested {ing} · failed or skipped {bad}", "head"))
    langs = prog.get("languages", {})
    L.append((f"{'LANGUAGE':18} {'STATE':8} {'NAMES':>7} {'COMMENTS':>9} {'KW-MISS':>8} {'COLL':>5} {'ROUND TRIP':>11} {'SCORE':>6}  DICTIONARY", "head"))
    rows = sorted(langs.values(), key=(lambda q: (q.get("score", 0), q.get("lang", ""))) if sort == "score" else (lambda q: q.get("lang", "")))
    for q in rows:
        d = core.dictionary_quality(DATA / "burp/glossary", q["lang"])
        dq = f"{d['entries']} entries, {'reviewed' if d['reviewed'] else 'proposed'}" if d["entries"] else "none yet"
        st = "error" if q.get("error") else ("done" if q.get("round_trip") not in ("pending", None) else "ingested")
        colour = "bad" if q.get("error") or q.get("score", 0) < 50 else ("warn" if q.get("score", 0) < 90 else "good")
        L.append((f"{q['lang']:18} {st:8} {q.get('names_pct', 0):6.1f}% {q.get('comments_pct', 0):8.1f}% {q.get('keywords_missing', 0):8} "
                  f"{q.get('collisions', 0):5} {q.get('round_trip', 'pending'):>11} {q.get('score', 0):6.1f}  {dq}", colour))
    if not rows:
        L.append(("(no language measured yet for this package)", "dim"))
    pending = [p.name for p in stack if p.name not in state][:8]
    L.append(("Pending: " + (", ".join(pending) + (" …" if len(stack) - len(state) > 8 else "") if pending else "nothing"), "dim"))
    L.append(("q quit · p pause or resume · c move to cores · s sort · ↑↓ scroll", "foot"))
    return L


def once(work):
    a = cpu_times(); time.sleep(0.5); b = cpu_times()
    for text, _ in snapshot(work, cpu_load(a, b), shutil.get_terminal_size((120, 40)).columns):
        print(text)


def run(work):
    import curses

    def ui(scr):
        curses.curs_set(0); scr.nodelay(True); curses.start_color(); curses.use_default_colors()
        pal = {"title": (curses.COLOR_CYAN, curses.A_BOLD), "bar": (curses.COLOR_GREEN, 0), "hot": (curses.COLOR_RED, 0), "ok": (curses.COLOR_GREEN, 0),
               "head": (curses.COLOR_YELLOW, curses.A_BOLD), "good": (curses.COLOR_GREEN, 0), "warn": (curses.COLOR_YELLOW, 0),
               "bad": (curses.COLOR_RED, curses.A_BOLD), "dim": (curses.COLOR_WHITE, curses.A_DIM), "foot": (curses.COLOR_BLACK, curses.A_REVERSE)}
        attr = {}
        for i, (k, (fg, extra)) in enumerate(pal.items(), 1):
            curses.init_pair(i, fg, -1 if k != "foot" else curses.COLOR_CYAN); attr[k] = curses.color_pair(i) | extra
        prev, top, msg, sort = cpu_times(), 0, "", "score"
        while True:
            time.sleep(1); cur = cpu_times(); load = cpu_load(prev, cur); prev = cur
            h, w = scr.getmaxyx(); lines = snapshot(work, load, w, sort)
            scr.erase()
            fixed = [l for l in lines if l[1] in ("title", "bar", "head")][:3 + len(load) // max(1, w // 22) + 2]
            body = lines[len(fixed):-1]
            y = 0
            for text, k in fixed:
                if y < h - 2: scr.addnstr(y, 0, text, w - 1, attr.get(k, 0)); y += 1
            for text, k in body[top:top + max(0, h - y - 2)]:
                scr.addnstr(y, 0, text, w - 1, attr.get(k, 0)); y += 1
            if msg:
                scr.addnstr(h - 2, 0, msg, w - 1, attr["warn"])
            scr.addnstr(h - 1, 0, lines[-1][0].ljust(w - 1), w - 1, attr["foot"])
            scr.refresh()
            ch = scr.getch()
            if ch in (ord("q"), 27):
                return
            if ch == ord("p"):
                c = core.read_json(Path(work) / "control.json", {}) or {}
                c["pause"] = not c.get("pause"); core.write_json(Path(work) / "control.json", c)
                msg = "pausing after the current package" if c["pause"] else "resuming"
            if ch == ord("c"):
                curses.echo(); scr.nodelay(False); scr.addnstr(h - 2, 0, "cores (like 0-5 or 0,2,4): ".ljust(w - 1), w - 1)
                spec = scr.getstr(h - 2, 28, 40).decode().strip(); curses.noecho(); scr.nodelay(True)
                try:
                    msg = set_cores(spec, work)
                except ValueError as e:
                    msg = str(e)
            if ch == ord("s"):
                sort = "lang" if sort == "score" else "score"; msg = f"sorted by {'language' if sort == 'lang' else 'score, weakest first'}"
            if ch == curses.KEY_DOWN:
                top += 1
            if ch == curses.KEY_UP:
                top = max(0, top - 1)
    curses.wrapper(ui)
