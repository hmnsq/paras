import json, os, subprocess, sys, pytest
from pathlib import Path
from paras_ilm import tui, core

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


def paras(*args):
    return subprocess.run([sys.executable, "-m", "paras_ilm", *args], capture_output=True, text=True, env=ENV)


@pytest.mark.parametrize("spec,cores", [("0", {0}), ("0-0", {0})])
def test_parse_cpus(spec, cores):
    assert tui.parse_cpus(spec) == cores


@pytest.mark.parametrize("spec", ["", "a", "3-1", "0-", "99999"])
def test_parse_cpus_refuses(spec):
    with pytest.raises(ValueError):
        tui.parse_cpus(spec)


def test_snapshot_shows_every_language_with_its_quality(tmp_path):
    q = core.Quality("urdu", files=3, identifiers=10, names_missing=2, exact=3, total=3).to_dict()
    core.write_json(tmp_path / "progress.json", {"package": "xv6", "layer": "2-kernel", "phase": "converting back", "index": 1, "total": 70,
                                                 "languages": {"urdu": q, "tamil": core.Quality("tamil", error="boom").to_dict()}})
    core.write_json(tmp_path / "state.json", {"neorv32": {"status": "published", "languages": 76}})
    text = "\n".join(t for t, _ in tui.snapshot(tmp_path, {0: 12.0}))
    assert "xv6" in text and "urdu" in text and "80.0%" in text and "exact" in text and "error" in text and "published 1" in text
    colours = dict((t.split()[0], c) for t, c in tui.snapshot(tmp_path) if t.startswith(("urdu", "tamil")))
    assert colours["tamil"] == "bad"


def test_cli_help_version_list_and_refusals(tmp_path):
    assert "paras ingest" in paras("--help").stdout
    assert paras("--version").stdout.strip().startswith("paras 2026.")
    assert "seabios" in paras("list").stdout
    assert "I do not know" in paras("frobnicate", "--work", str(tmp_path)).stderr
    assert "needs a repository" in paras("ingest", "--work", str(tmp_path)).stderr
    assert "cores" in paras("ingest", "x", "--cpus", "0-99999", "--work", str(tmp_path)).stderr
    assert "neither a Git URL nor a folder" in paras("ingest", str(tmp_path / "absent"), "--local", "--work", str(tmp_path)).stderr
    r = paras("top", "--once", "--work", str(tmp_path))
    assert r.returncode == 0 and "Stack [" in r.stdout
