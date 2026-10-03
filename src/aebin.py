"""auto-editor バイナリの取得と検証。

PyPI の ``auto-editor`` は 29.3.1 で止まっていて、31.x は GitHub Releases のバイナリでしか入手できない。
SnipSync は動作確認した版（AE_VERSION）に固定し、SHA-256 を照合してから実行する。

- 配布 EXE: ビルド時に同梱（``build/app.spec``、``scripts/fetch_auto_editor.py`` が取得）。
- ソース実行: 初回だけ ``%APPDATA%/SnipSync/bin`` へ取得して再利用する。
- SHA-256 は GitHub Releases API の asset ``digest`` と、手元でダウンロードしたファイルの実測値が一致している。

ライセンス上の注意（31.4.0 以降の公式仕様）: ライセンスキー無しでも、単一入力のタイムライン出力は制限なし。
レンダリング（メディア書き出し）は 3200x1800 を超えると自動で縮小される。複数入力の結合は要キー。
"""
from __future__ import annotations

import hashlib
import os
import platform
import sys
import urllib.request
from pathlib import Path

AE_VERSION = "31.7.2"
_RELEASE = f"https://github.com/WyattBlue/auto-editor/releases/download/{AE_VERSION}"
_ASSETS = {
    "x86_64": ("auto-editor-windows-x86_64.exe",
               "c5dd8d44a92e9b5fbce13aacea92d02436ea24f9f4c6177a6a9d851801fb74c3"),
    "aarch64": ("auto-editor-windows-aarch64.exe",
                "f88895ea55e7e8a6dc8146b68f499a0015b28d06c373b0397c67cc7e3547ca66"),
}
BUNDLED_NAME = "auto-editor.exe"

_verified: dict[str, bool] = {}


def _arch() -> str:
    m = platform.machine().lower()
    return "aarch64" if m in ("arm64", "aarch64") else "x86_64"


def asset() -> tuple[str, str, str]:
    """(ファイル名, ダウンロードURL, 期待する SHA-256)。"""
    name, sha = _ASSETS[_arch()]
    return name, f"{_RELEASE}/{name}", sha


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def bin_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) / "SnipSync" if base else Path.home() / ".snipsync"
    return root / "bin"


def cached_path() -> Path:
    return bin_dir() / f"auto-editor-{AE_VERSION}.exe"


def _is_valid(path: Path, expected: str) -> bool:
    key = f"{path}:{path.stat().st_mtime_ns}:{path.stat().st_size}"
    if key not in _verified:
        _verified[key] = sha256_of(path) == expected
    return _verified[key]


def download(dest: Path, on_log=None) -> Path:
    """公式リリースから固定版を取得し、SHA-256 が一致したときだけ dest に置く。"""
    name, url, expected = asset()
    if not url.startswith("https://"):
        raise ValueError(f"https 以外の URL は取得しません: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if on_log:
        on_log(f"  auto-editor {AE_VERSION} を取得しています（約45MB・初回のみ）...", "muted")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:  # nosec B310 - https のみ（上で検査）
            while True:
                block = resp.read(1 << 20)
                if not block:
                    break
                out.write(block)
        if sha256_of(tmp) != expected:
            raise RuntimeError(f"auto-editor のハッシュが一致しません（{name}）。ダウンロードを破棄しました。")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    _verified.clear()
    return dest


def bundled_path() -> Path | None:
    """PyInstaller で同梱した exe。ビルド時に版とハッシュを確認済み。"""
    base = getattr(sys, "_MEIPASS", None)
    if base and (Path(base) / BUNDLED_NAME).exists():
        return Path(base) / BUNDLED_NAME
    return None


def get_auto_editor_path(on_log=None) -> Path:
    """使う auto-editor の実行パス。同梱版 → 取得済みキャッシュ → 新規取得の順。"""
    bundled = bundled_path()
    if bundled:
        return bundled
    _, _, expected = asset()
    cached = cached_path()
    if cached.exists():
        if _is_valid(cached, expected):
            return cached
        cached.unlink(missing_ok=True)       # 壊れている/改ざんされている版は使わない
    return download(cached, on_log)
