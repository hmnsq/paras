import json, os, pytest
from pathlib import Path
from paras_ilm import core

GOOD = "1-firmware\tseabios\thttps://github.com/coreboot/seabios\t-\tsrc\tingest\n"


def test_packaged_stack_parses():
    stack = core.parse_manifest((Path(core.__file__).parent / "data/stack.tsv").read_text(encoding="utf-8"))
    assert len(stack) > 50 and stack[0].layer.startswith("0-")
    assert len({p.name for p in stack}) == len(stack)


@pytest.mark.parametrize("line,err", [
    ("1-firmware\tseabios\thttps://x\t-\tsrc\n", "six tab-separated"),
    ("firmware\tseabios\thttps://x\t-\tsrc\tingest\n", "layer"),
    ("1-firmware\tsea bios\thttps://x\t-\tsrc\tingest\n", "safe repository name"),
    ("1-firmware\tseabios\tftp://x\t-\tsrc\tingest\n", "must be https"),
    ("1-firmware\tseabios\thttps://x\t-\t../etc\tingest\n", "stay inside"),
    ("1-firmware\tseabios\thttps://x\t-\t/etc\tingest\n", "stay inside"),
    ("1-firmware\tseabios\thttps://x\tv1;rm\tsrc\tingest\n", "plain branch"),
    ("1-firmware\tseabios\thttps://x\t-\tsrc\tbuild\n", "mode"),
    (GOOD + GOOD, "appears twice"),
    ("# only a comment\n", "no packages"),
])
def test_manifest_faults_are_named(line, err):
    with pytest.raises(core.ManifestError, match=err):
        core.parse_manifest(line)


def test_write_json_is_atomic(tmp_path):
    p = tmp_path / "s.json"; core.write_json(p, {"a": 1}); core.write_json(p, {"a": 2})
    assert json.loads(p.read_text()) == {"a": 2}
    assert [x.name for x in tmp_path.iterdir()] == ["s.json"]          # no temporary file left behind


def test_read_json_refuses_a_damaged_file(tmp_path):
    p = tmp_path / "s.json"; p.write_text("{half")
    with pytest.raises(ValueError, match="not valid JSON"):
        core.read_json(p)
    assert core.read_json(tmp_path / "absent.json", {"x": 1}) == {"x": 1}


def test_lock_refuses_a_live_run_and_takes_over_a_stale_one(tmp_path):
    with core.Lock(tmp_path):
        with pytest.raises(RuntimeError, match="another paras run"):
            core.Lock(tmp_path).__enter__()
    import socket
    (tmp_path / "paras.lock").write_text(json.dumps({"pid": 999999, "host": socket.gethostname(), "since": "x"}))
    with core.Lock(tmp_path):
        assert json.loads((tmp_path / "paras.lock").read_text())["pid"] == os.getpid()
    assert not (tmp_path / "paras.lock").exists()


def test_quality_measures():
    q = core.Quality("urdu", identifiers=200, names_missing=50, comments_translated=3, comments_missing=1, exact=10, total=10)
    assert q.names_pct == 75.0 and q.comments_pct == 75.0 and q.round_trip == "exact"
    assert q.score == round((75 + 75 + 100) / 3, 1)
    assert core.Quality("x", exact=9, total=10).round_trip == "9/10"
    assert core.Quality("x", error="boom").score == 0.0
    assert core.Quality("x").round_trip == "pending" and core.Quality("x").names_pct == 100.0


def test_dictionary_quality(tmp_path):
    (tmp_path / "urdu.tsv").write_text("# urdu: proposed words, for review by its speakers\nkey\tکلید\nvalue\tقدر\n", encoding="utf-8")
    d = core.dictionary_quality(tmp_path, "urdu")
    assert d["entries"] == 2 and d["reviewed"] is False
    assert core.dictionary_quality(tmp_path, "none")["entries"] == 0


def test_events_are_appended(tmp_path):
    e = core.Events(tmp_path); e(step="a"); e(step="b")
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert [json.loads(l)["step"] for l in lines] == ["a", "b"]
