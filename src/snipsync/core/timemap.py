"""編集後の時刻 ⇔ 元の動画の時刻の対応（画面を知らない）。

字幕の時刻は、カット後の時間軸（編集後）。カットを足すと、それ以降の字幕の時刻が、前へ詰まる。
字幕を消すと同時に、その区間の映像・音声をカットするときの、時刻の換算に使う。
"""
from __future__ import annotations

import bisect

from snipsync.core.player import segments_from_chunks
from snipsync.core.subtitle_edit import MIN_CUE_LENGTH, survives_retime  # noqa: F401
from snipsync.core.subtitles import Cue


class TimeMap:
    """chunks=[(開始フレーム, 終了フレーム, 速度)]、tb=フレームレート から作る、時刻の対応。"""

    def __init__(self, chunks, tb: float):
        self.segments = segments_from_chunks(chunks, tb)
        self._edited_starts = [s.edited_start for s in self.segments]

    @property
    def duration(self) -> float:
        """編集後の長さ（秒）。"""
        return self.segments[-1].edited_end if self.segments else 0.0

    def edited_to_source(self, t: float) -> float:
        if not self.segments:
            return 0.0
        i = max(0, bisect.bisect_right(self._edited_starts, t) - 1)
        s = self.segments[i]
        return min(s.source_end, s.source_start + max(0.0, t - s.edited_start) * s.speed)

    def source_to_edited(self, t: float) -> float:
        """元の時刻 → 編集後の時刻。切られた所を指していたら、次に残る所の頭へ送る。"""
        for s in self.segments:
            if t < s.source_start:
                return s.edited_start
            if t < s.source_end:
                return s.edited_start + (t - s.source_start) / s.speed
        return self.duration


def timecode(seconds: float, fps: float | None) -> str:
    """秒を、タイムラインの目盛りの形（時:分:秒:フレーム）にする。fps が分からなければ、小数の秒（時:分:秒.1）。"""
    seconds = max(0.0, float(seconds))
    if not fps or fps <= 0:
        whole, tenth = divmod(int(round(seconds * 10)), 10)
        h, rest = divmod(whole, 3600)
        return f"{h:02d}:{rest // 60:02d}:{rest % 60:02d}.{tenth}"
    base = max(1, round(fps))
    h, rest = divmod(int(round(seconds * base)), 3600 * base)
    m, rest = divmod(rest, 60 * base)
    return f"{h:02d}:{m:02d}:{rest // base:02d}:{rest % base:02d}"


def srt_placement_lines(first_start: float, fps: float | None, tr) -> list[str]:
    """字幕（.srt）を、編集ソフトのタイムラインのどこへ置けばよいかの案内。
    Resolve は、読み込むとき、最初の字幕より前の空白を詰めるので、置く場所は、最初の字幕の時刻になる。"""
    return [tr("log_srt_place", timecode(first_start, fps), f"{first_start:.1f}")]


def edited_range_to_source(tm: TimeMap, start: float, end: float, margin: float = 0.0) -> tuple[float, float]:
    """編集後の区間 [start, end]（前後に margin 秒を足す）を、元の動画の区間（秒）にする。
    間に、すでにカットされた所があれば、それも含む（切った所は、切ったまま）。"""
    a = max(0.0, start - margin)
    b = min(tm.duration, end + margin)
    return tm.edited_to_source(a), tm.edited_to_source(b)


def retime_cues(cues, old: TimeMap, new: TimeMap) -> list[Cue]:
    """カットを足す前の時間軸（old）の字幕を、足したあとの時間軸（new）に付け直す。
    カットに飲まれて、付け直したあとの長さが MIN_CUE_LENGTH に満たなくなった字幕は、除く。"""
    out = []
    for c in cues:
        s = new.source_to_edited(old.edited_to_source(c.start))
        e = new.source_to_edited(old.edited_to_source(c.end))
        if survives_retime(c.end - c.start, e - s):
            out.append(Cue(round(s, 3), round(e, 3), c.text, c.speaker))
    return out
