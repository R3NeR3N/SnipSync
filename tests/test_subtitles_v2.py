"""日本語の文節改行・字幕分割・話者付与・倍速対応の境界計算。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core.subtitles import (
    Cue,
    build_cut_aligned_cues,
    chunks_to_boundaries,
    cues_from_segments,
    detect_cjk_lang,
    display_width,
    format_srt,
    normalize_turns,
    parse_v1_boundaries,
    speaker_for_span,
    speaker_label,
    tag_words,
    wrap_text,
)

budoux = pytest.importorskip("budoux")  # 文節改行テストは BudouX 必須（CI の最小構成ではスキップ）


# ── wrap_text ──────────────────────────────────────────────────────────────────
def test_wrap_text_breaks_at_phrase_boundaries_not_mid_phrase():
    text = "今日はスニプシンクの新機能について説明します"
    wrapped = wrap_text(text, 10, "ja")
    assert wrapped.replace("\n", "") == text
    for line in wrapped.split("\n"):
        assert display_width(line) <= 20
    # 文節の途中では切らない: 「新機能について」が1行に収まっている
    assert "新機能について" in wrapped.split("\n")


def test_wrap_text_short_text_untouched_and_zero_disables():
    assert wrap_text("こんにちは", 10, "ja") == "こんにちは"
    long = "あ" * 50
    assert wrap_text(long, 0, "ja") == long


def test_wrap_text_force_splits_single_overlong_phrase():
    wrapped = wrap_text("あ" * 25, 10, "ja")
    assert all(display_width(line) <= 20 for line in wrapped.split("\n"))
    assert wrapped.replace("\n", "") == "あ" * 25


def test_wrap_text_english_wraps_on_spaces():
    wrapped = wrap_text("this is a rather long english subtitle line that wraps", 12, "en")
    assert all(len(line) <= 24 for line in wrapped.split("\n"))
    assert " ".join(wrapped.split("\n")) == "this is a rather long english subtitle line that wraps"


def test_detect_cjk_lang():
    assert detect_cjk_lang("こんにちは") == "ja"
    assert detect_cjk_lang("hello") is None
    assert detect_cjk_lang("x", "ja") == "ja"
    assert detect_cjk_lang("x", "en") is None


# ── 話者 ────────────────────────────────────────────────────────────────────────
def test_normalize_turns_renumbers_by_first_appearance():
    turns = [(5.0, 6.0, 7), (0.0, 2.0, 3), (2.0, 4.0, 7)]
    assert normalize_turns(turns) == [(0.0, 2.0, 0), (2.0, 4.0, 1), (5.0, 6.0, 1)]


def test_speaker_for_span_prefers_largest_overlap_then_nearest():
    turns = [(0.0, 2.0, 0), (2.0, 5.0, 1)]
    assert speaker_for_span(1.5, 3.0, turns) == 1          # 重なり: 0側0.5s / 1側1.0s
    assert speaker_for_span(5.4, 5.6, turns) == 1          # 重なり無し -> 1秒以内で最寄り
    assert speaker_for_span(20.0, 21.0, turns) is None     # 遠すぎる


def test_speaker_label_language():
    assert speaker_label(0, "ja") == "話者1"
    assert speaker_label(1, "en") == "Speaker 2"


def test_tag_words_attaches_speaker_as_fourth_element():
    tagged = tag_words([(0.1, 0.5, "A"), (2.1, 2.5, "B")], [(0.0, 2.0, 0), (2.0, 4.0, 1)])
    assert [w[3] for w in tagged] == [0, 1]


# ── カット整合 + 話者 + 長さ分割 ─────────────────────────────────────────────────
def test_cut_aligned_cues_split_on_speaker_change_inside_one_cut():
    words = [(0.0, 0.4, "A", 0), (0.5, 0.9, "B", 0), (1.0, 1.4, "C", 1), (1.5, 1.9, "D", 1)]
    cues = build_cut_aligned_cues(words, [(0.0, 2.0)], [0.0, 2.0])
    assert [(c.text, c.speaker) for c in cues] == [("AB", 0), ("CD", 1)]
    assert cues[0].start == 0.0          # カット境界に厳密一致
    assert cues[1].start == 1.0          # 話者交代は最初の単語の開始
    assert cues[0].end <= cues[1].start  # 重ならない


def test_cut_aligned_cues_without_speaker_matches_legacy_srt():
    from snipsync.core.subtitles import build_cut_aligned_srt
    words = [(0.0, 0.9, "A"), (1.0, 1.9, "B"), (2.0, 2.9, "C"), (3.0, 3.9, "D")]
    srt = build_cut_aligned_srt(words, [(0.0, 4.0)], [0.0, 2.0])
    cues = build_cut_aligned_cues(words, [(0.0, 4.0)], [0.0, 2.0])
    assert srt == format_srt(cues)
    assert len(cues) == 2 and cues[1].start == 2.0


def test_long_cue_is_split_to_fit_two_lines():
    chars = "こんにちは今日はスニプシンクの新機能について説明しますまず無音カットの精度についてお話しします"
    words = [(i * 0.3, i * 0.3 + 0.25, c) for i, c in enumerate(chars)]
    cues = build_cut_aligned_cues(words, [(0.0, 9.0)], [0.0, 9.0], max_chars=10, max_lines=2, lang="ja")
    assert len(cues) >= 2
    for c in cues:
        assert wrap_text(c.text, 10, "ja").count("\n") + 1 <= 2
    assert "".join(c.text for c in cues) == chars
    assert cues[0].start == 0.0


def test_cues_from_segments_keeps_natural_when_nothing_requested():
    cues = cues_from_segments([(0.5, 2.3, " Hello world ", None)])
    assert cues == [Cue(0.5, 2.3, "Hello world", None)]


def test_cues_from_segments_assigns_speaker_per_segment_without_words():
    cues = cues_from_segments([(0.0, 2.0, "one", None), (3.0, 5.0, "two", None)],
                              turns=[(0.0, 2.5, 0), (2.5, 6.0, 1)])
    assert [c.speaker for c in cues] == [0, 1]


def test_format_srt_prefixes_speaker_and_wraps():
    cues = [Cue(0.0, 2.0, "今日はスニプシンクの新機能について説明します", 1)]
    srt = format_srt(cues, max_chars=10, lang="ja", speaker_labels=True, ui_lang="ja")
    assert "話者2：" in srt and "00:00:00,000 --> 00:00:02,000" in srt
    assert "話者2：" not in format_srt(cues, speaker_labels=False)
    assert "Speaker 2: " in format_srt(cues, speaker_labels=True, ui_lang="en")


# ── 倍速化を含む境界計算（auto-editor v1 chunks）──────────────────────────────────
def test_chunks_to_boundaries_divides_sped_up_chunks_by_speed():
    # 30f(=3s)残す / 80f(=8s)を8倍速(=1s) / 30f残す @tb=10
    chunks = [(0, 30, 1.0), (30, 110, 8.0), (110, 140, 1.0)]
    assert chunks_to_boundaries(chunks, 10) == [0.0, 3.0, 4.0, 7.0]


def test_chunks_to_boundaries_drops_cut_and_handles_empty():
    assert chunks_to_boundaries([(0, 30, 99999.0)], 10) == []
    assert chunks_to_boundaries([], 10) == []
    assert chunks_to_boundaries([(0, 30, 1.0)], 0) == []


def test_parse_v1_boundaries_uses_speed(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"chunks": [[0, 30, 1.0], [30, 110, 8.0]]}), encoding="utf-8")
    assert parse_v1_boundaries(p, 10) == [0.0, 3.0, 4.0]


# ── 倍速モードの境界: 小数のまま累積し、境界ごとにフレームへ丸める（31.7.2 の XML と最大1フレーム以内）──
def test_chunks_to_boundaries_accumulate_fractions_then_round_per_boundary():
    # 実測データ（st30.mp4 を --when-inactive speed:8 で処理した 31.7.2 の XML のクリップ位置 0,4,159,167,...）の先頭部分
    chunks = [(0, 29, 8.0), (29, 184, 1.0), (184, 247, 8.0), (247, 295, 1.0)]
    frames = [round(b * 30) for b in chunks_to_boundaries(chunks, 30)]
    assert frames == [0, 4, 159, 167, 215]       # 3.625→4 / 158.625→159 / 166.5→167 / 214.5→215（実測と一致）


def test_chunks_to_boundaries_collapse_sub_frame_chunks():
    # 2フレームの倍速区間(0.25f)は、丸めると前後と同じ位置になり境界が重複しない
    chunks = [(0, 30, 1.0), (30, 32, 8.0), (32, 62, 1.0)]
    assert chunks_to_boundaries(chunks, 30) == [0.0, 1.0, 2.0]


def test_chunks_to_boundaries_stay_within_one_frame_of_exact_time():
    chunks = [(0, 29, 8.0), (29, 61, 1.0), (61, 90, 8.0), (90, 150, 1.0)] * 5
    exact, acc = [], 0.0
    shifted = []
    off = 0
    for c in chunks:
        shifted.append((c[0] + off, c[1] + off, c[2]))
        off += c[1] - c[0] + 5
    for s_, e_, sp in shifted:
        acc += (e_ - s_) / sp
        exact.append(acc / 30)
    got = chunks_to_boundaries(shifted, 30)[1:]
    for b in got:
        assert min(abs(b - x) for x in exact) <= 0.5 / 30 + 1e-6    # 各境界は正確な時刻から半フレーム以内


# ── 字幕の時刻を、実際に声がある区間に合わせる補正 ───────────────────────────────────────
from snipsync.core.subtitles import refine_cue_times  # noqa: E402


def C(a, b, t="x", s=None):
    return Cue(a, b, t, s)


def times(cues):
    return [(round(c.start, 3), round(c.end, 3)) for c in cues]


def test_refine_the_reported_case_late_voice_and_a_voice_that_continues_past_the_last_cut():
    """実測（あなたの録画）: 最後の字幕は 39.72-40.883。直前の字幕の声が 40.04 まで食い込み、「今」は 40.38、
    「から」は 41.05-41.95。最後のカット点は 40.883、全体は 41.95 秒。VAD の実測値を、そのまま使う。"""
    cues = [C(36.0, 37.86), C(37.86, 38.82), C(38.82, 39.72), C(39.72, 40.883, "今から")]
    speech = [(36.41, 37.96), (38.3, 40.04), (40.38, 40.84), (41.05, 41.95)]
    out = refine_cue_times(cues, speech, boundaries=[38.817, 40.883], total=41.95)
    assert times(out)[-1] == (40.38, 41.95)            # 開始は声の始まりへ、終了はカット点をこえて、声の終わりまで
    assert out[-1].text == "今から"
    assert out[-2].end <= out[-1].start                # 前の字幕は、食い込んでいた声の端まで延びても、重ならない


def test_refine_ignores_a_short_tail_of_the_previous_voice_at_the_head_of_a_cue():
    cues = [C(5.0, 6.0, "a"), C(6.0, 8.0, "b")]
    out = refine_cue_times(cues, [(4.0, 6.3), (7.0, 7.9)], total=10)
    assert times(out) == [(5.0, 6.3), (7.0, 8.0)]      # 終了の 0.1 秒の違いは、そのまま
    out = refine_cue_times(cues, [(4.0, 7.0), (7.4, 7.9)], total=10)      # 食い込みが長い: 続いている声
    assert out[1].start == 6.0


def test_refine_does_not_move_a_start_that_sits_on_a_cut_point():
    cues = [C(17.633, 18.58)]
    out = refine_cue_times(cues, [(17.9, 18.6)], boundaries=[17.633], total=30)
    assert out[0].start == 17.633                      # クリップの頭にそろえる設計は、保つ


def test_refine_moves_a_late_start_only_when_the_gap_is_clear():
    out = refine_cue_times([C(5.0, 7.0)], [(5.1, 7.0)], total=20)
    assert times(out) == [(5.0, 7.0)]                  # 0.1 秒のずれは、そのまま
    out = refine_cue_times([C(5.0, 7.0)], [(5.6, 7.0)], total=20)
    assert times(out) == [(5.6, 7.0)]


def test_refine_never_extends_into_the_next_cue():
    cues = [C(1.0, 2.0), C(3.0, 4.0)]
    out = refine_cue_times(cues, [(1.0, 2.0), (2.1, 5.0)], total=10)
    assert out[0].end == 3.0 and out[1].start == 3.0   # 次の字幕の開始まで。こえない


def test_refine_extends_across_short_pauses_but_stops_at_longer_silence():
    cues = [C(1.0, 2.0)]
    out = refine_cue_times(cues, [(1.0, 2.0), (2.2, 3.4), (5.0, 6.0)], total=10)
    assert times(out) == [(1.0, 3.4)]                  # 0.2 秒の途切れは続いている。次の無音で止まる
    out = refine_cue_times(cues, [(1.0, 2.0), (2.6, 3.4)], total=10)
    assert times(out) == [(1.0, 2.0)]                  # 0.6 秒の途切れは、別の発話（文字になっていない声）とみなす


def test_refine_shrinks_an_end_that_is_too_late():
    out = refine_cue_times([C(1.0, 5.0)], [(1.0, 2.0)], total=10)
    assert times(out) == [(1.0, 2.0)]
    out = refine_cue_times([C(1.0, 2.2)], [(1.0, 2.0)], total=10)
    assert times(out) == [(1.0, 2.2)]                  # 0.2 秒の違いは、そのまま


def test_refine_keeps_cues_that_overlap_no_speech_and_ignores_empty_inputs():
    cues = [C(1.0, 2.0)]
    assert refine_cue_times(cues, [(5.0, 6.0)], total=10) == cues
    assert refine_cue_times(cues, [], total=10) == cues
    assert refine_cue_times([], [(1, 2)], total=10) == []


def test_refine_keeps_the_text_speaker_and_order_and_never_overlaps():
    cues = [C(0.0, 1.5, "a", 0), C(1.5, 3.0, "b", 1), C(4.0, 6.0, "c", 0)]
    speech = [(0.3, 1.2), (1.9, 3.4), (4.4, 6.4)]
    out = refine_cue_times(cues, speech, boundaries=[1.5], total=7.0)
    assert [(c.text, c.speaker) for c in out] == [("a", 0), ("b", 1), ("c", 0)]
    for a, b in zip(out, out[1:], strict=False):
        assert a.end <= b.start + 1e-9 and a.start < a.end


def test_refine_does_not_make_a_cue_shorter_than_the_minimum():
    out = refine_cue_times([C(1.0, 3.0)], [(2.9, 3.0)], total=10)
    assert times(out) == [(1.0, 3.0)]                  # 補正すると 0.1 秒になる: やめる


def test_refine_does_not_change_the_input():
    cues = [C(39.72, 40.883)]
    refine_cue_times(cues, [(40.35, 41.8)], boundaries=[40.883], total=41.95)
    assert times(cues) == [(39.72, 40.883)]
