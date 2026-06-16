"""Subtitle (.srt) helpers."""


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

