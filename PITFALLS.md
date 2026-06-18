# PITFALLS.md — 失敗・ハマりどころ記録

> 開発中に**試して失敗した手順**を残し、同じ轍を二度踏まないためのログ。
> MEMORY.md が「採用した決定」なら、こちらは「うまくいかなかった試み」。
> 着手前に必ず一読すること。新しいものを上に追記。

書式:
```
## YYYY-MM-DD — 症状の一言
- やったこと:
- 何が起きたか（エラー/症状）:
- 原因:
- 回避策 / 正しい手順:
- 関連: ファイル/関数
```

---

## 2026-06-19 — faster-whisper GPU: nvidia-* wheel 導入だけ／add_dll_directory だけでは cuBLAS を読めない
- やったこと: GPU を使うため `.venv` に `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` を入れ、cuda で `WhisperModel` を構築。
- 何が起きたか: `RuntimeError: Library cublas64_12.dll is not found or cannot be loaded`。(1) wheel 導入だけ → DLL 未発見。(2) `os.add_dll_directory(.../nvidia/cublas/bin)` を足すだけでも依然「cannot be loaded」。(3) `nvidia-cuda-runtime-cu12`(cudart) 欠落も一因。
- 原因: ctranslate2 は `site-packages/nvidia/*/bin` を自動探索しない。さらに Windows の LoadLibrary 探索順の都合で `add_dll_directory` 単独では不足。`cublas64_12.dll` は `cudart64_12.dll` に依存。
- 正しい手順: cublas + cudnn + **cuda-runtime** を入れ、**インポート/モデル構築前に各 `bin` を `os.add_dll_directory` ＋ `PATH` 前置**する（PATH 前置が決め手）。SnipSync は `subtitles.add_cuda_dll_dirs()` で自動化し `pipeline._decode` の cuda 構築直前で呼ぶ。CUDA ライブラリは `.venv` 内に閉じ込めホスト非汚染。
- 関連: `src/subtitles.py`, `src/pipeline.py`, `pyproject.toml [gpu]`, MEMORY 2026-06-19

## 2026-06-19 — auto-editor の `--temp-dir` は `{stem}_tracks`（多トラック分解）を移動しない
- やったこと: 多トラック音声の動画で、元動画の隣に出る `{stem}_tracks` フォルダ（`_1.wav`/`_2.wav`...）を消そうとして auto-editor に `--temp-dir <空dir>` を渡した。
- 何が起きたか: `_tracks` は**依然として入力ファイルの隣に生成**され、指定した temp-dir は空のままだった。`--help` を見てもトラック分解の出力先変更/抑制フラグは無い。
- 原因: `--temp-dir` が制御するのは auto-editor の内部一時ファイルであって、多トラック入力を分解した音声フォルダ（`_tracks`）の置き場所ではない。`_tracks` は入力パス基準で作られる。
- 回避策 / 正しい手順: auto-editor 側では抑止できない。**呼び出し側（SnipSync）が処理後に掃除する**。`run_pipeline` 開始前に `{stem}_tracks` の存在を記録し、`finally` で「本実行中に出現した場合のみ」`shutil.rmtree`（既存フォルダは温存）。単トラック動画では `_tracks` は出ない（再現には多トラック入力が必要）。
- 関連: `src/pipeline.py` run_pipeline(tracks掃除), `tests/test_pipeline.py`, MEMORY 2026-06-19

## 2026-06-18 — GitHub Actions の job-level `environment:` は `steps.*` 出力を読めない
- やったこと: release.yml で 1ジョブ内の step でチャネル（staging/prod）を判定し、同ジョブの `environment: ${{ steps.channel.outputs.env }}` に渡そうとした。
- 何が起きるか: `environment` はジョブ開始時（step実行前）に評価されるため `steps.*` は空。環境が解決されず無効。
- 正しい手順: 判定を別ジョブ（classify）に切り出し outputs に出す → build ジョブで `needs: classify` + `environment: ${{ needs.classify.outputs.env }}`。job-level environment は `needs`/`github`/`vars`/`inputs` は読めるが `steps` は不可。
- 関連: `.github/workflows/release.yml`

## 2026-06-18 — ruff の F401 自動修正が「再エクスポート / 可用性プローブ import」を消す
- やりがちなこと: `ruff check --fix` を丸ごと走らせ F401（未使用 import）を一括削除。
- 何が起きるか: app.py の `APP_VERSION`/`format_timestamp` は test_p0 が `from app import ...` する**再エクスポート**、`from faster_whisper import WhisperModel` は try 内の**可用性判定専用**で本体未使用。一括削除すると test破壊・WHISPER_AVAILABLE 判定破壊。
- 正しい手順: 自動修正は安全規則のみに限定（`--select W293,I001,E401 --fix`）。再エクスポート/プローブ import は `# noqa: F401` で残す（または `__all__`）。真の不要 import だけ手で削除。
- 関連: `src/app.py`, `tests/test_p0.py`, `pyproject.toml [tool.ruff]`

## 2026-06-17 — faster-whisper transcribe() は遅延ジェネレータ。例外はデコード（反復）時に出る
- やりがちなこと: `model.transcribe()` 呼び出しを try で囲み「これで GPU 失敗を捕捉できる」と考える。
- 何が起きるか: `transcribe()` は (segments_generator, info) を即返すだけで**実デコードは segments を反復したとき**に走る。CUDA OOM 等の実行時エラーは反復ループ（SRT書込）で送出され、transcribe() を囲んだ try/except を**素通り**する → GPUフォールバックが効かない。DIモックが即時例外で落ちる設計だとテストでも露見しない。
- 正しい手順: フォールバック判定をしたい範囲内で `list(seg_iter)` 等により**デコードを完走させてから**SRT書込へ進む。フォールバック時は device と compute_type を同時に CPU 用へ切り替える。
- 関連: `src/pipeline.py` 2bブロック, `docs/handoff/P3-review-fixes.md`, `tests/test_pipeline.py`

## 2026-06-17 — テスト内で subprocess.Popen をモックすると taskkill 等の subprocess.run も巻き込まれる
- やったこと: `tests/test_pipeline.py` で `subprocess.Popen` をモックした。また、`_kill_tree` の Windows 用処理で `subprocess.run(["taskkill", ...])` を呼び出した。
- 何が起きたか: `subprocess.run` は内部で `Popen` を呼び出すため、モックされた `Popen` が返された。モッククラスがコンテキストマネージャプロトコル (`__enter__`/`__exit__`) や `communicate` / `args` などの属性を実装していなかったため、`TypeError` や `AttributeError` が発生した。
- 原因: グローバルな `subprocess.Popen` のモックが、テストフレームワークや `subprocess.run` の内部呼び出しに影響を与えたため。
- 回避策 / 正しい手順: モック用の `Popen` に `__enter__`, `__exit__`, `communicate() -> ("", "")`, `args` を持たせる。また、コマンドが `"taskkill"` のときはダミーの MockPopen を返すようにモック関数内で条件分岐させる。
- 関連: `tests/test_pipeline.py`, `src/pipeline.py` `_kill_tree`

## （初期エントリ）プロジェクト固有の既知の落とし穴

実コードと環境から判明している、繰り返しやすい失敗を先に登録しておく。

### P-1: UI に文字列を直接書くと言語切替で消える
- やりがちなこと: `CTkLabel(text="処理開始")` のように文字列を直書きする。
- 何が起きるか: 言語切替 (`_apply_lang`) で上書きされない／英語側に出ない。
- 正しい手順: 必ず `I18N` にキーを足し、`self.t("key")` 経由で設定する。`ja` と `en` 両方追加。
- 関連: `src/app.py` `I18N`, `_apply_lang`

### P-2: auto-editor の margin/threshold をメインと字幕用で食い違わせる
- やりがちなこと: メインカット (`cmd`) と字幕用 WAV 抽出 (`temp_cmd`) で別パラメータを使う。
- 何が起きるか: カット位置がズレて **字幕タイムコードがタイムラインと同期しなくなる**（本プロダクトの核心価値が壊れる）。
- 正しい手順: 両者で `--margin` と `--edit audio:threshold=` を必ず一致させる。
- 関連: `src/app.py` `_worker`（①と②）, CONTEXT.md §1

### P-3: 相対パスで auto-editor を呼ぶと出力先が迷子になる
- やりがちなこと: 入力/出力をそのままの相対パスで渡す。
- 何が起きるか: 作業ディレクトリ依存で出力ファイルが想定外の場所に出る。
- 正しい手順: `Path(...).resolve()` で絶対パス化してから渡す（既存方針）。
- 関連: `src/app.py` `_start_process`

### P-4: FFmpeg 不在で無言に失敗する
- やりがちなこと: FFmpeg を PATH に通さず実行。
- 何が起きるか: auto-editor が内部で FFmpeg を呼べず処理が失敗する。
- 正しい手順: 開発環境で FFmpeg を PATH に通す。READMEの前提条件参照。
- 関連: CONTEXT.md §7

### P-5: Whisper モデルを git にコミットしてしまう
- やりがちなこと: キャッシュされた `*.bin` / `*.pt`（数 GB）をうっかり追加。
- 何が起きるか: リポジトリが肥大化。
- 正しい手順: `.gitignore` 済み（`*.bin` `*.pt` `huggingface/`）。コミット前に `git status` で確認。
- 関連: `.gitignore`

### P-6: subprocess の文字化け
- やりがちなこと: `subprocess.run` を encoding 指定なしで呼ぶ。
- 何が起きるか: 日本語ログ/パスが文字化け・デコード例外。
- 正しい手順: `text=True, encoding="utf-8", errors="replace"` を踏襲。
- 関連: `src/app.py` `_worker`

### P-7: 生成物ディレクトリでの作業
- やりがちなこと: `build/` `dist/` の中のファイルを直接編集して挙動を変えようとする。
- 何が起きるか: 再ビルドで消える。ソースは `src/`、ビルド設定は `build/app.spec`。
- 正しい手順: ソースを直し `pyinstaller build/app.spec` で再生成。
- 関連: `build/app.spec`, `dist/`
