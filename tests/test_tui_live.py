"""The live display, driven in a real pseudo-terminal: it draws the language table, sorts on s, and leaves on q."""
import os, pty, re, select, struct, subprocess, sys, time, fcntl, termios, pytest
from pathlib import Path
from paras_ilm import core

ROOT = Path(__file__).resolve().parents[1]


def test_top_draws_sorts_and_quits(tmp_path):
    core.write_json(tmp_path / "progress.json", {"package": "xv6", "layer": "2-kernel", "phase": "converting back", "index": 1, "total": 70,
                                                 "languages": {"urdu": core.Quality("urdu", identifiers=10, exact=1, total=1).to_dict()}})
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(PYTHONPATH=str(ROOT / "src"), TERM="xterm-256color")
        os.execv(sys.executable, [sys.executable, "-m", "paras_ilm", "top", "--work", str(tmp_path)])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))
    out, t0, sent = b"", time.time(), []
    while time.time() - t0 < 8:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                out += os.read(fd, 65536)
            except OSError:
                break
        text = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", out)
        if b"LANGUAGE" in text and "s" not in sent:
            os.write(fd, b"s"); sent.append("s")
        elif b"sorted by" in text and "q" not in sent:
            os.write(fd, b"q"); sent.append("q")
    _, status = os.waitpid(pid, 0)
    text = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", out)
    assert b"Traceback" not in text, text[-800:]
    assert b"LANGUAGE" in text and b"urdu" in text and b"sorted by" in text
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
