"""開発用の印（src/snipsync/build_info.py）を作る。EXE のビルドの前に呼ぶ（build/app.spec が自動で呼ぶ）。

使い方:
    python scripts/dev_stamp.py            印を作る・作り直す
    python scripts/dev_stamp.py --refresh  印がすでにあるときだけ、作り直す（テストの前に使う）
    python scripts/dev_stamp.py --local    GitHub Actions の中では、何もしない（配布版に印を入れないため）。それ以外は、作る

印は手元の確認用で、コミットしない（.gitignore）。意味と仕組みは、src/snipsync/buildinfo.py の先頭に書いてある。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snipsync.buildinfo import (  # noqa: E402
    PACKAGE_DIR,
    STAMP_NAME,
    describe_checkout,
    stamp_source,
)

TARGET = PACKAGE_DIR / STAMP_NAME


def main(argv: list[str]) -> int:
    if "--local" in argv and os.environ.get("GITHUB_ACTIONS"):
        return 0                                    # 配布版（GitHub Actions のビルド）には、印を入れない
    if "--refresh" in argv and not TARGET.exists():
        return 0
    info = describe_checkout(ROOT)
    if info is None:
        print("git のチェックアウトの中ではないので、印は作りません。")
        return 0
    TARGET.write_text(stamp_source(info), encoding="utf-8")
    print(f"印を作りました: dev {info['hash']}（コミット {info['commit']}{'・未コミットの変更あり' if info['dirty'] else ''}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
