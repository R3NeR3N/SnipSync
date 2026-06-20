import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import subprocess

from autoeditor import probe_fps


def test_probe_fps_parses_rational(monkeypatch):
    class R:
        stdout = "60/1\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert probe_fps("video.mp4") == 60.0


def test_probe_fps_parses_integer(monkeypatch):
    class R:
        stdout = "30\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert probe_fps("video.mp4") == 30.0


def test_probe_fps_empty_returns_none(monkeypatch):
    class R:
        stdout = "\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert probe_fps("video.mp4") is None


def test_probe_fps_zero_denominator_returns_none(monkeypatch):
    class R:
        stdout = "0/0\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert probe_fps("video.mp4") is None


def test_probe_fps_exception_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("ffprobe missing")
    monkeypatch.setattr(subprocess, "run", boom)
    assert probe_fps("video.mp4") is None


def test_build_v1_export_cmd_shape():
    from autoeditor import build_v1_export_cmd
    cmd = build_v1_export_cmd("auto-editor", "in.mp4", 0.2, 4.0, "out.json", 60.0)
    assert cmd[0] == "auto-editor"
    assert "--export" in cmd and cmd[cmd.index("--export") + 1] == "v1"
    assert "-tb" in cmd and cmd[cmd.index("-tb") + 1] == "60"
    assert "--margin" in cmd and cmd[cmd.index("--margin") + 1] == "0.200s"
    assert "--edit" in cmd and cmd[cmd.index("--edit") + 1] == "audio:threshold=4.0%"
    assert "--no-open" in cmd
    out_i = cmd.index("--output") + 1
    assert cmd[out_i].endswith("out.json")


def test_build_v1_export_cmd_tb_rounds_to_int():
    from autoeditor import build_v1_export_cmd
    cmd = build_v1_export_cmd("auto-editor", "in.mp4", 0.2, 4.0, "out.json", 59.94)
    assert cmd[cmd.index("-tb") + 1] == "60"

