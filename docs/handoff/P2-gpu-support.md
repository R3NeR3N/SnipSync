# 設計書 — P2: GPU 対応の検討（faster-whisper の device/compute_type 切替）

> 区分: 🧠頭脳(Opus 4.8) 判断/設計 → 🔧作業(Gemini) 実装
> 対象: ROADMAP P2「GPU 対応の検討」
> 前提ブランチ: `feat/p1-refactor`（P2 即時停止まで完了済み）

非開発者向け要約: 字幕の文字起こし(faster-whisper)はいま **CPU 固定**で動く。確実だが遅い。
NVIDIA GPU がある PC なら GPU で数倍速くできる。ただし GPU 実行には CUDA/cuDNN という
追加ライブラリが要り、これを `.exe` に同梱すると配布物が数百 MB〜GB 級に肥大する
（CONTEXT.md §7 が「配布 EXE に巨大な GPU バイナリを同梱しない」と明記）。
そこで本タスクは **同梱はしない**。GPU が使える環境でだけ**自動検出して任意で有効化**し、
無い/失敗したら**黙って CPU にフォールバック**する「best-effort オプトイン」とする。

---

## 1. 判断（このタスクの核心）

| 論点 | 決定 | 根拠 |
|---|---|---|
| CUDA/cuDNN を EXE に同梱するか | **しない** | CONTEXT.md §7・既存方針。配布物肥大を避ける |
| GPU をどう提供するか | **オプトイン（既定 OFF）+ 自動検出 + CPU フォールバック** | 既定挙動・出力は不変。GPU 環境の人だけ恩恵 |
| 検出方法 | `ctranslate2.get_cuda_device_count() > 0` | faster-whisper の依存 ctranslate2 に同梱の関数。新規依存不要 |
| GPU 時の compute_type | **`int8_float16`** | float16 より VRAM 少・速度同等。GPU 無い環境では従来どおり `int8` |

> ⚠ **EXE 配布での制約（必ず README/docs に明記）**: PyInstaller でビルドした `.exe` から GPU を使うには、
> ユーザー環境に **NVIDIA ドライバ + CUDA 12 ランタイム + cuDNN 9** の DLL が PATH 上に必要。
> これらは同梱しないため、**EXE 利用者の大半は CPU のまま**になる。GPU は「環境を自前で整えた上級者/開発者向けの任意機能」と位置づける。デフォルト CPU 挙動は 100% 不変。

## 2. 現状の結合点

文字起こしは `pipeline.py` の②b ブロックにハードコードされている:

```python
# src/pipeline.py:177-179（現状）
from faster_whisper import WhisperModel
model = WhisperModel(params.model_size, device="cpu", compute_type="int8")
segments, info = model.transcribe(str(temp_wav), beam_size=5, language=None)
```

`device` / `compute_type` が固定。ここを `PipelineParams` 経由で外から渡せるようにする。

## 3. 設計方針

- **`PipelineParams` に `use_gpu: bool = False` を追加**（既定 False＝従来挙動）。`device`/`compute_type`
  を直接フィールドにせず**意図(use_gpu)だけ**渡し、解決は pipeline 内の純関数 `resolve_device()` に閉じる
  → UI は OS/CUDA 事情を知らなくてよい（UI 非依存維持）。
- **検出ヘルパ（新規・純粋寄り）** を `subtitles.py` に置く（ASR の関心事のため）:
  ```python
  # src/subtitles.py
  def cuda_available() -> bool:
      """ctranslate2 が CUDA デバイスを1つ以上見つけられるか。失敗時 False。"""
      try:
          import ctranslate2
          return ctranslate2.get_cuda_device_count() > 0
      except Exception:
          return False

  def resolve_device(use_gpu: bool) -> tuple[str, str]:
      """(device, compute_type) を返す。use_gpu かつ CUDA 可なら GPU、でなければ CPU。"""
      if use_gpu and cuda_available():
          return "cuda", "int8_float16"
      return "cpu", "int8"
  ```
- **pipeline ②b を置換**:
  ```python
  device, compute_type = resolve_device(params.use_gpu)
  model = WhisperModel(params.model_size, device=device, compute_type=compute_type)
  on_log(tr("log_device", device), "muted")   # 実際に使ったデバイスを可視化
  ```
- **フォールバックの堅牢化**: `WhisperModel(device="cuda", ...)` が DLL 不在で例外を投げる場合がある。
  `cuda_available()` が True でも生成失敗しうるため、**GPU 生成を try し、失敗したら CPU で1回リトライ**してから
  `on_log(tr("log_gpu_fallback"), "warn")` を出す。ハングせず必ず CPU で完走させる。

## 4. UI 側（app.py）の変更（最小）

- 設定カードの「字幕生成」行の近くに **GPU チェックボックス**を1つ追加（既定 OFF）:
  - `self.gpu_var = ctk.BooleanVar(value=False)`（`__init__` の var 群へ。`app.py:79` 付近）。
  - ラベルは i18n キー `gpu_label`。`_build_settings`（`app.py:154-`）に行追加。
- **起動時に CUDA 検出 → 無ければ disabled + 説明ログ1行**（DESIGN.md §5「未導入は disabled+警告1行」に倣う。
  faster-whisper 未導入時のモデル選択 disabled と同じ作法）:
  ```python
  if not cuda_available():
      self.gpu_checkbox.configure(state="disabled")
      self._log(self.t("log_gpu_unavailable"), "muted")
  ```
- **字幕 OFF 時は GPU チェックも disabled**（モデル選択と同じトグル連動。既存の srt トグルハンドラに1行追加）。
- `_start_process` で `PipelineParams(..., use_gpu=self.gpu_var.get())` を渡す。

## 5. 追加する i18n キー（`i18n.py` ja/en 両方・必須）

| key | ja | en |
|---|---|---|
| `gpu_label` | `GPU を使用 (CUDA)` | `Use GPU (CUDA)` |
| `log_device` | `  使用デバイス: {}` | `  Device: {}` |
| `log_gpu_unavailable` | `  GPU 不可: CUDA が見つからないため CPU で実行します` | `  GPU unavailable: CUDA not found, using CPU` |
| `log_gpu_fallback` | `  GPU 初期化に失敗。CPU にフォールバックしました` | `  GPU init failed, fell back to CPU` |

## 6. テスト計画（`tests/test_pipeline.py` / 純関数）

- **`resolve_device`**: `use_gpu=False`→`("cpu","int8")`。`use_gpu=True` & `cuda_available` モック True→
  `("cuda","int8_float16")`。`use_gpu=True` & False→`("cpu","int8")`。（純関数・モック容易）
- **`cuda_available`**: `ctranslate2` import 失敗時に False を返す（例外握り）。
- **pipeline ②b**: `transcribe` DI フックで device 引数の経路は既存テスト流用（`WhisperModel` 実体は呼ばない）。
  GPU 生成失敗→CPU リトライの分岐は `transcribe=None` 経路なのでテストは `resolve_device` 単体で担保し、
  リトライは**人手目視**（受け入れ基準参照）。
- 既存 16 テストを壊さない（`PipelineParams` への `use_gpu` 追加は**末尾・既定値付き**で後方互換）。

## 7. 受け入れ基準（Definition of Done）

1. CUDA 無し環境: GPU チェックが **disabled**、字幕は従来どおり CPU で生成（**挙動完全不変**）。
2. CUDA 有り環境（あれば）: GPU ON で文字起こしが GPU 実行され `log_device: cuda` が出る。
   無い場合は最低限 `resolve_device` の単体テストで代替検証し、その旨 MEMORY に記録。
3. GPU 初期化失敗時に **CPU フォールバックして完走**（ハングしない）。
4. `tests/`（test_unit / test_pipeline）全 green。i18n 4キー ja/en 両方。
5. README（4言語）の「前提条件」に **GPU は任意・CUDA/cuDNN 別途必要・EXE には非同梱**を1行追記。
6. MEMORY.md に判断（非同梱・オプトイン）を追記。バージョン整合(§5)不変・生成物未コミット。

## 8. 非対象（やらない）

- CUDA/cuDNN の **EXE 同梱**・PyInstaller への CUDA バイナリ収集（配布肥大。CONTEXT §7 違反）。
- GPU の **自動選択（既定 ON）**。あくまでオプトイン。
- auto-editor 側の GPU 化（本タスクは ASR のみ。auto-editor は別エンジン）。
- マルチGPU 選択 UI・VRAM 別 compute_type 自動調整（過剰実装）。

## 9. 変更ファイル

| ファイル | 操作 |
|---|---|
| `src/subtitles.py` | `cuda_available` / `resolve_device` 追加 |
| `src/pipeline.py` | `PipelineParams.use_gpu` 追加、②b を `resolve_device`＋GPU失敗時CPUリトライへ |
| `src/app.py` | GPU チェックボックス追加、起動時検出 disabled、srt トグル連動、`use_gpu` 受け渡し |
| `src/i18n.py` | 4キー追加（ja/en） |
| `tests/test_pipeline.py` | `resolve_device`/`cuda_available` テスト追補 |
| `README*.md` | 前提条件に GPU 任意・非同梱を1行 |
| `ROADMAP.md` / `MEMORY.md` | 完了・判断追記 |

## 10. 実装者（Gemini）への注意 — PITFALLS 先読み

- **P-6**: ②b は外部プロセスではないが、ログ文字列は i18n 経由（ハードコード禁止）。
- **後方互換**: `PipelineParams` への追加は**末尾フィールド + 既定値**。位置引数で壊さない。
- **新規依存禁止**: `ctranslate2` は faster-whisper の既存依存。`import torch` 等を**足さない**（検出は ctranslate2 で十分）。
- **並列実装の注意**: 本タスクと「出力プリセット保存」は**どちらも `app.py` 設定UI と `i18n.py` を編集**する。
  同時並行で書くと衝突するため、**片方ずつ直列**で実装し、後発はリベースしてから着手すること。
