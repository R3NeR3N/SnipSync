"""auto-editor command builders.

Pure functions -> unit-testable without spawning processes. The main cut and
the subtitle WAV extraction MUST share margin/threshold or subtitle timecodes
drift from the timeline (PITFALLS P-2 / CONTEXT.md §1).
"""
from pathlib import Path


def build_cut_cmd(ae_path, inp, margin, threshold, export_key, output):
    """auto-editor command: silence cut -> NLE timeline (.fcpxml/.xml)."""
    return [
        str(ae_path), str(inp),
        "--margin", f"{margin:.3f}s",
        "--edit", f"audio:threshold={threshold:.1f}%",
        "--export", export_key,
        "--output", str(output),
        "--no-open",
    ]


def build_extract_wav_cmd(ae_path, inp, margin, threshold, output):
    """auto-editor command: extract cut audio only -> temp WAV for ASR."""
    return [
        str(ae_path), str(inp),
        "--margin", f"{margin:.3f}s",
        "--edit", f"audio:threshold={threshold:.1f}%",
        "-vn", "-sn", "-dn",
        "--mix-audio-streams",
        "--output", str(output),
        "--no-open",
    ]
