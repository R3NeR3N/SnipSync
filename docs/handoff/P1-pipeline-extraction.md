# 設計書 — P1 stage2: pipeline 抽出（コールバックI/F化）

> 区分: 🧠頭脳(Opus 4.8) 設計 → 🔧作業(Gemini) 実装
> 対象: ROADMAP P1「モノリス分割（段階2）」の残り = `_worker` のオーケストレーション抽出
> 前提ブランチ: `feat/p1-refactor`（#1/#2/#4 + autoeditor/subtitles 分離は実装済み）

非開発者向け要約: 「動画カット→音声抽出→文字起こし→字幕」の一連の流れ（パイプライン）が、いまは
画面（UI）に直結していて画面なしでは動かない。この流れを `pipeline.py` に切り出し、画面への報告・
停止確認・翻訳は「外から手渡す小さな関数（コールバック）」で受け取る形にする。結果、画面なしでも
自動テストできるようになる。**処理の挙動は一切変えない（リファクタのみ）**。

---

## 1. 目的

`src/app.py` `SnipSyncApp._worker` に同居している処理オーケストレーションを、UI 非依存の
`src/pipeline.py` へ移す。UI との連絡はコールバック（呼び返し用関数）経由にし、`pipeline` 側は
`self`（画面オブジェクト）を一切参照しない。これにより subprocess をモック（ニセモノ差し替え）した
**単体テストが可能**になる。

## 2. 背景 — 現状の結合点（app.py `_worker`）

`_worker` は以下4つで画面に直結している。これを引数（コールバック）へ置換する。

| 結合 | 現コード | 役割 |
|---|---|---|
| ログ出力 | `self._log(msg, level)` | 進捗・結果をコンソールへ |
| UIスレッド反映 | `self.after(0, ...)` | 完了ダイアログ / UIリセット |
| 停止確認 | `self.stop_requested` | 次ステージをスキップ判定 |
| 翻訳 | `self.t(key, *args)` | i18n（ja/en）文字列取得 |

外部依存: `subprocess.run`（auto-editor 呼出, 既に `build_cut_cmd`/`build_extract_wav_cmd` で組立）、
`faster_whisper.WhisperModel`（文字起こし）、`format_timestamp`（`subtitles.py`、抽出済み）。

## 3. 設計方針

- **挙動不変**: ステージ順・パラメータ・停止セマンティクス（課題C: subprocess は kill せず次段スキップ）を維持。
- **i18n はキー渡し**: `pipeline` は翻訳表を持たず、`tr(key, *args)` コールバックで翻訳済み文字列を得る。
  （将来「構造化イベントを返して UI 側で翻訳」へ発展可。今回は最小差分で `tr` 採用。）
- **UI スレッド差分**: `self.after(...)` は UI 専用。`pipeline` は呼ばない。完了/失敗は**戻り値**で返し、
  ダイアログ表示・UIリセットは従来どおり `_worker`(UI側ラッパ) が `self.after` で行う。
- **副作用の所在**: ファイル入出力（SRT書込, 一時WAV削除）は `pipeline` 内に残す（処理の本体のため）。

## 4. 公開API（`src/pipeline.py`）

```python
from dataclasses import dataclass

@dataclass
class PipelineParams:
    margin: float
    threshold: float
    export_key: str          # "resolve" | "premiere" | "final-cut-pro"
    do_srt: bool
    model_size: str          # "tiny" | "base" | "small" | "medium"

@dataclass
class PipelineResult:
    ok: bool                 # メインカット成功（完了ダイアログ可否の判定に使用）
    stopped: bool            # 停止要求で中断したか
    timeline_path: Path | None
    srt_path: Path | None

def run_pipeline(
    ae_path,                 # auto-editor 実行パス（呼び出し側で get_auto_editor_path()）
    inp: Path,               # 入力動画（解決済み絶対パス）
    out_dir: Path,           # 出力先（解決済み絶対パス）
    params: PipelineParams,
    *,
    on_log,                  # (msg: str, level: str="") -> None   ← self._log 相当
    should_stop,             # () -> bool                          ← self.stop_requested 相当
    tr,                      # (key: str, *args) -> str            ← self.t 相当
    transcribe=None,         # DI用フック（既定 None→内部で faster_whisper を使用）
) -> PipelineResult:
    ...
```

### コールバック契約

- `on_log(msg, level)`: `level ∈ {"", "info", "success", "error", "warn", "muted"}`。
  スレッド安全性は **呼び出し側（UI）の責務**（現 `self._log` が内部で `self.after` 済み）。
- `should_stop()`: 各ステージ境界・SRT書込ループ毎回で参照。`True` なら以降をスキップ。
- `tr(key, *args)`: i18n キー→翻訳済み文字列。`pipeline` はキー文字列のみ知る。
- `transcribe`: テスト時に faster_whisper を差し替えるための注入点（**依存性注入＝DI**）。
  既定 `None` のとき内部で `WhisperModel(model_size, "cpu", "int8").transcribe(...language=None)` を使う。
  シグネチャ: `transcribe(wav_path, model_size) -> (segments_iterable, info)`。

## 5. ステージと停止チェック位置（挙動不変）

```
run_pipeline:
  result = PipelineResult(ok=False, stopped=False, ...)
  ① auto-editor カット（build_cut_cmd → subprocess.run）
       rc==0 & not should_stop() → on_log(done,"success"); result.ok=True
       should_stop()             → on_log(stopped,"warn"); result.stopped=True
       else                      → on_log(error...,"error")
  ── result.ok かつ params.do_srt かつ not should_stop() のときのみ ②へ ──
  ②a 一時WAV抽出（build_extract_wav_cmd → subprocess.run）→ 存在確認
  ②b 文字起こし: transcribe() → SRT 書込ループ
        ループ各回先頭で should_stop() → break
  ②c finally: 一時WAV を unlink（存在時）
  return result
```

- 例外境界: 現状どおり各ステージを try/except で囲み、`on_log(tr("log_unexpected", traceback...), "error")`。
  トップレベルも try/except で thread クラッシュを握る。`pipeline` は例外を**外へ投げない**（UI を落とさない）。
- subprocess は `capture_output=True, text=True, encoding="utf-8", errors="replace"`（PITFALLS P-6 踏襲）。

## 6. UI 側（app.py `_worker`）の差し替え

`_worker` は薄いラッパに縮小:

```python
def _worker(self, ae_path, inp, out_dir, params):
    result = run_pipeline(
        ae_path, inp, out_dir, params,
        on_log=self._log,
        should_stop=lambda: self.stop_requested,
        tr=self.t,
    )
    self.running = False
    if not result.stopped and result.ok:
        self.after(0, lambda: self._popup_done(out_dir=out_dir))
    self.after(0, self._reset_ui)
```

`_start_process` は `PipelineParams` を組んで `threading.Thread(target=self._worker, ...)` に渡すよう調整。
（cmd 組立は pipeline 内へ移るため、`_start_process` の `build_cut_cmd` 呼びは削除。ログの開始サマリは
UI 側に残してよい。）

## 7. テスト計画（`tests/test_pipeline.py`、subprocess/whisper モック）

- `subprocess.run` を monkeypatch（`rc=0`/`rc!=0`/`FileNotFoundError`）。
- `transcribe` に偽セグメント（`.start/.end/.text` を持つ簡易オブジェクト）を注入。
- 検証項目:
  1. do_srt=False → ②をスキップ、`result.ok=True`、`srt_path=None`。
  2. do_srt=True 正常 → SRT ファイルが生成され中身が `format_timestamp` 整形。
  3. `should_stop` が途中 True → 以降スキップ、`result.stopped=True`、完了ダイアログ条件を満たさない。
  4. メインカット `rc!=0` → `result.ok=False`、②未実行。
  5. 一時WAV が出来ない → `tr("log_wav_missing")` ログ、②b未実行。
  6. 一時WAV は最後に削除される（DI したダミーファイルで確認）。
- `on_log`/`tr` はスタブ（`tr = lambda k,*a: k` で十分）。

## 8. 受け入れ基準（Definition of Done）

1. `python src/app.py` 起動、実カット＋字幕が従来どおり動く（**人手目視**）。停止挙動も不変。
2. `pipeline.py` は `import customtkinter` / `self` を参照しない（UI非依存）。
3. `tests/`（既存 test_p0 / test_unit ＋新 test_pipeline）が全 green。
4. i18n は ja/en 双方そろう（文字列追加があれば）。
5. MEMORY.md に決定追記、失敗あれば PITFALLS.md。バージョン整合（§5）不変。

## 9. 非対象（やらない）

- 即時停止（`subprocess.Popen`+`terminate` / ログのストリーミング）= **P2 課題C**。本設計は現行の
  「次ステージスキップ」セマンティクスを維持するのみ。
- 完全パッケージ化（`src/snipsync/`）。flat 配置を継続（PyInstaller `pathex=src`、build/app.spec 無変更）。

## 10. 変更ファイル

| ファイル | 操作 |
|---|---|
| `src/pipeline.py` | 新規（`run_pipeline` + dataclass群） |
| `src/app.py` | `_worker` 縮小・`_start_process` 調整（cmd組立は pipeline へ移管） |
| `tests/test_pipeline.py` | 新規 |
| `ROADMAP.md` | P1 stage2 を [x] へ |
| `MEMORY.md` | 決定追記 |
