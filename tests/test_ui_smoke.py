"""画面を実際に起動する煙テスト。ディスプレイが無い環境では丸ごとスキップする。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

tk = pytest.importorskip("tkinter")
pytest.importorskip("customtkinter")

from snipsync.core.player import sounddevice_available  # noqa: E402
from snipsync.core.subtitles import Cue  # noqa: E402

needs_audio = pytest.mark.skipif(not sounddevice_available(),
                                  reason="sounddevice（音の再生）が無い環境では、再生バーは作られない（CI など）")

CUES = [Cue(0.0, 2.0, "あいう", 0), Cue(2.0, 4.0, "えおか", 1), Cue(4.0, 6.0, "きくけ", 0)]


@pytest.fixture(scope="module")
def _root(tmp_path_factory):
    """Tk のルートは1プロセスに1つだけ作る。作っては壊すを繰り返すと、Tcl の初期化や tkdnd の読み込みが不安定になる。"""
    mp = pytest.MonkeyPatch()
    cfg = tmp_path_factory.mktemp("cfg")
    mp.setenv("APPDATA", str(cfg))                       # 設定ファイルは一時フォルダへ（本物の設定を汚さない）
    mp.setenv("XDG_CONFIG_HOME", str(cfg))
    from snipsync.ui import app as appmod

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


def test_log_and_save_folder_use_the_font_that_draws_underscores(app):
    from snipsync.ui import theme as T
    pump(app)
    assert app.console.cget("font").cget("family") == T.LITERAL_FAMILY
    assert app.folder_lbl.cget("font").cget("family") == T.LITERAL_FAMILY
    assert "BIZ" not in T.LITERAL_FAMILY


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
    from snipsync.ui.subtitle_editor import SubtitleEditor

    dest = {"srt": tmp_path / "talk.srt", "txt": tmp_path / "talk.txt"}
    reported = {}
    ed = SubtitleEditor(app, list(CUES), "talk", dest, pending=True,
                        on_closed=lambda cues, saved, paths, info: reported.update(cues=cues, saved=saved, paths=paths, info=info))
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

    from snipsync.ui.subtitle_editor import SubtitleEditor

    dest = {"srt": tmp_path / "talk.srt"}
    reported = {}
    ed = SubtitleEditor(app, list(CUES), "talk", dest, pending=True,
                        on_closed=lambda cues, saved, paths, info: reported.update(saved=saved))
    app.review_win = ed
    pump(app, 10)
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: False)    # 「保存せず閉じる」
    ed._close()
    assert reported == {"saved": False} and not dest["srt"].exists()
    app.review_win = None


def test_cancelling_the_close_prompt_keeps_the_review_window_open(app, tmp_path, monkeypatch):
    from tkinter import messagebox

    from snipsync.ui.subtitle_editor import SubtitleEditor

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

    from snipsync.core import player as pl
    from snipsync.core.preview import CutPreview

    class InlineThread:
        """テストは mainloop を回さない。スレッドから after() は呼べないので、その場で実行する。"""

        def __init__(self, target=None, args=(), daemon=None):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    from snipsync.ui import app as appmod
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


@needs_audio
def test_transport_is_disabled_until_a_result_exists(app):
    pump(app)
    for b in (app.btn_prev, app.btn_play, app.btn_next):
        assert b.cget("state") == "disabled"


@needs_audio
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


@needs_audio
def test_clicking_the_cut_map_moves_the_playhead_without_starting(app, monkeypatch):
    _prepare_result(app, monkeypatch)
    app._seek_source(8.0)
    assert _wait(app, lambda: app.player.loaded)
    assert not app.player.playing
    assert app.player.position == pytest.approx(5.0, abs=0.05)      # 元の 8 秒 = 編集後 2 + 3 = 5 秒


@needs_audio
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


@needs_audio
def test_a_new_result_discards_the_loaded_audio(app, monkeypatch):
    _prepare_result(app, monkeypatch)
    app._seek_source(1.0)
    assert _wait(app, lambda: app.player.loaded)
    app._preview_gen += 0
    app._reset_player()
    assert not app.player.loaded and not app.cutmap.canvas.find_withtag("playhead")


@needs_audio
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


@needs_audio
def test_speed_choices_go_up_to_four_times(app):
    from snipsync.core.player import RATES
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
    from snipsync.core import models
    monkeypatch.setattr(models, "models_dir", lambda: tmp_path / "SnipSync" / "models")
    from snipsync.ui import app as appmod
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

    from snipsync.ui import app as appmod

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
    monkeypatch.setattr(app, "_worker", lambda files, params, fetch=False, run_folder=False: started.append((params, fetch)))

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
    from snipsync.core import cudalibs

    def boom(**kw):
        raise cudalibs.CudaLibsFailed("timed out")

    monkeypatch.setattr(cudalibs, "download_libs", boom)
    from snipsync.core.pipeline import PipelineParams
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
    from snipsync.ui import widgets as W
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
    from snipsync.ui import widgets as W
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
    from snipsync.i18n import I18N
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
    from snipsync.ui.subtitle_editor import SubtitleEditor
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

    from snipsync.core import cudalibs
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
    from snipsync.ui import widgets as W
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


# ── 編集後の字幕から、話者交代のマーカーを入れる ───────────────────────────────────────
def _timeline(tmp_path):
    xml = tmp_path / "talk_snipsynced.xml"
    xml.write_text('<?xml version="1.0"?><xmeml version="5"><sequence><name>s</name><duration>300</duration>'
                   '<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate><media><video/></media></sequence></xmeml>',
                   encoding="utf-8")
    return xml


def test_speaker_markers_come_from_the_saved_edited_subtitles_with_custom_names(app, tmp_path):
    from snipsync.core.pipeline import PipelineResult
    from snipsync.core.subtitles import Cue
    xml = _timeline(tmp_path)
    result = PipelineResult(ok=True, stopped=False, timeline_path=xml, srt_path=None, speaker_markers_pending=True)
    saved = [Cue(0.0, 2.0, "a", 1), Cue(2.0, 4.0, "b", 0)]          # 確認画面で話者を直した結果
    app._add_speaker_markers(result, {"saved": True, "info": {"saved_cues": saved, "names": {1: "山田"}}})
    text = xml.read_text(encoding="utf-8")
    assert text.count("<marker>") == 2 and "山田" in text and "話者1" in text
    assert result.markers_added == 2 and result.speaker_markers_pending is False


def test_no_speaker_markers_when_the_subtitles_were_not_saved(app, tmp_path):
    from snipsync.core.pipeline import PipelineResult
    xml = _timeline(tmp_path)
    result = PipelineResult(ok=True, stopped=False, timeline_path=xml, srt_path=None, speaker_markers_pending=True)
    app._add_speaker_markers(result, {"saved": False, "info": {"saved_cues": None, "names": {}}})
    assert "<marker>" not in xml.read_text(encoding="utf-8") and result.speaker_markers_pending is False


def test_nothing_happens_when_no_markers_were_deferred(app, tmp_path):
    from snipsync.core.pipeline import PipelineResult
    xml = _timeline(tmp_path)
    result = PipelineResult(ok=True, stopped=False, timeline_path=xml, srt_path=None)
    app._add_speaker_markers(result, {"saved": True, "info": {"saved_cues": list(CUES), "names": {}}})
    assert "<marker>" not in xml.read_text(encoding="utf-8")


def test_review_window_reports_the_cues_as_of_the_last_save(app, tmp_path):
    from snipsync.ui.subtitle_editor import SubtitleEditor
    got = {}
    ed = SubtitleEditor(app, list(CUES), "talk", {"srt": tmp_path / "a.srt"}, pending=True,
                        on_closed=lambda cues, saved, paths, info: got.update(cues=cues, info=info, saved=saved))
    app.review_win = ed
    pump(app, 10)
    ed.editor.set_speakers([0, 1, 2], 2)
    ed.editor.rename_speaker(2, "鈴木")
    ed.save()
    ed.editor.set_speakers([0], 0)                                  # 保存したあとの変更は、保存した字幕には入らない
    monkey_answer = ed.editor.dirty
    assert monkey_answer
    ed.editor.mark_saved()                                          # 確認ダイアログを出さずに閉じるため
    ed._close()
    assert got["saved"] is True
    assert [c.speaker for c in got["info"]["saved_cues"]] == [2, 2, 2] and got["info"]["names"] == {2: "鈴木"}
    assert [c.speaker for c in got["cues"]][0] == 0                 # 画面上の最終状態
    app.review_win = None


def test_review_window_reports_no_saved_cues_when_nothing_was_saved(app, tmp_path, monkeypatch):
    from tkinter import messagebox

    from snipsync.ui.subtitle_editor import SubtitleEditor
    got = {}
    ed = SubtitleEditor(app, list(CUES), "talk", {"srt": tmp_path / "a.srt"}, pending=True,
                        on_closed=lambda cues, saved, paths, info: got.update(info=info, saved=saved))
    app.review_win = ed
    pump(app, 10)
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **k: False)
    ed._close()
    assert got["saved"] is False and got["info"]["saved_cues"] is None and got["info"]["names"] == {}
    app.review_win = None


def test_speaker_names_can_be_hidden_from_the_output_and_the_switch_follows_the_speakers(app, tmp_path):
    ed = _open_plain_editor(app)
    assert ed.sp_var.get() is True and str(ed.sp_switch.cget("state")) == "normal"
    ed.view.set_key("srt")
    ed._show_view()
    assert "話者1：" in ed.preview.get("1.0", "end")
    ed.sp_var.set(False)
    ed._show_view()                                                      # スイッチの command と同じ
    shown = ed.preview.get("1.0", "end")
    assert "話者" not in shown and "あいう" in shown
    ed.paths = {"srt": tmp_path / "demo.srt"}
    ed.save()
    assert "話者" not in (tmp_path / "demo.srt").read_text(encoding="utf-8")
    ed.sp_var.set(True)
    ed.save()
    assert "話者1：" in (tmp_path / "demo.srt").read_text(encoding="utf-8")
    ed.editor.set_speakers(list(range(len(ed.editor))), None)           # 話者を全部外すと、効くものが無いので押せない
    ed._refresh_all()
    assert str(ed.sp_switch.cget("state")) == "disabled"


@pytest.fixture
def restore_settings(app):
    """app は、このファイルの全試験で共有される。設定を書き換える試験のあと、元に戻す。"""
    saved = (app.output_dir, app.model_key, app.srt_var.get(), app.run_folder_var.get(), app.last_out_dir,
             app.last_paths, app.stop_requested)
    yield
    app.output_dir, app.model_key = saved[0], saved[1]
    app.srt_var.set(saved[2])
    app.run_folder_var.set(saved[3])
    app.last_out_dir, app.last_paths, app.stop_requested = saved[4:]


def _run_worker(app, monkeypatch, tmp_path, *, run_folder, out_dir):
    import types

    from snipsync.ui import app as appmod

    media = tmp_path / "talk.wav"
    media.write_bytes(b"x")
    seen = []
    done = types.SimpleNamespace(pending_paths={}, stopped=False, ok=True, cues=[], timeline_path=None,
                                 srt_path=None, extra_paths=[])
    monkeypatch.setattr(appmod, "get_auto_editor_path", lambda *_a, **_k: Path("ae.exe"))
    monkeypatch.setattr(appmod, "run_pipeline", lambda ae, inp, out, params, **kw: seen.append(out) or done)
    app.output_dir = str(out_dir) if out_dir else ""
    app.stop_requested = False
    params = app._build_params()
    app._worker([media.resolve()], params, False, run_folder)
    return seen, params


def test_each_run_writes_into_its_own_dated_model_folder(app, monkeypatch, tmp_path, restore_settings):
    import re
    out = tmp_path / "out"
    out.mkdir()
    app.srt_var.set(True)
    app.model_key = "large-v3"
    seen, _ = _run_worker(app, monkeypatch, tmp_path, run_folder=True, out_dir=out)
    assert len(seen) == 1 and seen[0].parent == out.resolve()
    assert re.fullmatch(r"\d{4}-\d\d-\d\d_\d{6}_large-v3", seen[0].name)
    assert seen[0].is_dir()                                         # 処理に渡す前に作っている
    assert app.last_out_dir == seen[0]                              # 「出力フォルダを開く」は、そのフォルダーを開く


def test_run_folder_off_writes_straight_into_the_save_folder_and_default_is_on(app, monkeypatch, tmp_path,
                                                                                  restore_settings):
    assert app.run_folder_var.get() is True                          # 既定はオン
    out = tmp_path / "out"
    out.mkdir()
    seen, _ = _run_worker(app, monkeypatch, tmp_path, run_folder=False, out_dir=out)
    assert seen == [out.resolve()] and list(out.iterdir()) == []


def test_run_folder_without_subtitles_is_the_date_only_and_follows_the_input_folder(app, monkeypatch, tmp_path,
                                                                                    restore_settings):
    import re
    app.srt_var.set(False)
    seen, _ = _run_worker(app, monkeypatch, tmp_path, run_folder=True, out_dir=None)
    assert seen[0].parent == tmp_path.resolve()                      # 保存先が未設定なら、入力ファイルの隣
    assert re.fullmatch(r"\d{4}-\d\d-\d\d_\d{6}", seen[0].name)


def test_run_folder_setting_is_saved_in_presets_and_restored(app):
    from snipsync.presets import SETTING_KEYS
    assert "run_folder" in SETTING_KEYS
    app.run_folder_var.set(False)
    saved = app._collect_settings()
    assert saved["run_folder"] is False
    app.run_folder_var.set(True)
    app._apply_settings(saved)
    assert app.run_folder_var.get() is False
    app.run_folder_var.set(True)


def test_resolve_speaker_markers_rewrite_the_edl_with_the_cut_points_kept(app, tmp_path):
    from snipsync.core.pipeline import PipelineResult
    timeline = tmp_path / "talk_snipsynced.fcpxml"
    timeline.write_text('<?xml version="1.0"?><fcpxml version="1.11"><resources><format id="r1" frameDuration="1/30s"/>'
                        '</resources><library><event name="e"><project name="p"><sequence tcStart="0s" format="r1">'
                        '<spine/></sequence></project></event></library></fcpxml>', encoding="utf-8")
    edl = tmp_path / "talk_markers.edl"
    result = PipelineResult(ok=True, stopped=False, timeline_path=timeline, srt_path=None, speaker_markers_pending=True,
                            marker_edl_path=edl, marker_cuts=[(3.0, "カット 1")], markers_added=1)
    saved = [Cue(0.0, 2.0, "a", 0), Cue(2.0, 5.0, "b", 1), Cue(5.0, 7.0, "c", 1)]
    app._add_speaker_markers(result, {"saved": True, "info": {"saved_cues": saved, "names": {1: "山田"}}})
    text = edl.read_bytes().decode("utf-8")
    assert text.count("|D:1") == 3 == result.markers_added and result.speaker_markers_pending is False
    assert "|M:カット 1 " in text and "|M:山田 " in text
    assert text.index("|M:話者1 ") < text.index("|M:山田 ") < text.index("|M:カット 1 ")      # 0.0 秒、2.0 秒、3.0 秒の順


def test_resolve_speaker_markers_are_skipped_when_the_subtitles_were_not_saved(app, tmp_path):
    from snipsync.core.pipeline import PipelineResult
    edl = tmp_path / "talk_markers.edl"
    edl.write_bytes(b"keep")
    result = PipelineResult(ok=True, stopped=False, timeline_path=tmp_path / "x.fcpxml", srt_path=None,
                            speaker_markers_pending=True, marker_edl_path=edl, marker_cuts=[(3.0, "カット 1")])
    app._add_speaker_markers(result, {"saved": False, "info": {"saved_cues": None, "names": {}}})
    assert edl.read_bytes() == b"keep"                                      # 保存しなかったら、EDL は、そのまま


def test_a_run_folder_that_cannot_be_created_is_reported_and_does_not_leave_the_app_busy(app, monkeypatch, tmp_path,
                                                                                         restore_settings):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")                                   # ファイルの下には、フォルダーを作れない
    seen, _ = _run_worker(app, monkeypatch, tmp_path, run_folder=True, out_dir=blocker / "out")
    assert seen == [] and app.running is False                # 処理は始まらず、画面は「処理中」のままにならない
    pump(app, 10)                                             # ログは、画面のイベントを回すと、表示に反映される
    assert "blocker" in app.console.get("1.0", "end")         # 何が起きたかが、ログに出る


def test_resolve_speaker_markers_create_the_edl_when_there_were_no_cut_points(app, tmp_path):
    from snipsync.core.pipeline import PipelineResult
    timeline = tmp_path / "talk_snipsynced.fcpxml"
    timeline.write_text('<?xml version="1.0"?><fcpxml version="1.11"><resources><format id="r1" frameDuration="1/30s"/>'
                        '</resources><library><event name="e"><project name="p"><sequence tcStart="0s" format="r1">'
                        '<spine/></sequence></project></event></library></fcpxml>', encoding="utf-8")
    edl = tmp_path / "talk_markers.edl"                       # カット点が 0 件: 処理の中では、まだ書かれていない
    result = PipelineResult(ok=True, stopped=False, timeline_path=timeline, srt_path=None, speaker_markers_pending=True,
                            marker_edl_path=edl, marker_cuts=[])
    saved = [Cue(0.0, 2.0, "a", 0), Cue(2.0, 5.0, "b", 1)]
    app._add_speaker_markers(result, {"saved": True, "info": {"saved_cues": saved, "names": {}}})
    assert edl.exists() and edl.read_bytes().decode("utf-8").count("|D:1") == 2 == result.markers_added


def _open_editor_with_result(app, monkeypatch):
    _prepare_result(app, monkeypatch)
    app.last_cues, app.last_title = list(CUES), "demo"
    app._open_editor()
    pump(app, 10)
    return app.editor_win


@needs_audio
def test_clicking_a_cue_time_plays_the_main_preview_from_that_cue(app, monkeypatch):
    ed = _open_editor_with_result(app, monkeypatch)
    ed._play_cue(1)                                                  # 2 番目の字幕（頭は編集後 2.0 秒）
    assert _wait(app, lambda: app.player.playing)
    assert app.player.position >= 2.0 - 0.05
    assert app.cutmap.canvas.find_withtag("playhead")                # 本体の再生位置の線が動く


@needs_audio
def test_clicking_a_cue_time_while_already_playing_jumps_without_pausing(app, monkeypatch):
    ed = _open_editor_with_result(app, monkeypatch)
    app._play_toggle()
    assert _wait(app, lambda: app.player.playing)
    ed._play_cue(2)
    assert app.player.playing and app.player.position >= 4.0 - 0.05


@needs_audio
def test_a_ctrl_or_shift_click_on_the_time_column_only_selects(app, monkeypatch):
    import types
    ed = _open_editor_with_result(app, monkeypatch)
    monkeypatch.setattr(ed, "_time_cell_at", lambda _e: 1)
    ed._on_tree_click(types.SimpleNamespace(x=0, y=0, state=0x4))      # Ctrl
    ed._on_tree_click(types.SimpleNamespace(x=0, y=0, state=0x1))      # Shift
    assert not app.player.loaded
    ed._on_tree_click(types.SimpleNamespace(x=0, y=0, state=0))
    assert _wait(app, lambda: app.player.playing)


def test_clicking_a_cue_time_without_a_ready_preview_says_why(app, monkeypatch):
    monkeypatch.setattr(app, "_preview_result", None)                # 前のテストの結果を引き継がない
    app.last_cues, app.last_title = list(CUES), "demo"
    app._open_editor()
    pump(app, 10)
    ed = app.editor_win
    ed._play_cue(0)
    expected = "tr_unavailable" if app.player is None else "ed_play_not_ready"
    assert ed.status.cget("text") == app.t(expected)


# ── 更新の確認画面 ────────────────────────────────────────────────────────────────────
def _release(version="0.3.0", sha="a" * 64, url="https://github.com/R3NeR3N/SnipSync/releases/download/v0.3.0/SnipSync.exe"):
    from snipsync.core.updater import Release
    return Release(version, f"v{version}", "新機能のお知らせ", "https://github.com/R3NeR3N/SnipSync/releases/tag/v0.3.0",
                   url, 1_000_000, sha)


def _model_update(key="small"):
    from snipsync.core.models import ModelUpdate
    return ModelUpdate(key, "Systran/faster-whisper-small", "aaa", "bbb", 484_000_000)


class _InlineThread:
    def __init__(self, target=None, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


@pytest.fixture
def dialog_env(app, monkeypatch, tmp_path):
    """更新画面を、通信せず・設定ファイルを汚さず・スレッドを使わずに動かす。"""
    import types

    from snipsync.ui import update_dialog as ud
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(ud, "threading", types.SimpleNamespace(Thread=_InlineThread))
    opened = []
    yield types.SimpleNamespace(ud=ud, opened=opened)
    if app.update_win is not None and app.update_win.winfo_exists():
        app.update_win.destroy()
    app.update_win = None


def _texts(dlg):
    out = []

    def walk(w):
        for c in w.winfo_children():
            try:
                out.append(c.cget("text"))
            except Exception:
                pass
            walk(c)

    walk(dlg.body)
    return " ".join(x for x in out if isinstance(x, str))


def test_update_dialog_offers_the_download_page_when_the_app_cannot_replace_itself(app, dialog_env):
    ud = dialog_env.ud
    found = ud.Findings(release=_release(), latest="0.3.0", model_updates=[_model_update()], models_checked=1)
    dlg = ud.UpdateDialog(app, found)
    pump(app, 10)
    assert dlg.btn_install is None                                   # ソース実行: 入れ替えは申し出ない
    assert len(dlg._model_buttons) == 2                              # モデル: 「更新」と「通知しない」
    assert app.t("upd_open_page") in _texts(dlg)


def test_skipping_a_version_is_remembered_and_closes_the_dialog(app, dialog_env):
    from snipsync.core import updater
    ud = dialog_env.ud
    dlg = ud.UpdateDialog(app, ud.Findings(release=_release(), latest="0.3.0"))
    pump(app, 10)
    dlg._skip_app()
    state = updater.load_state()
    assert state["skip_version"] == "0.3.0"
    none = ud.models.ModelCheck([], 0, 0)
    assert ud.collect(state, manual=False, fetch=_release, check_models=lambda: none).release is None   # 自動では出さない
    assert ud.collect(state, manual=True, fetch=_release, check_models=lambda: none).release is not None  # 手動では出す


def test_collect_reports_only_newer_releases_and_unskipped_models():
    from snipsync.core.updater import UpdateError
    from snipsync.ui import update_dialog as ud
    state = {"skip_version": "", "skip_models": {"small": "bbb"}}
    check = ud.models.ModelCheck([_model_update("small"), _model_update("tiny")], 2, 0)
    found = ud.collect(state, manual=False, fetch=lambda: _release("0.1.0"), check_models=lambda: check)
    assert found.release is None and found.latest == "0.1.0"
    assert [m.key for m in found.model_updates] == ["tiny"]           # small は「通知しない」済み
    assert found.has_news

    def offline():
        raise UpdateError("offline")

    found = ud.collect(state, manual=True, fetch=offline, check_models=lambda: ud.models.ModelCheck([], 0, 1))
    assert found.app_error == "offline" and found.release is None and found.models_failed == 1
    assert not found.has_news


def test_update_dialog_checks_on_open_and_says_when_everything_is_current(app, dialog_env, monkeypatch):
    ud = dialog_env.ud
    monkeypatch.setattr(ud, "collect", lambda state, manual: ud.Findings(latest="0.2.0", models_checked=2))
    dlg = ud.UpdateDialog(app)
    pump(app, 10)
    texts = _texts(dlg)
    assert app.t("upd_uptodate", "0.2.0") in texts and app.t("upd_models_latest") in texts
    assert not dlg.busy


def test_updating_a_model_downloads_it_and_removes_it_from_the_list(app, dialog_env, monkeypatch):
    ud = dialog_env.ud
    calls = []
    monkeypatch.setattr(ud.models, "download_model", lambda key, on_progress=None, should_stop=None: calls.append(key))
    m = _model_update()
    dlg = ud.UpdateDialog(app, ud.Findings(model_updates=[m], models_checked=1))
    pump(app, 10)
    dlg._update_model(m)
    pump(app, 10)
    assert calls == ["small"] and dlg.findings.model_updates == [] and not dlg.busy
    assert dlg.status.cget("text") == app.t("upd_model_done", "small")


def test_a_failed_model_update_keeps_it_in_the_list_and_reports_the_reason(app, dialog_env, monkeypatch):
    ud = dialog_env.ud

    def boom(key, on_progress=None, should_stop=None):
        raise ud.models.DownloadFailed("disk full")

    monkeypatch.setattr(ud.models, "download_model", boom)
    m = _model_update()
    dlg = ud.UpdateDialog(app, ud.Findings(model_updates=[m], models_checked=1))
    dlg._update_model(m)
    pump(app, 10)
    assert dlg.findings.model_updates == [m] and not dlg.busy
    assert dlg.status.cget("text") == app.t("upd_failed", "disk full")


def test_nothing_is_updated_while_a_job_is_running(app, dialog_env, monkeypatch):
    ud = dialog_env.ud
    monkeypatch.setattr(ud.models, "download_model", lambda *a, **k: pytest.fail("must not download"))
    monkeypatch.setattr(app, "running", True)
    m = _model_update()
    dlg = ud.UpdateDialog(app, ud.Findings(model_updates=[m], models_checked=1))
    dlg._update_model(m)
    assert dlg.status.cget("text") == app.t("upd_busy_running")


def _install_env(app, ud, monkeypatch, tmp_path, *, confirm=True, swap=None):
    events = []
    monkeypatch.setattr(ud.updater, "can_install", lambda r, exe=None: True)
    monkeypatch.setattr(ud.updater, "current_exe", lambda: tmp_path / "SnipSync.exe")
    monkeypatch.setattr(ud.updater, "download", lambda r, dest, **k: events.append("download"))
    monkeypatch.setattr(ud.updater, "swap_and_relaunch", swap or (lambda new: events.append("swap")))
    monkeypatch.setattr(app, "confirm_close_editors", lambda: events.append("confirm") or confirm)
    monkeypatch.setattr(app, "exit_now", lambda: events.append("exit"))
    return events


def test_installing_downloads_swaps_and_exits_only_after_unsaved_edits_are_settled(app, dialog_env, monkeypatch, tmp_path):
    ud = dialog_env.ud
    events = _install_env(app, ud, monkeypatch, tmp_path)
    dlg = ud.UpdateDialog(app, ud.Findings(release=_release(), latest="0.3.0"))
    pump(app, 10)
    assert dlg.btn_install is not None
    dlg._install()
    pump(app, 10)
    assert events == ["download", "confirm", "swap", "exit"]


def test_installing_is_abandoned_when_the_user_keeps_unsaved_subtitles(app, dialog_env, monkeypatch, tmp_path):
    ud = dialog_env.ud
    events = _install_env(app, ud, monkeypatch, tmp_path, confirm=False)
    dlg = ud.UpdateDialog(app, ud.Findings(release=_release(), latest="0.3.0"))
    dlg._install()
    pump(app, 10)
    assert events == ["download", "confirm"] and not dlg.busy        # 入れ替えない・終了しない


def test_a_failed_swap_reports_the_reason_and_keeps_the_app_running(app, dialog_env, monkeypatch, tmp_path):
    ud = dialog_env.ud

    def swap(new):
        raise ud.updater.UpdateError("locked")

    events = _install_env(app, ud, monkeypatch, tmp_path, swap=swap)
    dlg = ud.UpdateDialog(app, ud.Findings(release=_release(), latest="0.3.0"))
    dlg._install()
    pump(app, 10)
    assert "exit" not in events and dlg.status.cget("text") == app.t("upd_failed", "locked")


def test_the_auto_check_stays_quiet_unless_something_is_new(app, monkeypatch):
    from snipsync.ui import update_dialog as ud
    opened = []
    monkeypatch.setattr("snipsync.ui.app.UpdateDialog", lambda a, f=None: opened.append(f))
    monkeypatch.setattr(app, "update_win", None)
    app._auto_checked(ud.Findings(latest="0.2.0"))
    assert opened == []
    news = ud.Findings(release=_release(), latest="0.3.0")
    monkeypatch.setattr(app, "running", True)                        # 処理中は、画面を割り込ませない
    app._auto_checked(news)
    assert opened == []
    monkeypatch.setattr(app, "running", False)
    app._auto_checked(news)
    assert opened == [news]


def test_the_header_has_an_updates_button_that_follows_the_language(app):
    pump(app)
    assert app.btn_updates.cget("text") == app.t("upd_btn")
    app._on_lang_change("en")
    assert app.btn_updates.cget("text") == "Updates"
    app._on_lang_change("ja")


def test_release_notes_show_the_current_language_without_markdown_marks():
    from snipsync.ui.update_dialog import notes_for
    body = "## 日本語\n\n**新機能**: [README](https://example.com) と `SnipSync.exe`\n\n\n\n### 使い方\n\n---\n\n## English\n\n**New**: see [README](https://example.com)\n"
    ja, en = notes_for(body, "ja"), notes_for(body, "en")
    assert ja.startswith("新機能: README と SnipSync.exe") and "使い方" in ja and "New" not in ja
    assert en == "New: see README" and "新機能" not in en
    assert "#" not in ja and "**" not in ja and "`" not in ja and "\n\n\n" not in ja
    assert notes_for("plain text only", "ja") == "plain text only"          # 2 部構成でなければ、そのまま


# ── 話者の一覧・整理、編集セッションの保存と復元 ───────────────────────────────────────────
def _fragmented_cues():
    out, t = [], 0.0
    for i in range(4):
        out.append(Cue(t, t + 20, "Aの長い発言" * 5, 0))
        t += 20
        out.append(Cue(t, t + 1, "うん", 10 + i))
        t += 1
        out.append(Cue(t, t + 20, "Aの続きの長い発言" * 5, 0))
        t += 20
        out.append(Cue(t, t + 25, "Bの長い発言" * 5, 1))
        t += 25
    return out


def _open_speakers(app, cues=None):
    app.last_cues, app.last_title = list(cues or _fragmented_cues()), "demo"
    app._open_editor()
    pump(app, 10)
    ed = app.editor_win
    ed.view.set_key("speakers")
    ed._show_view()
    pump(app, 5)
    return ed


def test_speaker_view_lists_speakers_by_speaking_time(app):
    ed = _open_speakers(app)
    rows = ed.spk_tree.get_children()
    assert len(rows) == 6 and rows[0] == "0" and rows[1] == "1"            # 話者0（A）、話者1（B）、小さなラベル 4 つ
    assert ed.spk_tree.set("0", "cues") == 8 or ed.spk_tree.set("0", "cues") == "8"
    assert "%" in ed.spk_tree.set("0", "share")
    assert ed.btn_spk_merge.cget("state") == "disabled" and ed.btn_spk_listen.cget("state") == "disabled"


def test_merging_selected_speakers_into_a_target_and_undoing(app):
    ed = _open_speakers(app)
    ed.spk_tree.selection_set("10", "11")
    ed._spk_selection_changed()
    assert ed.btn_spk_merge.cget("state") == "normal"
    ed.spk_target_var.set(next(k for k, v in ed._spk_targets.items() if v == 0))
    ed._spk_merge()
    assert sorted({c.speaker for c in ed.editor.cues}) == [0, 1, 12, 13]
    assert ed.status.cget("text") == app.t("ed_spk_merged", 6, 4)
    assert len(ed.spk_tree.get_children()) == 4                              # 一覧も更新された
    ed.undo()
    assert len(ed.spk_tree.get_children()) == 6


def test_merging_with_nothing_selected_says_so(app):
    ed = _open_speakers(app)
    ed._spk_merge()
    assert ed.status.cget("text") == app.t("ed_spk_pick") and not ed.editor.dirty


def test_renaming_a_speaker_from_the_list(app):
    ed = _open_speakers(app)
    ed.spk_tree.selection_set("1")
    ed._spk_selection_changed()
    ed.spk_name_var.set("佐藤")
    ed._spk_rename()
    assert ed.editor.names == {1: "佐藤"} and ed.spk_tree.set("1", "who") == "佐藤"


def test_auto_cleanup_shows_the_counts_first_and_only_applies_when_confirmed(app, monkeypatch):
    from snipsync.ui import subtitle_editor as se
    ed = _open_speakers(app)
    asked = []
    monkeypatch.setattr(se.messagebox, "askyesno", lambda title, text, **k: asked.append(text) or False)
    ed.spk_min_var.set("5")
    ed._spk_small()
    assert asked == [app.t("ed_spk_confirm", 6, 2, 4)] and not ed.editor.dirty        # 断ったので、何も変わらない
    monkeypatch.setattr(se.messagebox, "askyesno", lambda *a, **k: True)
    ed._spk_small()
    assert sorted({c.speaker for c in ed.editor.cues}) == [0, 1] and ed.editor.dirty
    ed._spk_small()                                                                    # もう対象が無い
    assert ed.status.cget("text") == app.t("ed_spk_nothing")


def test_sandwiched_cleanup_uses_the_character_limit_from_the_entry(app, monkeypatch):
    from snipsync.ui import subtitle_editor as se
    ed = _open_speakers(app)
    monkeypatch.setattr(se.messagebox, "askyesno", lambda *a, **k: True)
    ed.spk_chars_var.set("1")                                                          # 「うん」は 2 文字: 対象外
    ed._spk_sandwiched()
    assert ed.status.cget("text") == app.t("ed_spk_nothing")
    ed.spk_chars_var.set("abc")                                                        # 数でなければ、初期値（10 字）
    ed._spk_sandwiched()
    assert sorted({c.speaker for c in ed.editor.cues}) == [0, 1]


def test_renumber_from_the_list(app):
    ed = _open_speakers(app)
    ed.editor.merge_speakers([0], 10)                                                  # 長い話者が、番号 10 になる
    ed._after_speaker_change()
    ed._spk_renumber()
    assert ed.spk_tree.get_children()[0] == "0" and ed.status.cget("text") == app.t("ed_spk_renumbered")


def test_speaker_view_says_so_when_no_cue_has_a_speaker(app):
    ed = _open_speakers(app, [Cue(0, 2, "あ", None), Cue(2, 4, "い", None)])
    assert ed.spk_tree.get_children() == () and ed.spk_note.cget("text") == app.t("ed_spk_empty")


def test_saving_writes_a_session_next_to_the_output_and_opening_it_restores_everything(app, tmp_path, monkeypatch):
    from snipsync.core import session as sess
    from snipsync.ui.subtitle_editor import SubtitleEditor
    ed = SubtitleEditor(app, _fragmented_cues(), "talk", {"srt": tmp_path / "talk.srt", "txt": tmp_path / "talk.txt"},
                        pending=True, source=str(tmp_path / "talk.mp4"), settings={"margin": 0.3, "threshold": 5.0})
    app.review_win = ed
    pump(app, 10)
    ed.editor.rename_speaker(1, "佐藤")
    ed.editor.merge_speakers([10, 11, 12, 13], 0)
    ed.save()
    pump(app, 5)
    path = tmp_path / "talk.snipsync.json"
    assert path.exists() and (tmp_path / "talk.srt").exists()
    got = sess.read_session(path)
    assert got.source == str(tmp_path / "talk.mp4") and got.settings == {"margin": 0.3, "threshold": 5.0}

    calls = []
    monkeypatch.setattr(app, "restore_context", lambda source, settings: calls.append((source, settings)))
    ed.destroy()
    app.review_win = None
    ed2 = SubtitleEditor(app)
    app.editor_win = ed2
    ed2.open_path(path)                                                                # 再起動後を想定して、ファイルから開く
    pump(app, 5)
    assert sorted({c.speaker for c in ed2.editor.cues}) == [0, 1] and ed2.editor.names == {1: "佐藤"}
    assert ed2.editor.is_changed(1) and not ed2.editor.dirty                           # 元の字幕との差（変更の印）も戻る
    assert set(ed2.paths) == {"srt", "txt"} and ed2.stem == "talk"
    assert calls == [(str(tmp_path / "talk.mp4"), {"margin": 0.3, "threshold": 5.0})]
    assert ed2.status.cget("text") == app.t("ed_session_opened")
    ed2.editor.dirty = False
    ed2.destroy()
    app.editor_win = None


def test_opening_an_srt_reads_speakers_and_offers_the_sibling_session(app, tmp_path, monkeypatch):
    from snipsync.core import session as sess
    from snipsync.core.subtitle_edit import CueEditor
    from snipsync.ui import subtitle_editor as se
    srt = tmp_path / "talk.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n話者2：こんにちは\n\n2\n00:00:02,000 --> 00:00:04,000\n話者1：はい\n",
                   encoding="utf-8")
    app.last_cues, app.last_title = [], ""
    ed = se.SubtitleEditor(app)
    app.editor_win = ed
    pump(app, 5)
    ed.open_path(srt)                                                                  # セッションが無ければ、そのまま .srt
    assert [(c.speaker, c.text) for c in ed.editor.cues] == [(1, "こんにちは"), (0, "はい")]
    saved = CueEditor([Cue(0, 2, "セッション側", 0)])
    sess.write_session(sess.session_path(srt), sess.Session(title="talk", editor=saved.export_state()))
    asked = []
    monkeypatch.setattr(se.messagebox, "askyesno", lambda title, text, **k: asked.append(title) or False)
    ed.open_path(srt)                                                                  # 「いいえ」: .srt だけを開く
    assert asked == [app.t("ed_session_ask_title")] and ed.editor.cues[0].text == "こんにちは"
    monkeypatch.setattr(se.messagebox, "askyesno", lambda *a, **k: True)
    ed.open_path(srt)                                                                  # 「はい」: セッションで開く
    assert ed.editor.cues[0].text == "セッション側"
    ed.destroy()
    app.editor_win = None


def test_a_broken_session_is_reported_and_the_editor_keeps_its_content(app, tmp_path, monkeypatch):
    from snipsync.ui import subtitle_editor as se
    shown = []
    monkeypatch.setattr(se.messagebox, "showerror", lambda title, text, **k: shown.append(text))
    ed = _open_speakers(app)
    bad = tmp_path / "bad.snipsync.json"
    bad.write_text("{oops", encoding="utf-8")
    ed.open_path(bad)
    assert shown and len(ed.editor) == len(_fragmented_cues())


def test_restore_context_applies_settings_and_selects_the_video_when_it_exists(app, tmp_path, monkeypatch):
    video = tmp_path / "talk.wav"
    video.write_bytes(b"x")
    chosen = []
    monkeypatch.setattr(app, "_set_files", lambda files: chosen.append(files))
    assert app.restore_context(str(video), {"margin": 0.35, "threshold": 6.0}) is None
    assert chosen == [[str(video)]] and app.margin_var.get() == 0.35 and app.threshold_var.get() == 6.0
    assert app.restore_context(str(tmp_path / "gone.mp4"), {}) == "ed_session_source_missing"
    assert app.restore_context("", {}) is None


def test_a_run_without_review_still_leaves_a_session_behind(app, tmp_path):
    from snipsync.core import session as sess

    class R:
        srt_path = tmp_path / "out.srt"
        cues = _fragmented_cues()

    app._run_settings = {"margin": 0.2, "threshold": 4.0, "output_dir": "x"}
    app._save_run_session(R, tmp_path / "talk.mp4")
    got = sess.read_session(tmp_path / "out.snipsync.json")
    assert got.source == str(tmp_path / "talk.mp4") and got.settings == {"margin": 0.2, "threshold": 4.0}
    assert len(got.editor["items"]) == len(_fragmented_cues())


def test_open_saved_button_exists_and_follows_the_language(app):
    pump(app)
    assert app.btn_open_saved.cget("text") == app.t("btn_open_saved")
    app._on_lang_change("en")
    assert app.btn_open_saved.cget("text") == "Open saved…"
    app._on_lang_change("ja")


# ── 文字起こしの清書の画面 ────────────────────────────────────────────────────────────────
@pytest.fixture
def polish_env(app, monkeypatch, tmp_path):
    import types

    from snipsync.ui import polish_dialog as pd
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.setattr(pd, "threading", types.SimpleNamespace(Thread=_InlineThread))
    monkeypatch.setattr(pd.messagebox, "askyesno", lambda *a, **k: True)
    app.last_cues, app.last_title = _fragmented_cues(), "demo"
    app.last_paths = {"srt": tmp_path / "talk.srt"}
    app._open_editor()
    pump(app, 10)
    ed = app.editor_win
    yield types.SimpleNamespace(pd=pd, ed=ed, dir=tmp_path)
    if ed._polish_win is not None and ed._polish_win.winfo_exists():
        ed._polish_win.destroy()


def test_polish_button_opens_one_dialog(app, polish_env):
    ed = polish_env.ed
    ed.open_polish()
    pump(app, 5)
    first = ed._polish_win
    ed.open_polish()
    assert ed._polish_win is first and first.winfo_exists()
    assert ed.btn_polish.cget("text") == app.t("ed_polish")


def test_paste_mode_writes_a_howto_and_numbered_files_next_to_the_output(app, polish_env):
    ed = polish_env.ed
    ed.open_polish()
    dlg = ed._polish_win
    dlg.mode.set_key("paste")
    dlg._show_mode()
    dlg.chunk_var.set("600")
    dlg._run()
    pump(app, 5)
    out = polish_env.dir / "talk_polish"
    assert (out / "00_使い方.md").exists() and (out / "01.txt").exists()
    assert dlg.btn_open.cget("state") == "normal" and dlg.out_dir == out
    assert "校正者" in (out / "01.txt").read_text(encoding="utf-8")


def test_local_mode_refuses_a_non_local_address_and_needs_a_model(app, polish_env):
    dlg = (polish_env.ed.open_polish(), polish_env.ed._polish_win)[1]
    dlg.mode.set_key("local")
    dlg._show_mode()
    dlg.model_var.set("")
    dlg._run()
    assert dlg.status.cget("text") == app.t("pl_need_model")
    dlg.model_var.set("m")
    dlg.endpoint_var.set("https://api.example.com/v1")
    dlg._run()
    assert dlg.status.cget("text") == app.t("pl_not_local") and not dlg.busy


def test_local_mode_polishes_and_writes_txt_and_md(app, polish_env, monkeypatch):
    pd = polish_env.pd

    class Echo:
        def __init__(self, endpoint, model, **k):
            self.model = model

        def complete(self, system, user):
            out = []
            for ln in user.split("【直す行】")[1].strip().splitlines():
                num, _label, text = ln.split("｜", 2)
                out.append(f"{num}｜{text}。")
            return "\n".join(out)

    monkeypatch.setattr(pd.polish, "LocalLLM", Echo)
    ed = polish_env.ed
    ed.open_polish()
    dlg = ed._polish_win
    dlg.mode.set_key("local")
    dlg._show_mode()
    dlg.model_var.set("qwen")
    dlg._run()
    pump(app, 10)
    txt = (polish_env.dir / "talk_polished.txt").read_text(encoding="utf-8")
    assert txt.splitlines()[0].startswith("[00:00:00] 話者") and txt.splitlines()[0].endswith("。")
    assert (polish_env.dir / "talk_polished.md").exists() and not dlg.busy
    assert "talk_polished" in dlg.status.cget("text")
    assert polish_env.pd.polish.load_settings()["model"] == "qwen"                    # 次回のために、設定を覚える


def test_a_failing_local_server_is_reported_and_nothing_is_written(app, polish_env, monkeypatch):
    pd = polish_env.pd

    class Broken:
        def __init__(self, endpoint, model, **k):
            pass

        def complete(self, system, user):
            raise pd.polish.PolishError("HTTP 500")

    monkeypatch.setattr(pd.polish, "LocalLLM", Broken)
    ed = polish_env.ed
    ed.open_polish()
    dlg = ed._polish_win
    dlg.mode.set_key("local")
    dlg._show_mode()
    dlg.model_var.set("m")
    dlg._run()
    pump(app, 10)
    assert dlg.status.cget("text") == app.t("pl_failed", "HTTP 500") and not dlg.busy
    assert not (polish_env.dir / "talk_polished.txt").exists()


def test_connection_check_fills_in_the_first_model(app, polish_env, monkeypatch):
    pd = polish_env.pd

    class Lister:
        def __init__(self, endpoint, model, **k):
            pass

        def models(self):
            return ["qwen2.5:14b", "gemma"]

    monkeypatch.setattr(pd.polish, "LocalLLM", Lister)
    polish_env.ed.open_polish()
    dlg = polish_env.ed._polish_win
    dlg._check()
    pump(app, 5)
    assert dlg.model_var.get() == "qwen2.5:14b" and dlg.status.cget("text") == app.t("pl_check_ok", 2, "qwen2.5:14b, gemma")


# ── 手動のカット・倍速 ──────────────────────────────────────────────────────────────────
@pytest.fixture
def manual_env(app, monkeypatch, tmp_path):
    import types

    import numpy as np
    monkeypatch.setenv("APPDATA", str(tmp_path))
    video = tmp_path / "talk.wav"
    video.write_bytes(b"x")
    app.input_files = [str(video)]
    app.manual_edits = []
    monkeypatch.setattr(app, "_run_preview", lambda: None)              # 実際の再計算は、ここでは行わない
    monkeypatch.setattr(app.cutmap.canvas, "winfo_width", lambda: 1000)
    app.cutmap.set_data(np.ones(10, dtype=np.float32), [(0, 10, "keep")], 100.0)
    pump(app, 3)
    yield types.SimpleNamespace(video=video)
    app.cutmap.set_selection(None)
    app.manual_edits = []
    app._update_manual()
    if app.manual_win is not None and app.manual_win.alive():
        app.manual_win.destroy()
    app.manual_win = None


def _ev(x):
    import types
    return types.SimpleNamespace(x=x, y=10)


def test_dragging_on_the_wave_selects_a_span_and_a_click_still_seeks(app, manual_env, monkeypatch):
    seeks = []
    monkeypatch.setattr(app, "_seek_source", lambda s: seeks.append(s))
    cm = app.cutmap
    cm._on_seek = lambda s: seeks.append(s)
    cm._press(_ev(200))
    cm._release(_ev(203))                                              # 3 px: ドラッグではなく、クリック
    assert seeks == [pytest.approx(20.0, abs=0.5)] and cm.selection is None
    cm._press(_ev(200))
    cm._drag(_ev(400))
    cm._release(_ev(400))
    assert cm.selection == (pytest.approx(20.0, abs=0.5), pytest.approx(40.0, abs=0.5)) and len(seeks) == 1
    cm._press(_ev(600))
    cm._drag(_ev(500))                                                # 右から左へのドラッグも、小さい順に
    cm._release(_ev(500))
    assert cm.selection[0] < cm.selection[1]


def test_a_selection_shows_buttons_and_adding_a_cut_marks_the_preview_stale(app, manual_env, monkeypatch):
    stale = []
    monkeypatch.setattr(app, "_mark_stale", lambda: stale.append(1))
    app.cutmap.set_selection((10.0, 25.0))
    app._on_map_select(10.0, 25.0)
    assert app.btn_man_cut.winfo_manager() == "pack" and "15.0" in app.manual_sel.cget("text")
    app._add_manual("cut")
    assert [(e.start, e.end, e.action) for e in app.manual_edits] == [(10.0, 25.0, "cut")]
    assert app.cutmap.selection is None and stale and app.btn_man_list.cget("text") == app.t("manual_list", 1)


def test_a_too_short_selection_is_dropped(app, manual_env):
    app.cutmap.set_selection((10.0, 10.05))
    app._on_map_select(10.0, 10.05)
    assert app.cutmap.selection is None


def test_a_speed_up_uses_the_current_speed_value(app, manual_env):
    app.speed_var.set(4.0)
    app.cutmap.set_selection((30.0, 40.0))
    app._add_manual("speed")
    assert app.manual_edits[0].action == "speed" and app.manual_edits[0].speed == 4.0


def test_manual_edits_reach_the_preview_settings_and_the_pipeline_params(app, manual_env, monkeypatch):
    import threading
    app.cutmap.set_selection((10.0, 25.0))
    app._add_manual("cut")
    assert app._build_params().manual_edits == tuple(app.manual_edits)
    seen = []

    def fake(path, cfg, ae, cache):
        seen.append(cfg)
        raise RuntimeError("stop here")

    monkeypatch.setattr("snipsync.ui.app.compute_preview", fake)
    monkeypatch.setattr(app, "cut_mode", "vad")                       # 音量方式は、auto-editor を取りに行くので、避ける
    monkeypatch.setattr(app, "after", lambda *a, **k: None)           # 作業スレッドから画面へ返す所は、ここでは要らない
    app._preview_busy = False
    type(app)._run_preview(app)
    for th in threading.enumerate():
        if th is not threading.current_thread() and th.daemon:
            th.join(timeout=3)
    assert seen and seen[0].manual == tuple(app.manual_edits)
    app._preview_busy = False


def test_choosing_another_video_clears_the_manual_edits(app, manual_env):
    app.cutmap.set_selection((10.0, 25.0))
    app._add_manual("cut")
    app._on_files_changed()
    assert app.manual_edits == [] and app.btn_man_list.winfo_manager() == ""


def test_the_list_dialog_shows_each_edit_and_removes_them(app, manual_env):
    for a, b in ((10.0, 20.0), (40.0, 50.0)):
        app.cutmap.set_selection((a, b))
        app._add_manual("cut")
    app.open_manual_list()
    dlg = app.manual_win
    pump(app, 5)
    assert "削除" in dlg.describe(app.manual_edits[0]) and "10.0" in dlg.describe(app.manual_edits[0])
    first = app.manual_edits[0]
    dlg._remove(first)
    assert app.manual_edits and first not in app.manual_edits and len(app.manual_edits) == 1
    dlg._clear_all()
    assert app.manual_edits == [] and dlg.btn_all.cget("state") == "disabled"


def test_the_session_keeps_the_manual_edits_and_restoring_brings_them_back(app, manual_env, monkeypatch):
    from snipsync.core import session as sess
    app.cutmap.set_selection((10.0, 25.0))
    app._add_manual("cut")
    app.cutmap.set_selection((60.0, 70.0))
    app.speed_var.set(3.0)
    app._add_manual("speed")
    from snipsync.core.manualcuts import to_json
    saved = {**app._collect_settings(), "manual": to_json(app.manual_edits)}
    assert sess.pick_settings(saved)["manual"] == saved["manual"]
    app.manual_edits = []
    monkeypatch.setattr(app, "_set_files", lambda files: None)
    monkeypatch.setattr(app, "_mark_stale", lambda: None)
    assert app.restore_context(str(manual_env.video), sess.pick_settings(saved)) is None
    assert [(e.start, e.end, e.action) for e in app.manual_edits] == [(10.0, 25.0, "cut"), (60.0, 70.0, "speed")]


def test_the_guide_buttons_open_the_browser_with_the_right_pages(app, polish_env, monkeypatch):
    pd = polish_env.pd
    opened = []
    monkeypatch.setattr(pd.webbrowser, "open", lambda url: opened.append(url))
    polish_env.ed.open_polish()
    dlg = polish_env.ed._polish_win
    dlg.mode.set_key("local")
    dlg._show_mode()
    assert set(dlg.btn_guides) == {"browser", "claude", "chatgpt"}
    dlg.btn_guides["claude"].invoke()
    dlg.btn_guides["browser"].invoke()
    assert opened[0].startswith("https://claude.ai/new?q=") and opened[1].startswith("https://www.google.com/search?q=")
    assert dlg.status.cget("text") == app.t("pl_guide_opened")
