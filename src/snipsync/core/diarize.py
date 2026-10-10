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
MAX_SEG_BYTES = 64 * 1024 * 1024      # 取り出すモデルは約 7MB。改ざんされた巨大な部品を、ハッシュを見る前にメモリへ読まない
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
                if member.size > MAX_SEG_BYTES:
                    raise RuntimeError("segmentation モデルが大きすぎます（改ざんの可能性）")
                src = tf.extractfile(member)
                seg.write_bytes(src.read())
        finally:
            archive.unlink(missing_ok=True)
        if _sha256(seg) != SEG_SHA256:
            seg.unlink(missing_ok=True)
            raise RuntimeError("segmentation モデルのハッシュが一致しません")
    return seg, emb


# 人数を指定しないときの、クラスタリングの閾値。小さいほど話者が増え、大きいほど減る。
# 実測（2026-10・約 95 分・参加者約 8 人の録音の 30 分）: 0.5 は 103 ラベル、0.8 は 36 ラベル、1.0 は 15 ラベル。
# 人数を 8 と指定した結果と時間で重ねた純度は、どれも同じ（別々の話者を 1 つにまとめた形跡は、この基準では見えない）。
# ただし基準も同じモデルの結果なので、正解ではない。0.8 にとどめ、残りは、字幕の編集画面の話者タブで直せるようにする。
AUTO_THRESHOLD = 0.8
EMBED_MIN_SECONDS = 30.0            # 発話の合計がこれに満たないラベルは、声の近い大きなラベルへ寄せる候補
# 寄せるのに必要な、声の特徴の近さ（コサイン類似度）。低いほど、よく寄せるが、誤りが増える。
# 実測（上と同じ録音）: 0.5 は 36 → 23 ラベル、0.6 は 36 → 27 ラベルで、基準との純度の低下は 1 ポイント以内。
EMBED_MIN_SIMILARITY = 0.6
EMBED_MAX_SECONDS = 40.0            # ラベルの声の特徴を求めるのに使う、発話の長さの上限（長い発言から先に使う）
EMBED_TURN_MIN = 0.8                # 短すぎる区間は、声の特徴が不安定なので使わない
EMBED_TURN_MAX = 10.0


def diarize(samples, *, num_speakers: int = -1, cluster_threshold: float = AUTO_THRESHOLD,
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


def label_embeddings(samples, turns, *, on_log=None) -> dict:
    """ラベルごとの「声の特徴」（長さ 1 に揃えた平均）。{ラベル: ベクトル}。使える区間が無いラベルは入らない。
    samples は 16kHz mono float32。長い区間から先に、合計 EMBED_MAX_SECONDS 秒まで使う。"""
    import numpy as np
    import sherpa_onnx
    _seg, emb = ensure_models(on_log)
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb), num_threads=2))
    spans: dict = {}
    for s, e, k in turns:
        spans.setdefault(k, []).append((s, e))
    out = {}
    for k, items in spans.items():
        items.sort(key=lambda x: x[1] - x[0], reverse=True)
        vecs, used = [], 0.0
        for s, e in items:
            if e - s < EMBED_TURN_MIN:
                continue
            take = min(e - s, EMBED_TURN_MAX)
            stream = extractor.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples[int(s * SAMPLE_RATE):int((s + take) * SAMPLE_RATE)])
            stream.input_finished()
            if extractor.is_ready(stream):
                v = np.asarray(extractor.compute(stream), dtype=np.float32)
                vecs.append(v / (np.linalg.norm(v) + 1e-9))
            used += take
            if used >= EMBED_MAX_SECONDS:
                break
        if vecs:
            m = np.mean(vecs, axis=0)
            out[k] = m / (np.linalg.norm(m) + 1e-9)
    return out


def merge_similar_small_labels(turns, vectors: dict, *, min_seconds: float = EMBED_MIN_SECONDS,
                               min_similarity: float = EMBED_MIN_SIMILARITY):
    """発話の合計が min_seconds に満たないラベルを、声の特徴が min_similarity 以上近い、いちばん近い大きなラベルへ寄せる。
    近いものが無いラベルは、そのまま（別の人かもしれないので、無理に寄せない）。[(開始, 終了, ラベル)] を返す。"""
    import numpy as np
    total: dict = {}
    for s, e, k in turns:
        total[k] = total.get(k, 0.0) + (e - s)
    big = [k for k, v in total.items() if v >= min_seconds and k in vectors]
    mapping = {}
    for k, v in total.items():
        if v >= min_seconds or k not in vectors or not big:
            continue
        sims = {b: float(np.dot(vectors[k], vectors[b])) for b in big}
        best = max(sims, key=sims.get)
        if sims[best] >= min_similarity:
            mapping[k] = best
    return [(s, e, mapping.get(k, k)) for s, e, k in turns]
