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
    app._on_model_progress(0, 0)
    app._on_model_progress(300_000_000, 1_500_000_000)
    pump(app, 3)
    assert app.dl_bar.winfo_manager() and app.dl_bar.get() == pytest.approx(0.2)
    text = app.dl_text.cget("text")
    assert "300" in text and "1500" in text and "20%" in text
    app._on_model_progress(None, None)
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
