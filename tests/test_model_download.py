"""AI モデルの取得: 進捗・停止・停滞・失敗・保存先。ネットワークには出ず、huggingface_hub を偽物に差し替える。"""
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from snipsync.core import models  # noqa: E402

pytest.importorskip("tqdm")


def fake_hub(monkeypatch, snapshot):
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(snapshot_download=snapshot))


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))


# ── 保存先 ──
def test_repo_table_matches_faster_whisper():
    utils = pytest.importorskip("faster_whisper.utils")
    for name, repo in models.REPOS.items():
        assert utils._MODELS[name] == repo


def test_model_folder_kotoba_is_ours_and_the_rest_are_in_the_hugging_face_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert models.model_folder("kotoba-ja") == tmp_path / "SnipSync" / "models" / "kotoba-whisper-v2.0-faster"
    assert models.model_folder("small") == tmp_path / "hf" / "hub" / "models--Systran--faster-whisper-small"
    assert models.model_folder("turbo").name == "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "cache"))
    assert models.model_folder("small").parent == tmp_path / "cache"


def test_unknown_key_falls_back_to_the_default_model_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert models.model_folder("nope") == models.model_folder(models.DEFAULT_MODEL)


def test_needs_download_for_named_models_follows_the_cache(monkeypatch):
    monkeypatch.setattr(models, "_hf_cached", lambda repo: repo.endswith("small"))
    assert models.needs_download("small") is False
    assert models.needs_download("turbo") is True


# ── 取得 ──
def test_progress_is_reported_and_the_end_is_signalled(monkeypatch):
    def snapshot(repo, **kw):
        bar = kw["tqdm_class"](total=1000, unit="B", desc="Downloading bytes")
        for _ in range(10):
            time.sleep(0.05)
            bar.update(100)
        return "C:/cache/snap"

    fake_hub(monkeypatch, snapshot)
    seen = []
    path = models.download_model("small", on_progress=lambda d, t: seen.append((d, t)), poll=0.02)
    assert path == "C:/cache/snap"
    assert seen[-1] == (None, None)
    done = [d for d, t in seen if d]
    assert done == sorted(done) and done[-1] > 0 and all(t == 1000 for d, t in seen if d)


def test_the_largest_byte_bar_is_taken_as_the_overall_progress(monkeypatch):
    def snapshot(repo, **kw):
        small = kw["tqdm_class"](total=10, unit="B", desc="config.json")
        small.update(10)
        big = kw["tqdm_class"](total=5000, unit="B", desc="model.bin")
        big.update(2500)
        time.sleep(0.15)
        return "p"

    fake_hub(monkeypatch, snapshot)
    seen = []
    models.download_model("small", on_progress=lambda d, t: seen.append((d, t)), poll=0.02)
    assert (2500, 5000) in seen


def test_finished_small_files_do_not_show_as_one_hundred_percent(monkeypatch):
    def snapshot(repo, **kw):
        small = kw["tqdm_class"](total=10, unit="B", desc="config.json")
        small.update(10)                               # 設定ファイルだけ先に終わった
        time.sleep(0.15)
        big = kw["tqdm_class"](total=5000, unit="B", desc="model.bin")
        big.update(100)
        time.sleep(0.15)
        return "p"

    fake_hub(monkeypatch, snapshot)
    seen = []
    models.download_model("small", on_progress=lambda d, t: seen.append((d, t)), poll=0.02)
    real = [(d, t) for d, t in seen if d]
    assert (10, 10) not in real and (100, 5000) in real


def test_kotoba_goes_to_its_own_folder_with_the_pinned_revision(tmp_path, monkeypatch):
    calls = {}

    def snapshot(repo, **kw):
        calls.update(kw, repo=repo)
        return "ignored"

    fake_hub(monkeypatch, snapshot)
    path = models.download_model("kotoba-ja")
    spec = models.MODELS["kotoba-ja"]
    assert path == str(tmp_path / "SnipSync" / "models" / spec.local_dir)
    assert calls["revision"] == spec.revision and calls["local_dir"] == path
    assert "model.bin" in calls["allow_patterns"]


def test_stop_cancels_at_once_even_if_the_connection_is_hung(monkeypatch):
    hung = threading.Event()
    seen = {}

    def snapshot(repo, **kw):
        bar = kw["tqdm_class"](total=100, unit="B", desc="Downloading bytes")
        hung.wait(5)                                   # 通信が固まっている状態
        try:
            bar.update(1)                              # 動き出したら、次の更新で打ち切られる
        except models.DownloadCancelled:
            seen["worker_stopped"] = True
            raise
        return "p"

    fake_hub(monkeypatch, snapshot)
    stop = {"now": False}
    threading.Timer(0.2, lambda: stop.update(now=True)).start()
    t0 = time.monotonic()
    with pytest.raises(models.DownloadCancelled):
        models.download_model("small", should_stop=lambda: stop["now"], poll=0.02)
    assert time.monotonic() - t0 < 1.0                 # 固まった転送を待たずに戻る
    hung.set()
    time.sleep(0.3)
    assert seen.get("worker_stopped")                  # 放置した転送は、動き出したところで終わる


def test_progress_end_is_signalled_on_cancel_too(monkeypatch):
    fake_hub(monkeypatch, lambda repo, **kw: time.sleep(2))
    seen = []
    with pytest.raises(models.DownloadCancelled):
        models.download_model("small", should_stop=lambda: True, on_progress=lambda d, t: seen.append(d), poll=0.02)
    assert seen[-1] is None


def test_a_stalled_connection_is_reported_instead_of_waiting_forever(monkeypatch):
    monkeypatch.setattr(models, "STALL_SECONDS", 0.3)
    release = threading.Event()
    fake_hub(monkeypatch, lambda repo, **kw: release.wait(5))
    with pytest.raises(models.DownloadFailed, match="stalled"):
        models.download_model("small", poll=0.02)
    release.set()


def test_download_errors_become_failures_with_the_reason(monkeypatch):
    def snapshot(repo, **kw):
        raise OSError("disk full")

    fake_hub(monkeypatch, snapshot)
    with pytest.raises(models.DownloadFailed, match="disk full"):
        models.download_model("small", poll=0.02)


def test_prepare_model_downloads_only_when_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(models, "download_model", lambda key, **kw: calls.append(key) or "C:/dl")
    monkeypatch.setattr(models, "needs_download", lambda key: False)
    assert models.prepare_model("small") == "small"
    assert calls == []
    monkeypatch.setattr(models, "needs_download", lambda key: True)
    assert models.prepare_model("small") == "C:/dl" and calls == ["small"]


def test_xet_is_disabled_before_hugging_face_is_imported():
    root = Path(__file__).parent.parent / "src"
    app = (root / "snipsync" / "ui" / "app.py").read_text(encoding="utf-8")
    assert app.index("HF_HUB_DISABLE_XET") < app.index("from faster_whisper import")
    assert "HF_HUB_DISABLE_XET" in (root / "snipsync" / "core" / "models.py").read_text(encoding="utf-8")


# ── パイプラインでの扱い ──
def _run_with_failing_model(monkeypatch, error):
    from snipsync.core import pipeline as pl
    from test_pipeline_v2 import Recorder, base_params, run

    np = pytest.importorskip("numpy")
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    monkeypatch.setattr(pl, "decode_mix", lambda p, sr=16000: np.zeros(20 * sr, dtype=np.float32))
    attempts = []

    def prepare(key, **kw):
        attempts.append(key)
        raise error

    monkeypatch.setattr(pl, "needs_download", lambda key: True)
    monkeypatch.setattr(pl, "prepare_model", prepare)
    d = Path(tempfile.mkdtemp())
    inp = d / "input.mp4"
    inp.write_bytes(b"x")
    out = d / "out"
    out.mkdir()
    res, logs = run((inp, out), monkeypatch, base_params(do_srt=True, snap_srt=False),
                    Recorder(v1_chunks=[[0, 60, 1.0]]), transcribe=None)
    return res, logs, attempts, out


def test_stop_during_model_download_ends_the_run_without_a_gpu_retry_or_a_traceback(monkeypatch):
    res, logs, attempts, out = _run_with_failing_model(monkeypatch, models.DownloadCancelled())
    assert res.stopped and attempts == ["small"]                       # 取得の試行は1回だけ
    assert any(m == "log_stopped" for m, _ in logs)
    assert not any(m.startswith("log_unexpected") or m == "log_gpu_fallback" for m, _ in logs)
    assert not list(out.glob("*.srt"))


def test_failed_model_download_is_logged_with_a_friendly_reason(monkeypatch):
    res, logs, attempts, out = _run_with_failing_model(monkeypatch, models.DownloadFailed("stalled"))
    assert res.ok and not res.stopped                                  # カット自体は成功している
    assert any(m.startswith("log_model_failed") for m, _ in logs)
