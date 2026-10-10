"""話者のラベルの整理（画面を知らない）。

話者分離は、同じ人の声を、何十ものラベルに分けてしまうことがある（実測: 約 95 分・参加者約 8 人の録音で 249 ラベル、
うち 211 ラベルは発話が 30 秒に満たない）。ここは、その手直しの計画を作る。計画は {字幕の番号: 新しい話者} で、
適用は CueEditor.reassign（元に戻すは 1 回分）が行う。計画だけ見て、適用するかを利用者が決める。
"""
from __future__ import annotations

from snipsync.core.subtitles import Cue


def speaker_seconds(cues) -> dict[int, float]:
    """話者ごとの発話時間（秒）の合計。話者なしは数えない。"""
    out: dict[int, float] = {}
    for c in cues:
        if c.speaker is not None:
            out[c.speaker] = out.get(c.speaker, 0.0) + max(0.0, c.end - c.start)
    return out


def plan_small_speakers(cues: list[Cue], min_seconds: float = 30.0) -> dict[int, int]:
    """発話の合計が min_seconds に満たない話者の字幕を、時間のうえで近い、大きな話者へ寄せる計画。

    近い = 前後の「大きな話者の字幕」のうち、間の時間が短い方。同じなら、発話の合計が長い話者。
    大きな話者が 1 人もいなければ、何もしない（全員を 1 人にしてしまわないため）。
    """
    totals = speaker_seconds(cues)
    small = {s for s, t in totals.items() if t < min_seconds}
    if not small or len(small) == len(totals):
        return {}

    def big(i):
        return cues[i].speaker is not None and cues[i].speaker not in small

    n = len(cues)
    prev_big: list[int | None] = [None] * n
    last = None
    for i in range(n):
        prev_big[i] = last
        if big(i):
            last = i
    next_big: list[int | None] = [None] * n
    nxt = None
    for i in range(n - 1, -1, -1):
        next_big[i] = nxt
        if big(i):
            nxt = i
    plan: dict[int, int] = {}
    for i, c in enumerate(cues):
        if c.speaker not in small:
            continue
        a, b = prev_big[i], next_big[i]
        if a is None and b is None:
            continue
        gap_a = c.start - cues[a].end if a is not None else float("inf")
        gap_b = cues[b].start - c.end if b is not None else float("inf")
        if gap_a < gap_b:
            pick = a
        elif gap_b < gap_a:
            pick = b
        else:
            pick = a if totals[cues[a].speaker] >= totals[cues[b].speaker] else b
        plan[i] = cues[pick].speaker
    return plan


def plan_sandwiched(cues: list[Cue], max_chars: int = 10) -> dict[int, int]:
    """同じ話者の発言に前後を挟まれた、短い別の話者の発言（max_chars 字以下）を、挟んでいる話者へ寄せる計画。

    あいづち（「はい」など）が、実は別の人の声のときもある。適用の前に、件数を見せて確かめること。
    """
    runs: list[list] = []                         # [話者, 最初の番号, 最後の番号, 文字数]
    for i, c in enumerate(cues):
        if runs and runs[-1][0] == c.speaker:
            runs[-1][2] = i
            runs[-1][3] += len(c.text.replace("\n", ""))
        else:
            runs.append([c.speaker, i, i, len(c.text.replace("\n", ""))])
    plan: dict[int, int] = {}
    for k in range(1, len(runs) - 1):
        before, mid, after = runs[k - 1], runs[k], runs[k + 1]
        if (before[0] is not None and before[0] == after[0] and mid[0] != before[0]
                and mid[0] is not None and mid[3] <= max_chars):
            for i in range(mid[1], mid[2] + 1):
                plan[i] = before[0]
    return plan


def count_after(cues: list[Cue], plan: dict[int, int]) -> int:
    """plan を適用したあとの、話者の数。"""
    return len({(plan.get(i, c.speaker)) for i, c in enumerate(cues) if plan.get(i, c.speaker) is not None})
