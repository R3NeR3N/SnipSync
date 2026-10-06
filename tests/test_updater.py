"""本体の更新（core/updater.py）とモデルの更新確認（core/models.py）。通信はしない。"""
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core import models, updater  # noqa: E402

PAYLOAD = b"MZ-new-snipsync" * 1000
SHA = hashlib.sha256(PAYLOAD).hexdigest()
URL = f"https://github.com/{updater.REPO}/releases/download/v0.3.0/SnipSync.exe"


SIZE = len(PAYLOAD)


def release_json(tag="v0.3.0", digest=f"sha256:{SHA}", size=SIZE, assets=True):
    data = {"tag_name": tag, "html_url": f"https://github.com/{updater.REPO}/releases/tag/{tag}", "body": "notes"}
    data["assets"] = [{"name": "SnipSync.exe", "size": size, "digest": digest, "browser_download_url": URL}] if assets else []
    return data


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def opener_for(payload: bytes):
    seen = []

    def opener(req, timeout=None):
        seen.append(req.full_url if hasattr(req, "full_url") else req)
        return FakeResponse(payload)

    opener.seen = seen
    return opener


# ── 版の比較 ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("remote,local,expected", [
    ("0.3.0", "0.2.0", True), ("v0.3.0", "0.2.0", True), ("0.2.0", "0.2.0", False), ("0.1.9", "0.2.0", False),
    ("0.10.0", "0.9.0", True),                       # 文字の比較ではなく、数の比較
    ("0.3.0-rc.1", "0.2.0", False),                  # プレリリースは促さない
    ("not-a-version", "0.2.0", False),               # 読めない版は更新を促さない
])
def test_is_newer(remote, local, expected):
    assert updater.is_newer(remote, local) is expected


def test_parse_release_reads_the_asset_and_the_github_digest():
    r = updater.parse_release(release_json())
    assert (r.version, r.tag, r.size, r.sha256, r.asset_url) == ("0.3.0", "v0.3.0", len(PAYLOAD), SHA, URL)


@pytest.mark.parametrize("digest", [None, "", "md5:abc", "sha256:xyz", f"sha256:{SHA[:-1]}"])
def test_a_release_without_a_valid_sha256_digest_is_never_installed_automatically(digest):
    r = updater.parse_release(release_json(digest=digest))
    assert r.sha256 is None and not updater.can_install(r, exe=Path(__file__))


def test_a_release_without_the_exe_asset_cannot_be_installed():
    r = updater.parse_release(release_json(assets=False))
    assert r.asset_url is None and not updater.can_install(r, exe=Path(__file__))


def test_fetch_latest_and_find_update_use_the_github_api():
    body = json.dumps(release_json()).encode("utf-8")
    opener = opener_for(body)
    assert updater.find_update(opener, current="0.2.0").version == "0.3.0"
    assert opener.seen == [updater.API_URL] and updater.API_URL.startswith("https://api.github.com/")
    assert updater.find_update(opener, current="0.3.0") is None


def test_fetch_latest_turns_any_failure_into_update_error():
    def broken(req, timeout=None):
        raise OSError("offline")

    with pytest.raises(updater.UpdateError, match="offline"):
        updater.fetch_latest(broken)
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest(opener_for(b"not json"))


# ── 取得 ─────────────────────────────────────────────────────────────────────────────
def test_download_verifies_size_and_hash_then_places_the_file(tmp_path):
    r = updater.parse_release(release_json())
    dest = tmp_path / "SnipSync.exe.new"
    progress = []
    updater.download(r, dest, opener=opener_for(PAYLOAD), on_progress=lambda d, t: progress.append((d, t)))
    assert dest.read_bytes() == PAYLOAD
    assert progress[-1] == (None, None) and progress[0][1] == len(PAYLOAD)
    assert not list(tmp_path.glob("*.part"))


def test_download_discards_a_file_whose_hash_does_not_match(tmp_path):
    r = updater.parse_release(release_json())
    dest = tmp_path / "SnipSync.exe.new"
    tampered = b"X" + PAYLOAD[1:]                      # 大きさは同じで、中身だけ違う
    with pytest.raises(updater.UpdateError, match="does not match"):
        updater.download(r, dest, opener=opener_for(tampered))
    assert not dest.exists() and not list(tmp_path.iterdir())


def test_download_discards_a_truncated_file(tmp_path):
    r = updater.parse_release(release_json())
    with pytest.raises(updater.UpdateError):
        updater.download(r, tmp_path / "x.new", opener=opener_for(PAYLOAD[:-5]))
    assert not list(tmp_path.iterdir())


def test_download_can_be_stopped(tmp_path):
    r = updater.parse_release(release_json())
    with pytest.raises(updater.UpdateCancelled):
        updater.download(r, tmp_path / "x.new", opener=opener_for(PAYLOAD), should_stop=lambda: True)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("url", [
    "http://github.com/R3NeR3N/SnipSync/releases/download/v0.3.0/SnipSync.exe",
    "https://evil.example.com/R3NeR3N/SnipSync/releases/download/v0.3.0/SnipSync.exe",
    "https://github.com/someone-else/SnipSync/releases/download/v0.3.0/SnipSync.exe",
])
def test_download_refuses_addresses_outside_this_repositorys_releases(tmp_path, url):
    r = updater.Release("0.3.0", "v0.3.0", "", "", url, len(PAYLOAD), SHA)
    called = []
    with pytest.raises(updater.UpdateError):
        updater.download(r, tmp_path / "x.new", opener=lambda *a, **k: called.append(1))
    assert not called


# ── 差し替え ──────────────────────────────────────────────────────────────────────────
def test_swap_moves_the_running_exe_aside_puts_the_new_one_and_starts_it(tmp_path):
    exe, new = tmp_path / "SnipSync.exe", tmp_path / "SnipSync.exe.new"
    exe.write_bytes(b"old"), new.write_bytes(b"new")
    launched = []
    updater.swap_and_relaunch(new, exe, spawn=lambda cmd, **kw: launched.append((cmd, kw)))
    assert exe.read_bytes() == b"new" and (tmp_path / "SnipSync.exe.old").read_bytes() == b"old"
    assert not new.exists()
    cmd, kw = launched[0]
    assert cmd == [str(exe)] and kw["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and kw["close_fds"]


def test_swap_puts_the_old_exe_back_when_the_new_one_cannot_be_placed(tmp_path):
    exe = tmp_path / "SnipSync.exe"
    exe.write_bytes(b"old")
    missing = tmp_path / "SnipSync.exe.new"               # 新しい exe が無い → 置けない
    with pytest.raises(updater.UpdateError):
        updater.swap_and_relaunch(missing, exe, spawn=lambda *a, **k: pytest.fail("must not start"))
    assert exe.read_bytes() == b"old" and not (tmp_path / "SnipSync.exe.old").exists()


def test_cleanup_removes_leftovers_but_only_for_the_given_exe(tmp_path):
    exe = tmp_path / "SnipSync.exe"
    exe.write_bytes(b"cur")
    (tmp_path / "SnipSync.exe.old").write_bytes(b"o")
    (tmp_path / "SnipSync.exe.new").write_bytes(b"n")
    (tmp_path / "keep.txt").write_bytes(b"k")
    updater.cleanup_old(exe)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["SnipSync.exe", "keep.txt"]


def test_running_from_source_never_installs_or_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "frozen", lambda: False)
    r = updater.parse_release(release_json())
    assert not updater.can_install(r)
    updater.cleanup_old()                                   # 例外なく何もしない


# ── 設定 ─────────────────────────────────────────────────────────────────────────────
def test_state_defaults_roundtrips_and_survives_a_broken_file(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    s = updater.load_state()
    assert s["check_enabled"] is True and s["skip_version"] == "" and s["skip_models"] == {}
    s.update(check_enabled=False, skip_version="0.3.0", last_check=123.0)
    updater.save_state(s)
    assert updater.load_state()["skip_version"] == "0.3.0" and updater.load_state()["check_enabled"] is False
    updater._state_path().write_text("{broken", encoding="utf-8")
    assert updater.load_state()["check_enabled"] is True


def test_check_is_due_once_a_day_and_only_when_enabled():
    now = 1_000_000.0
    base = {"check_enabled": True, "last_check": now - updater.CHECK_INTERVAL + 1}
    assert not updater.check_due(base, now)
    assert updater.check_due({**base, "last_check": now - updater.CHECK_INTERVAL}, now)
    assert not updater.check_due({"check_enabled": False, "last_check": 0.0}, now)


# ── モデルの更新確認 ───────────────────────────────────────────────────────────────────
def fake_cache(tmp_path, monkeypatch, key="small", revision="aaa111"):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    folder = models.model_folder(key)
    (folder / "refs").mkdir(parents=True)
    (folder / "refs" / "main").write_text(revision + "\n", encoding="utf-8")
    monkeypatch.setattr(models, "needs_download", lambda k: False)
    return folder


def test_a_model_with_a_newer_remote_commit_is_reported(tmp_path, monkeypatch):
    fake_cache(tmp_path, monkeypatch)
    check = models.find_model_updates(["small"], remote_info=lambda repo: ("bbb222", 484_000_000))
    (u,) = check.updates
    assert (u.key, u.local, u.remote, u.size, u.repo) == ("small", "aaa111", "bbb222", 484_000_000, "Systran/faster-whisper-small")
    assert check.checked == 1 and check.failed == 0


def test_a_model_at_the_latest_commit_is_not_reported(tmp_path, monkeypatch):
    fake_cache(tmp_path, monkeypatch)
    check = models.find_model_updates(["small"], remote_info=lambda repo: ("aaa111", 1))
    assert check.updates == [] and check.checked == 1


def test_models_that_are_not_downloaded_or_are_pinned_are_never_asked_about(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    asked = []

    def info(repo):
        asked.append(repo)
        return ("zzz", 1)

    check = models.find_model_updates(None, remote_info=info)        # 何も取得していない
    assert check.updates == [] and asked == []
    assert models.local_revision("kotoba-ja") is None                 # コミット固定のモデルは対象外


def test_a_failed_lookup_is_counted_and_does_not_stop_the_others(tmp_path, monkeypatch):
    fake_cache(tmp_path, monkeypatch)

    def info(repo):
        raise OSError("offline")

    check = models.find_model_updates(["small"], remote_info=info)
    assert check.updates == [] and check.checked == 0 and check.failed == 1


def test_prepare_model_passes_the_cached_folder_so_faster_whisper_never_updates_silently(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "needs_download", lambda k: False)
    monkeypatch.setattr(models, "_cached_snapshot", lambda repo: str(tmp_path / "snap"))
    assert models.prepare_model("small") == str(tmp_path / "snap")
    monkeypatch.setattr(models, "_cached_snapshot", lambda repo: None)      # 引けなければ名前に戻す
    assert models.prepare_model("small") == "small"
