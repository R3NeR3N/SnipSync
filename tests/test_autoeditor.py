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
