"""字幕の編集ロジック（画面なし）。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core.subtitle_edit import CueEditor, format_for_path, render, save  # noqa: E402
from snipsync.core.subtitles import Cue  # noqa: E402
from snipsync.core.transcript import parse_srt  # noqa: E402


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


# ── 元に戻す・やり直す、結合・分割のあとの「最初に戻す」、話者名 ─────────────────────────
def texts(ed):
    return [c.text for c in ed.cues]


def test_revert_after_merge_restores_both_original_cues():
    ed = CueEditor(sample())
    ed.merge_next(0)
    assert len(ed) == 2 and ed.is_changed(0)
    assert ed.revert(0) is True
    assert texts(ed) == ["こんにちは、", "今日は説明します。", "お願いします。"]
    assert [(c.start, c.end) for c in ed.cues] == [(0.0, 2.0), (2.0, 6.0), (6.5, 8.0)]
    assert not any(ed.is_changed(i) for i in range(3))
    assert ed.revert(0) is False


def test_revert_after_merge_and_text_edit_still_restores():
    ed = CueEditor(sample())
    ed.merge_next(0)
    ed.set_text(0, "ぜんぶ書き換えた")
    ed.revert(0)
    assert texts(ed) == ["こんにちは、", "今日は説明します。", "お願いします。"]


def test_revert_after_split_joins_the_pieces_back():
    ed = CueEditor(sample())
    ed.split(1, 3)
    assert len(ed) == 4 and ed.is_changed(1) and ed.is_changed(2)
    ed.revert(2)                                     # どちらの片方からでも
    assert texts(ed) == ["こんにちは、", "今日は説明します。", "お願いします。"]
    assert (ed.cue(1).start, ed.cue(1).end) == (2.0, 6.0)


def test_revert_a_merged_cue_in_the_middle_leaves_the_others_alone():
    ed = CueEditor(sample())
    ed.set_text(2, "別の編集")
    ed.merge_next(0)                                 # 0+1 を結合。2 は編集済み
    ed.revert(0)
    assert texts(ed) == ["こんにちは、", "今日は説明します。", "別の編集"]


def test_revert_also_restores_the_speaker():
    ed = CueEditor(sample())
    ed.set_speaker(2, 0)
    assert ed.is_changed(2)
    ed.revert(2)
    assert ed.cue(2).speaker == 1


def test_undo_and_redo_text_edit_with_typing_grouped_into_one_step():
    ed = CueEditor(sample())
    for t in ("あ", "あい", "あいう"):                # 1文字ずつ打つ
        ed.set_text(0, t)
    assert len(ed._undo) == 1
    assert ed.undo() is True and ed.cue(0).text == "こんにちは、" and not ed.dirty
    assert ed.redo() is True and ed.cue(0).text == "あいう" and ed.dirty
    assert ed.redo() is False


def test_typing_in_another_cue_or_after_a_break_is_a_separate_step():
    ed = CueEditor(sample())
    ed.set_text(0, "a")
    ed.set_text(1, "b")
    assert len(ed._undo) == 2
    ed.end_typing()
    ed.set_text(1, "bb")
    assert len(ed._undo) == 3


@pytest.mark.parametrize("do", [
    lambda ed: ed.merge_next(0),
    lambda ed: ed.split(1, 3),
    lambda ed: ed.delete(1),
    lambda ed: ed.set_speaker(0, 1),
    lambda ed: ed.set_speakers([0, 1, 2], None),
    lambda ed: ed.rename_speaker(0, "山田"),
    lambda ed: (ed.merge_next(0), ed.set_text(0, "x"), ed.end_typing(), ed.split(0, 1)),
])
def test_every_operation_can_be_undone_and_redone(do):
    ed = CueEditor(sample())
    before = ed._state()
    do(ed)
    after = ed._state()
    assert after != before
    while ed.can_undo:
        ed.undo()
    assert ed._state() == before and not ed.dirty
    while ed.can_redo:
        ed.redo()
    assert ed._state() == after


def test_a_new_edit_after_undo_discards_the_redo_history():
    ed = CueEditor(sample())
    ed.set_speaker(0, 1)
    ed.undo()
    assert ed.can_redo
    ed.delete(0)
    assert not ed.can_redo


def test_dirty_follows_the_saved_state_through_undo():
    ed = CueEditor(sample())
    ed.delete(0)
    ed.mark_saved()
    assert not ed.dirty
    ed.undo()                                        # 保存したあとで元に戻すと、保存済みの内容と違う
    assert ed.dirty
    ed.redo()
    assert not ed.dirty


def test_set_speakers_changes_many_at_once_as_one_undo_step():
    ed = CueEditor(sample())
    assert ed.set_speakers([0, 1, 2], 3) is True
    assert [c.speaker for c in ed.cues] == [3, 3, 3]
    assert ed.set_speakers([0, 1, 2], 3) is False     # 変わらない
    assert len(ed._undo) == 1
    ed.undo()
    assert [c.speaker for c in ed.cues] == [0, 0, 1]


def test_set_speakers_skips_cues_that_already_have_it():
    ed = CueEditor(sample())
    assert ed.set_speakers([0, 1], 0) is False


def test_rename_speaker_applies_to_every_cue_of_that_speaker_in_all_outputs():
    ed = CueEditor(sample())
    assert ed.rename_speaker(0, "  山田  ") is True and ed.names == {0: "山田"}
    srt = render(ed.cues, "srt", names=ed.names)
    assert "山田：こんにちは、" in srt and "山田：今日は説明します。" in srt and "話者2：お願いします。" in srt
    assert "山田：" in render(ed.cues, "txt", names=ed.names)
    md = render(ed.cues, "md", title="t", names=ed.names)
    assert "## 山田" in md and "- 話者: 山田、話者2" in md
    assert ed.rename_speaker(0, "山田") is False
    assert ed.rename_speaker(0, "") is True and ed.names == {}        # 空にすると「話者N」に戻る
    assert "話者1：" in render(ed.cues, "srt", names=ed.names)


def test_speaker_name_falls_back_to_the_default():
    ed = CueEditor(sample())
    assert ed.speaker_name(0, "話者1") == "話者1" and ed.speaker_name(None, "x") == ""
    ed.rename_speaker(0, "A")
    assert ed.speaker_name(0, "話者1") == "A"


def test_english_labels_use_custom_names_too():
    ed = CueEditor(sample())
    ed.rename_speaker(1, "Bob")
    assert "Bob: お願いします。" in render(ed.cues, "srt", ui_lang="en", names=ed.names)


def test_save_uses_the_names(tmp_path):
    ed = CueEditor(sample())
    ed.rename_speaker(0, "山田")
    save(ed.cues, tmp_path / "o.srt", names=ed.names)
    assert "山田：" in (tmp_path / "o.srt").read_text(encoding="utf-8")


def test_render_can_leave_out_the_speaker_names_in_every_format():
    ed = CueEditor(sample())
    for fmt in ("srt", "txt", "md"):
        assert "話者1" in render(ed.cues, fmt, title="t")                        # 既定は、話者名を付ける
        assert "話者" not in render(ed.cues, fmt, title="t", show_speakers=False)
    assert "こんにちは" in render(ed.cues, "srt", show_speakers=False)               # 本文は、残る


def test_save_honours_the_speaker_name_switch(tmp_path):
    from snipsync.core.subtitle_edit import save
    ed = CueEditor(sample())
    save(ed.cues, tmp_path / "a.srt", show_speakers=False)
    save(ed.cues, tmp_path / "b.srt")
    assert "話者" not in (tmp_path / "a.srt").read_text(encoding="utf-8")
    assert "話者1：" in (tmp_path / "b.srt").read_text(encoding="utf-8")
