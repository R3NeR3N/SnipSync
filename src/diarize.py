"""Speaker diarization (who spoke when) with sherpa-onnx.

採用理由（2026-10 実測）:
- pyannote.audio 本体は PyTorch が必須で、モデルは Hugging Face のトークン発行と利用条件の承認が
  要る（gated）。「環境構築なしの単一 EXE」という SnipSync の前提に合わない。
- sherpa-onnx は onnxruntime だけで動き（Apache-2.0）、モデルは公式 GitHub リリースから
  トークン無しで取得できる。
- 合成した日本語の2話者音声で、CAM++(zh_en) と NeMo titanet-small は発話5つを正しく分離した。
  英語のみで学習した wespeaker は日本語で過剰分割したため既定にしない。

モデルは初回だけ %APPDATA%/SnipSync/models/diarization に取得し、SHA-256 を検証する。
"""
import hashlib
import os
import tarfile
import urllib.request
from pathlib import Path

SAMPLE_RATE = 16000
_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

# segmentation: pyannote segmentation-3.0 の ONNX 版（MIT）。tar.bz2 から model.onnx だけ取り出す。
SEG_URL = f"{_BASE}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
SEG_MEMBER = "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
SEG_SHA256 = "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079"
SEG_FILE = "pyannote-segmentation-3-0.onnx"

# embedding: 3D-Speaker CAM++ 中英対応版（Apache-2.0, 28MB）。SHA は公式 checksum.txt と一致。
EMB_URL = (f"{_BASE}/speaker-recongition-models/"
           "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx")
EMB_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"
EMB_FILE = "3dspeaker_campplus_zh_en.onnx"


def diarization_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) / "SnipSync" if base else Path.home() / ".snipsync"
    return root / "models" / "diarization"


def sherpa_available() -> bool:
    try:
        import sherpa_onnx  # noqa: F401
        return True
    except ImportError:
        return False


def models_ready() -> bool:
    d = diarization_dir()
    return (d / SEG_FILE).exists() and (d / EMB_FILE).exists()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    if not url.startswith("https://"):
        raise ValueError(f"https 以外の URL は取得しません: {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:  # nosec B310 - https のみ（上で検査）
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            out.write(block)
    tmp.replace(dest)


def ensure_models(on_log=None) -> tuple[Path, Path]:
    """segmentation / embedding モデルを用意してパスを返す。ハッシュ不一致なら例外。"""
    d = diarization_dir()
    d.mkdir(parents=True, exist_ok=True)
    seg, emb = d / SEG_FILE, d / EMB_FILE

    if not emb.exists() or _sha256(emb) != EMB_SHA256:
        if on_log:
            on_log("  話者分離モデル(embedding, 約28MB)を取得しています...", "muted")
        _download(EMB_URL, emb)
        if _sha256(emb) != EMB_SHA256:
            emb.unlink(missing_ok=True)
            raise RuntimeError("embedding モデルのハッシュが一致しません")

    if not seg.exists() or _sha256(seg) != SEG_SHA256:
        if on_log:
            on_log("  話者分離モデル(segmentation, 約7MB)を取得しています...", "muted")
        archive = d / "segmentation.tar.bz2"
        _download(SEG_URL, archive)
        try:
            with tarfile.open(archive, "r:bz2") as tf:
                member = tf.getmember(SEG_MEMBER)       # 想定した1ファイルだけを読む
                src = tf.extractfile(member)
                seg.write_bytes(src.read())
        finally:
            archive.unlink(missing_ok=True)
        if _sha256(seg) != SEG_SHA256:
            seg.unlink(missing_ok=True)
            raise RuntimeError("segmentation モデルのハッシュが一致しません")
    return seg, emb


def diarize(samples, *, num_speakers: int = -1, cluster_threshold: float = 0.5,
            on_log=None, progress=None):
    """16kHz mono float32 の音声から [(開始秒, 終了秒, 話者ID)] を返す（開始順）。

    num_speakers: 人数が分かっていれば指定（-1 は自動推定）。
    cluster_threshold: 自動推定時の閾値。小さいほど話者が増え、大きいほど減る。
    """
    import sherpa_onnx
    seg, emb = ensure_models(on_log)
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg)),
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb)),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=num_speakers, threshold=cluster_threshold),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RuntimeError("話者分離の設定が不正です（モデルファイルを確認してください）")
    engine = sherpa_onnx.OfflineSpeakerDiarization(config)
    if engine.sample_rate != SAMPLE_RATE:
        raise RuntimeError(f"想定外のサンプルレート: {engine.sample_rate}")

    def _cb(done, total):
        if progress:
            progress(done / total if total else 1.0)
        return 0

    result = engine.process(samples, callback=_cb).sort_by_start_time()
    return [(r.start, r.end, r.speaker) for r in result]
