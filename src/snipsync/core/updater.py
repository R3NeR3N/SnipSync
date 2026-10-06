"""SnipSync 本体の更新: 新しい版の確認・取得・差し替え（画面は知らない）。

- 確認: GitHub Releases の「最新の正式版」（プレリリースは含まれない）を 1 回だけ読む。
- 取得: リリースの SnipSync.exe を、GitHub が付けた SHA-256（API の ``digest``）と照合してから使う。
  ``digest`` が無いリリースは、勝手に入れ替えない（案内だけ）。
- 差し替え: 動いている exe は Windows でも名前の変更ができる。現在の exe を ``.old`` に改名し、新しい exe を同じ名前で
  置いて、新しい方を起動する。``.old`` は次の起動で消す。
- 設定（自動確認の有無・最後に確認した日時・通知しない版）は ``%APPDATA%/SnipSync/update.json``。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from packaging.version import InvalidVersion, Version

from snipsync.version import APP_VERSION

REPO = "R3NeR3N/SnipSync"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "SnipSync.exe"
CHECK_INTERVAL = 24 * 3600           # 自動確認は 1 日に 1 回まで
API_TIMEOUT = 10
READ_TIMEOUT = 60
CHUNK = 1 << 20


class UpdateError(Exception):
    """確認・取得・差し替えのどれかに失敗した。利用者に見せてよい原因が入っている。"""


class UpdateCancelled(Exception):
    """利用者の「停止」で取得をやめた。"""


@dataclass(frozen=True)
class Release:
    version: str                     # "0.3.0"（先頭の v は付けない）
    tag: str                         # "v0.3.0"
    notes: str
    page_url: str                    # リリースのページ
    asset_url: str | None            # SnipSync.exe の取得先（無ければ None）
    size: int
    sha256: str | None               # 取得したファイルを照合する値（無ければ None = 自動では入れ替えない）


# ── 設定の保存 ─────────────────────────────────────────────────────────────────────────
def data_dir() -> Path:
    base = os.environ.get("APPDATA")
    return Path(base) / "SnipSync" if base else Path.home() / ".snipsync"


def _state_path() -> Path:
    return data_dir() / "update.json"


def load_state() -> dict:
    state = {"check_enabled": True, "last_check": 0.0, "skip_version": "", "skip_models": {}}
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if isinstance(data, dict):
        for key, default in state.items():
            if isinstance(data.get(key), type(default)):
                state[key] = data[key]
    return state


def save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def check_due(state: dict, now: float | None = None) -> bool:
    """自動確認をしてよいか（オンで、前回から 1 日以上たっている）。"""
    now = time.time() if now is None else now
    return bool(state["check_enabled"]) and now - float(state["last_check"]) >= CHECK_INTERVAL


# ── 版の確認 ───────────────────────────────────────────────────────────────────────────
def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    """remote が local より新しい正式版なら True。読めない版は False（更新を促さない側に倒す）。"""
    try:
        r, loc = Version(remote.lstrip("v")), Version(local.lstrip("v"))
    except InvalidVersion:
        return False
    return not r.is_prerelease and r > loc


def _clean_digest(value) -> str | None:
    if isinstance(value, str) and value.startswith("sha256:"):
        hexa = value[len("sha256:"):].lower()
        if len(hexa) == 64 and all(c in "0123456789abcdef" for c in hexa):
            return hexa
    return None


def _check_asset_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname != "github.com" or not u.path.startswith(f"/{REPO}/releases/download/"):
        raise UpdateError(f"unexpected download address: {url}")


def parse_release(data: dict) -> Release:
    """GitHub の「最新リリース」の JSON から Release を作る。"""
    if not isinstance(data, dict) or not data.get("tag_name"):
        raise UpdateError("unexpected response from GitHub")
    tag = str(data["tag_name"])
    asset = next((a for a in data.get("assets") or [] if a.get("name") == ASSET_NAME), None)
    return Release(
        version=tag.lstrip("v"), tag=tag, notes=str(data.get("body") or ""),
        page_url=str(data.get("html_url") or f"https://github.com/{REPO}/releases/latest"),
        asset_url=asset.get("browser_download_url") if asset else None,
        size=int(asset.get("size") or 0) if asset else 0,
        sha256=_clean_digest(asset.get("digest")) if asset else None,
    )


def fetch_latest(opener=urllib.request.urlopen) -> Release:
    """最新の正式版を GitHub から読む。通信できなければ UpdateError。"""
    req = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"SnipSync/{APP_VERSION}"})
    try:
        with opener(req, timeout=API_TIMEOUT) as resp:     # nosec B310 - https の固定 URL
            return parse_release(json.loads(resp.read().decode("utf-8")))
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(str(exc) or type(exc).__name__) from exc


def find_update(opener=urllib.request.urlopen, current: str = APP_VERSION) -> Release | None:
    """いまの版より新しい正式版があれば、その Release。無ければ None。"""
    release = fetch_latest(opener)
    return release if is_newer(release.version, current) else None


# ── 取得と差し替え（配布 EXE のとき） ───────────────────────────────────────────────────
def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_exe() -> Path:
    return Path(sys.executable).resolve()


def can_install(release: Release, exe: Path | None = None) -> bool:
    """この場で入れ替えられるか。配布 EXE で、置き場に書き込めて、照合できる値があるときだけ。"""
    if not frozen() and exe is None:
        return False
    exe = exe or current_exe()
    return bool(release.asset_url and release.sha256 and os.access(exe.parent, os.W_OK))


def new_exe_path(exe: Path | None = None) -> Path:
    exe = exe or current_exe()
    return exe.with_name(exe.name + ".new")


def old_exe_path(exe: Path | None = None) -> Path:
    exe = exe or current_exe()
    return exe.with_name(exe.name + ".old")


def download(release: Release, dest: Path, *, on_progress=None, should_stop=None, opener=urllib.request.urlopen) -> Path:
    """SnipSync.exe を dest へ取得する。大きさとハッシュが合わなければ捨てて UpdateError。
    on_progress(取得済みバイト, 全体バイト) を呼ぶ。終わったら (None, None)。"""
    if not release.asset_url or not release.sha256:
        raise UpdateError("this release has no verifiable download")
    _check_asset_url(release.asset_url)
    part = dest.with_name(dest.name + ".part")
    sha = hashlib.sha256()
    done = 0
    try:
        with opener(urllib.request.Request(release.asset_url, headers={"User-Agent": f"SnipSync/{APP_VERSION}"}),
                    timeout=READ_TIMEOUT) as resp, open(part, "wb") as out:      # nosec B310 - https・github.com のみ（上で検査）
            while True:
                if should_stop and should_stop():
                    raise UpdateCancelled()
                block = resp.read(CHUNK)
                if not block:
                    break
                out.write(block)
                sha.update(block)
                done += len(block)
                if on_progress:
                    on_progress(done, release.size)
        if (release.size and done != release.size) or sha.hexdigest() != release.sha256:
            raise UpdateError("the downloaded file does not match the release (discarded)")
        os.replace(part, dest)
    except (UpdateError, UpdateCancelled):
        raise
    except Exception as exc:                       # 通信エラー・タイムアウト・ディスク不足など
        raise UpdateError(str(exc) or type(exc).__name__) from exc
    finally:
        part.unlink(missing_ok=True)
        if on_progress:
            on_progress(None, None)
    return dest


def _fresh_environment() -> dict:
    """PyInstaller の onefile は、親の展開先を子に引き継ぐ。入れ替えた新しい exe は、まっさらな起動にする。"""
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    env.pop("_MEIPASS2", None)
    return env


def swap_and_relaunch(new_exe: Path, exe: Path | None = None, *, spawn=subprocess.Popen) -> None:
    """動いている exe を .old に改名し、new_exe を同じ名前で置いて、新しい方を起動する。
    入れ替えに失敗したら元へ戻す。呼んだあと、呼び出し側はアプリを終了する。"""
    exe = exe or current_exe()
    old = old_exe_path(exe)
    try:
        old.unlink(missing_ok=True)                # 前回の .old が残っていたら片付ける（まだ使われていれば失敗する）
        os.replace(exe, old)
    except OSError as exc:
        raise UpdateError(f"could not move the running app aside: {exc}") from exc
    try:
        os.replace(new_exe, exe)
    except OSError as exc:
        try:
            os.replace(old, exe)                   # 元へ戻す
        except OSError:
            pass
        raise UpdateError(f"could not put the new version in place: {exc}") from exc
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        spawn([str(exe)], env=_fresh_environment(), close_fds=True, creationflags=flags, cwd=str(exe.parent))
    except OSError as exc:
        raise UpdateError(f"the new version was installed but could not be started: {exc}") from exc


def cleanup_old(exe: Path | None = None) -> None:
    """前回の更新で残った .old / .new を消す（使用中なら、次の起動に回す）。配布 EXE のときだけ。"""
    if exe is None and not frozen():
        return
    exe = exe or current_exe()
    for p in (old_exe_path(exe), new_exe_path(exe)):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
