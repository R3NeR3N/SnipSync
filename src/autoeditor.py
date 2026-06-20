"""auto-editor command builders.

Pure functions -> unit-testable without spawning processes. The main cut and
the subtitle WAV extraction MUST share margin/threshold or subtitle timecodes
drift from the timeline (PITFALLS P-2 / CONTEXT.md §1).
"""


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


def probe_fps(path):
    """ffprobe で動画の r_frame_rate を読み fps(float) を返す。失敗時 None。

    v1 export の frame->秒 変換 timebase に使う（CFR 前提）。
    """
    import subprocess
    from pathlib import Path
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(Path(path).resolve())],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        out = (result.stdout or "").strip()
        if not out:
            return None
        if "/" in out:
            num, den = out.split("/")
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        return float(out)
    except Exception:
        return None

