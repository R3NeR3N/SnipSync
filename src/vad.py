"""Voice-activity-detection based cut decisions.

音量しきい値の代わりに、faster-whisper に同梱の Silero VAD で「人の声がある区間」を求め、
そこから auto-editor の v1 JSON（chunks）を自前で組み立てる。この JSON を auto-editor に
入力として渡すと、直接実行と同じ形式の出力が得られる（実測: premiere XML がバイト一致）。
CLI の --cut-out は1回に1区間しか取れないため、区間数に上限が無いこの経路を使う。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from autoeditor import CUT_SPEED

if TYPE_CHECKING:
    import numpy as np

SAMPLE_RATE = 16000


def decode_mix(path, sr: int = SAMPLE_RATE) -> np.ndarray:
    """全音声ストリームを sr の mono float32 にして加算する（-1..1 にクリップ）。

    faster_whisper.decode_audio は先頭の音声ストリームしか読まないため自前で行う。
    多トラック収録（マイク別録り等）で、どのトラックの声も VAD に拾わせたい。
    """
    import av
    import numpy as np
    tracks: list[np.ndarray] = []
    with av.open(str(Path(path))) as probe:
        count = len(probe.streams.audio)
    for idx in range(count):
        chunks: list[np.ndarray] = []
        with av.open(str(Path(path))) as container:
            stream = container.streams.audio[idx]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=sr)
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
            for out in resampler.resample(None) or []:
                chunks.append(out.to_ndarray().reshape(-1))
        if chunks:
            tracks.append(np.concatenate(chunks).astype(np.float32) / 32768.0)
    if not tracks:
        return np.zeros(0, dtype=np.float32)
    n = max(len(t) for t in tracks)
    mix = np.zeros(n, dtype=np.float32)
    for t in tracks:
        mix[:len(t)] += t
    return np.clip(mix, -1.0, 1.0)


def detect_speech(samples: np.ndarray, sr: int = SAMPLE_RATE, *, threshold: float = 0.5,
                  min_silence_ms: int = 300, speech_pad_ms: int = 100) -> list[tuple[float, float]]:
    """Silero VAD で発話区間 [(開始秒, 終了秒)] を返す。"""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    opts = VadOptions(threshold=threshold, min_silence_duration_ms=min_silence_ms,
                      speech_pad_ms=speech_pad_ms)
    return [(t["start"] / sr, t["end"] / sr) for t in get_speech_timestamps(samples, opts)]


def speech_to_chunks(ranges, total_sec: float, fps: float, *, margin: float = 0.2,
                     min_cut: float = 0.2, silent_speed: float | None = None):
    """発話区間 -> v1 chunks [[start_frame, end_frame, speed], ...]（全体を隙間なく覆う）。

    - 各発話区間の前後に margin 秒の余白を足す（auto-editor の --margin と同じ意味）。
    - min_cut 秒より短い隙間は切らない（細切れの不自然なカットを避ける）。
    - 隙間は silent_speed があればその倍速、無ければカット(99999)。
    戻り値が空リストなら「発話が見つからなかった」。
    """
    if not ranges or total_sec <= 0 or fps <= 0:
        return []
    padded = []
    for s, e in sorted(ranges):
        padded.append([max(0.0, s - margin), min(total_sec, e + margin)])
    merged = [padded[0]]
    for s, e in padded[1:]:
        if s - merged[-1][1] < min_cut:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    total_frames = int(total_sec * fps)
    gap_speed = float(silent_speed) if silent_speed else CUT_SPEED
    chunks: list[list] = []
    cursor = 0

    def push(a, b, speed):
        if b <= a:
            return
        if chunks and chunks[-1][2] == speed and chunks[-1][1] == a:
            chunks[-1][1] = b
        else:
            chunks.append([a, b, speed])

    for s, e in merged:
        fs = min(max(cursor, round(s * fps)), total_frames)
        fe = min(max(fs, round(e * fps)), total_frames)
        push(cursor, fs, gap_speed)
        push(fs, fe, 1.0)
        cursor = fe
    push(cursor, total_frames, gap_speed)
    if not any(c[2] < CUT_SPEED for c in chunks):
        return []
    return chunks


def write_v1(path, source, chunks) -> Path:
    """auto-editor が入力として読める v1 JSON を書く。source は絶対パスにする。"""
    p = Path(path)
    p.write_text(json.dumps(
        {"version": "1", "source": str(Path(source).resolve()), "chunks": chunks},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def read_v1_chunks(path):
    """v1 JSON の chunks を [(start_frame, end_frame, speed)] で返す。読めなければ []。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return [(c[0], c[1], c[2]) for c in data.get("chunks", [])]
    except Exception:
        return []
