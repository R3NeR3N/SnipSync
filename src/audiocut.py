"""カット区間（v1 chunks）から、字幕用のカット後音声を自前で組み立てる。

auto-editor に字幕用の WAV を書き出させる代わりに、タイムラインの元になる区間（chunks）から
直接作る。理由は3つ:
- chunks はタイムラインそのものなので、字幕の時刻が厳密に揃う。
- auto-editor 29.3.1 はモノラル音声のカット書き出しで音を壊した（31.x で修正済み。PITFALLS 参照）。
  自前で組み立てれば版に依存しない。
- 字幕のためだけに音声をレンダリングし直す必要が無い（v1 export は解析のみで軽い）。
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import TYPE_CHECKING

from autoeditor import CUT_SPEED

if TYPE_CHECKING:
    import numpy as np


def render_cut_audio(samples: np.ndarray, chunks, tb: float, sr: int) -> np.ndarray:
    """元音声 samples（サンプルレート sr, mono）に chunks を適用した音声を返す。

    chunks = [(start_frame, end_frame, speed)]。speed>=99999 は除去。speed が 1 でない区間は
    リサンプルして長さを 1/speed にする。区間の位置は、小数のまま累積したタイムライン上のフレームを
    サンプルへ丸めて決める（誤差が溜まらない）。auto-editor 31.7.2 の XML 上のクリップ位置とは
    最大1フレーム以内で一致する（実測）。
    """
    import numpy as np
    parts = []
    n = len(samples)
    acc = 0.0                     # タイムライン上の累積フレーム数（小数）
    for start, end, speed in chunks:
        if speed >= CUT_SPEED:
            continue
        sp = speed if speed and speed > 0 else 1.0
        frames = (end - start) / sp
        out_a = int(round(acc / tb * sr))
        out_b = int(round((acc + frames) / tb * sr))
        acc += frames
        want = out_b - out_a
        if want < 1:
            continue
        a = min(n, max(0, int(round(start / tb * sr))))
        b = min(n, max(a, int(round(end / tb * sr))))
        seg = samples[a:b]
        if sp != 1.0:
            if len(seg) > 1:
                seg = np.interp(np.linspace(0, len(seg) - 1, want), np.arange(len(seg)), seg).astype(np.float32)
            else:
                seg = np.zeros(want, dtype=np.float32)
        elif len(seg) != want:
            # 等速: 元音声が短いとき（映像より音声が先に終わる等）は無音で埋め、±数サンプルの丸めは切り詰める。
            # 引き伸ばすと、以降の字幕の時刻がずれる。
            seg = seg[:want] if len(seg) > want else np.concatenate([seg, np.zeros(want - len(seg), dtype=np.float32)])
        parts.append(seg)
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def write_wav(path, samples: np.ndarray, sr: int) -> Path:
    """float32(-1..1) の mono 音声を 16bit PCM WAV に書く。"""
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    p = Path(path)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return p
