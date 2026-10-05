"""Design tokens for SnipSync. Every value here has a stated reason in DESIGN.md §2-§5.

Change a token and DESIGN.md together; tests/test_design.py checks the contrast claims.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ── Surfaces: neutral graphite, the same family NLEs use, so footage colours are never tinted by the UI ──
BENCH = "#2a2c30"       # window
PANEL = "#33363b"       # the settings area
WELL = "#1b1c1f"        # inset areas that show media or logs (monitor, log, tables)
EDGE = "#474b52"        # 1px dividers and resting borders
RAISED = "#3d4147"      # hover on neutral controls

# ── Text ──
CHALK = "#efede8"       # primary text (warm white: easier on the eyes than #fff in a dark room)
DUST = "#a6abb3"        # secondary text, captions

# ── Signal colours. Rule: yellow = something you can press or change; the rest describe your footage ──
PENCIL = "#f2c230"      # grease-pencil yellow: the primary action, selected state, focus ring
PENCIL_HOVER = "#ffd44f"
PENCIL_INK = "#1b1600"  # text on yellow
CUT = "#ef5a4f"         # removed
SPEED = "#5aa9f2"       # sped up
KEEP = "#c9ced6"        # kept (waveform)
OK = "#62cf8c"
WARN = "#f0a23a"

# Speaker tints for the subtitle table: pastel hues, apart from CUT / SPEED / PENCIL
SPEAKERS = ("#7fd1b9", "#d7a6ea", "#f4b183", "#b9c98a")

# ── Shape: radius encodes role. Big for containers, small for controls, none for the media strip ──
R_PANEL = 10
R_CONTROL = 6
R_STRIP = 0

# ── Space: 4 px grid ──
S1, S2, S3, S4, S6 = 4, 8, 12, 16, 24

# ── Type scale (px) ──
SIZE_WORDMARK = 20
SIZE_TITLE = 15
SIZE_BODY = 13
SIZE_CAPTION = 12
SIZE_MONO = 13

# Windows lists a font under its localized family name (the same file is "BIZ UDPゴシック" on a Japanese
# system and "BIZ UDPGothic" on an English one), so look for every spelling.
_UI_NAMES = ("BIZ UDPGothic", "BIZ UDPゴシック")
_MONO_NAMES = ("BIZ UDGothic", "BIZ UDゴシック")
# BIZ UD の下線「_」は行の高さの外に描かれ、Tk の Text や Label で切れて空白に見える。ファイル名・保存先・ログは
# 下線が命なので、その表示だけ、OS 標準で下線が出る等幅体にする（日本語は Tk が別の書体で補う）。
_LITERAL_NAMES = ("Consolas", "Cascadia Mono")
_FALLBACK_UI = "Segoe UI"
_FALLBACK_MONO = "Consolas"
_FONT_FILES = ("BIZUDPGothic-Regular.ttf", "BIZUDPGothic-Bold.ttf", "BIZUDGothic-Regular.ttf")

UI_FAMILY = _FALLBACK_UI
MONO_FAMILY = _FALLBACK_MONO
LITERAL_FAMILY = _FALLBACK_MONO
_cache: dict = {}


def asset_path(rel: str) -> Path:
    """Path to a bundled file, both from source and inside a PyInstaller EXE."""
    try:
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    except AttributeError:
        base = Path(__file__).resolve().parent.parent   # snipsync/（assets/ がある）
    return base / rel


ICON = "assets/icon/snipsync.ico"


def apply_icon(window) -> None:
    """ウィンドウとタスクバーのアイコンを SnipSync のものにする。

    CustomTkinter は起動直後（約 200 ms 後）に自分の既定アイコンを設定し直すので、それより後に上書きする。
    """
    def _set():
        try:
            window.iconbitmap(str(asset_path(ICON)))
        except Exception:
            pass          # .ico を扱えない環境では既定のまま
    window.after(350, _set)


def load_fonts(ctk, root) -> None:
    """Register the bundled fonts for this process only, then pick the family names that exist.

    Call once, after the Tk root exists. Safe to call again. If anything fails the OS fonts are used.
    """
    global UI_FAMILY, MONO_FAMILY, LITERAL_FAMILY
    if sys.platform == "win32":
        for name in _FONT_FILES:
            f = asset_path(f"assets/fonts/{name}")
            if f.exists():
                try:
                    ctk.FontManager.load_font(str(f))
                except Exception:
                    pass
    try:
        from tkinter import font as tkfont
        families = set(tkfont.families(root))
    except Exception:
        families = set()
    UI_FAMILY = next((n for n in _UI_NAMES if n in families), _FALLBACK_UI)
    MONO_FAMILY = next((n for n in _MONO_NAMES if n in families), _FALLBACK_MONO)
    LITERAL_FAMILY = next((n for n in _LITERAL_NAMES if n in families), MONO_FAMILY)
    _cache.clear()


def font(ctk, role: str):
    """CTkFont for a role. Created lazily because a font needs a Tk root."""
    if role not in _cache:
        spec = {
            "wordmark": (UI_FAMILY, SIZE_WORDMARK, "bold"),
            "title": (UI_FAMILY, SIZE_TITLE, "bold"),
            "label": (UI_FAMILY, SIZE_BODY, "bold"),
            "body": (UI_FAMILY, SIZE_BODY, "normal"),
            "caption": (UI_FAMILY, SIZE_CAPTION, "normal"),
            "mono": (MONO_FAMILY, SIZE_MONO, "normal"),
            "mono_small": (MONO_FAMILY, SIZE_CAPTION, "normal"),
            "mono_large": (MONO_FAMILY, SIZE_TITLE + 3, "normal"),
            "literal": (LITERAL_FAMILY, SIZE_CAPTION, "normal"),
        }[role]
        _cache[role] = ctk.CTkFont(family=spec[0], size=spec[1], weight=spec[2])
    return _cache[role]


def contrast(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio between two #rrggbb colours."""
    def lum(c: str) -> float:
        rgb = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def blend(fg: str, bg: str, alpha: float) -> str:
    """fg over bg at the given opacity, as #rrggbb (Tk has no alpha)."""
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * alpha + y * (1 - alpha)):02x}" for x, y in zip(f, b, strict=True))
