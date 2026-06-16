"""Unit tests for pure helpers (no GUI, no subprocess)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from subtitles import format_timestamp
from autoeditor import build_cut_cmd, build_extract_wav_cmd


def test_format_timestamp():
    cases = [
        (0.0, "00:00:00,000"),
        (3661.5, "01:01:01,500"),
        (59.999, "00:00:59,999"),
        (7322.004, "02:02:02,004"),
        (0.0009, "00:00:00,001"),  # rounds, not truncated (truncation -> 000)
    ]
    for seconds, expected in cases:
        assert format_timestamp(seconds) == expected


def test_build_cut_cmd():
    cmd = build_cut_cmd("auto-editor", "in.mp4", 0.2, 4.0, "resolve", "out.fcpxml")
    assert cmd == [
        "auto-editor", "in.mp4",
        "--margin", "0.200s",
        "--edit", "audio:threshold=4.0%",
        "--export", "resolve",
        "--output", "out.fcpxml",
        "--no-open",
    ]


def test_build_extract_wav_cmd():
    cmd = build_extract_wav_cmd("auto-editor", "in.mp4", 0.2, 4.0, "tmp.wav")
    assert cmd == [
        "auto-editor", "in.mp4",
        "--margin", "0.200s",
        "--edit", "audio:threshold=4.0%",
        "-vn", "-sn", "-dn",
        "--mix-audio-streams",
        "--output", "tmp.wav",
        "--no-open",
    ]


def test_cut_and_extract_share_margin_threshold():
    """PITFALLS P-2: cut and subtitle WAV must use identical margin/threshold."""
    cut = build_cut_cmd("ae", "in.mp4", 0.35, 7.5, "premiere", "o.xml")
    wav = build_extract_wav_cmd("ae", "in.mp4", 0.35, 7.5, "t.wav")
    # margin + edit args identical in both
    assert cut[2:6] == wav[2:6]
