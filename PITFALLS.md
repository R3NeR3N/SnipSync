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
