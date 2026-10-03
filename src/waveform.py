"""波形プレビュー用の計算（描画は app 側）。

「どこが切られるか」は auto-editor の v1 JSON（chunks）をそのまま使う。独自に再現した
近似ではなく、実際の出力と同じ判定を表示するため。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from autoeditor import CUT_SPEED

if TYPE_CHECKING:
    import numpy as np


def compute_peaks(samples: np.ndarray, bins: int = 1200) -> np.ndarray:
    """samples を bins 個に分け、各区間の最大絶対値（0..1）を返す。"""
    import numpy as np
    n = len(samples)
    if n == 0 or bins <= 0:
        return np.zeros(0, dtype=np.float32)
    bins = min(bins, n)
    edges = np.linspace(0, n, bins + 1, dtype=np.int64)
    abs_s = np.abs(samples)
    return np.array([abs_s[a:b].max() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:], strict=True)],
                    dtype=np.float32)


def chunk_regions(chunks, fps: float):
    """v1 chunks -> [(開始秒, 終了秒, 種類)]。種類は 'keep' / 'cut' / 'speed'。"""
    out = []
    for start, end, speed in chunks:
        kind = "cut" if speed >= CUT_SPEED else ("keep" if speed == 1.0 else "speed")
        out.append((start / fps, end / fps, kind))
    return out


def preview_stats(chunks, fps: float) -> dict:
    """元の長さ・結果の長さ・カット数・削減率。倍速化した区間は短縮後の長さで数える。"""
    original = sum((e - s) / fps for s, e, _ in chunks)
    result = sum((e - s) / fps / (sp if sp > 0 else 1.0) for s, e, sp in chunks if sp < CUT_SPEED)
    cuts = sum(1 for _, _, sp in chunks if sp >= CUT_SPEED)
    return {
        "original": original,
        "result": result,
        "cuts": cuts,
        "saved_pct": (1 - result / original) * 100 if original > 0 else 0.0,
    }
