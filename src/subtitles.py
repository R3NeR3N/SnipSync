"""Subtitle (.srt) helpers."""
import os
import sys
from pathlib import Path

_cuda_dll_registered = False


def add_cuda_dll_dirs() -> None:
    """Register pip-installed CUDA libs so ctranslate2 can load cuBLAS/cuDNN.

    The GPU libs ship as ``nvidia-*`` wheels under ``site-packages/nvidia/*/bin``
    (kept inside the venv, not on the host) but ctranslate2 does not auto-discover
    them on Windows -> a CUDA WhisperModel fails with ``cublas64_12.dll ... cannot
    be loaded``. Add each ``bin`` dir to the DLL search path AND PATH *before* the
    model is built. No-op off Windows, when the wheels are absent, or if already run.
    """
    global _cuda_dll_registered
    if _cuda_dll_registered or sys.platform != "win32":
        return
    try:
        import nvidia
    except ImportError:
        return
    base = Path(list(nvidia.__path__)[0])
    for sub in base.iterdir():
        bind = sub / "bin"
        if bind.is_dir():
            os.add_dll_directory(str(bind))
            if str(bind) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(bind) + os.pathsep + os.environ.get("PATH", "")
    _cuda_dll_registered = True


def format_timestamp(seconds: float) -> str:
    """Seconds -> SRT timestamp ``HH:MM:SS,mmm``.

    Rounds to whole milliseconds first to avoid float truncation errors.
    """
    total_ms = int(round(seconds * 1000))
    hrs = total_ms // 3600000
    mins = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    ms = total_ms % 1000
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def cuda_available() -> bool:
    """Check if ctranslate2 can find at least one CUDA device. Return False on error."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def resolve_device(use_gpu: bool) -> tuple[str, str]:
    """Resolve (device, compute_type) based on GPU preference and availability."""
    if use_gpu and cuda_available():
        return "cuda", "int8_float16"
    return "cpu", "int8"





def parse_timestamp(ts_str: str) -> float:
    """SRT timestamp ``HH:MM:SS,mmm`` -> seconds (float)."""
    ts_str = ts_str.strip().replace(".", ",")
    parts = ts_str.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format: {ts_str}")
    hrs = int(parts[0])
    mins = int(parts[1])
    secs_parts = parts[2].split(",")
    if len(secs_parts) != 2:
        raise ValueError(f"Invalid timestamp format: {ts_str}")
    secs = int(secs_parts[0])
    ms = int(secs_parts[1])
    return hrs * 3600.0 + mins * 60.0 + secs + ms / 1000.0


def parse_v1_boundaries(json_path, tb):
    """auto-editor v1 JSON の kept chunk 累積尺からタイムライン境界(秒)を作る。

    chunk = [start_frame, end_frame, speed]。speed>=99999 は cut(除去)。
    kept chunk の尺 (end-start)/tb を累積し、各境界 + 先頭 0.0 を返す。
    解析不能/tb 無し/kept 無し -> []。
    """
    import json
    from pathlib import Path
    try:
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except Exception:
        return []
    chunks = data.get("chunks", [])
    if not chunks or not tb:
        return []
    boundaries = [0.0]
    acc = 0.0
    for chunk in chunks:
        try:
            start, end, speed = chunk[0], chunk[1], chunk[2]
        except (IndexError, TypeError):
            continue
        if speed >= 99999:
            continue
        acc += (end - start) / tb
        boundaries.append(round(acc, 6))
    if len(boundaries) <= 1:
        return []
    return sorted(set(boundaries))


def build_cut_aligned_srt(words, natural_segments, boundaries):
    """whisper word-level を「カット境界 ∪ 文境界」で再分割した SRT を返す。

    各区間 [b_i, b_{i+1}) に start が入る単語を 1 字幕に連結。
    カット境界由来の b_i は字幕 start に厳密一致する。空区間/ゼロ尺は除外。
    boundaries か words が空なら "" を返す（呼び出し側でフォールバック）。
    """
    if not boundaries or not words:
        return ""

    breaks = {round(b, 3) for b in boundaries}
    for seg_start, _seg_end in natural_segments:
        breaks.add(round(seg_start, 3))
    last_word_end = max(w[1] for w in words)
    breaks.add(round(last_word_end, 3))
    breaks = sorted(breaks)

    entries = []
    for i in range(len(breaks) - 1):
        b0, b1 = breaks[i], breaks[i + 1]
        seg_words = [w for w in words if b0 <= round(w[0], 3) < b1]
        if not seg_words:
            continue
        text = "".join(w[2] for w in seg_words).strip()
        if not text:
            continue
        start = b0
        end = min(max(w[1] for w in seg_words), b1)
        if start >= end:
            continue
        entries.append((start, end, text))

    out = []
    for idx, (start, end, text) in enumerate(entries, start=1):
        out.append(str(idx))
        out.append(f"{format_timestamp(start)} --> {format_timestamp(end)}")
        out.append(text)
        out.append("")
    return "\n".join(out)



