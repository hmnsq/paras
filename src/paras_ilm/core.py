"""core: the parts everything else stands on. Manifest validation, atomic state, a single-instance lock, an append-only
event log, and the quality measures. Each function either does exactly what it says or raises with the reason.
© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI. Licensed under the MIT licence (see LICENSE)."""
import json, os, re, socket, tempfile, time
from dataclasses import dataclass, asdict
from pathlib import Path

LAYER = re.compile(r"^\d{1,2}-[a-z][a-z0-9-]*$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
MODES = ("ingest", "report")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Package:
    layer: str
    name: str
    url: str
    ref: str
    scope: str
    mode: str


def parse_manifest(text, source="stack.tsv"):
    """One package per line: layer, name, upstream, ref ('-' for the default branch), scope ('-' for the whole tree), mode.
    Every line is checked; the first fault stops parsing with its line number, so a bad manifest is never half-used."""
    out, seen = [], set()
    for no, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        f = line.rstrip("\n").split("\t")
        if len(f) != 6:
            raise ManifestError(f"{source}:{no}: six tab-separated fields are needed, found {len(f)}")
        layer, name, url, ref, scope, mode = (x.strip() for x in f)
        if not LAYER.match(layer):
            raise ManifestError(f"{source}:{no}: layer {layer!r} is not of the form 3-toolchain")
        if not NAME.match(name):
            raise ManifestError(f"{source}:{no}: name {name!r} is not a safe repository name")
        if name in seen:
            raise ManifestError(f"{source}:{no}: {name} appears twice")
        if not (url.startswith("https://") or url.startswith("file://") or url.startswith("/")):
            raise ManifestError(f"{source}:{no}: upstream {url!r} must be https://, file:// or an absolute path")
        if scope != "-" and (scope.startswith("/") or ".." in Path(scope).parts):
            raise ManifestError(f"{source}:{no}: scope {scope!r} must stay inside the repository")
        if ref != "-" and not re.match(r"^[A-Za-z0-9._/+-]{1,200}$", ref):
            raise ManifestError(f"{source}:{no}: ref {ref!r} is not a plain branch or tag name")
        if mode not in MODES:
            raise ManifestError(f"{source}:{no}: mode {mode!r} must be one of {', '.join(MODES)}")
        seen.add(name)
        out.append(Package(layer, name, url, ref, scope, mode))
    if not out:
        raise ManifestError(f"{source}: no packages")
    return out


def write_json(path, data):
    """Atomic: written to a temporary file beside it, flushed to disk, then renamed over the old one. A reader never sees
    half a file, and a crash leaves either the old or the new version."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True); raise


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON ({e}); it was not written by paras, or a disk failed") from e


class Lock:
    """One run at a time per work folder. A lock whose process is gone (the machine restarted, the run was killed) is
    recognised as stale and taken over; a live one refuses with who holds it."""
    def __init__(self, work):
        self.path = Path(work) / "paras.lock"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                held = read_json(self.path, {}) or {}
                pid, host = held.get("pid"), held.get("host")
                if host == socket.gethostname() and pid and not Path(f"/proc/{pid}").exists():
                    self.path.unlink(missing_ok=True); continue          # stale: its process is gone
                raise RuntimeError(f"another paras run holds {self.path} (pid {pid} on {host}, since {held.get('since')})")
            with os.fdopen(fd, "w") as f:
                json.dump({"pid": os.getpid(), "host": socket.gethostname(), "since": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
            return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


class Events:
    """An append-only log, one JSON object per line, flushed as written: what happened, when, how long it took."""
    def __init__(self, work):
        self.path = Path(work) / "events.jsonl"; self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, **kw):
        kw = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **kw}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(kw, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())


@dataclass
class Quality:
    """How well one language's ingestion went, as measured by BURP while it ran, and by the round trip after."""
    lang: str
    files: int = 0
    identifiers: int = 0
    names_missing: int = 0
    comments_translated: int = 0
    comments_missing: int = 0
    keywords_missing: int = 0
    collisions: int = 0
    unsupported: int = 0
    exact: int = -1          # files converting back exactly; -1 until checked
    total: int = -1
    error: str = ""

    @property
    def names_pct(self):
        return 100.0 if not self.identifiers else 100.0 * max(0, self.identifiers - self.names_missing) / self.identifiers

    @property
    def comments_pct(self):
        n = self.comments_translated + self.comments_missing
        return 100.0 if not n else 100.0 * self.comments_translated / n

    @property
    def round_trip(self):
        return "pending" if self.total < 0 else ("exact" if self.exact == self.total else f"{self.exact}/{self.total}")

    @property
    def score(self):
        """One number to sort by, defined openly: the mean of names translated, comments translated, and the round trip
        (100 when exact, 0 otherwise). It never stands alone: the parts are always shown beside it."""
        if self.error:
            return 0.0
        rt = 100.0 if self.total >= 0 and self.exact == self.total else 0.0
        return round((self.names_pct + self.comments_pct + rt) / 3, 1)

    def to_dict(self):
        d = asdict(self); d.update(names_pct=round(self.names_pct, 1), comments_pct=round(self.comments_pct, 1), score=self.score,
                                   round_trip=self.round_trip); return d


def dictionary_quality(glossary_dir, lang):
    """The dictionary BURP used for a language: how many entries, and whether its speakers have reviewed it yet."""
    p = Path(glossary_dir) / f"{lang}.tsv"
    if not p.exists():
        return {"entries": 0, "reviewed": False, "note": "no dictionary"}
    lines = p.read_text(encoding="utf-8").splitlines()
    entries = sum(1 for l in lines if "\t" in l and not l.startswith("#"))
    head = lines[0] if lines else ""
    return {"entries": entries, "reviewed": "reviewed" in head.lower() and "unreviewed" not in head.lower(),
            "note": "proposed words, for review by its speakers" if "proposed" in head.lower() else ""}
