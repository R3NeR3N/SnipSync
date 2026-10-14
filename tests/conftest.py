"""テスト全体の準備。"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pytest_sessionstart(session):
    """開発用の印（src/snipsync/build_info.py）が、すでに手元にあるときだけ、いまのソースで作り直す。
    印が古いまま残って、「印がソースと合っているか」の試験が、手元だけで落ちるのを防ぐ。"""
    stamp = ROOT / "src" / "snipsync" / "build_info.py"
    if not stamp.exists():
        return
    sys.path.insert(0, str(ROOT / "src"))
    spec = importlib.util.spec_from_file_location("dev_stamp", ROOT / "scripts" / "dev_stamp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main(["--refresh"])
