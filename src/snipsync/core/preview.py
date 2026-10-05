"""切れる場所の確認（カットマップ）に使うデータを計算する。画面（tkinter）には依存しない。

実際の処理と同じ判定を使う。音量方式は auto-editor の v1 export、声方式は Silero VAD。
近似ではなく、処理を実行したときと同じ区間が出る。
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from snipsync.core.autoeditor import (
    AUDIO_ONLY_TIMEBASE,
    CREATE_NO_WINDOW,
    build_v1_export_cmd,
    is_audio_only,
    probe_fps,
)
from snipsync.core.vad import (
    SAMPLE_RATE,
    decode_mix,
    detect_speech,
    read_v1_chunks,
    speech_to_chunks,
)
from snipsync.core.waveform import chunk_regions, compute_peaks, preview_stats

PEAK_BINS = 2400


@dataclass
class CutSettings:
    margin: float
    threshold: float
    cut_mode: str = "threshold"          # "threshold" | "vad"
    silent_speed: float | None = None


@dataclass
class CutPreview:
    peaks: object
    regions: list
    stats: dict
    duration: float
    chunks: list = field(default_factory=list)     # 再生用: [(開始フレーム, 終了フレーム, 速度)]
    fps: float = 0.0                               # chunks のフレームレート（タイムベース）


class PreviewError(Exception):
    """利用者に見せてよい失敗（原因が文言になっている）。"""


def compute_preview(path, cfg: CutSettings, ae_path, cache: dict | None = None) -> CutPreview:
    """path のカット結果を計算する。cache に音声を残すと、設定だけ変えた再計算が速い。"""
    path = str(path)
    cache = cache if cache is not None else {}
    audio_only = is_audio_only(path)
    fps = AUDIO_ONLY_TIMEBASE if audio_only else probe_fps(path)
    if not fps:
        raise PreviewError("fps")
    if cache.get("path") != path:
        cache.clear()
        cache["path"], cache["samples"] = path, decode_mix(path, SAMPLE_RATE)
    samples = cache["samples"]
    if cfg.cut_mode == "vad":
        chunks = speech_to_chunks(detect_speech(samples), len(samples) / SAMPLE_RATE, fps,
                                  margin=cfg.margin, silent_speed=cfg.silent_speed)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            out_json = Path(tmp) / "v1.json"
            cmd = build_v1_export_cmd(ae_path, path, cfg.margin, cfg.threshold, out_json, fps,
                                      silent_speed=cfg.silent_speed)
            subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=CREATE_NO_WINDOW)
            chunks = read_v1_chunks(out_json)
    if not chunks:
        raise PreviewError("no cut data")
    stats = preview_stats(chunks, fps)
    return CutPreview(compute_peaks(samples, PEAK_BINS), chunk_regions(chunks, fps), stats, stats["original"],
                      list(chunks), fps)
