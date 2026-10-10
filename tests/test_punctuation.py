"""句読点（core/punctuation.py）と、字幕 .srt には付けない取り決め。語は (開始秒, 終了秒, 文字[, 話者])。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402

from snipsync.core import pipeline  # noqa: E402
from snipsync.core.punctuation import (  # noqa: E402
    normalize_marks,
    prompt_for,
    punctuate_words,
    strip_subtitle_punctuation,
)
from snipsync.core.subtitle_edit import render  # noqa: E402
from snipsync.core.subtitles import Cue, cues_from_segments, format_srt  # noqa: E402


def seq(*items, start=0.0):
    """(文字, 次の語までの間) の並びから、語列を作る。1 語 0.3 秒。"""
    words, t = [], start
    for text, gap in items:
        words.append((t, t + 0.3, text))
        t += 0.3 + gap
    return words


def texts(words):
    return [w[2] for w in words]


# ── 見本文 ──────────────────────────────────────────────────────────────────────────
def test_the_prompt_exists_only_for_the_language_it_was_measured_on():
    assert prompt_for("ja") and "、" in prompt_for("ja") and "。" in prompt_for("ja")
    assert prompt_for("JA") == prompt_for("ja")
    assert prompt_for("en") is None and prompt_for(None) is None and prompt_for("zh") is None


# ── 補う規則 ────────────────────────────────────────────────────────────────────────
def test_a_sentence_final_form_followed_by_a_pause_gets_a_full_stop():
    out = punctuate_words(seq(("今日は", 0.0), ("説明します", 0.5), ("次に", 0.0), ("進みます", 0.0)), "ja")
    assert texts(out) == ["今日は", "説明します。", "次に", "進みます。"]            # 最後は、文の終わり


def test_a_question_form_gets_a_question_mark():
    out = punctuate_words(seq(("どうでしたか", 0.6), ("はい", 0.0)), "ja")
    assert texts(out)[0] == "どうでしたか？"


def test_a_pause_inside_a_sentence_gets_a_comma_but_a_tiny_one_does_not():
    out = punctuate_words(seq(("今日は", 0.5), ("天気が", 0.1), ("いいですね", 0.0)), "ja")
    assert texts(out) == ["今日は、", "天気が", "いいですね。"]


def test_a_conjunction_gets_a_comma_after_a_short_pause():
    out = punctuate_words(seq(("行きたいんです", 0.0), ("けど", 0.2), ("時間が", 0.0), ("ありません", 0.0)), "ja")
    assert "けど、" in texts(out)


def test_a_long_pause_ends_a_sentence_even_without_a_final_form():
    out = punctuate_words(seq(("えーと", 1.2), ("そうですね", 0.0)), "ja")
    assert texts(out)[0] == "えーと。"


def test_a_speaker_change_ends_the_sentence():
    words = [(0.0, 0.3, "そうなんです", 0), (0.3, 0.6, "はい", 1), (0.6, 0.9, "ありがとう", 1)]
    out = punctuate_words(words, "ja")
    assert texts(out)[0] == "そうなんです。" and out[0][3] == 0 and out[1][3] == 1       # 話者はそのまま


def test_a_final_form_directly_followed_by_a_sentence_opener_is_split_even_without_a_pause():
    """Whisper が句読点を落とした「ありがとうございますはいのこさん…」のような所。"""
    out = punctuate_words(seq(("ありがとうございます", 0.0), ("はい", 0.0), ("のこさん", 0.0), ("どうでしたか", 0.0), ("私ね", 0.0)), "ja")
    assert texts(out)[0] == "ありがとうございます。" and texts(out)[3] == "どうでしたか？"


def test_a_long_run_without_punctuation_gets_a_comma_at_a_small_pause():
    words = seq(*[("あいうえお", 0.0)] * 9, ("かきくけこ", 0.25), ("さしすせそ", 0.0))        # 45 字続いたあとの、0.25 秒の間
    out = punctuate_words(words, "ja")
    assert texts(out)[9] == "かきくけこ、"


def test_existing_punctuation_is_kept_and_not_doubled():
    out = punctuate_words(seq(("そうです。", 0.8), ("はい、", 0.8), ("どうも", 0.0)), "ja")
    assert texts(out)[:2] == ["そうです。", "はい、"]


def test_half_width_marks_in_japanese_text_become_full_width_but_numbers_are_left_alone():
    assert normalize_marks("どうですか?はい,そうです.") == "どうですか？はい、そうです。"
    assert normalize_marks("3.14と1,000") == "3.14と1,000"


def test_other_languages_and_empty_input_are_left_alone():
    words = seq(("hello ", 0.5), ("world", 0.0))
    assert punctuate_words(words, "en") == words
    assert punctuate_words([], "ja") == []


def test_word_count_times_and_speakers_never_change():
    words = [(0.0, 0.3, "今日は", 0), (0.8, 1.1, "説明します", 0), (1.2, 1.5, "はい", 1)]
    out = punctuate_words(words, "ja")
    assert [(w[0], w[1], w[3]) for w in out] == [(w[0], w[1], w[3]) for w in words]


# ── 字幕（.srt）には付けない ────────────────────────────────────────────────────────────
def test_srt_drops_commas_and_full_stops_but_keeps_question_marks():
    assert strip_subtitle_punctuation("そうですね、はい。どうですか？") == "そうですねはいどうですか？"
    cues = [Cue(0.0, 2.0, "そうですね、はい。", 0), Cue(2.0, 4.0, "どうですか？", 1)]
    srt = format_srt(cues, speaker_labels=True, strip_punct=True)
    assert "話者1：そうですねはい\n" in srt and "話者2：どうですか？" in srt and "、" not in srt and "。" not in srt
    assert "、" in format_srt(cues)                                   # 既定では、何も変えない（互換）


def test_the_editor_renders_srt_without_punctuation_but_txt_and_md_keep_it():
    cues = [Cue(0.0, 2.0, "そうですね、はい。", 0)]
    assert "、" not in render(cues, "srt") and "。" not in render(cues, "srt")
    assert "そうですね、はい。" in render(cues, "txt") and "そうですね、はい。" in render(cues, "md", title="t")


# ── 字幕を作る経路 ──────────────────────────────────────────────────────────────────
def test_cues_from_segments_punctuates_when_asked():
    words = seq(("今日は", 0.0), ("説明します", 0.5), ("次に", 0.0), ("進みます", 0.0))
    segs = [(0.0, 3.0, "今日は説明します次に進みます", words)]
    plain = cues_from_segments(segs, None, lang="ja")
    assert plain[0].text == "今日は説明します次に進みます"                  # 語を使わない経路（折り返しも話者も無し）は、変わらない
    marked = cues_from_segments(segs, None, max_chars=20, lang="ja", punctuate=True)
    assert "".join(c.text for c in marked) == "今日は説明します。次に進みます。"
    unmarked = cues_from_segments(segs, None, max_chars=20, lang="ja")
    assert "".join(c.text for c in unmarked) == "今日は説明します次に進みます"
    words4 = [(w[0], w[1], w[2]) for w in words]
    by_turn = cues_from_segments([(0.0, 3.0, "x", words4)], [(0.0, 1.2, 0), (1.2, 3.0, 1)], max_chars=0, lang="ja",
                                 punctuate=True)
    assert all(c.text for c in by_turn)


# ── パイプラインの部品 ──────────────────────────────────────────────────────────────
def test_language_detection_failure_just_means_no_prompt():
    class Broken:
        def detect_language(self, audio):
            raise RuntimeError("boom")

    assert pipeline._detect_language(Broken(), Path("nonexistent.wav")) is None


def test_punctuation_is_on_by_default_and_the_switch_is_saved_in_presets():
    from snipsync.presets import SETTING_KEYS
    assert pipeline.PipelineParams.__dataclass_fields__["punctuate"].default is True
    assert "punctuate" in SETTING_KEYS


@pytest.mark.parametrize("model_langs", ["en"])
def test_english_only_models_never_get_the_japanese_prompt(model_langs):
    from snipsync.core.models import MODELS
    assert MODELS["distil-en"].langs == model_langs
    assert "language" in MODELS["kotoba-ja"].transcribe_kwargs          # 言語が固定のモデルにも、見本文は付けない
