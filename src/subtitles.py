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


# --- SRT-snap logic and constants ---
SRT_SNAP_TOLERANCE_EXTRA = 0.15


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



def _fcpxml_time_to_seconds(text: str) -> float:
    """Convert rational time format "N/Ds" or "Ns" or "0s" to float seconds."""
    text = text.strip()
    if text.endswith("s"):
        text = text[:-1]
    if "/" in text:
        num, denom = text.split("/")
        return float(num) / float(denom)
    return float(text)


def parse_fcpxml_cut_boundaries(timeline_path: Path, stem: str) -> list[float]:
    """Extract cut boundaries (seconds, sorted, unique) from FCPXML timeline.

    Scans for video asset-clip elements (ref corresponding to hasVideo="1") and
    collects their offset values, plus the final clip's offset + duration.
    Returns sorted list of float seconds, or [] on parse failure or empty boundary.
    """
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(timeline_path)
    except Exception:
        return []
    root = tree.getroot()

    video_id = None
    for asset in root.findall(".//resources/asset"):
        aid = asset.get("id")
        if asset.get("hasVideo") == "1":
            video_id = aid
            break

    if video_id is None:
        return []

    spine = root.find(".//sequence/spine")
    if spine is None:
        return []

    video_clips = []
    for child in spine:
        if child.tag == "asset-clip" and child.get("ref") == video_id:
            video_clips.append(child)

    if not video_clips:
        return []

    boundaries = set()
    last_clip = None
    for clip in video_clips:
        offset_str = clip.get("offset")
        if offset_str:
            boundaries.add(_fcpxml_time_to_seconds(offset_str))
        last_clip = clip

    if last_clip is not None:
        offset_str = last_clip.get("offset")
        duration_str = last_clip.get("duration")
        if offset_str and duration_str:
            end_time = _fcpxml_time_to_seconds(offset_str) + _fcpxml_time_to_seconds(duration_str)
            boundaries.add(end_time)

    return sorted(list(boundaries))


def snap_srt_to_boundaries(srt_text: str, boundaries: list[float], tolerance: float) -> str:
    """Snap SRT subtitle timestamps (start/end) to the nearest cut boundaries

    if they fall within the given tolerance.
    """
    import re
    if not boundaries:
        return srt_text

    lines = srt_text.replace("\r\n", "\n").split("\n")
    entries = []
    ts_pattern = re.compile(r"^(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[,\.]\d{3})")

    current_index = None
    current_times = None
    current_text_lines = []

    for line in lines:
        line_str = line.strip()
        if not line_str:
            if current_index is not None and current_times is not None:
                entries.append((current_index, current_times[0], current_times[1], "\n".join(current_text_lines)))
                current_index = None
                current_times = None
                current_text_lines = []
            continue

        match = ts_pattern.match(line_str)
        if match:
            try:
                start_sec = parse_timestamp(match.group(1))
                end_sec = parse_timestamp(match.group(2))
                current_times = (start_sec, end_sec)
            except ValueError:
                pass
        elif line_str.isdigit() and current_index is None:
            current_index = int(line_str)
        else:
            if current_times is not None:
                current_text_lines.append(line)

    # Hande the last entry if it doesn't end with blank line
    if current_index is not None and current_times is not None:
        entries.append((current_index, current_times[0], current_times[1], "\n".join(current_text_lines)))

    if not entries:
        return srt_text

    # Extract distinct times
    times = []
    for _, start, end, _ in entries:
        times.append(start)
        times.append(end)
    times = sorted(list(set(times)))

    # Remap times to nearest boundary if within tolerance
    remap = {}
    for t in times:
        nb = min(boundaries, key=lambda b: abs(b - t))
        if abs(nb - t) <= tolerance:
            remap[t] = nb
        else:
            remap[t] = t

    # Build initial remapped entries with single-entry constraints
    temp_remapped = []
    for idx, start, end, text in entries:
        rs = remap[start]
        re_val = remap[end]

        if rs >= re_val:
            # Revert end to original value to avoid zero/negative duration
            re_val = end

        if rs >= re_val:
            # Revert both if still invalid
            rs = start
            re_val = end

        temp_remapped.append({
            "idx": idx,
            "orig_start": start,
            "orig_end": end,
            "start": rs,
            "end": re_val,
            "text": text
        })

    # Prevent adjacent entries from overlapping (maintain non-decreasing order)
    changed = True
    while changed:
        changed = False
        for i in range(len(temp_remapped) - 1):
            curr = temp_remapped[i]
            nxt = temp_remapped[i+1]
            if curr["end"] > nxt["start"]:
                # Conflict! Revert snaps to resolve overlap
                if curr["end"] != curr["orig_end"]:
                    curr["end"] = curr["orig_end"]
                    changed = True
                if nxt["start"] != nxt["orig_start"]:
                    nxt["start"] = nxt["orig_start"]
                    changed = True

                # Re-verify single-entry validity after revert
                if curr["start"] >= curr["end"]:
                    curr["start"] = curr["orig_start"]
                    curr["end"] = curr["orig_end"]
                if nxt["start"] >= nxt["end"]:
                    nxt["start"] = nxt["orig_start"]
                    nxt["end"] = nxt["orig_end"]

    # Reconstruct SRT text
    output_lines = []
    for item in temp_remapped:
        start_str = format_timestamp(item["start"])
        end_str = format_timestamp(item["end"])
        output_lines.append(f"{item['idx']}")
        output_lines.append(f"{start_str} --> {end_str}")
        output_lines.append(item["text"])
        output_lines.append("")

    return "\n".join(output_lines)


