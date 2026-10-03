"""auto-editor バイナリの取得・検証（ネットワークはモックする）。"""
import hashlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import aebin  # noqa: E402

REAL_ASSET = aebin.asset          # フィクスチャが差し替える前の本物
PAYLOAD = b"fake auto-editor binary"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    aebin._verified.clear()
    monkeypatch.setattr(aebin, "asset", lambda: ("auto-editor-test.exe", "https://example.invalid/ae.exe", PAYLOAD_SHA))


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_pinned_asset_is_an_official_github_release_with_a_sha256():
    name, url, sha = REAL_ASSET()
    assert url.startswith("https://github.com/WyattBlue/auto-editor/releases/download/")
    assert aebin.AE_VERSION in url and url.endswith(name)
    assert len(sha) == 64 and int(sha, 16) >= 0


def test_download_places_file_only_when_hash_matches(monkeypatch, tmp_path):
    monkeypatch.setattr(aebin.urllib.request, "urlopen", lambda url, timeout=60: _Resp(PAYLOAD))
    dest = tmp_path / "bin" / "ae.exe"
    assert aebin.download(dest) == dest and dest.read_bytes() == PAYLOAD
    assert not dest.with_suffix(".exe.part").exists()


def test_download_rejects_tampered_binary_and_leaves_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(aebin.urllib.request, "urlopen", lambda url, timeout=60: _Resp(b"tampered"))
    dest = tmp_path / "bin" / "ae.exe"
    with pytest.raises(RuntimeError, match="ハッシュ"):
        aebin.download(dest)
    assert not dest.exists() and not dest.with_suffix(".exe.part").exists()


def test_get_path_prefers_bundled_exe(monkeypatch, tmp_path):
    bundle = tmp_path / "meipass"
    bundle.mkdir()
    (bundle / aebin.BUNDLED_NAME).write_bytes(b"x")
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(aebin, "download", lambda *a, **k: pytest.fail("must not download"))
    assert aebin.get_auto_editor_path() == bundle / aebin.BUNDLED_NAME


def test_get_path_uses_verified_cache_without_downloading(monkeypatch):
    cached = aebin.cached_path()
    cached.parent.mkdir(parents=True)
    cached.write_bytes(PAYLOAD)
    monkeypatch.setattr(aebin, "download", lambda *a, **k: pytest.fail("must not download"))
    assert aebin.get_auto_editor_path() == cached


def test_get_path_discards_corrupt_cache_and_redownloads(monkeypatch):
    cached = aebin.cached_path()
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"corrupted or replaced")
    monkeypatch.setattr(aebin.urllib.request, "urlopen", lambda url, timeout=60: _Resp(PAYLOAD))
    got = aebin.get_auto_editor_path()
    assert got == cached and cached.read_bytes() == PAYLOAD


def test_get_path_downloads_when_missing_and_logs(monkeypatch):
    monkeypatch.setattr(aebin.urllib.request, "urlopen", lambda url, timeout=60: _Resp(PAYLOAD))
    logs = []
    got = aebin.get_auto_editor_path(on_log=lambda m, *_: logs.append(m))
    assert got.exists() and any("auto-editor" in m for m in logs)


def test_arch_selection(monkeypatch):
    monkeypatch.setattr(aebin.platform, "machine", lambda: "ARM64")
    assert REAL_ASSET()[0].endswith("aarch64.exe")
    monkeypatch.setattr(aebin.platform, "machine", lambda: "AMD64")
    assert REAL_ASSET()[0].endswith("x86_64.exe")
