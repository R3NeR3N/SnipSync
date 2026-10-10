"""話者の切り替わりを、語・文節の途中に置かない処理（subtitles.smooth_word_speakers / tag_words）。
語は (開始秒, 終了秒, 文字, 話者) の並び。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core.subtitles import (  # noqa: E402
    cues_from_segments,
    smooth_word_speakers,
    tag_words,
)


def test_a_phrase_takes_the_speaker_who_spoke_it_longest():
    words = [(0.0, 0.30, "毎", 2), (0.30, 0.40, "月", 3), (0.4, 1.4, "ちょっとずつ", 2)]
    out = smooth_word_speakers(words, "ja")
    assert [w[3] for w in out][:2] == [2, 2]                    # 「毎月」は、1 人の発言


def test_a_short_swap_between_the_same_speaker_goes_back_to_that_speaker():
    words = [(0.0, 1.0, "hello ", 0), (1.0, 1.2, "hmm ", 1), (1.2, 2.5, "world", 0)]
    assert [w[3] for w in smooth_word_speakers(words, "en")] == [0, 0, 0]


def test_a_longer_interjection_is_kept():
    words = [(0.0, 1.0, "hello ", 0), (1.0, 2.2, "yes really ", 1), (2.2, 3.5, "world", 0)]
    assert [w[3] for w in smooth_word_speakers(words, "en")] == [0, 1, 0]


def test_different_neighbours_are_not_touched():
    words = [(0.0, 1.0, "a ", 0), (1.0, 1.2, "b ", 1), (1.2, 2.5, "c", 2)]
    assert [w[3] for w in smooth_word_speakers(words, "en")] == [0, 1, 2]


def test_empty_and_unlabelled_words_pass_through():
    assert smooth_word_speakers([], "ja") == []
    words = [(0.0, 1.0, "a ", None), (1.0, 2.0, "b", None)]
    assert smooth_word_speakers(words, "en") == words


def test_tag_words_assigns_by_overlap_and_then_smooths():
    turns = [(0.0, 0.32, 2), (0.32, 3.0, 3)]                    # 境目が「毎月」の真ん中
    words = [(0.0, 0.30, "毎"), (0.30, 0.45, "月"), (0.45, 1.4, "ちょっとずつ")]
    tagged = tag_words(words, turns, "ja")
    assert tagged[0][3] == tagged[1][3]                          # 「毎」と「月」が別の人にならない


def test_cues_split_at_the_phrase_boundary_not_inside_the_phrase():
    turns = [(0.0, 0.32, 0), (0.32, 3.0, 1)]                    # 境目は「毎月」の真ん中。本当の交代は、文節の切れ目
    words = [(0.0, 0.30, "毎"), (0.30, 0.45, "月"), (0.45, 1.4, "ちょっとずつ")]
    cues = cues_from_segments([(0.0, 1.4, "毎月ちょっとずつ", words)], turns, max_chars=0, lang="ja")
    assert [(c.text, c.speaker) for c in cues] == [("毎月", 0), ("ちょっとずつ", 1)]
