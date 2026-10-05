"""構造の方針を守る試験（ARCHITECTURE.md §2）。画面は起動しない。"""
import ast
from pathlib import Path

PKG = Path(__file__).parent.parent / "src" / "snipsync"
MOVED = {  # 以前は src 直下に平らに置かれていたモジュール。`import pipeline` のような旧い書き方を、戻さない
    "aebin", "app", "audiocut", "autoeditor", "cudalibs", "diarize", "i18n", "i18n_tips", "markers", "models",
    "pipeline", "player", "presets", "preview", "safexml", "subtitle_edit", "subtitle_editor", "subtitles",
    "theme", "transcript", "vad", "version", "waveform", "widgets",
}


def _imported_modules(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            yield mod
            for alias in node.names:
                yield f"{mod}.{alias.name}"


def test_core_never_imports_the_ui():
    files = sorted((PKG / "core").glob("*.py"))
    assert files, "src/snipsync/core に Python ファイルが無い（検査が空振りになる）"
    bad = [(f.name, m) for f in files for m in _imported_modules(f) if m == "snipsync.ui" or m.startswith("snipsync.ui.")]
    assert not bad, bad


def test_imports_are_absolute_package_paths():
    files = sorted(PKG.rglob("*.py"))
    assert files
    bad = []
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                bad.append((f.name, "relative import"))
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else []
            bad += [(f.name, n) for n in names if n.split(".")[0] in MOVED]
    assert not bad, bad
