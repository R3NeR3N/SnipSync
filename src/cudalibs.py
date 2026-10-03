"""GPU（CUDA）で文字起こしするための NVIDIA ライブラリを、初回だけ取得する。

なぜ必要か（実測 2026-10）: ctranslate2（faster-whisper の計算部分）は、GPU で動かすとき NVIDIA の
cuBLAS と cuDNN の DLL を探す。これらは 1GB 以上あるため、配布する EXE には入れていない。
入っていない環境で GPU を使うと「Library cublas64_12.dll is not found」で失敗し、CPU へ切り替わる
（kotoba に限らず、どのモデルでも同じ）。

どうするか: 公式の配布元（PyPI の nvidia-* パッケージ）から、版・ハッシュを固定して取得し、必要な DLL だけを
%APPDATA%\\SnipSync\\cuda\\bin に取り出す。そこを DLL の探索先に加える（subtitles.add_cuda_dll_dirs）。
取得は利用者が許可したときだけ（約 1.4GB）。
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

ALLOWED_HOST = "files.pythonhosted.org"
CHUNK = 1 << 20
READ_TIMEOUT = 30          # 秒。通信が 30 秒まったく来なければ失敗にする


@dataclass(frozen=True)
class Wheel:
    package: str
    version: str
    filename: str
    url: str
    sha256: str
    size: int


# PyPI の nvidia-* パッケージ（CUDA 12 系。ctranslate2 4.x が要求する cuBLAS 12 / cuDNN 9）。
# cuDNN は cuBLAS に、cuBLAS は NVRTC に依存する（PyPI のメタデータで確認）。
WHEELS = (
    Wheel("nvidia-cublas-cu12", "12.9.2.10", "nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl",
          "https://files.pythonhosted.org/packages/20/e2/fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl",
          "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661", 553162896),
    Wheel("nvidia-cudnn-cu12", "9.27.0.42", "nvidia_cudnn_cu12-9.27.0.42-py3-none-win_amd64.whl",
          "https://files.pythonhosted.org/packages/aa/38/f856579877f7c1c5066e61182e7de7bc27bf35a78c8d1b0fa592e6985bc4/nvidia_cudnn_cu12-9.27.0.42-py3-none-win_amd64.whl",
          "06e9b0026f3bad97d2b58666330fabec04fe1672f776661ecb0ce0029c27f142", 743068852),
    Wheel("nvidia-cuda-nvrtc-cu12", "12.9.86", "nvidia_cuda_nvrtc_cu12-12.9.86-py3-none-win_amd64.whl",
          "https://files.pythonhosted.org/packages/52/de/823919be3b9d0ccbf1f784035423c5f18f4267fb0123558d58b813c6ec86/nvidia_cuda_nvrtc_cu12-12.9.86-py3-none-win_amd64.whl",
          "72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349", 76408187),
    Wheel("nvidia-cuda-runtime-cu12", "12.9.79", "nvidia_cuda_runtime_cu12-12.9.79-py3-none-win_amd64.whl",
          "https://files.pythonhosted.org/packages/59/df/e7c3a360be4f7b93cee39271b792669baeb3846c58a4df6dfcf187a7ffab/nvidia_cuda_runtime_cu12-12.9.79-py3-none-win_amd64.whl",
          "8e018af8fa02363876860388bd10ccb89eb9ab8fb0aa749aaf58430a9f7c4891", 3591604),
)
TOTAL_BYTES = sum(w.size for w in WHEELS)
REQUIRED_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "nvrtc64_120_0.dll")
_DLL_IN_WHEEL = re.compile(r"^nvidia/[A-Za-z0-9_]+/bin/([A-Za-z0-9_.\-]+\.dll)$")


class CudaLibsCancelled(Exception):
    """利用者の「停止」で取得をやめた。"""


class CudaLibsFailed(Exception):
    """取得できなかった。利用者に見せてよい原因が入っている。"""


def cuda_dir() -> Path:
    """取得した DLL の置き場（アプリ専用。モデルと同じ %APPDATA%\\SnipSync の下）。"""
    from models import models_dir
    return models_dir().parent / "cuda"


def cuda_bin_dir() -> Path:
    return cuda_dir() / "bin"


def libs_present() -> bool:
    """必要な DLL がそろっているか（取得済みか）。"""
    b = cuda_bin_dir()
    return all((b / name).exists() for name in REQUIRED_DLLS)


def dll_names_in_wheel(names) -> list[tuple[str, str]]:
    """wheel の中の (元の名前, 取り出し先のファイル名)。nvidia/<部品>/bin/*.dll だけを対象にし、
    それ以外（パスをさかのぼる名前を含む）は取り出さない。"""
    out = []
    for n in names:
        m = _DLL_IN_WHEEL.match(n)
        if m:
            out.append((n, m.group(1)))
    return out


def _check_url(url: str) -> None:
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme != "https" or u.hostname != ALLOWED_HOST:
        raise CudaLibsFailed(f"unexpected download address: {url}")


def _download(wheel: Wheel, dest: Path, *, base: int, on_progress, should_stop, opener=urllib.request.urlopen):
    """wheel を dest へ取得し、サイズとハッシュを確かめる。base は、先に取得し終えた分のバイト数。"""
    _check_url(wheel.url)
    sha = hashlib.sha256()
    done = 0
    with opener(wheel.url, timeout=READ_TIMEOUT) as resp, open(dest, "wb") as f:
        while True:
            if should_stop and should_stop():
                raise CudaLibsCancelled()
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            f.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(base + done, TOTAL_BYTES)
    if done != wheel.size or sha.hexdigest() != wheel.sha256:
        raise CudaLibsFailed(f"{wheel.filename}: the downloaded file does not match the expected one")


def _extract(wheel_path: Path, bin_dir: Path) -> int:
    n = 0
    with zipfile.ZipFile(wheel_path) as z:
        for member, name in dll_names_in_wheel(z.namelist()):
            tmp = bin_dir / (name + ".part")
            with z.open(member) as src, open(tmp, "wb") as dst:
                while block := src.read(CHUNK):
                    dst.write(block)
            os.replace(tmp, bin_dir / name)
            n += 1
    return n


def download_libs(*, on_progress=None, should_stop=None, opener=urllib.request.urlopen, wheels=WHEELS) -> Path:
    """cuBLAS・cuDNN などの DLL を取得して cuda_bin_dir() に置く。on_progress(取得済み, 全体バイト)。

    成功すると DLL の置き場を返す。途中で止めたり失敗したりしても、そろっていない DLL は
    置かない（libs_present は、4 つそろったときだけ True）。
    """
    bin_dir = cuda_bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    total = sum(w.size for w in wheels)
    base = 0
    try:
        with tempfile.TemporaryDirectory(prefix="snipsync-cuda-") as tmp:
            for w in wheels:
                path = Path(tmp) / w.filename
                try:
                    _download(w, path, base=base, on_progress=(lambda d, _t: on_progress(d, total)) if on_progress else None,
                              should_stop=should_stop, opener=opener)
                except (CudaLibsCancelled, CudaLibsFailed):
                    raise
                except Exception as exc:                      # 通信エラー・タイムアウトなど
                    raise CudaLibsFailed(str(exc) or type(exc).__name__) from exc
                if _extract(path, bin_dir) == 0:
                    raise CudaLibsFailed(f"{w.filename}: no DLL found inside")
                path.unlink(missing_ok=True)                  # 取り出したら、容量を空ける
                base += w.size
    finally:
        if on_progress:
            on_progress(None, None)
    if not libs_present():
        raise CudaLibsFailed("required DLLs are still missing after the download")
    return bin_dir

