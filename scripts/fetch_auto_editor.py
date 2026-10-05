"""配布 EXE に同梱する auto-editor を build/vendor/ に取得する（SHA-256 検証つき）。

使い方（EXE ビルドの前に1回）:
    python scripts/fetch_auto_editor.py
    pyinstaller build/app.spec
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snipsync.core import aebin  # noqa: E402


def main() -> int:
    dest = ROOT / "build" / "vendor" / aebin.BUNDLED_NAME
    _, _, expected = aebin.asset()
    if dest.exists() and aebin.sha256_of(dest) == expected:
        print(f"OK (already present): {dest}  [auto-editor {aebin.AE_VERSION}]")
        return 0
    aebin.download(dest, on_log=lambda msg, *_: print(msg))
    print(f"OK: {dest}  [auto-editor {aebin.AE_VERSION}, sha256 verified]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
