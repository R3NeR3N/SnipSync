"""デザインの主張（DESIGN.md）が、実際に成り立っていることを守るテスト。画面は起動しない。"""
import re
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from snipsync.i18n import I18N  # noqa: E402
from snipsync.ui import theme as T  # noqa: E402

PY_FILES = sorted((SRC / "snipsync").rglob("*.py"))
assert PY_FILES, "src/snipsync に Python ファイルが無い（検査が空振りになる）"


# ── 配色: 読めること ──────────────────────────────────────────────────────────────────
TEXT_PAIRS = [
    (T.CHALK, T.BENCH, 7), (T.CHALK, T.PANEL, 7), (T.CHALK, T.WELL, 7),          # 本文は AAA
    (T.DUST, T.BENCH, 4.5), (T.DUST, T.PANEL, 4.5), (T.DUST, T.WELL, 4.5),        # 補助テキストは AA
    (T.PENCIL_INK, T.PENCIL, 7), (T.PENCIL_INK, T.PENCIL_HOVER, 7),               # 黄色いボタンの文字
    (T.OK, T.WELL, 4.5), (T.WARN, T.WELL, 4.5), (T.CUT, T.WELL, 4.5), (T.SPEED, T.WELL, 4.5),  # ログの文字色
]
GRAPHIC_PAIRS = [
    (T.PENCIL, T.PANEL, 3), (T.PENCIL, T.WELL, 3),          # 選択・フォーカスの黄色
    (T.CUT, T.WELL, 3), (T.SPEED, T.WELL, 3), (T.KEEP, T.WELL, 3),   # カットマップの3色
]


@pytest.mark.parametrize("fg,bg,need", TEXT_PAIRS + GRAPHIC_PAIRS)
def test_color_pairs_meet_their_contrast_target(fg, bg, need):
    assert T.contrast(fg, bg) >= need, f"{fg} on {bg}: {T.contrast(fg, bg):.2f} < {need}"


@pytest.mark.parametrize("color", T.SPEAKERS)
def test_speaker_tints_keep_text_readable(color):
    row = T.blend(color, T.WELL, 0.13)
    assert T.contrast(T.CHALK, row) >= 7
    assert T.contrast(color, T.WELL) >= 4.5


def test_the_three_meanings_of_the_cut_map_are_distinguishable_from_each_other():
    # 削除・倍速・残るが同じに見えない（色相か明度が十分に違う）
    pairs = [(T.CUT, T.SPEED), (T.CUT, T.KEEP), (T.SPEED, T.KEEP)]
    for a, b in pairs:
        assert T.contrast(a, b) >= 1.3 or abs(int(a[1:3], 16) - int(b[1:3], 16)) > 60, (a, b)


def test_the_accent_is_not_reused_for_a_footage_meaning():
    # 黄色は「押せる・選んだ」だけ。素材の意味（残る/削除/倍速）と同じ色にしない
    for meaning in (T.CUT, T.SPEED, T.KEEP, T.OK):
        assert meaning.lower() != T.PENCIL.lower()
    assert T.contrast(T.PENCIL, T.CUT) > 1.5 and T.contrast(T.PENCIL, T.SPEED) > 1.2


def test_blend_and_contrast_helpers():
    assert T.blend("#ffffff", "#000000", 0.5) == "#808080"
    assert T.contrast("#000000", "#ffffff") == pytest.approx(21.0)


# ── 色・フォントはトークンから ─────────────────────────────────────────────────────────
HEX = re.compile(r"""["']#[0-9a-fA-F]{6}["']""")


@pytest.mark.parametrize("path", [p for p in PY_FILES if p.name != "theme.py"], ids=lambda p: p.name)
def test_no_colour_literals_outside_the_theme(path):
    hits = HEX.findall(path.read_text(encoding="utf-8"))
    assert not hits, f"{path.name} defines colours itself: {hits}. Add a token to theme.py instead"


@pytest.mark.parametrize("path", [p for p in PY_FILES if p.name != "theme.py"], ids=lambda p: p.name)
def test_no_font_names_outside_the_theme(path):
    text = path.read_text(encoding="utf-8")
    assert "family=" not in text and "Segoe UI" not in text and "Consolas" not in text, path.name


def test_radius_and_spacing_tokens_follow_the_stated_scale():
    assert T.R_STRIP == 0 < T.R_CONTROL < T.R_PANEL        # 素材の帯 < 操作部品 < 面
    for s in (T.S1, T.S2, T.S3, T.S4, T.S6):
        assert s % 4 == 0                                   # 4px グリッド


# ── 同梱フォント ─────────────────────────────────────────────────────────────────────
def test_bundled_fonts_and_their_licence_are_present():
    d = SRC / "snipsync" / "assets" / "fonts"
    for name in T._FONT_FILES:
        f = d / name
        assert f.exists() and f.stat().st_size > 1_000_000, name
        assert f.read_bytes()[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO")      # TrueType / OpenType
    licence = (d / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence
    assert "Reserved Font Name" not in licence.split("PREAMBLE")[0]       # 予約名の指定なし = そのまま再配布できる


def test_font_roles_are_defined_and_use_the_resolved_families():
    sizes = [T.SIZE_CAPTION, T.SIZE_BODY, T.SIZE_TITLE, T.SIZE_WORDMARK]
    assert sizes == sorted(set(sizes)) and T.SIZE_CAPTION >= 12     # 最小でも 12px
    assert "BIZ" in " ".join(T._UI_NAMES + T._MONO_NAMES)


def test_text_with_underscores_is_not_set_in_biz_ud():
    """BIZ UD は下線「_」が行の高さの外に出て、Tk に切り取られる（ファイル名が空白に見える）。DESIGN.md §4。"""
    assert not any("BIZ" in n for n in T._LITERAL_NAMES)
    src = (SRC / "snipsync" / "ui" / "app.py").read_text(encoding="utf-8")
    assert re.search(r'self\.folder_lbl = W\.label\(row, "", "literal"', src)
    assert re.search(r'self\.console = ctk\.CTkTextbox\([^)]*font=T\.font\(ctk, "literal"\)', src, re.S)


# ── 文言 ─────────────────────────────────────────────────────────────────────────────
def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_captions_fit_on_one_line(lang):
    """補足文は1行（約 460px）に収める。Tk のラベルは行間を調整できず、折り返すと詰まって読みにくい。"""
    too_long = {k: width(v) for k, v in I18N[lang].items() if k.startswith("cap_") and width(v) > 72}
    assert not too_long, too_long


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_ui_copy_has_no_emoji_and_no_trailing_decoration(lang):
    for key, value in I18N[lang].items():
        texts = value.values() if isinstance(value, dict) else [value]
        for v in texts:
            assert not any(ord(c) > 0x1F000 for c in v), (key, v)          # 絵文字なし（フォントが変わるため）
            assert "→" not in v, (key, v)                                   # ボタンや文言に矢印を付けない


def test_i18n_has_no_dead_keys_and_no_missing_keys():
    sources = {p.name: p.read_text(encoding="utf-8") for p in PY_FILES if p.name not in ("i18n.py", "i18n_tips.py")}
    blob = "\n".join(sources.values())
    dynamic = ("cap_export_", "hover_")          # f"cap_export_{key}" / "hover_" + kind
    dead = [k for k in I18N["ja"] if f'"{k}"' not in blob and f"'{k}'" not in blob and not k.startswith(dynamic)]
    assert not dead, f"keys that nothing uses: {dead}"
    used = set(re.findall(r'(?:\bt|\btr|\.t)\(\s*"(\w+)"', blob)) | set(re.findall(r'reg\([^,]+,\s*"(\w+)"\)', blob))
    used |= set(re.findall(r'self\._field\([^,]+,\s*"(\w+)"', blob)) | set(re.findall(r'"(f_\w+|cap_\w+)"\)', blob))
    missing = sorted(k for k in used if k not in I18N["ja"])
    assert not missing, f"keys used but not defined: {missing}"


def test_buttons_use_the_same_word_in_the_flow():
    """動作の名前は流れの中で変えない: 開始 → ログ。保存 → 保存しました。"""
    ja = I18N["ja"]
    assert "開始" in ja["btn_start"] and "開始" in ja["log_start"]
    assert "停止" in ja["btn_stop"] and "停止" in ja["log_stopped"]
    assert "保存" in ja["ed_save"] and "保存" in ja["ed_saved"]
    en = I18N["en"]
    assert "Start" in en["btn_start"] and "Stop" in en["btn_stop"] and "Save" in en["ed_save"] and "Saved" in en["ed_saved"]


# ── アプリアイコン ───────────────────────────────────────────────────────────────────
def test_app_icon_is_bundled_with_all_standard_sizes():
    ico = (SRC / "snipsync" / "assets" / "icon" / "snipsync.ico").read_bytes()
    reserved, kind, count = int.from_bytes(ico[0:2], "little"), int.from_bytes(ico[2:4], "little"), int.from_bytes(ico[4:6], "little")
    assert (reserved, kind) == (0, 1)
    sizes = {ico[6 + 16 * i] or 256 for i in range(count)}              # 幅（0 は 256）
    assert {16, 24, 32, 48, 64, 128, 256} <= sizes
    assert (SRC / "snipsync" / "assets" / "icon" / "snipsync.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_icon_and_header_logo_are_drawn_from_the_same_shapes():
    """アイコン（scripts/make_icon.py）とヘッダーのロゴ（widgets.Logo）は、同じ座標を使う。片方だけ直すと食い違う。"""
    shapes = ("3, 9, 15, 9, 11, 21, 3, 21", "19, 9, 27, 9, 27, 21, 15, 21", "18, 5, 9, 25")
    icon = (ROOT / "scripts" / "make_icon.py").read_text(encoding="utf-8")
    logo = (SRC / "snipsync" / "ui" / "widgets.py").read_text(encoding="utf-8")
    for s in shapes:
        assert s in icon and s in logo, s


def test_apply_icon_sets_the_bundled_ico_after_customtkinter_has_set_its_own():
    """CustomTkinter は約 200 ms 後に既定アイコンを入れる。それより後（350 ms）に自分のアイコンで上書きする。"""
    calls = {}

    class Win:
        def after(self, ms, fn):
            calls["delay"] = ms
            fn()

        def iconbitmap(self, path):
            calls["icon"] = Path(path)

    T.apply_icon(Win())
    assert calls["delay"] > 200
    assert calls["icon"].name == "snipsync.ico" and calls["icon"].exists()


def test_apply_icon_survives_a_platform_that_rejects_ico():
    class Win:
        def after(self, ms, fn):
            fn()

        def iconbitmap(self, path):
            raise RuntimeError("bitmap not defined")

    T.apply_icon(Win())          # 例外を外へ出さない
