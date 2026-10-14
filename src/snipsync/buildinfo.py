"""開発用の印: いま動いているアプリが、最新のソースから作られたかを、ヘッダーの ID で確かめる。

版（0.3.0 など）は、リリースまで変わらない。開発中は、版が同じまま中身だけが変わるので、「古い EXE を開いていた」
「直したはずの変更が入っていない」が、版の番号では分からない。そこで、ソースの中身から計算した 7 桁の ID を、
ヘッダーに「v0.3.0 · dev 1a2b3c4」と出す。直したあと、ID が変わっていれば、新しい中身で動いている。

- ソースから実行しているとき（git のチェックアウトの中）: 起動のたびに、ソースから ID を計算する（印のファイルは要らない）。
- EXE: ビルドのとき、scripts/dev_stamp.py が `src/snipsync/build_info.py` を作り、EXE に入る（コミットしない）。
- 配布版（GitHub Actions が、きれいなチェックアウトから作る EXE）には、印が無いので、ヘッダーは「v0.3.0」のまま。
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
STAMP_NAME = "build_info.py"          # 印のファイル（コミットしない）。ID の計算には含めない
HASH_LEN = 7


def _source_files(package_dir: Path, root: Path) -> list[Path]:
    files = [p for p in package_dir.rglob("*.py") if p.name != STAMP_NAME and "__pycache__" not in p.parts]
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        files.append(pyproject)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def source_hash(package_dir: Path = PACKAGE_DIR, root: Path | None = None) -> str:
    """ソース（パッケージの .py と pyproject.toml）の中身から作る、7 桁の ID。改行コード（CRLF・LF）の違いでは変わらない。"""
    root = root or package_dir.parent.parent
    h = hashlib.sha256()
    for path in _source_files(package_dir, root):
        h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\n")
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\n")
    return h.hexdigest()[:HASH_LEN]


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def describe_checkout(root: Path | None = None, package_dir: Path = PACKAGE_DIR) -> dict | None:
    """git のチェックアウトにいるとき、いまのソースの印（hash・commit・dirty・builtAt）。そうでなければ None。"""
    root = root or package_dir.parent.parent
    if not (root / ".git").exists():
        return None
    status = _git(root, "status", "--porcelain", "--", ".", f":!src/snipsync/{STAMP_NAME}")
    return {"hash": source_hash(package_dir, root), "commit": _git(root, "rev-parse", "--short", "HEAD") or "unknown",
            "dirty": status != "", "builtAt": datetime.now().isoformat(timespec="seconds")}


def stamp_source(info: dict) -> str:
    """印のファイル（build_info.py）の中身。"""
    return ("# 開発用の印（scripts/dev_stamp.py が作る。コミットしない）\n"
            f"BUILD = {{'hash': {info['hash']!r}, 'commit': {info['commit']!r}, 'dirty': {bool(info['dirty'])!r}, "
            f"'builtAt': {info['builtAt']!r}}}\n")


def get_build() -> dict | None:
    """いま動いているアプリの印。EXE は、ビルドのときに入れた印。ソースから実行しているときは、いまのソースから計算した印。
    どちらでもなければ（配布版・pip で入れたもの）、None。"""
    if getattr(sys, "frozen", False):
        try:
            from snipsync.build_info import BUILD
        except ImportError:
            return None
        return dict(BUILD) if isinstance(BUILD, dict) and BUILD.get("hash") else None
    try:
        return describe_checkout()
    except Exception:
        return None


def version_label(version: str, build: dict | None) -> str:
    """ヘッダーに出す版の表示。印があれば「v版 · dev ID」。"""
    hash_ = build.get("hash") if isinstance(build, dict) else None
    return f"v{version} · dev {hash_}" if isinstance(hash_, str) and hash_ else f"v{version}"
