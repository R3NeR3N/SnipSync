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
