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


def test_build_v1_export_cmd_keeps_ntsc_rational():
    # 旧実装は 59.94 を 60 へ丸め、NLE のフレーム格子（60000/1001）とずれていた。
    from autoeditor import build_v1_export_cmd
    cmd = build_v1_export_cmd("auto-editor", "in.mp4", 0.2, 4.0, "out.json", 59.94005994)
    assert cmd[cmd.index("-tb") + 1] == "60000/1001"


def test_format_timebase():
    from fractions import Fraction

    from autoeditor import format_timebase
    assert format_timebase(30) == "30"
    assert format_timebase(30.0) == "30"
    assert format_timebase(29.97002997) == "30000/1001"
    assert format_timebase(23.976023976) == "24000/1001"
    assert format_timebase(Fraction(25, 1)) == "25"


def test_silent_speed_adds_when_inactive_to_all_builders():
    from autoeditor import build_cut_cmd, build_extract_wav_cmd, build_v1_export_cmd
    c1 = build_cut_cmd("ae", "in.mp4", 0.2, 4.0, "premiere", "o.xml", silent_speed=8)
    c2 = build_extract_wav_cmd("ae", "in.mp4", 0.2, 4.0, "o.wav", silent_speed=8)
    c3 = build_v1_export_cmd("ae", "in.mp4", 0.2, 4.0, "o.json", 30, silent_speed=8)
    for cmd in (c1, c2, c3):
        assert cmd[cmd.index("--when-inactive") + 1] == "speed:8"


def test_default_commands_have_no_when_inactive():
    from autoeditor import build_cut_cmd
    assert "--when-inactive" not in build_cut_cmd("ae", "in.mp4", 0.2, 4.0, "resolve", "o.fcpxml")


def test_media_export_omits_export_flag():
    from autoeditor import EXPORT_MEDIA, build_cut_cmd
    cmd = build_cut_cmd("ae", "in.mp4", 0.2, 4.0, EXPORT_MEDIA, "o.mp4")
    assert "--export" not in cmd
    assert cmd[cmd.index("--output") + 1] == "o.mp4"


def test_chunk_builders_take_json_input():
    from autoeditor import build_cut_cmd_from_chunks, build_extract_wav_cmd_from_chunks
    c = build_cut_cmd_from_chunks("ae", "cuts.json", "premiere", "o.xml", tb=30000 / 1001)
    assert c[1] == "cuts.json"
    assert "--margin" not in c and "--edit" not in c
    assert c[c.index("-tb") + 1] == "30000/1001"
    w = build_extract_wav_cmd_from_chunks("ae", "cuts.json", "o.wav")
    assert "-vn" in w and "--mix-audio-streams" in w and "-tb" not in w


def test_is_audio_only():
    from autoeditor import is_audio_only
    assert is_audio_only("talk.WAV") and is_audio_only("a/b.m4a")
    assert not is_audio_only("movie.mp4")


def test_probe_fps_falls_back_to_av(monkeypatch):
    import autoeditor

    class R:
        stdout = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    monkeypatch.setattr(autoeditor, "_probe_fps_av", lambda p: 29.97)
    assert autoeditor.probe_fps("video.mp4") == 29.97



def test_commands_silence_the_progress_bar():
    # 進捗バー（ANSI 制御文字）がログ欄を汚さないよう、全コマンドで --progress none
    from autoeditor import (
        build_cut_cmd,
        build_cut_cmd_from_chunks,
        build_extract_wav_cmd,
        build_extract_wav_cmd_from_chunks,
        build_v1_export_cmd,
    )
    cmds = [
        build_cut_cmd("ae", "i.mp4", 0.2, 4.0, "premiere", "o.xml"),
        build_extract_wav_cmd("ae", "i.mp4", 0.2, 4.0, "o.wav"),
        build_v1_export_cmd("ae", "i.mp4", 0.2, 4.0, "o.json", 30),
        build_cut_cmd_from_chunks("ae", "c.json", "premiere", "o.xml"),
        build_extract_wav_cmd_from_chunks("ae", "c.json", "o.wav"),
    ]
    for c in cmds:
        assert c[c.index("--progress") + 1] == "none"
        assert c[-1] == "--no-open"


def test_audio_render_exts_exclude_encoders_missing_from_the_bundled_binary():
    from autoeditor import AUDIO_RENDER_EXTS
    assert {".wav", ".flac", ".ogg", ".opus"} == set(AUDIO_RENDER_EXTS)
    for missing in (".mp3", ".m4a", ".aac"):
        assert missing not in AUDIO_RENDER_EXTS      # 実測: Could not open encoder


def test_unlicensed_render_limit():
    from autoeditor import exceeds_unlicensed_render_limit
    assert exceeds_unlicensed_render_limit((3840, 2160)) is True
    assert exceeds_unlicensed_render_limit((3200, 1800)) is False       # 上限ちょうどは縮小されない
    assert exceeds_unlicensed_render_limit((1920, 1080)) is False
    assert exceeds_unlicensed_render_limit(None) is False
