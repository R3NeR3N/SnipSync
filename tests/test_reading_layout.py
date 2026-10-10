"""文字起こし（.txt / .md）を読みやすく整える処理（transcript.reading_turns など）。字幕 .srt には効かない。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core.subtitle_edit import render  # noqa: E402
from snipsync.core.subtitles import Cue  # noqa: E402
from snipsync.core.transcript import cues_to_md, cues_to_txt, reading_turns, write_transcripts  # noqa: E402


def broken_sentence():
    """A の 1 つの文が、B のあいづち「うまい。」で割れている（実際の録音で多い形）。"""
    return [Cue(0.0, 5.0, "地域のお祭りで出る食料廃棄物を", 0), Cue(5.0, 6.0, "うまい。", 1),
            Cue(6.0, 9.0, "こと処理したいとか、", 0), Cue(9.0, 12.0, "なるほど。", 1)]


def test_a_short_remark_between_the_same_speaker_goes_into_brackets_and_the_sentence_is_whole():
    turns = reading_turns(broken_sentence())
    assert [(t.speaker, t.paras[0][1]) for t in turns] == [
        (0, "地域のお祭りで出る食料廃棄物を（話者2：うまい。）こと処理したいとか、"), (1, "なるほど。")]


def test_the_remark_can_be_dropped_or_kept_as_it_is():
    dropped = reading_turns(broken_sentence(), backchannel="drop")
    assert dropped[0].paras[0][1] == "地域のお祭りで出る食料廃棄物をこと処理したいとか、" and len(dropped) == 2
    kept = reading_turns(broken_sentence(), backchannel="keep")
    assert [t.speaker for t in kept] == [0, 1, 0, 1]


def test_a_longer_remark_is_a_real_turn_and_stays_separate():
    cues = [Cue(0, 5, "前半の話をします", 0), Cue(5, 9, "それはちょっと違うと思います", 1), Cue(9, 14, "後半の話をします", 0)]
    assert [t.speaker for t in reading_turns(cues)] == [0, 1, 0]


def test_a_remark_between_different_speakers_is_not_a_backchannel():
    cues = [Cue(0, 5, "最初の話", 0), Cue(5, 6, "はい", 1), Cue(6, 9, "次の話", 2)]
    assert [t.speaker for t in reading_turns(cues)] == [0, 1, 2]


def test_english_uses_plain_brackets_and_a_space():
    cues = [Cue(0, 5, "we should fix", 0), Cue(5, 6, "yes", 1), Cue(6, 9, "the roof today", 0)]
    assert reading_turns(cues, ui_lang="en")[0].paras[0][1] == "we should fix (Speaker 2: yes) the roof today"


def test_names_are_used_in_the_bracketed_remark():
    out = reading_turns(broken_sentence(), names={1: "佐藤"})
    assert "（佐藤：うまい。）" in out[0].paras[0][1]


def test_a_long_turn_is_split_into_paragraphs_at_sentence_ends():
    cues = [Cue(float(i * 10), float(i * 10 + 9), "これは長い発言の一文です。" * 3, 0) for i in range(4)]
    paras = reading_turns(cues, para_chars=60)[0].paras
    assert len(paras) >= 2 and all(p[1].endswith("。") for p in paras) and paras[0][0] == 0.0
    assert paras[1][0] > 0.0                                          # 段落の開始時刻は、その段落の最初の字幕


def test_a_long_silence_after_a_sentence_end_starts_a_new_paragraph_but_not_mid_sentence():
    cues = [Cue(0, 5, "最初の話です。", 0), Cue(10, 15, "しばらくして続きです。", 0)]
    assert len(reading_turns(cues, para_gap=2.0)[0].paras) == 2
    mid = [Cue(0, 5, "最初の話が", 0), Cue(10, 15, "続きます。", 0)]
    assert len(reading_turns(mid, para_gap=2.0)[0].paras) == 1        # 文の途中なら、間があいても切らない


def test_cues_without_speakers_become_paragraphs_too():
    cues = [Cue(0, 5, "一つ目です。", None), Cue(5, 9, "二つ目です。", None)]
    turns = reading_turns(cues)
    assert len(turns) == 1 and turns[0].paras[0][1] == "一つ目です。二つ目です。"


def test_empty_cues_are_ignored():
    assert reading_turns([]) == []
    assert reading_turns([Cue(0, 1, "  ", 0)]) == []


# ── 書き出し ────────────────────────────────────────────────────────────────────────
def test_txt_in_reading_mode_has_one_line_per_paragraph_with_the_speaker_on_every_line():
    txt = cues_to_txt(broken_sentence(), reading=True)
    assert txt.splitlines() == [
        "[00:00:00] 話者1：地域のお祭りで出る食料廃棄物を（話者2：うまい。）こと処理したいとか、",
        "[00:00:09] 話者2：なるほど。"]
    long = [Cue(float(i * 10), float(i * 10 + 9), "これは長い発言の一文です。" * 3, 0) for i in range(4)]
    lines = cues_to_txt(long, reading=True).splitlines()
    assert len(lines) >= 1 and all("話者1：" in ln for ln in lines)


def test_md_in_reading_mode_has_one_heading_per_turn_and_a_blank_line_between_paragraphs():
    long = [Cue(float(i * 10), float(i * 10 + 9), "これは長い発言の一文です。" * 3, 0) for i in range(8)]
    md = cues_to_md(long + [Cue(90, 95, "次の人です。", 1)], title="t", reading=True)
    assert md.count("## ") == 2 and "話者: 話者1、話者2" in md
    assert "\n\nこれは長い発言の一文です。" in md


def test_the_default_layout_is_unchanged():
    old = cues_to_txt(broken_sentence())
    assert len(old.splitlines()) == 4                                  # 従来どおり、話者交代ごとに 1 行


def test_render_passes_the_switch_and_srt_is_never_changed():
    cues = broken_sentence()
    assert len(render(cues, "txt", reading=True).splitlines()) == 2
    assert len(render(cues, "txt", reading=False).splitlines()) == 4
    assert render(cues, "srt", reading=True) == render(cues, "srt", reading=False)


def test_write_transcripts_honours_the_reading_switch(tmp_path):
    write_transcripts(broken_sentence(), tmp_path / "a", title="a", want_txt=True, want_md=True, reading=True)
    assert len((tmp_path / "a.txt").read_text(encoding="utf-8").splitlines()) == 2
    write_transcripts(broken_sentence(), tmp_path / "b", title="b", want_txt=True, want_md=False)
    assert len((tmp_path / "b.txt").read_text(encoding="utf-8").splitlines()) == 4


def test_reading_defaults_and_the_switches_exist():
    from snipsync.core.pipeline import PipelineParams
    from snipsync.presets import SETTING_KEYS
    assert PipelineParams.__dataclass_fields__["reading"].default is True and "reading" in SETTING_KEYS
