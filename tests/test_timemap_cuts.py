"""字幕を消すと同時にカットする: 時刻の対応（core/timemap.py）、編集の印（CueEditor）、セッションのタイムラインの情報。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core import session as sess  # noqa: E402
from snipsync.core.autoeditor import CUT_SPEED  # noqa: E402
from snipsync.core.manualcuts import CUT, ManualEdit, apply_manual_edits  # noqa: E402
from snipsync.core.subtitle_edit import CueEditor  # noqa: E402
from snipsync.core.subtitles import Cue  # noqa: E402
from snipsync.core.timemap import (  # noqa: E402
    MIN_CUE_LENGTH,
    TimeMap,
    edited_range_to_source,
    retime_cues,
)

TB = 30.0
# 元の動画: 0-10 秒 残す / 10-20 秒 カット / 20-40 秒 残す / 40-50 秒 4 倍速 / 50-60 秒 残す
CHUNKS = [(0, 300, 1.0), (300, 600, CUT_SPEED), (600, 1200, 1.0), (1200, 1500, 4.0), (1500, 1800, 1.0)]


def test_the_time_map_converts_both_ways_across_cuts_and_speed_ups():
    tm = TimeMap(CHUNKS, TB)
    assert tm.duration == pytest.approx(10 + 20 + 2.5 + 10)                       # 残る 10 + 20、4 倍速の 10 秒が 2.5 秒、残る 10
    assert tm.edited_to_source(5.0) == pytest.approx(5.0)
    assert tm.edited_to_source(10.0) == pytest.approx(20.0)                       # カットの先へ飛ぶ
    assert tm.edited_to_source(31.0) == pytest.approx(40.0 + 1.0 * 4)             # 4 倍速の中: 編集後 1 秒 = 元の 4 秒
    assert tm.source_to_edited(25.0) == pytest.approx(15.0)
    assert tm.source_to_edited(15.0) == pytest.approx(10.0)                       # 切られた所は、次に残る所の頭
    assert tm.source_to_edited(999.0) == pytest.approx(tm.duration)


def test_an_edited_range_becomes_a_source_range_with_the_margin_and_clamped_to_the_video():
    tm = TimeMap(CHUNKS, TB)
    a, b = edited_range_to_source(tm, 12.0, 14.0, margin=0.1)
    assert (a, b) == (pytest.approx(22.0 - 0.1), pytest.approx(24.0 + 0.1))
    a0, b0 = edited_range_to_source(tm, 0.02, 1.0, margin=0.1)
    assert a0 == 0.0                                                              # 先頭より前へは、出ない
    a1, b1 = edited_range_to_source(tm, tm.duration - 1.0, tm.duration, margin=5.0)
    assert b1 <= 60.0 + 1e-6                                                      # 終わりより後へも、出ない
    cross = edited_range_to_source(tm, 8.0, 12.0)                                 # すでにカットされた所をまたぐ
    assert cross == (pytest.approx(8.0), pytest.approx(22.0))


def test_cutting_a_deleted_cue_shifts_every_later_cue_forward_by_the_cut_length():
    old = TimeMap(CHUNKS, TB)
    rng = edited_range_to_source(old, 12.0, 14.0, margin=0.0)                    # 元の 22-24 秒
    new_chunks = apply_manual_edits(CHUNKS, TB, [ManualEdit(*rng, CUT)])
    new = TimeMap(new_chunks, TB)
    assert new.duration == pytest.approx(old.duration - 2.0)
    cues = [Cue(0.0, 5.0, "前", 0), Cue(12.0, 14.0, "消す", 0), Cue(16.0, 19.0, "後", 1), Cue(31.0, 33.0, "倍速のあと", 1)]
    out = retime_cues([c for c in cues if c.text != "消す"], old, new)
    assert [(c.start, c.end, c.text) for c in out] == [(0.0, 5.0, "前"), (14.0, 17.0, "後"), (29.0, 31.0, "倍速のあと")]


def test_a_cue_swallowed_by_the_cut_disappears_and_a_partly_cut_cue_is_shortened():
    old = TimeMap(CHUNKS, TB)
    new = TimeMap(apply_manual_edits(CHUNKS, TB, [ManualEdit(22.0, 26.0, CUT)]), TB)
    swallowed = Cue(12.5, 13.5, "のまれる", 0)                                    # 元の 22.5-23.5 秒: すべてカット内
    partial = Cue(11.0, 15.0, "一部", 0)                                          # 元の 21-25 秒: 後ろ側がカット内
    out = retime_cues([swallowed, partial], old, new)
    assert [c.text for c in out] == ["一部"]
    assert out[0].start == pytest.approx(11.0) and out[0].end - out[0].start < 4.0 and out[0].end - out[0].start >= MIN_CUE_LENGTH


def test_a_cue_that_was_already_tiny_is_kept_when_the_cut_does_not_touch_it():
    old = TimeMap(CHUNKS, TB)
    new = TimeMap(apply_manual_edits(CHUNKS, TB, [ManualEdit(22.0, 26.0, CUT)]), TB)
    tiny = Cue(1.0, 1.02, "ん", 0)                                                # 文字起こしが作った、0.02 秒の字幕
    swallowed_tiny = Cue(12.6, 12.62, "の", 0)                                    # 元の 22.6 秒: カットの中
    out = retime_cues([tiny, swallowed_tiny], old, new)
    assert [c.text for c in out] == ["ん"]
    ed = CueEditor([Cue(1.0, 1.02, "ん", 0), Cue(2.0, 5.0, "あ", 0)])
    ed.retime(lambda t: t)
    assert [c.text for c in ed.cues] == ["ん", "あ"]


def test_without_any_new_cut_the_times_do_not_change():
    tm = TimeMap(CHUNKS, TB)
    cues = [Cue(1.0, 2.0, "a", 0), Cue(11.0, 13.0, "b", 1), Cue(30.5, 32.0, "c", None)]
    out = retime_cues(cues, tm, TimeMap(CHUNKS, TB))
    assert [(c.start, c.end) for c in out] == [(1.0, 2.0), (11.0, 13.0), (30.5, 32.0)]


# ── CueEditor: カットの印 ─────────────────────────────────────────────────────────────────
def editor():
    return CueEditor([Cue(0.0, 5.0, "あ", 0), Cue(5.0, 8.0, "い", 1), Cue(8.0, 12.0, "う", 0)])


def test_delete_and_cut_removes_the_cue_marks_the_span_and_undoes_together():
    ed = editor()
    ed.delete_and_cut(1, (5.0, 8.0))
    assert [c.text for c in ed.cues] == ["あ", "う"] and ed.cuts == [(5.0, 8.0)] and ed.dirty
    assert ed.undo()
    assert [c.text for c in ed.cues] == ["あ", "い", "う"] and ed.cuts == []
    assert ed.redo() and ed.cuts == [(5.0, 8.0)]


def test_a_plain_delete_leaves_no_cut():
    ed = editor()
    ed.delete(1)
    assert ed.cuts == [] and len(ed) == 2


def test_the_cut_marks_survive_the_session_state_and_make_it_dirty_when_added():
    ed = editor()
    ed.delete_and_cut(0, (0.0, 5.2))
    back = CueEditor.from_state(json.loads(json.dumps(ed.export_state())))
    assert back.cuts == [(0.0, 5.2)] and not back.dirty
    assert editor().export_state()["cuts"] == []


def test_retime_moves_cues_and_the_original_clears_the_marks_and_the_history_and_drops_tiny_cues():
    ed = editor()
    ed.set_text(0, "あ！")
    ed.delete_and_cut(1, (5.0, 8.0))
    ed.retime(lambda t: t if t <= 5.0 else max(5.0, t - 3.0))
    assert [(c.start, c.end, c.text) for c in ed.cues] == [(0.0, 5.0, "あ！"), (5.0, 9.0, "う")]
    assert ed.cuts == [] and not ed.can_undo and not ed.can_redo
    assert ed.is_changed(0) and not ed.is_changed(1)                              # 変えた印は、付け直したあとも、そのまま
    tiny = editor()
    tiny.retime(lambda t: 1.0 if 5.0 <= t <= 8.0 else t)                          # 「い」が、長さ 0 になる
    assert [c.text for c in tiny.cues] == ["あ", "う"]


# ── セッションのタイムラインの情報 ──────────────────────────────────────────────────────────
def session_with(tl, cuts=None):
    ed = editor()
    state = ed.export_state()
    if cuts is not None:
        state["cuts"] = cuts
    return sess.Session(title="t", source="x.mp4", editor=state, timeline=tl)


def good_timeline():
    return {"path": "D:/out/t_snipsynced.fcpxml", "source": "x.mp4", "tb": 30.0, "chunks": [[0, 300, 1.0], [300, 600, 99999.0]],
            "export": "resolve", "markers": True, "export_pending": False}


def test_the_session_keeps_the_timeline_and_the_pending_cuts(tmp_path):
    path = tmp_path / "t.snipsync.json"
    sess.write_session(path, session_with(good_timeline(), [[5.0, 8.0]]))
    got = sess.read_session(path)
    assert got.timeline["chunks"] == [[0, 300, 1.0], [300, 600, 99999.0]] and got.timeline["tb"] == 30.0
    assert got.timeline["export"] == "resolve" and got.timeline["markers"] is True
    assert CueEditor.from_state(got.editor).cuts == [(5.0, 8.0)]


@pytest.mark.parametrize("tl", [
    None, "x", {}, {"tb": 30.0}, {"tb": 0, "chunks": [[0, 1, 1.0]]}, {"tb": 30.0, "chunks": []}, {"tb": 30.0, "chunks": [[5, 1, 1.0]]},
    {"tb": 30.0, "chunks": [[0, 1]]}, {"tb": "30", "chunks": [[0, 1, 1.0]]}, {"tb": float("nan"), "chunks": [[0, 1, 1.0]]},
])
def test_a_malformed_timeline_drops_only_this_feature_and_the_rest_still_opens(tmp_path, tl):
    path = tmp_path / "t.snipsync.json"
    data = {"format": 1, "title": "t", "editor": editor().export_state(), "timeline": tl}
    path.write_text(json.dumps(data), encoding="utf-8")
    got = sess.read_session(path)
    assert got.timeline == {} and len(got.editor["items"]) == 3


def test_malformed_pending_cuts_are_refused(tmp_path):
    path = tmp_path / "t.snipsync.json"
    for bad in ("x", [[1]], [["a", "b"]], [[1, float("inf")]]):
        state = editor().export_state()
        state["cuts"] = bad
        path.write_text(json.dumps({"format": 1, "editor": state}), encoding="utf-8")
        with pytest.raises(sess.SessionError):
            sess.read_session(path)


def test_a_session_written_before_this_feature_still_opens(tmp_path):
    path = tmp_path / "old.snipsync.json"
    state = editor().export_state()
    del state["cuts"]
    path.write_text(json.dumps({"format": 1, "title": "old", "editor": state}), encoding="utf-8")
    got = sess.read_session(path)
    assert got.timeline == {} and CueEditor.from_state(got.editor).cuts == []


# ── .srt の置き場所の案内 ───────────────────────────────────────────────────────────────────
def test_timecode_uses_the_timeline_frame_rate_or_falls_back_to_seconds():
    from snipsync.core.timemap import timecode
    assert timecode(19.7, 60.0) == "00:00:19:42"
    assert timecode(0.0, 60.0) == "00:00:00:00"
    assert timecode(3725.5, 30.0) == "01:02:05:15"
    assert timecode(19.7, 29.97) == "00:00:19:21"                                 # 29.97 は、30 の目盛りで数える
    assert timecode(19.7, None) == "00:00:19.7"
    assert timecode(-1.0, 30.0) == "00:00:00:00"


def test_the_placement_note_names_the_timeline_start_and_warns_only_about_a_long_gap():
    from snipsync.core.timemap import srt_placement_lines
    tr = lambda key, *args: f"{key}:{'|'.join(map(str, args))}"  # noqa: E731
    gap = srt_placement_lines(19.7, 60.0, tr)
    assert gap == ["log_srt_place:00:00:00:00|00:00:19:42|19.7", "log_srt_place_gap:"]
    assert srt_placement_lines(1.2, 60.0, tr) == ["log_srt_place:00:00:00:00|00:00:01:12|1.2"]
