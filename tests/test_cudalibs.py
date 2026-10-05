"""GPU 用の NVIDIA ライブラリの取得。ネットワークには出ず、偽の wheel（zip）を返す opener で確かめる。"""
import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core import cudalibs  # noqa: E402


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))


def make_wheel(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def wheel_for(name: str, files: dict, **override):
    blob = make_wheel(files)
    w = cudalibs.Wheel(name, "1.0", f"{name}.whl", f"https://{cudalibs.ALLOWED_HOST}/x/{name}.whl",
                       override.get("sha256", hashlib.sha256(blob).hexdigest()), override.get("size", len(blob)))
    return w, blob


def opener_for(blobs: dict):
    def opener(url, timeout=None):
        return FakeResponse(blobs[url])
    return opener


ALL_DLLS = {
    "a": {"nvidia/cublas/bin/cublas64_12.dll": b"1", "nvidia/cublas/bin/cublasLt64_12.dll": b"2"},
    "b": {"nvidia/cudnn/bin/cudnn64_9.dll": b"3", "nvidia/cudnn/bin/cudnn_ops64_9.dll": b"4"},
    "c": {"nvidia/cuda_nvrtc/bin/nvrtc64_120_0.dll": b"5", "nvidia/cuda_nvrtc/include/nvrtc.h": b"x"},
}


def fake_set():
    wheels, blobs = [], {}
    for k, files in ALL_DLLS.items():
        w, blob = wheel_for(k, files)
        wheels.append(w)
        blobs[w.url] = blob
    return wheels, blobs


# ── 固定した取得元 ──
def test_pinned_wheels_are_https_from_pypi_with_a_full_sha256():
    assert len(cudalibs.WHEELS) >= 3
    for w in cudalibs.WHEELS:
        assert w.url.startswith(f"https://{cudalibs.ALLOWED_HOST}/")
        assert len(w.sha256) == 64 and int(w.sha256, 16) >= 0
        assert w.url.endswith(w.filename) and w.filename.endswith("win_amd64.whl")
        assert w.size > 1_000_000
    assert {"cublas", "cudnn"} <= {w.package.split("-")[1] for w in cudalibs.WHEELS}
    assert cudalibs.TOTAL_BYTES == sum(w.size for w in cudalibs.WHEELS)


@pytest.mark.parametrize("url", ["http://files.pythonhosted.org/a.whl", "https://evil.example/a.whl",
                                 "https://files.pythonhosted.org.evil.example/a.whl", "file:///c:/a.whl"])
def test_only_https_pypi_hosts_are_accepted(url):
    with pytest.raises(cudalibs.CudaLibsFailed):
        cudalibs._check_url(url)


# ── 取り出す DLL の選び方 ──
def test_only_dlls_under_nvidia_component_bin_are_picked():
    names = ["nvidia/cublas/bin/cublas64_12.dll", "nvidia/cublas/include/cublas.h", "nvidia/cublas/bin/readme.txt",
             "nvidia/cudnn/bin/cudnn64_9.dll", "other/bin/evil.dll", "nvidia/x/bin/../../evil.dll",
             "../nvidia/x/bin/evil.dll", "nvidia/x/bin/sub/evil.dll", "nvidia/x/bin/a b.dll"]
    assert cudalibs.dll_names_in_wheel(names) == [("nvidia/cublas/bin/cublas64_12.dll", "cublas64_12.dll"),
                                                  ("nvidia/cudnn/bin/cudnn64_9.dll", "cudnn64_9.dll")]


# ── 取得 ──
def test_download_extracts_dlls_reports_progress_and_signals_the_end():
    wheels, blobs = fake_set()
    seen = []
    bin_dir = cudalibs.download_libs(wheels=wheels, opener=opener_for(blobs),
                                     on_progress=lambda d, t: seen.append((d, t)))
    assert (bin_dir / "cublas64_12.dll").read_bytes() == b"1"
    assert not (bin_dir / "nvrtc.h").exists()                     # DLL 以外は取り出さない
    assert cudalibs.libs_present()
    total = sum(w.size for w in wheels)
    real = [(d, t) for d, t in seen if d]
    assert real[-1] == (total, total) and [d for d, _ in real] == sorted(d for d, _ in real)
    assert seen[-1] == (None, None)


def test_libs_present_needs_all_four_key_dlls(tmp_path):
    assert not cudalibs.libs_present()
    b = cudalibs.cuda_bin_dir()
    b.mkdir(parents=True)
    for name in cudalibs.REQUIRED_DLLS[:-1]:
        (b / name).write_bytes(b"x")
    assert not cudalibs.libs_present()                              # 1つ足りない
    (b / cudalibs.REQUIRED_DLLS[-1]).write_bytes(b"x")
    assert cudalibs.libs_present()


def test_a_wrong_hash_is_refused_and_nothing_is_extracted():
    w, blob = wheel_for("a", ALL_DLLS["a"], sha256="0" * 64)
    with pytest.raises(cudalibs.CudaLibsFailed, match="does not match"):
        cudalibs.download_libs(wheels=[w], opener=opener_for({w.url: blob}))
    assert not list(cudalibs.cuda_bin_dir().glob("*.dll"))


def test_a_wrong_size_is_refused():
    w, blob = wheel_for("a", ALL_DLLS["a"], size=12345)
    with pytest.raises(cudalibs.CudaLibsFailed):
        cudalibs.download_libs(wheels=[w], opener=opener_for({w.url: blob}))


def test_stop_cancels_the_download_and_signals_the_end():
    wheels, blobs = fake_set()
    seen = []
    with pytest.raises(cudalibs.CudaLibsCancelled):
        cudalibs.download_libs(wheels=wheels, opener=opener_for(blobs), should_stop=lambda: True,
                               on_progress=lambda d, t: seen.append(d))
    assert seen[-1] is None and not cudalibs.libs_present()


def test_network_errors_become_failures_with_the_reason():
    wheels, _ = fake_set()

    def broken(url, timeout=None):
        raise TimeoutError("timed out")

    with pytest.raises(cudalibs.CudaLibsFailed, match="timed out"):
        cudalibs.download_libs(wheels=wheels, opener=broken)


def test_a_wheel_without_dlls_is_a_failure():
    w, blob = wheel_for("empty", {"nvidia/x/include/a.h": b"x"})
    with pytest.raises(cudalibs.CudaLibsFailed, match="no DLL"):
        cudalibs.download_libs(wheels=[w], opener=opener_for({w.url: blob}))


def test_a_partial_download_does_not_count_as_ready():
    wheels, blobs = fake_set()
    calls = {"n": 0}

    def stop_after_first_wheel():
        calls["n"] += 1
        return calls["n"] > 3                    # 1つ目を取り出したあと、2つ目の途中で停止

    with pytest.raises(cudalibs.CudaLibsCancelled):
        cudalibs.download_libs(wheels=wheels, opener=opener_for(blobs), should_stop=stop_after_first_wheel)
    assert not cudalibs.libs_present()
    assert not list(cudalibs.cuda_bin_dir().glob("*.part"))


# ── DLL の探索先への登録 ──
def test_downloaded_dlls_are_added_to_the_dll_search_path(tmp_path, monkeypatch):
    from snipsync.core import subtitles
    bin_dir = cudalibs.cuda_bin_dir()
    bin_dir.mkdir(parents=True)
    added = []
    monkeypatch.setattr(subtitles, "_cuda_dll_registered", False)
    monkeypatch.setattr(subtitles.sys, "platform", "win32")
    monkeypatch.setattr(subtitles.os, "add_dll_directory", lambda p: added.append(Path(p)), raising=False)
    monkeypatch.setenv("PATH", "")
    subtitles.add_cuda_dll_dirs()
    assert bin_dir in added
    assert str(bin_dir) in subtitles.os.environ["PATH"]


def test_dll_dirs_are_registered_again_after_a_later_download(tmp_path, monkeypatch):
    """起動時には何も無く、あとで取得した場合も、同じプロセスで効く。"""
    from snipsync.core import subtitles
    added = []
    monkeypatch.setattr(subtitles, "_cuda_dll_registered", False)
    monkeypatch.setattr(subtitles.sys, "platform", "win32")
    monkeypatch.setattr(subtitles.os, "add_dll_directory", lambda p: added.append(Path(p)), raising=False)
    monkeypatch.setenv("PATH", "")
    subtitles.add_cuda_dll_dirs()                           # まだ置き場が無い
    assert added == [] and subtitles._cuda_dll_registered is False
    cudalibs.cuda_bin_dir().mkdir(parents=True)
    subtitles.add_cuda_dll_dirs()
    assert added == [cudalibs.cuda_bin_dir()]
