"""Whisper model registry, download, and preparation.

実測メモ（2026-10, faster-whisper 1.2.1 / ctranslate2 4.8.2, 合成2話者の日本語音声で確認）:
- large-v3-turbo: word_timestamps 付きで正常動作。
- kotoba-whisper-v2.0-faster (MIT): 配布 config の alignment_heads が large-v3（デコーダ32層）の
  番号のままで、2層に蒸留した本モデルには存在しない層を指す。このまま word_timestamps=True
  にするとプロセスがセグメンテーション違反で落ちる。蒸留元の同型モデル
  (distil-large-v3) と同じ ``[[1, 0..19]]`` に差し替えると動く。
- distil-large-v3 は英語専用。
- huggingface_hub の Xet 方式の転送は、model.bin（1.5GB）で進捗 0 のまま止まり続けることがある（実測: 30 分以上）。
  同じ回線で、Xet を切った通常の HTTP 転送は約 8MB/s で完走する。そのため Xet を無効にする（下の環境変数。
  huggingface_hub を最初に import するより前に設定する必要がある）。
"""
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

STALL_SECONDS = 120          # この時間、1バイトも進まなければ「止まった」とみなす
ALLOW_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]

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

# faster-whisper が名前から引くリポジトリ（faster_whisper.utils._MODELS と同じ。テストで一致を確かめる）
REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}


class DownloadCancelled(Exception):
    """利用者の「停止」でダウンロードをやめた。"""


class DownloadFailed(Exception):
    """ダウンロードできなかった。利用者に見せてよい原因が入っている。"""


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


def repo_id(spec: ModelSpec) -> str:
    return spec.source if "/" in spec.source else REPOS.get(spec.source, spec.source)


def hf_cache_dir() -> Path:
    """huggingface_hub の既定の保存先（HF_HOME / HF_HUB_CACHE があればそちら）。"""
    explicit = os.environ.get("HF_HUB_CACHE")
    if explicit:
        return Path(explicit)
    home = os.environ.get("HF_HOME")
    return (Path(home) if home else Path.home() / ".cache" / "huggingface") / "hub"


def model_folder(key: str) -> Path:
    """このモデルのファイルがある（これから置かれる）フォルダ。

    kotoba は設定ファイルを書き換えるので、共有キャッシュではなく専用フォルダに置く。
    それ以外は faster-whisper が使う Hugging Face のキャッシュに置かれる。
    """
    spec = get_spec(key)
    if spec.local_dir:
        return models_dir() / spec.local_dir
    return hf_cache_dir() / ("models--" + repo_id(spec).replace("/", "--"))


def _hf_cached(repo: str) -> bool:
    """名前指定のモデルが、Hugging Face のキャッシュに揃っているか（ネットワークには出ない）。"""
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo, allow_patterns=ALLOW_PATTERNS, local_files_only=True)  # nosec B615 - 取得済みの確認だけ
        return True
    except Exception:
        return False


def needs_download(key: str) -> bool:
    """モデルが未取得なら True（実行前に利用者へ知らせる用）。"""
    spec = get_spec(key)
    if spec.local_dir:
        target = models_dir() / spec.local_dir
        return not ((target / "model.bin").exists() and (target / "config.json").exists())
    return not _hf_cached(repo_id(spec))


def download_model(key: str, *, on_progress=None, should_stop=None, poll: float = 0.2) -> str:
    """モデルを取得して、保存先のパスを返す。

    on_progress(取得済みバイト, 全体バイト) を転送中に呼ぶ（全体が不明の間は 0）。終わったら (None, None)。
    should_stop() が True になるとすぐ DownloadCancelled を送出する。通信が STALL_SECONDS 進まなければ DownloadFailed。
    転送は別スレッドで行い、通信が固まっていても「停止」が効くようにしている（固まった転送は放置し、動き出し
    次第、次の進捗更新で打ち切る）。
    """
    from huggingface_hub import snapshot_download

    spec = get_spec(key)
    repo = repo_id(spec)
    kwargs = {"allow_patterns": ALLOW_PATTERNS}
    target = None
    if spec.local_dir:
        target = models_dir() / spec.local_dir
        target.mkdir(parents=True, exist_ok=True)
        kwargs.update(local_dir=str(target), revision=spec.revision)
    cancelled = threading.Event()
    state = {"done": 0, "total": 0, "moved": time.monotonic()}
    bars: dict = {}

    try:
        from tqdm.auto import tqdm

        class _Progress(tqdm):
            """Hugging Face の進捗を受け取る。表示はせず、バイト数だけを読み、キャンセルを伝える。"""

            def __init__(self, *a, **k):
                k["file"] = open(os.devnull, "w")           # noqa: SIM115  画面（コンソール）には出さない
                super().__init__(*a, **k)

            def update(self, n=1):
                if cancelled.is_set():
                    raise DownloadCancelled()
                super().update(n)
                if getattr(self, "unit", "") == "B":
                    # バイトの進捗バーが複数あってもよい（版によって、まとめのバーとファイルごとのバーがある）。
                    # 終わった小さなファイル（設定など）のバーは「100%」に見えて紛らわしいので、進行中のうち
                    # いちばん大きなもの（= model.bin かその合計）を全体の進み具合とみなす。
                    bars[str(getattr(self, "desc", ""))] = (int(self.n), int(self.total or 0))
                    running = [b for b in bars.values() if b[1] > b[0]]
                    if running:
                        done, total = max(running, key=lambda b: b[1])
                        if done != state["done"]:
                            state["moved"] = time.monotonic()
                        state["done"], state["total"] = done, total

        kwargs["tqdm_class"] = _Progress
    except ImportError:
        pass

    box: dict = {}

    def run():
        try:
            box["path"] = snapshot_download(repo, **kwargs)  # nosec B615 - revision は ModelSpec で固定
        except BaseException as exc:  # noqa: BLE001  呼び出し側へそのまま渡す
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(poll)
            if should_stop and should_stop():
                cancelled.set()
                raise DownloadCancelled()
            if on_progress:
                on_progress(state["done"], state["total"])
            if time.monotonic() - state["moved"] > STALL_SECONDS:
                cancelled.set()
                raise DownloadFailed("stalled")
    finally:
        if on_progress:
            on_progress(None, None)
    if "error" in box:
        if isinstance(box["error"], DownloadCancelled):
            raise box["error"]
        raise DownloadFailed(str(box["error"]) or type(box["error"]).__name__) from box["error"]
    return str(target) if target else box["path"]


def prepare_model(key: str, *, on_progress=None, should_stop=None) -> str:
    """WhisperModel に渡す名前またはローカルパスを返す。未取得なら取得し、必要なら config を補正する。"""
    spec = get_spec(key)
    if needs_download(key):
        path = download_model(key, on_progress=on_progress, should_stop=should_stop)
    else:
        path = str(models_dir() / spec.local_dir) if spec.local_dir else spec.source
    if spec.patch_alignment_heads:
        patch_alignment_heads(Path(path) / "config.json")
    return path


def lang_hint(key: str):
    """このモデルが言語を固定するなら言語コード、そうでなければ None（自動判定）。"""
    return get_spec(key).transcribe_kwargs.get("language")
