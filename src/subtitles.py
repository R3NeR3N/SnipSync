"""Subtitle (.srt) helpers."""
import os
import sys
from pathlib import Path

_cuda_dll_registered = False


def add_cuda_dll_dirs() -> None:
    """Register pip-installed CUDA libs so ctranslate2 can load cuBLAS/cuDNN.

    The GPU libs ship as ``nvidia-*`` wheels under ``site-packages/nvidia/*/bin``
    (kept inside the venv, not on the host) but ctranslate2 does not auto-discover
    them on Windows -> a CUDA WhisperModel fails with ``cublas64_12.dll ... cannot
    be loaded``. Add each ``bin`` dir to the DLL search path AND PATH *before* the
    model is built. No-op off Windows, when the wheels are absent, or if already run.
    """
    global _cuda_dll_registered
    if _cuda_dll_registered or sys.platform != "win32":
        return
    try:
        import nvidia
    except ImportError:
        return
    base = Path(list(nvidia.__path__)[0])
    for sub in base.iterdir():
        bind = sub / "bin"
        if bind.is_dir():
            os.add_dll_directory(str(bind))
            if str(bind) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(bind) + os.pathsep + os.environ.get("PATH", "")
    _cuda_dll_registered = True


def format_timestamp(seconds: float) -> str:
    """Seconds -> SRT timestamp ``HH:MM:SS,mmm``.

    Rounds to whole milliseconds first to avoid float truncation errors.
    """
    total_ms = int(round(seconds * 1000))
    hrs = total_ms // 3600000
    mins = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    ms = total_ms % 1000
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def cuda_available() -> bool:
    """Check if ctranslate2 can find at least one CUDA device. Return False on error."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def resolve_device(use_gpu: bool) -> tuple[str, str]:
    """Resolve (device, compute_type) based on GPU preference and availability."""
    if use_gpu and cuda_available():
        return "cuda", "int8_float16"
    return "cpu", "int8"

