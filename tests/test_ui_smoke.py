"""画面を実際に起動する煙テスト。ディスプレイが無い環境では丸ごとスキップする。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

tk = pytest.importorskip("tkinter")
pytest.importorskip("customtkinter")

from subtitles import Cue  # noqa: E402

CUES = [Cue(0.0, 2.0, "あいう", 0), Cue(2.0, 4.0, "えおか", 1), Cue(4.0, 6.0, "きくけ", 0)]


@pytest.fixture(scope="module")
def _root(tmp_path_factory):
    """Tk のルートは1プロセスに1つだけ作る。作っては壊すを繰り返すと、Tcl の初期化や tkdnd の読み込みが不安定になる。"""
    mp = pytest.MonkeyPatch()
    cfg = tmp_path_factory.mktemp("cfg")
    mp.setenv("APPDATA", str(cfg))                       # 設定ファイルは一時フォルダへ（本物の設定を汚さない）
    mp.setenv("XDG_CONFIG_HOME", str(cfg))
    import app as appmod

    try:
        a = appmod.SnipSyncApp()
    except (tk.TclError, RuntimeError) as e:
        mp.undo()
        pytest.skip(f"cannot start the GUI here: {e}")
    a.withdraw()
    yield a
    a.destroy()
    mp.undo()


@pytest.fixture
def app(_root):
    a = _root
    a.last_cues, a.last_title, a.last_paths = [], "", {}
    a._reset_ui()
    a._on_lang_change("ja")
    yield a
    if a.editor_win is not None and a.editor_win.winfo_exists():
        a.editor_win.editor.dirty = False       # 未保存確認ダイアログを出さずに閉じる
        a.editor_win.destroy()
    a.editor_win = None


def pump(a, n=5):
    for _ in range(n):
        a.update()


def test_buttons_that_need_input_start_disabled(app):
    pump(app)
    assert app.btn_preview.cget("state") == "disabled"
    assert app.btn_review.cget("state") == "disabled"
    app.last_cues = list(CUES)
    app._reset_ui()
    assert app.btn_review.cget("state") == "normal"


def test_main_window_builds_and_switches_tabs_and_language(app):
    pump(app)
    for key in ("cut", "subs", "export"):
        app.tabs.set_key(key)
        app._show_tab(key)
        pump(app, 2)
    ja_title = app.title()
    app._on_lang_change("en")
    pump(app)
    assert app.title() == ja_title                      # 題名は言語で変えない（SnipSync v0.x）
    app._on_lang_change("ja")
    pump(app)


def test_editing_a_cue_in_the_review_window_marks_it_changed_but_not_the_others(app):
    app.last_cues, app.last_title = list(CUES), "demo"
    app._open_editor()
    pump(app, 10)
    ed = app.editor_win
    assert ed is not None and not ed.editor.dirty

    ed.tree.selection_set("1")
    ed._on_select()
    pump(app)
    ed.text.delete("1.0", "end")
    ed.text.insert("1.0", "修正後")
    pump(app, 10)

    assert ed.editor.cue(1).text == "修正後"
    assert ed.editor.is_changed(1) and not ed.editor.is_changed(0) and not ed.editor.is_changed(2)
    assert ed.editor.dirty
    assert ed.winfo_toplevel().title().startswith("●")        # 題名に未保存マーク

    # 元の文字列へ戻せば「変更あり」ではなくなる
    ed.text.delete("1.0", "end")
    ed.text.insert("1.0", "えおか")
    pump(app, 10)
    assert not ed.editor.is_changed(1)


def test_the_original_cues_are_never_mutated_by_editing(app):
    app.last_cues, app.last_title = list(CUES), "demo"
    app._open_editor()
    pump(app, 10)
    ed = app.editor_win
    ed.tree.selection_set("0")
    ed._on_select()
    pump(app)
    ed.text.delete("1.0", "end")
    ed.text.insert("1.0", "別の文")
    pump(app, 10)
    assert CUES[0].text == "あいう"


def test_review_editor_writes_nothing_until_saved_and_reports_the_outcome(app, tmp_path):
    from subtitle_editor import SubtitleEditor

    dest = {"srt": tmp_path / "talk.srt", "txt": tmp_path / "talk.txt"}
    reported = {}
    ed = SubtitleEditor(app, list(CUES), "talk", dest, pending=True,
                        on_closed=lambda cues, saved, paths: reported.update(cues=cues, saved=saved, paths=paths))
    app.review_win = ed
    pump(app, 10)
    assert ed.pending and not any(p.exists() for p in dest.values())
    assert ed.title().startswith("●")                                   # まだ保存していない印

    ed.tree.selection_set("1")
    ed._on_select()
    pump(app)
    ed.text.delete("1.0", "end")
    ed.text.insert("1.0", "確認で直した")
    pump(app, 10)
    ed.save()
    pump(app, 5)
    assert dest["srt"].exists() and dest["txt"].exists() and not ed.pending
    assert "確認で直した" in dest["srt"].read_text(encoding="utf-8")
    assert "確認で直した" in dest["txt"].read_text(encoding="utf-8")

    ed._close()
    assert reported["saved"] is True and reported["cues"][1].text == "確認で直した"
    assert set(reported["paths"]) == {"srt", "txt"}
    app.review_win = None


def test_review_editor_closed_without_saving_reports_not_saved(app, tmp_path, monkeypatch):
    from tkinter import messagebox

    from subtitle_editor import SubtitleEditor

    dest = {"srt": tmp_path / "talk.srt"}
    reported = {}
    ed = SubtitleEditor(app, list(CUES), "talk", dest, pending=True,
                        on_closed=lambda cues, saved, paths: reported.update(saved=saved))
    app.review_win = ed
    pump(app, 10)
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: False)    # 「保存せず閉じる」
    ed._close()
    assert reported == {"saved": False} and not dest["srt"].exists()
    app.review_win = None


def test_cancelling_the_close_prompt_keeps_the_review_window_open(app, tmp_path, monkeypatch):
    from tkinter import messagebox

    from subtitle_editor import SubtitleEditor

    ed = SubtitleEditor(app, list(CUES), "talk", {"srt": tmp_path / "talk.srt"}, pending=True)
    app.review_win = ed
    pump(app, 10)
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: None)
    ed._close()
    assert ed.winfo_exists()
    ed.pending = False
    ed.destroy()
    app.review_win = None



class _FakeStream:
    def __init__(self, sr, callback, finished):
        self.callback = callback

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def _prepare_result(app, monkeypatch):
    """実ファイルなしで「確認結果が出ている」状態を作る。再生は音の出ない偽のストリームにする。"""
    import threading
    import types

    import numpy as np

    import player as pl
    from preview import CutPreview

    class InlineThread:
        """テストは mainloop を回さない。スレッドから after() は呼べないので、その場で実行する。"""

        def __init__(self, target=None, args=(), daemon=None):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    import app as appmod
    monkeypatch.setattr(appmod, "threading", types.SimpleNamespace(Thread=InlineThread, Event=threading.Event))
    monkeypatch.setattr(app, "player", pl.Player(lambda sr, cb, fin: _FakeStream(sr, cb, fin)))
    app.input_files = ["talk.wav"]
    app._play_cache = {"path": "talk.wav", "samples": np.zeros(10 * pl.PLAY_SR, dtype=np.float32)}
    chunks = [(0, 20, 1.0), (20, 50, 99999.0), (50, 100, 1.0)]
    app._stats = {"original": 10.0, "result": 7.0, "cuts": 1, "saved_pct": 30.0}
    app.cutmap.set_data(np.ones(10, dtype=np.float32), [(0, 2, "keep"), (2, 5, "cut"), (5, 10, "keep")], 10.0)
    app._preview_result = CutPreview(None, [], app._stats, 10.0, chunks, 10.0)
    app._update_transport()


def _wait(app, cond, seconds=3.0):
    import time
    end = time.time() + seconds
    while time.time() < end and not cond():
        app.update()
        time.sleep(0.02)
    return cond()


def test_transport_is_disabled_until_a_result_exists(app):
    pump(app)
    for b in (app.btn_prev, app.btn_play, app.btn_next):
        assert b.cget("state") == "disabled"


def test_transport_plays_pauses_and_follows_the_playhead(app, monkeypatch):
    _prepare_result(app, monkeypatch)
    assert app.btn_play.cget("state") == "normal"
    app._play_toggle()                                              # 初回は音を組み立ててから再生する
    assert _wait(app, lambda: app.player.playing)
    assert app.btn_play.cget("text") == app.t("tr_pause")
    app._play_next()                                                # 次のカット点（編集後 2.0 秒）
    assert app.player.position == pytest.approx(2.0, abs=0.05)
    assert app.cutmap.canvas.find_withtag("playhead")              # 再生位置の線が出ている
    assert app.player.source_position == pytest.approx(5.0, abs=0.1)    # 削除を飛ばした分、元の時刻は 5 秒
    app._play_toggle()
    assert not app.player.playing and app.btn_play.cget("text") == app.t("tr_play")


def test_clicking_the_cut_map_moves_the_playhead_without_starting(app, monkeypatch):
    _prepare_result(app, monkeypatch)
    app._seek_source(8.0)
    assert _wait(app, lambda: app.player.loaded)
    assert not app.player.playing
    assert app.player.position == pytest.approx(5.0, abs=0.05)      # 元の 8 秒 = 編集後 2 + 3 = 5 秒


def test_changing_a_setting_pauses_playback_and_disables_the_buttons_until_recomputed(app, monkeypatch):
    _prepare_result(app, monkeypatch)
    app._play_toggle()
    assert _wait(app, lambda: app.player.playing)
    app._mark_stale()
    if app._preview_timer:
        app.after_cancel(app._preview_timer)
        app._preview_timer = None
    assert not app.player.playing
    assert app.btn_play.cget("state") == "disabled"


def test_a_new_result_discards_the_loaded_audio(app, monkeypatch):
    _prepare_result(app, monkeypatch)
    app._seek_source(1.0)
    assert _wait(app, lambda: app.player.loaded)
    app._preview_gen += 0
    app._reset_player()
    assert not app.player.loaded and not app.cutmap.canvas.find_withtag("playhead")


def test_rate_choice_applies_to_the_loaded_audio(app, monkeypatch):
    _prepare_result(app, monkeypatch)
    app._seek_source(1.0)
    assert _wait(app, lambda: app.player.loaded)
    app.rate_choice.set_key("2")
    app._on_rate("2")
    assert _wait(app, lambda: not app._audio_loading)
    assert app.player.rate == 2.0
    app.rate_choice.set_key("1")
    app._on_rate("1")


def test_speed_choices_go_up_to_four_times(app):
    from player import RATES
    assert RATES[-1] == 4.0 and 3.0 in RATES
    assert {"3", "4"} <= set(app.rate_choice._choices)


def test_model_download_progress_shows_a_bar_and_hides_it_at_the_end(app):
    assert not app.dl_bar.winfo_manager()
    app._on_progress("model", 0, 0)
    app._on_progress("model", 300_000_000, 1_500_000_000)
    pump(app, 3)
    assert app.dl_bar.winfo_manager() and app.dl_bar.get() == pytest.approx(0.2)
    text = app.dl_text.cget("text")
    assert "300" in text and "1500" in text and "20%" in text
    app._on_progress("model", None, None)
    pump(app, 3)
    assert not app.dl_bar.winfo_manager() and not app.dl_text.winfo_manager()


def test_open_model_folder_opens_the_folder_of_the_selected_model(app, tmp_path, monkeypatch):
    import os
    opened = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(Path(p)), raising=False)
    app.model_key = "kotoba-ja"
    (tmp_path / "SnipSync" / "models").mkdir(parents=True, exist_ok=True)
    import models
    monkeypatch.setattr(models, "models_dir", lambda: tmp_path / "SnipSync" / "models")
    import app as appmod
    monkeypatch.setattr(appmod, "models_dir", models.models_dir)
    monkeypatch.setattr(appmod, "model_folder", lambda key: tmp_path / "SnipSync" / "models" / "kotoba")
    app._open_model_folder()
    assert opened == [tmp_path / "SnipSync" / "models"]        # まだ無いので、いちばん近い既存のフォルダ
    (tmp_path / "SnipSync" / "models" / "kotoba").mkdir()
    app._open_model_folder()
    assert opened[-1] == tmp_path / "SnipSync" / "models" / "kotoba"
    app.model_key = "small"


def _open_plain_editor(app):
    app.last_cues, app.last_title = list(CUES), "demo"
    app._open_editor()
    pump(app, 10)
    return app.editor_win


def test_several_rows_can_be_selected_and_their_speaker_changed_together(app):
    ed = _open_plain_editor(app)
    ed.tree.selection_set("0", "1", "2")
    ed._on_select()
    pump(app)
    assert ed._sel is None and ed._sels == [0, 1, 2]
    assert str(ed.text._textbox.cget("state")) == "disabled"        # 本文は1件ずつ
    assert ed.speaker_var.get() == app.t("ed_speaker_mixed")         # 話者がばらばら
    ed._on_speaker(app.t("ed_speaker_n", 2))
    assert [c.speaker for c in ed.editor.cues] == [1, 1, 1]
    assert ed.speaker_var.get() == app.t("ed_speaker_n", 2)
    ed.undo()
    assert [c.speaker for c in ed.editor.cues] == [0, 1, 0]            # 1回で、まとめて元に戻る


def test_speaker_can_be_renamed_and_the_name_shows_in_the_table_and_the_output(app):
    ed = _open_plain_editor(app)
    ed.tree.selection_set("0")
    ed._on_select()
    pump(app)
    ed.name_var.set("山田")
    ed._on_rename()
    assert ed.tree.item("0", "values")[1] == "山田" and ed.tree.item("2", "values")[1] == "山田"   # 同じ話者の行すべて
    assert ed.tree.item("1", "values")[1] == app.t("ed_speaker_n", 2)
    ed.view.set_key("srt")
    ed._show_view()
    assert "山田：あいう" in ed.preview.get("1.0", "end")
    assert ed.speaker_menu.cget("values")[1] == "山田"
    ed.undo()
    assert ed.tree.item("0", "values")[1] == app.t("ed_speaker_n", 1)


def test_revert_after_merge_works_from_the_window(app):
    ed = _open_plain_editor(app)
    ed.tree.selection_set("0")
    ed._on_select()
    pump(app)
    ed.merge()
    assert len(ed.editor) == 2 and str(ed.btn_revert.cget("state")) == "normal"
    ed.revert()
    assert len(ed.editor) == 3
    assert [c.text for c in ed.editor.cues] == [c.text for c in CUES]


def test_undo_and_redo_buttons_follow_the_history(app):
    ed = _open_plain_editor(app)
    assert str(ed.btn_undo.cget("state")) == "disabled" and str(ed.btn_redo.cget("state")) == "disabled"
    ed.tree.selection_set("1")
    ed._on_select()
    ed.delete()
    assert len(ed.editor) == 2 and str(ed.btn_undo.cget("state")) == "normal"
    ed.undo()
    assert len(ed.editor) == 3 and str(ed.btn_redo.cget("state")) == "normal" and not ed.editor.dirty
    ed.redo()
    assert len(ed.editor) == 2


def test_typed_text_is_undone_in_one_step_and_the_split_hint_is_shown(app):
    ed = _open_plain_editor(app)
    ed.tree.selection_set("0")
    ed._on_select()
    pump(app)
    for s in ("あ", "あい", "あいう！"):
        ed.text.delete("1.0", "end")
        ed.text.insert("1.0", s)
        pump(app, 3)
    assert ed.editor.cue(0).text == "あいう！"
    ed.undo()
    assert ed.editor.cue(0).text == "あいう"                          # CUES[0] の元の文
    assert "カーソル位置で分ける" in ed.split_hint.cget("text")


# ── GPU 用の部品（cuBLAS・cuDNN）がないとき ──────────────────────────────────────────
def _prepare_start(app, monkeypatch, tmp_path, *, libs_ready, answer):
    import threading
    import types

    import app as appmod

    media = tmp_path / "talk.wav"
    media.write_bytes(b"x")
    app.input_files = [str(media)]
    app.srt_var.set(True)
    app.gpu_var.set(True)
    monkeypatch.setattr(appmod, "cuda_available", lambda: True)
    monkeypatch.setattr(appmod, "cuda_libs_ready", lambda: libs_ready)
    asked = []
    monkeypatch.setattr(appmod.messagebox, "askyesnocancel", lambda *a, **k: asked.append(a) or answer)
    started = []
    monkeypatch.setattr(app, "_worker", lambda files, params, fetch=False: started.append((params, fetch)))

    class InlineThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(appmod, "threading", types.SimpleNamespace(Thread=InlineThread, Event=threading.Event))
    return asked, started


def test_without_gpu_parts_start_asks_and_cancel_does_not_start(app, tmp_path, monkeypatch):
    asked, started = _prepare_start(app, monkeypatch, tmp_path, libs_ready=False, answer=None)
    app._start_process()
    assert len(asked) == 1 and started == [] and not app.running


def test_without_gpu_parts_answering_no_runs_on_the_cpu_this_time(app, tmp_path, monkeypatch):
    _, started = _prepare_start(app, monkeypatch, tmp_path, libs_ready=False, answer=False)
    app._start_process()
    (params, fetch), = started
    assert params.use_gpu is False and fetch is False
    assert app.gpu_var.get() is True                    # 設定そのものは変えない（次回も GPU を選んだまま）
    app.running = False


def test_without_gpu_parts_answering_yes_fetches_them_and_keeps_the_gpu(app, tmp_path, monkeypatch):
    _, started = _prepare_start(app, monkeypatch, tmp_path, libs_ready=False, answer=True)
    app._start_process()
    (params, fetch), = started
    assert params.use_gpu is True and fetch is True
    app.running = False


def test_with_gpu_parts_present_start_does_not_ask(app, tmp_path, monkeypatch):
    asked, started = _prepare_start(app, monkeypatch, tmp_path, libs_ready=True, answer=None)
    app._start_process()
    assert asked == [] and started[0][0].use_gpu is True and started[0][1] is False
    app.running = False


def test_gpu_part_fetch_failure_continues_on_the_cpu(app, monkeypatch):
    import cudalibs

    def boom(**kw):
        raise cudalibs.CudaLibsFailed("timed out")

    monkeypatch.setattr(cudalibs, "download_libs", boom)
    from pipeline import PipelineParams
    params = PipelineParams(margin=0.2, threshold=4.0, export_key="resolve", do_srt=True, model_size="small",
                            use_gpu=True)
    out = app._fetch_gpu_libs(params)
    assert out.use_gpu is False


def test_gpu_part_fetch_progress_uses_its_own_text(app):
    app._on_progress("gpu", 700_000_000, 1_400_000_000)
    pump(app, 3)
    assert "GPU" in app.dl_text.cget("text") and "50%" in app.dl_text.cget("text")
    app._on_progress("gpu", None, None)


def test_transcription_progress_and_loading_text(app):
    app._on_progress("load", 0, 0)
    assert app.t("model_loading") in app.dl_text.cget("text")
    app._on_progress("transcribe", 35.0, 70.0)
    assert "50%" in app.dl_text.cget("text") and app.dl_bar.get() == pytest.approx(0.5)
    app._on_progress("transcribe", None, None)
    assert not app.dl_text.winfo_manager()


def test_stop_shows_immediate_feedback_even_when_the_stage_cannot_be_interrupted(app):
    app._stop_process()
    assert app.stop_requested and app.dl_text.cget("text") == app.t("stopping")
    app.stop_requested = False
    app._on_progress("model", None, None)


# ── 簡易ヘルプ（マウスを重ねると出る説明） ──────────────────────────────────────────
def test_tooltip_shows_text_for_the_current_language_and_hides(app, monkeypatch):
    import widgets as W
    lbl = W.label(app, "x")
    state = {"text": "最初"}
    tt = W.Tooltip(lbl, lambda: state["text"])
    monkeypatch.setattr(tt, "_inside", lambda: True)
    tt._show()
    assert tt._tip is not None and tt._tip.winfo_children()[0].cget("text") == "最初"
    tt._hide()
    assert tt._tip is None
    state["text"] = "English"                              # 言語を切り替えたあと、次に出すときは新しい文言
    tt._show()
    assert tt._tip.winfo_children()[0].cget("text") == "English"
    tt._hide()
    lbl.destroy()


def test_only_one_tooltip_is_visible_and_the_inner_widgets_one_wins(app, monkeypatch):
    import widgets as W
    outer = ctk_frame = __import__("customtkinter").CTkFrame(app)
    inner = W.label(outer, "i")
    a = W.Tooltip(outer, "外側")
    b = W.Tooltip(inner, "内側")
    for t_ in (a, b):
        monkeypatch.setattr(t_, "_inside", lambda: True)
    a._show()
    b._show()                                               # あとから出る内側のヘルプが、外側を置き換える
    assert a._tip is None and b._tip is not None and W.Tooltip._active is b
    b._hide()
    assert W.Tooltip._active is None
    ctk_frame.destroy()


def test_main_window_controls_have_help_in_both_languages(app):
    from i18n import I18N
    tip_keys = [k for k in I18N["ja"] if k.startswith("tip_")]
    assert len(tip_keys) >= 50
    for k in tip_keys:
        assert I18N["ja"][k].strip() and I18N["en"][k].strip()
        assert "→" not in I18N["ja"][k]


# ── 字幕確認画面のショートカット ─────────────────────────────────────────────────────
def test_shortcut_keys_work_from_the_text_box_and_keep_the_keyboard_flow(app):
    ed = _open_plain_editor(app)
    ed.tree.selection_set("0")
    ed._on_select()
    pump(app)
    tb = ed.text._textbox
    # 結合: つなぎ目にカーソルが残り、続けて押せる
    tb.event_generate("<Control-j>")
    pump(app)
    assert len(ed.editor) == 2
    joint = int(tb.index("insert").split(".")[1])
    assert joint == len(CUES[0].text)
    tb.event_generate("<Control-j>")
    pump(app)
    assert len(ed.editor) == 1                                          # 続けて、次とも結合
    # 分割: カーソル位置で2件に分かれ、あとの方が選ばれる
    tb.mark_set("insert", "1.2")
    tb.event_generate("<Control-Return>")
    pump(app)
    assert len(ed.editor) == 2 and ed._sel == 1
    assert tb.index("insert") == "1.0"


def test_shortcut_for_delete_revert_move_speaker_undo_and_help(app):
    ed = _open_plain_editor(app)
    ed.tree.selection_set("1")
    ed._on_select()
    pump(app)
    tb = ed.text._textbox
    tb.event_generate("<Alt-Down>")
    pump(app)
    assert ed._sel == 2
    tb.event_generate("<Alt-Up>")
    pump(app)
    assert ed._sel == 1
    tb.event_generate("<Control-Key-3>")                                # 話者3
    pump(app)
    assert ed.editor.cue(1).speaker == 2
    tb.event_generate("<Control-Key-0>")                                # なし
    pump(app)
    assert ed.editor.cue(1).speaker is None
    tb.event_generate("<Control-r>")                                    # 最初に戻す（話者も戻る）
    pump(app)
    assert ed.editor.cue(1).speaker == CUES[1].speaker
    tb.event_generate("<Control-d>")
    pump(app)
    assert len(ed.editor) == 2
    tb.event_generate("<Control-z>")
    pump(app)
    assert len(ed.editor) == 3
    tb.event_generate("<Control-y>")
    pump(app)
    assert len(ed.editor) == 2
    assert ed._help is None
    tb.event_generate("<F1>")
    pump(app)
    assert ed._help is not None
    tb.event_generate("<Escape>")
    pump(app)
    assert ed._help is None


def test_shortcut_help_lists_every_shortcut_and_follows_the_language(app):
    ed = _open_plain_editor(app)
    ed.toggle_help()
    pump(app)
    texts = [w.cget("text") for w in ed._help.winfo_children() if hasattr(w, "cget")]
    for key in ("Ctrl+Enter", "Ctrl+J", "Ctrl+D", "Ctrl+R", "Ctrl+Z", "Ctrl+Y", "Ctrl+S", "F1"):
        assert key in texts
    assert app.t("sc_split") in texts and app.t("sc_title") in texts
    ed.toggle_help()
    assert ed._help is None


def test_close_note_is_shown_only_while_processing_waits_for_the_window(app, tmp_path):
    from subtitle_editor import SubtitleEditor
    plain = _open_plain_editor(app)
    assert plain.close_note is None
    waiting = SubtitleEditor(app, list(CUES), "talk", {"srt": tmp_path / "a.srt"}, pending=True,
                             on_closed=lambda *a: None)
    app.review_win = waiting
    pump(app)
    assert waiting.close_note is not None and "処理" in waiting.close_note.cget("text")
    assert "保存" in waiting.close_note.cget("text")
    waiting.pending = False
    waiting._on_closed = None
    waiting.destroy()
    app.review_win = None


def test_open_gpu_parts_folder_opens_the_folder_or_the_nearest_existing_one(app, tmp_path, monkeypatch):
    import os

    import cudalibs
    opened = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(Path(p)), raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    (tmp_path / "SnipSync").mkdir()
    app._open_cuda_folder()
    assert opened[-1] == tmp_path / "SnipSync"                  # まだ取得していない: 一番近い既存のフォルダ
    cudalibs.cuda_dir().mkdir()
    app._open_cuda_folder()
    assert opened[-1] == cudalibs.cuda_dir()


def test_tooltip_wrapping_keeps_words_whole_and_punctuation_off_line_starts():
    import widgets as W
    def measure(s):
        return sum(13 if ord(c) > 0x2E80 else 6 for c in s)
    text = "取得した GPU 用の部品の置き場を開きます。消しても他のアプリには影響せず、GPU を使うときにまた取得します。"
    out = W.wrap_text(text, measure, 260)
    lines = out.split("\n")
    assert len(lines) >= 2 and all(measure(ln) <= 260 + 13 for ln in lines)       # 句読点は、行末にはみ出して置いてよい（ぶら下がり）
    assert "GPU" in " ".join(lines) and not any(ln.startswith(("。", "、")) for ln in lines)
    assert not any(ln.endswith("GP") or ln.startswith("PU") for ln in lines)         # 英単語は途中で切らない
    assert W.wrap_text("短い", measure, 260) == "短い"
    assert W.wrap_text("a\nb", measure, 260) == "a\nb"
