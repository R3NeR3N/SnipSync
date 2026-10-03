"""日本語の文節改行・字幕分割・話者付与・倍速対応の境界計算。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from subtitles import (
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
    from subtitles import build_cut_aligned_srt
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
