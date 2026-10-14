"""開発用の印（buildinfo.py・scripts/dev_stamp.py）。ヘッダーの ID で、最新のソースから動いているかを確かめる仕組み。"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from snipsync import buildinfo  # noqa: E402


def make_tree(tmp_path, body="x = 1\n"):
    pkg = tmp_path / "src" / "snipsync"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_text(body, encoding="utf-8")
    (pkg / "sub").mkdir()
    (pkg / "sub" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return pkg


def test_the_id_is_seven_hex_digits_and_changes_when_any_source_changes(tmp_path):
    pkg = make_tree(tmp_path)
    first = buildinfo.source_hash(pkg, tmp_path)
    assert len(first) == 7 and set(first) <= set("0123456789abcdef")
    assert buildinfo.source_hash(pkg, tmp_path) == first                          # 同じ中身なら、同じ ID
    (pkg / "sub" / "b.py").write_text("y = 3\n", encoding="utf-8")
    assert buildinfo.source_hash(pkg, tmp_path) != first
    (pkg / "sub" / "b.py").write_text("y = 2\n", encoding="utf-8")
    assert buildinfo.source_hash(pkg, tmp_path) == first                          # 戻せば、戻る
    (tmp_path / "pyproject.toml").write_text("[project]\nname='y'\n", encoding="utf-8")
    assert buildinfo.source_hash(pkg, tmp_path) != first                          # 依存の指定の変更も、中身の変更


def test_the_id_ignores_line_endings_the_stamp_itself_and_caches(tmp_path):
    pkg = make_tree(tmp_path)
    base = buildinfo.source_hash(pkg, tmp_path)
    (pkg / "a.py").write_bytes(b"x = 1\r\n")                                      # CRLF でも、同じ
    assert buildinfo.source_hash(pkg, tmp_path) == base
    (pkg / buildinfo.STAMP_NAME).write_text("BUILD = {}\n", encoding="utf-8")       # 印のファイル自身は、数えない
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "c.py").write_text("junk\n", encoding="utf-8")
    assert buildinfo.source_hash(pkg, tmp_path) == base


def test_the_stamp_file_is_importable_python_with_the_build_dict():
    info = {"hash": "abc1234", "commit": "d3d30b3", "dirty": True, "builtAt": "2026-10-16T09:00:00"}
    ns: dict = {}
    exec(buildinfo.stamp_source(info), ns)                                           # noqa: S102  自分で作った文字列
    assert ns["BUILD"] == info


@pytest.mark.parametrize("build,expected", [
    (None, "v0.3.0"), ({}, "v0.3.0"), ({"hash": ""}, "v0.3.0"), ({"hash": 5}, "v0.3.0"),
    ({"hash": "1a2b3c4"}, "v0.3.0 · dev 1a2b3c4"),
])
def test_the_header_shows_the_id_only_when_there_is_a_stamp(build, expected):
    assert buildinfo.version_label("0.3.0", build) == expected


def test_outside_a_git_checkout_there_is_no_build(tmp_path):
    pkg = make_tree(tmp_path)
    assert buildinfo.describe_checkout(tmp_path, pkg) is None


def test_inside_a_checkout_the_build_has_the_commit_and_the_dirty_flag(tmp_path):
    pkg = make_tree(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=t", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True)
    clean = buildinfo.describe_checkout(tmp_path, pkg)
    assert clean["dirty"] is False and len(clean["commit"]) >= 7 and clean["hash"] == buildinfo.source_hash(pkg, tmp_path)
    (pkg / "a.py").write_text("x = 2\n", encoding="utf-8")
    dirty = buildinfo.describe_checkout(tmp_path, pkg)
    assert dirty["dirty"] is True and dirty["hash"] != clean["hash"]
    (pkg / buildinfo.STAMP_NAME).write_text("BUILD = {}\n", encoding="utf-8")
    assert buildinfo.describe_checkout(tmp_path, pkg)["dirty"] is True               # 印の追加だけでは、汚れと数えない（下の確認）
    (pkg / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert buildinfo.describe_checkout(tmp_path, pkg)["dirty"] is False


def test_running_from_source_computes_the_id_live_and_a_frozen_app_reads_the_embedded_stamp(monkeypatch):
    live = buildinfo.get_build()
    assert live is None or live["hash"] == buildinfo.source_hash()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    import types
    fake = types.ModuleType("snipsync.build_info")
    fake.BUILD = {"hash": "9f8e7d6", "commit": "abc", "dirty": False, "builtAt": "t"}
    monkeypatch.setitem(sys.modules, "snipsync.build_info", fake)
    assert buildinfo.get_build()["hash"] == "9f8e7d6"
    fake.BUILD = {"hash": ""}
    assert buildinfo.get_build() is None
    monkeypatch.delitem(sys.modules, "snipsync.build_info")
    # 印が無い EXE（配布版）は、何も出さない
    import builtins
    real_import = builtins.__import__

    def refuse(name, *a, **k):
        if name == "snipsync.build_info":
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert buildinfo.get_build() is None


def load_script():
    spec = importlib.util.spec_from_file_location("dev_stamp_under_test", ROOT / "scripts" / "dev_stamp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_stamp_script_skips_in_github_actions_and_without_a_stamp_when_refreshing(tmp_path, monkeypatch):
    mod = load_script()
    monkeypatch.setattr(mod, "TARGET", tmp_path / "build_info.py")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert mod.main(["--local"]) == 0 and not mod.TARGET.exists()                    # 配布版には、印を入れない
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert mod.main(["--refresh"]) == 0 and not mod.TARGET.exists()                  # 印が無ければ、作らない
    assert mod.main([]) == 0 and mod.TARGET.exists()                                 # 指定なしは、作る
    assert "BUILD" in mod.TARGET.read_text(encoding="utf-8")
    before = mod.TARGET.read_text(encoding="utf-8")
    assert mod.main(["--refresh"]) == 0 and mod.TARGET.read_text(encoding="utf-8") != ""
    assert before.split("'hash': ")[1][:9] == mod.TARGET.read_text(encoding="utf-8").split("'hash': ")[1][:9]


def test_a_stamp_in_this_checkout_matches_the_current_source():
    """印がある手元では、印が古いまま残っていない（conftest が、テストの前に作り直す）。"""
    stamp = ROOT / "src" / "snipsync" / buildinfo.STAMP_NAME
    if not stamp.exists():
        pytest.skip("手元に印が無い（CI など）")
    ns: dict = {}
    exec(stamp.read_text(encoding="utf-8"), ns)                                      # noqa: S102
    assert ns["BUILD"]["hash"] == buildinfo.source_hash()


def test_the_stamp_is_never_tracked_and_the_release_workflow_does_not_stamp():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "src/snipsync/build_info.py" in ignore
    tracked = subprocess.run(["git", "ls-files", "src/snipsync/build_info.py"], cwd=ROOT, capture_output=True, text=True)
    assert tracked.stdout.strip() == ""
    spec = (ROOT / "build" / "app.spec").read_text(encoding="utf-8")
    assert "--local" in spec and "GITHUB_ACTIONS" in spec                             # CI では、印を作らず、入れもしない
