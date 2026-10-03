"""字幕の編集ロジック（画面なし）。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from subtitle_edit import CueEditor, format_for_path, render, save  # noqa: E402
from subtitles import Cue  # noqa: E402
from transcript import parse_srt  # noqa: E402


def sample():
    return [Cue(0.0, 2.0, "こんにちは、", 0), Cue(2.0, 6.0, "今日は説明します。", 0), Cue(6.5, 8.0, "お願いします。", 1)]


def test_editor_copies_input_and_starts_clean():
    src = sample()
    ed = CueEditor(src)
    ed.set_text(0, "changed")
    assert src[0].text == "こんにちは、"          # 元のリストは変えない
    assert len(ed) == 3 and ed.dirty and ed.is_changed(0) and not ed.is_changed(1)
    assert CueEditor(src).dirty is False


def test_set_text_reports_change_and_ignores_identical():
    ed = CueEditor(sample())
    assert ed.set_text(1, "今日は説明します。") is False and ed.dirty is False
    assert ed.set_text(1, "今日はご説明します。") is True and ed.dirty is True
    assert ed.cue(1).text == "今日はご説明します。"
    assert ed.cue(1).start == 2.0 and ed.cue(1).end == 6.0       # 時刻は変わらない


def test_revert_restores_original_text():
    ed = CueEditor(sample())
    ed.set_text(0, "x")
    assert ed.revert(0) is True and ed.cue(0).text == "こんにちは、"
    assert ed.revert(0) is False


def test_set_speaker():
    ed = CueEditor(sample())
    assert ed.set_speaker(0, 1) is True and ed.cue(0).speaker == 1
    assert ed.set_speaker(0, 1) is False
    assert ed.set_speaker(0, None) is True and ed.speakers() == [0, 1]


def test_delete_removes_one_cue():
    ed = CueEditor(sample())
    ed.delete(1)
    assert [c.text for c in ed.cues] == ["こんにちは、", "お願いします。"] and ed.dirty


def test_merge_next_joins_text_extends_end_and_keeps_first_speaker():
    ed = CueEditor(sample())
    assert ed.merge_next(0) is True
    assert len(ed) == 2
    assert ed.cue(0).text == "こんにちは、今日は説明します。"
    assert (ed.cue(0).start, ed.cue(0).end, ed.cue(0).speaker) == (0.0, 6.0, 0)


def test_merge_next_on_last_or_invalid_index_does_nothing():
    ed = CueEditor(sample())
    assert ed.merge_next(2) is False and ed.merge_next(-1) is False and len(ed) == 3 and not ed.dirty


def test_merge_uses_a_space_for_space_separated_languages():
    ed = CueEditor([Cue(0, 1, "Hello", None), Cue(1, 2, "world", None)])
    ed.merge_next(0)
    assert ed.cue(0).text == "Hello world"


def test_split_divides_text_and_time_proportionally():
    ed = CueEditor([Cue(10.0, 20.0, "あいうえおかきくけこ", 1)])
    assert ed.split(0, 4) is True
    a, b = ed.cues
    assert (a.text, b.text) == ("あいうえ", "おかきくけこ")
    assert a.start == 10.0 and b.end == 20.0 and a.end == b.start == pytest.approx(14.0)
    assert a.speaker == b.speaker == 1


@pytest.mark.parametrize("offset", [0, 10, -3, 99])
def test_split_at_the_edges_is_refused(offset):
    ed = CueEditor([Cue(0, 5, "あいうえおかきくけこ", None)])
    if offset in (0, 10):
        assert ed.split(0, offset) is False
        assert len(ed) == 1 and not ed.dirty


def test_split_ignores_whitespace_only_halves():
    ed = CueEditor([Cue(0, 5, "あいう   ", None)])
    assert ed.split(0, 3) is False


def test_mark_saved_clears_dirty():
    ed = CueEditor(sample())
    ed.delete(0)
    ed.mark_saved()
    assert ed.dirty is False


def test_render_formats_reflect_edits_and_speakers():
    ed = CueEditor(sample())
    ed.set_text(0, "こんばんは、")
    srt = render(ed.cues, "srt")
    assert "話者1：こんばんは、" in srt and "00:00:00,000 --> 00:00:02,000" in srt
    assert render(ed.cues, "txt").splitlines()[0].startswith("[00:00:00] 話者1：こんばんは、")
    assert render(ed.cues, "md", title="t").startswith("# t\n")
    assert "[00:00:00]" not in render(ed.cues, "txt", timestamps=False)


def test_render_skips_cues_emptied_by_the_user():
    ed = CueEditor(sample())
    ed.set_text(1, "  ")
    assert "今日は" not in render(ed.cues, "srt") and render(ed.cues, "srt").count("-->") == 2


def test_render_rejects_unknown_format():
    with pytest.raises(ValueError):
        render(sample(), "docx")


def test_format_for_path():
    assert format_for_path("a.MD") == "md" and format_for_path("a.txt") == "txt"
    assert format_for_path("a.srt") == "srt" and format_for_path("a.xyz") == "srt"


def test_save_writes_each_format_and_srt_roundtrips(tmp_path):
    ed = CueEditor(sample())
    ed.set_text(2, "お願いいたします。")
    for ext in ("srt", "txt", "md"):
        assert save(ed.cues, tmp_path / f"out.{ext}") == ext
        assert "お願いいたします。" in (tmp_path / f"out.{ext}").read_text(encoding="utf-8")
    back = parse_srt((tmp_path / "out.srt").read_text(encoding="utf-8"))
    assert [(c.start, c.end) for c in back] == [(0.0, 2.0), (2.0, 6.0), (6.5, 8.0)]
