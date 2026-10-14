"""手動のカット・倍速（画面を知らない）。

自動の判定（音量・声）に、利用者が指定した区間を重ねる。区間は、元の動画の時刻（秒）で持つ。
カット区間（chunks = [(開始フレーム, 終了フレーム, 速度)]。速度 99999 = カット）に、区間を割り込ませる。
プレビュー（カットマップ・再生）と、処理（タイムライン・字幕用の音声・字幕の時刻）は、同じ chunks を使うので、
ここで重ねれば、全部に反映される。
"""
from __future__ import annotations

from dataclasses import dataclass

from snipsync.core.autoeditor import CUT_SPEED

CUT = "cut"
SPEED = "speed"
DEFAULT_SPEED = 8.0
MIN_SPAN = 0.05          # これより短い区間は、無視する（誤ってドラッグした分）


@dataclass(frozen=True)
class ManualEdit:
    start: float             # 元の動画の秒
    end: float
    action: str              # "cut"（削除）| "speed"（倍速）
    speed: float = DEFAULT_SPEED     # action が "speed" のときの倍率

    @property
    def length(self) -> float:
        return self.end - self.start


def normalize(edits) -> list[ManualEdit]:
    """開始が終了より前の、0 秒以上の区間だけを、開始順に並べて返す。短すぎる区間は捨てる。"""
    out = []
    for e in edits:
        s, t = max(0.0, float(e.start)), float(e.end)
        if t - s >= MIN_SPAN and e.action in (CUT, SPEED):
            sp = float(e.speed) if e.action == SPEED and float(e.speed) > 1.0 else DEFAULT_SPEED
            out.append(ManualEdit(round(s, 3), round(t, 3), e.action, sp if e.action == SPEED else DEFAULT_SPEED))
    return sorted(out, key=lambda x: (x.start, x.end))


def _split(chunks: list, frame: int) -> None:
    """frame の位置で、chunks のどれかを 2 つに割る（境目なら何もしない）。"""
    for i, (a, b, sp) in enumerate(chunks):
        if a < frame < b:
            chunks[i:i + 1] = [[a, frame, sp], [frame, b, sp]]
            return


def apply_manual_edits(chunks, tb: float, edits) -> list:
    """chunks に、手動の区間を重ねた chunks を返す。
    - 削除: その区間は、自動の判定に関係なく、カット。
    - 倍速: その区間のうち、残っている（カットされていない）所だけを、その倍率にする。すでにカットされた所は、カットのまま。
    すべてがカットになってしまうときは、重ねる前の chunks を返す（何も残らない出力を作らない）。"""
    base = [list(c) for c in chunks]
    edits = normalize(edits)
    if not base or not edits or tb <= 0:
        return [tuple(c) for c in chunks]
    work = [list(c) for c in base]
    for e in edits:
        fa, fb = round(e.start * tb), round(e.end * tb)
        if fb <= fa:
            continue
        _split(work, fa)
        _split(work, fb)
        for c in work:
            if c[0] >= fa and c[1] <= fb:
                if e.action == CUT:
                    c[2] = CUT_SPEED
                elif c[2] < CUT_SPEED:
                    c[2] = e.speed
    merged: list[list] = []
    for c in work:
        if merged and merged[-1][2] == c[2] and merged[-1][1] == c[0]:
            merged[-1][1] = c[1]
        else:
            merged.append(list(c))
    if not any(c[2] < CUT_SPEED for c in merged):
        return [tuple(c) for c in chunks]
    return [tuple(c) for c in merged]


def parse_time(text: str) -> float | None:
    """「90」「90.5」「1:30」「1:30.25」「0:01:30.250」などの時刻を、秒にする。読めなければ None。
    全角の数字や記号も受け付ける。分・秒の部分は、60 未満。"""
    import unicodedata
    s = unicodedata.normalize("NFKC", str(text)).strip().replace("：", ":")
    if not s:
        return None
    parts = s.split(":")
    if len(parts) > 3:
        return None
    try:
        nums = [float(p) if p.strip() else 0.0 for p in parts]
    except ValueError:
        return None
    if any(n < 0 or n != n for n in nums) or any(n >= 60 for n in nums[1:]):
        return None
    sec = 0.0
    for n in nums:
        sec = sec * 60 + n
    return sec


def format_precise(sec: float) -> str:
    """秒を「H:MM:SS.mmm」にする（ミリ秒まで。数値で指定する欄に出す）。"""
    ms = int(round(max(0.0, sec) * 1000))
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, milli = divmod(rest, 1000)
    return f"{h}:{m:02d}:{s:02d}.{milli:03d}"


def to_json(edits) -> list:
    return [[e.start, e.end, e.action, e.speed] for e in normalize(edits)]


def from_json(data) -> list[ManualEdit]:
    """to_json の結果から戻す。形が合わないものは、捨てる。"""
    out = []
    if not isinstance(data, list):
        return out
    for row in data:
        try:
            s, t, action, speed = row
            out.append(ManualEdit(float(s), float(t), str(action), float(speed)))
        except (TypeError, ValueError):
            continue
    return normalize(out)
