"""Whisper model registry and preparation.

実測メモ（2026-10, faster-whisper 1.2.1 / ctranslate2 4.8.2, 合成2話者の日本語音声で確認）:
- large-v3-turbo: word_timestamps 付きで正常動作。
- kotoba-whisper-v2.0-faster (MIT): 配布 config の alignment_heads が large-v3（デコーダ32層）の
  番号のままで、2層に蒸留した本モデルには存在しない層を指す。このまま word_timestamps=True
  にするとプロセスがセグメンテーション違反で落ちる。蒸留元の同型モデル
  (distil-large-v3) と同じ ``[[1, 0..19]]`` に差し替えると動く。
- distil-large-v3 は英語専用。
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# 蒸留2層デコーダ向け alignment_heads（Systran/faster-distil-whisper-large-v3 と同じ値）
DISTIL_ALIGNMENT_HEADS = [[1, i] for i in range(20)]


@dataclass(frozen=True)
class ModelSpec:
    key: str
    source: str                       # faster-whisper のモデル名、または HF repo id
    langs: str = "multi"              # "multi" | "ja" | "en"
    local_dir: str | None = None      # 指定時は専用フォルダへ DL し config を補正する
    patch_alignment_heads: bool = False
    transcribe_kwargs: dict = field(default_factory=dict)
    revision: str | None = None       # local_dir 方式のモデルは HF のコミットを固定する


MODELS: dict[str, ModelSpec] = {
    "tiny":     ModelSpec("tiny", "tiny"),
    "base":     ModelSpec("base", "base"),
    "small":    ModelSpec("small", "small"),
    "medium":   ModelSpec("medium", "medium"),
    "turbo":    ModelSpec("turbo", "large-v3-turbo"),
    "large-v3": ModelSpec("large-v3", "large-v3"),
    "kotoba-ja": ModelSpec(
        "kotoba-ja", "kotoba-tech/kotoba-whisper-v2.0-faster", langs="ja",
        local_dir="kotoba-whisper-v2.0-faster", patch_alignment_heads=True,
        revision="f44edd35eaeb2274e85ac7b31fb2c6f59ff1c4bc",       # 2024-09-29 のコミット（MIT）
        # モデルカード推奨の推論設定
        transcribe_kwargs={"language": "ja", "chunk_length": 15,
                           "condition_on_previous_text": False},
    ),
    "distil-en": ModelSpec("distil-en", "distil-large-v3", langs="en"),
}

DEFAULT_MODEL = "small"


def get_spec(key: str) -> ModelSpec:
    """未知のキー（古いプリセット等）は既定モデルへ落とす。"""
    return MODELS.get(key) or MODELS[DEFAULT_MODEL]


def models_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) / "SnipSync" if base else Path.home() / ".snipsync"
    return root / "models"


def patch_alignment_heads(config_path: Path, heads=None) -> bool:
    """config.json の alignment_heads を差し替える。変更したら True。"""
    heads = heads or DISTIL_ALIGNMENT_HEADS
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if cfg.get("alignment_heads") == heads:
        return False
    cfg["alignment_heads"] = heads
    Path(config_path).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def needs_download(key: str) -> bool:
    """専用フォルダ方式のモデルが未取得なら True（UI/ログで事前に知らせる用）。"""
    spec = get_spec(key)
    if not spec.local_dir:
        return False
    target = models_dir() / spec.local_dir
    return not ((target / "model.bin").exists() and (target / "config.json").exists())


def prepare_model(key: str) -> str:
    """WhisperModel に渡す名前またはローカルパスを返す。必要なら DL と config 補正を行う。"""
    spec = get_spec(key)
    if not spec.local_dir:
        return spec.source
    target = models_dir() / spec.local_dir
    if needs_download(key):
        from huggingface_hub import snapshot_download
        target.mkdir(parents=True, exist_ok=True)
        snapshot_download(spec.source, local_dir=str(target), revision=spec.revision)  # nosec B615 - revision 固定
    if spec.patch_alignment_heads:
        patch_alignment_heads(target / "config.json")
    return str(target)


def lang_hint(key: str):
    """このモデルが言語を固定するなら言語コード、そうでなければ None（自動判定）。"""
    return get_spec(key).transcribe_kwargs.get("language")
