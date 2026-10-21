"""The whole path on a small project: a folder and a Git repository, ingested into three languages, checked, published to a
local repository standing in for GitHub, and the remote verified. Needs a Hindawi checkout: PARAS_TEST_HINDAWI=/path/to/it."""
import json, os, subprocess, sys, pytest
from pathlib import Path

H = os.environ.get("PARAS_TEST_HINDAWI")
pytestmark = pytest.mark.skipif(not H, reason="PARAS_TEST_HINDAWI is not set")
ROOT = Path(__file__).resolve().parents[1]
C = '#include <stdio.h>\n/* binary search in a sorted array */\nint binary_search(int values[], int count, int key) {\n  int low = 0, high = count - 1;\n' \
    '  while (low <= high) { int middle = low + (high - low) / 2;\n    if (values[middle] == key) return middle;\n' \
    '    if (values[middle] < key) low = middle + 1; else high = middle - 1; }\n  return -1;\n}\nint main(void) {\n' \
    '  int values[] = {2, 5, 8, 12, 16};\n  printf("%d\\n", binary_search(values, 5, 8));\n  return 0;\n}\n'


def run(work, *args, **env):
    e = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PARAS_NO_UPDATE="1", PARAS_MIN_FREE_GB="0", **env)
    return subprocess.run([sys.executable, "-m", "paras_ilm.runner", "--work", str(work), "--hindawi", H, "--langs", "urdu,tamil,hindi", *args],
                          capture_output=True, text=True, env=e)


def project(tmp, git):
    p = tmp / "demo"; p.mkdir(); (p / "search.c").write_text(C); (p / "Makefile").write_text("search: search.c\n\tcc -o search search.c\n")
    if git:
        for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
            subprocess.run(["git", "-C", str(p), *c], check=True)
    return p


def test_a_folder_is_ingested_and_converts_back(tmp_path):
    p = project(tmp_path, git=False); work = tmp_path / "work"
    r = run(work, "--target", str(p))
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    s = json.loads((work / "state.json").read_text())["demo"]
    assert s["status"] == "ingested" and s["languages"] == 3 and s["exact"] == 3, s
    assert s["quality"]["urdu"]["names_pct"] > 50 and s["quality"]["urdu"]["round_trip"] == "exact"
    assert (work / "reports/demo/REPORT.md").exists() and (work / "reports/demo/GAPS.md").exists()
    assert json.loads((work / "progress.json").read_text())["phase"] == "finished"
    assert not (work / "paras.lock").exists() and not (work / "tmp").exists()
    assert any(json.loads(l).get("step") == "package" for l in (work / "events.jsonl").read_text().splitlines())
    again = run(work, "--target", str(p))
    assert "in an earlier run, skipped" in again.stdout


def test_publishing_pushes_exact_languages_and_verifies_the_remote(tmp_path):
    p = project(tmp_path, git=True)
    forks = tmp_path / "forks"; (forks / "org").mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(p), str(forks / "org/demo.git")], check=True)
    work = tmp_path / "work"
    r = run(work, "--target", str(p), "--org", "org", PARAS_CONSENT="PUSH test", PARAS_NO_GH="1", PARAS_FORK_BASE=f"file://{forks}")
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert json.loads((work / "state.json").read_text())["demo"]["status"] == "published"
    heads = subprocess.run(["git", "-C", str(forks / "org/demo.git"), "branch"], capture_output=True, text=True).stdout
    for b in ("lang/urdu", "lang/tamil", "lang/hindi", "paras"):
        assert b in heads
    urdu = subprocess.run(["git", "-C", str(forks / "org/demo.git"), "show", "lang/urdu:search.c"], capture_output=True, text=True).stdout
    assert "ثنائی_تلاش" in urdu and "binary_search" not in urdu
