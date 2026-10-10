"""編集セッションの保存と復元、話者の整理（core。画面は使わない）。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core import session as sess  # noqa: E402
from snipsync.core.speaker_cleanup import (  # noqa: E402
    count_after,
    plan_sandwiched,
    plan_small_speakers,
    speaker_seconds,
)
from snipsync.core.subtitle_edit import CueEditor  # noqa: E402
from snipsync.core.subtitles import Cue  # noqa: E402
from snipsync.core.transcript import parse_srt, split_speaker_prefix  # noqa: E402


def cues():
    return [Cue(0.0, 10.0, "はじめまして", 0), Cue(10.0, 12.0, "はい", 5), Cue(12.0, 30.0, "よろしくお願いします", 0),
            Cue(30.0, 40.0, "こんにちは", 1), Cue(40.0, 41.0, "え", 7), Cue(41.0, 60.0, "そうですね", 1)]


# ── CueEditor の状態の保存と復元 ───────────────────────────────────────────────────────
def test_export_and_restore_keep_changes_names_and_origins():
    ed = CueEditor(cues())
    ed.set_text(0, "はじめまして！")
    ed.merge_next(2)                                  # 件 2 と 3 を結合 → 出どころが 2 つの件
    ed.rename_speaker(0, "山田")
    back = CueEditor.from_state(json.loads(json.dumps(ed.export_state())))
    assert [(c.start, c.end, c.text, c.speaker) for c in back.cues] == [(c.start, c.end, c.text, c.speaker) for c in ed.cues]
    assert back.names == {0: "山田"}
    assert back.is_changed(0) and back.is_changed(2) and not back.is_changed(1)     # 元の字幕との差が残る
    assert not back.dirty and not back.can_undo
    assert back.revert(0) and back.cue(0).text == "はじめまして"                       # 元の字幕へ戻せる


def test_restored_editor_is_not_dirty_until_something_changes():
    back = CueEditor.from_state(CueEditor(cues()).export_state())
    assert not back.dirty
    back.set_text(1, "うん")
    assert back.dirty


# ── 話者の操作 ─────────────────────────────────────────────────────────────────────────
def test_speaker_stats_are_sorted_by_speaking_time_and_find_the_longest_cue():
    stats = CueEditor(cues()).speaker_stats()
    assert [s.speaker for s in stats] == [1, 0, 5, 7]                                   # 29 秒、28 秒、2 秒、1 秒
    assert stats[1].seconds == 28.0 and stats[1].cues == 2 and stats[1].longest == 2     # 話者0 の最長は、12.0 から 30.0 の字幕


def test_merge_speakers_moves_every_cue_drops_source_names_and_undoes_in_one_step():
    ed = CueEditor(cues())
    ed.rename_speaker(0, "山田")
    ed.rename_speaker(5, "迷子")
    assert ed.merge_speakers([5, 7], 0)
    assert [c.speaker for c in ed.cues] == [0, 0, 0, 1, 0, 1]
    assert ed.names == {0: "山田"}
    assert not ed.merge_speakers([5, 7], 0)                     # もう何も動かない
    assert not ed.merge_speakers([0], 0)                        # 自分自身へは何もしない
    assert ed.undo()
    assert [c.speaker for c in ed.cues] == [0, 5, 0, 1, 7, 1] and ed.names == {0: "山田", 5: "迷子"}


def test_reassign_applies_a_plan_as_one_undo_step():
    ed = CueEditor(cues())
    assert ed.reassign({1: 0, 4: 1, 99: 3})                    # 範囲外の番号は無視
    assert [c.speaker for c in ed.cues] == [0, 0, 0, 1, 1, 1]
    assert not ed.reassign({1: 0})
    assert ed.undo() and [c.speaker for c in ed.cues][1] == 5


def test_renumber_orders_by_speaking_time_and_keeps_names_attached():
    ed = CueEditor(cues())
    ed.rename_speaker(1, "佐藤")
    assert ed.renumber_speakers()
    # 発話時間: 話者1=29秒, 話者0=28秒, 話者5=2秒, 話者7=1秒。長い順に 0, 1, 2, 3 になる
    assert [c.speaker for c in ed.cues] == [1, 2, 1, 0, 3, 0]
    assert ed.names == {0: "佐藤"}                                     # 名前は、人に付いて行く
    assert ed.undo() and [c.speaker for c in ed.cues] == [0, 5, 0, 1, 7, 1] and ed.names == {1: "佐藤"}


def test_renumber_does_nothing_when_already_in_order():
    ed = CueEditor([Cue(0, 5, "a", 0), Cue(5, 7, "b", 1)])
    assert not ed.renumber_speakers()


# ── セッションのファイル ───────────────────────────────────────────────────────────────
def test_session_roundtrip_through_a_file(tmp_path):
    ed = CueEditor(cues())
    ed.rename_speaker(0, "山田")
    path = sess.session_path(tmp_path / "talk.srt")
    assert path.name == "talk.snipsync.json" and sess.is_session_path(path)
    sess.write_session(path, sess.Session(title="talk", source=r"G:\a\talk.mp4", editor=ed.export_state(),
                                          settings={"margin": 0.2, "threshold": 4.0, "output_dir": "SECRET", "x": 1}))
    assert not list(tmp_path.glob("*.part"))
    got = sess.read_session(path)
    assert got.title == "talk" and got.source == r"G:\a\talk.mp4"
    assert got.settings == {"margin": 0.2, "threshold": 4.0}            # 必要な設定だけ（保存先などは残さない）
    assert CueEditor.from_state(got.editor).names == {0: "山田"}


@pytest.mark.parametrize("content", [
    "not json", "[]", json.dumps({"format": 99}), json.dumps({"format": 1}),
    json.dumps({"format": 1, "editor": {"original": [], "items": [[0, 1, "a", None]]}}),            # 出どころが無い
    json.dumps({"format": 1, "editor": {"original": [[0, 1, "a", None]], "items": [[0, 1, "a", None, [3]]]}}),
    json.dumps({"format": 1, "editor": {"original": [[0, 1, "a", -2]], "items": []}}),             # 負の話者
    json.dumps({"format": 1, "editor": {"original": [[0, "x", "a", None]], "items": []}}),
    json.dumps({"format": 1, "editor": {"original": [], "items": [], "names": {"a": "b"}}}),
])
def test_a_malformed_session_is_refused_not_crashed_on(tmp_path, content):
    p = tmp_path / "bad.snipsync.json"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(sess.SessionError):
        sess.read_session(p)


def test_a_missing_or_oversized_session_is_refused(tmp_path, monkeypatch):
    with pytest.raises(sess.SessionError):
        sess.read_session(tmp_path / "nope.snipsync.json")
    p = tmp_path / "big.snipsync.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sess, "MAX_BYTES", 1)
    with pytest.raises(sess.SessionError, match="too large"):
        sess.read_session(p)


# ── SRT の読み込み ─────────────────────────────────────────────────────────────────────
SRT = "1\n00:00:00,000 --> 00:00:02,000\n話者3：こんにちは\n\n2\n00:00:02,000 --> 00:00:04,000\nSpeaker 2: hello\n\n3\n00:00:04,000 --> 00:00:05,000\n山田：名前つき\n"


def test_parse_srt_reads_speaker_prefixes_only_when_asked():
    plain = parse_srt(SRT)
    assert [c.speaker for c in plain] == [None, None, None] and plain[0].text == "話者3：こんにちは"
    rich = parse_srt(SRT, speakers=True)
    assert [(c.speaker, c.text) for c in rich] == [(2, "こんにちは"), (1, "hello"), (None, "山田：名前つき")]


@pytest.mark.parametrize("text,expected", [
    ("話者1：はい", (0, "はい")), ("話者12:はい", (11, "はい")), ("Speaker 4: ok", (3, "ok")),
    ("話者0：x", (None, "話者0：x")), ("話者の話", (None, "話者の話")), ("こんにちは", (None, "こんにちは")),
])
def test_split_speaker_prefix(text, expected):
    assert split_speaker_prefix(text) == expected


# ── 話者の自動整理 ─────────────────────────────────────────────────────────────────────
def fragmented():
    """話者 A（大）と B（大）の会話に、小さなラベル（A の声が割れたもの）が混ざる。"""
    out, t = [], 0.0
    for i in range(6):
        out.append(Cue(t, t + 20, "Aの長い発言" * 5, 0))
        t += 20
        out.append(Cue(t, t + 1, "うん", 10 + i))                           # A に挟まれた小さなラベル
        t += 1
        out.append(Cue(t, t + 20, "Aの続きの長い発言" * 5, 0))
        t += 20
        out.append(Cue(t, t + 25, "Bの長い発言" * 5, 1))
        t += 25
    return out


def test_small_speakers_move_to_the_nearest_big_speaker_in_time():
    cs = fragmented()
    assert len({c.speaker for c in cs}) == 8
    plan = plan_small_speakers(cs, min_seconds=5)
    assert set(plan.values()) == {0}                           # 小さなラベルは、前後の A へ
    assert count_after(cs, plan) == 2
    assert all(cs[i].speaker >= 10 for i in plan)             # 動かすのは、小さなラベルの字幕だけ


def test_small_speaker_plan_never_collapses_everyone_into_nobody():
    cs = [Cue(0, 5, "a", 0), Cue(5, 8, "b", 1)]
    assert plan_small_speakers(cs, min_seconds=60) == {}        # 全員が小さい: 寄せ先が無いので、何もしない
    assert plan_small_speakers(cs, min_seconds=0) == {}


def test_small_speaker_goes_to_the_closer_neighbour():
    cs = [Cue(0, 50, "a", 0), Cue(50.0, 51, "x", 9), Cue(52.5, 100, "b", 1)]
    assert plan_small_speakers(cs, min_seconds=5) == {1: 0}      # 前との間 0 秒、後ろとの間 1.5 秒


def test_sandwiched_short_remarks_move_to_the_surrounding_speaker():
    cs = fragmented()
    plan = plan_sandwiched(cs, max_chars=3)
    assert len(plan) == 6 and set(plan.values()) == {0}
    assert plan_sandwiched(cs, max_chars=1) == {}              # 「うん」は 2 文字: 上限を下げれば、対象外
    boundary = [Cue(0, 5, "あ", 0), Cue(5, 6, "はい", 1), Cue(6, 9, "い", 2)]
    assert plan_sandwiched(boundary, 10) == {}                   # 前後が別の話者なら、挟まれていない


def test_speaker_seconds_ignores_cues_without_a_speaker():
    assert speaker_seconds([Cue(0, 4, "a", 0), Cue(4, 5, "b", None), Cue(5, 6, "c", 0)]) == {0: 5.0}
