# MEMORY.md — 意思決定ログ

> 「なぜそうしたか」を時系列で残す。実装を変えたら追記する。新しいものを上に。
> 失敗した手順そのものは PITFALLS.md、ここには**採用した決定とその理由**を書く。
> 見出しには**日付＋時刻**（`YYYY-MM-DD HH:MM`）を記載する。

書式:
```
## YYYY-MM-DD HH:MM — タイトル
- 決定:
- 理由:
- 影響/トレードオフ:
- 関連: ファイル/関数
```

---

## 2026-06-17 04:38 — P2 出力プリセット保存の実装完了（作業: Gemini 3.5）
- 決定: 設計書 `docs/handoff/P2-output-presets.md` に基づき、名前付きプリセット保存/読込/削除および前回終了時設定の自動復元機能（last_used）を実装。
- 理由: ユーザーが起動するたびに設定を再入力する手間を排除し、よく使用する設定の組み合わせを簡単に保存・復元できるようにするため。
- 実装詳細:
  1. 新規 `src/presets.py` を作成し、Tk/UI 依存なしのピュア Python モジュールとして JSON I/O をカプセル化（`%APPDATA%/SnipSync/presets.json` への読み書き）。
  2. 既存の GPU オプトイン対応に合わせて `SETTING_KEYS` に `"gpu"` を追加。存在するキーだけを読み書き・適用する前方/後方互換設計。
  3. `src/app.py` にて `_collect_settings()` と `_apply_settings()` を実装し、UI 側での Tk 変数と辞書の相互変換をハンドリング。適用後はスライダーと値ラベル、SRT オプションを双方向同期。
  4. 設定カード上部にプリセット OptionMenu、および「保存」「削除」ボタンを追加。言語切替 (`_apply_lang`) の同期、起動時の last_used 復元、`WM_DELETE_WINDOW` 終了時の last_used 自動保存を実装。
  5. `src/i18n.py` に `preset_label` / `preset_none` / `preset_save` / `preset_delete` / `preset_name_prompt` / `log_preset_saved` / `log_preset_deleted` を日英双方に追加。
  6. 新規 `tests/test_presets.py` で temporary directory の隔離環境で load/save、壊れた JSON 処理、日本語/マルチバイト名の upsert/delete、last_used の往復をテスト。
- 検証: `tests/test_presets.py` を含む全 25 テストがグリーンであることを確認。
- 関連: `src/presets.py`, `src/app.py`, `src/i18n.py`, `tests/test_presets.py`, `ROADMAP.md`

## 2026-06-17 04:32 — P2 GPU対応の実装完了（作業: Gemini 3.5）
- 決定: 設計書 `docs/handoff/P2-gpu-support.md` に基づき、オプトイン方式の GPU (CUDA) サポートを実装。
- 理由: CUDAが利用可能な環境で ASR 字幕生成の処理速度を向上させるため。
- 実装詳細:
  1. `src/subtitles.py` に `cuda_available()` と `resolve_device()` を実装。
  2. `src/pipeline.py` にて `PipelineParams` に `use_gpu` を追加し、`resolve_device` を経由してモデルの初期化を行う。GPU での初期化・処理に失敗した場合は CPU での 1 回リトライ（フォールバック）を行い、その旨を警告ログとして可視化。
  3. `src/app.py` にて設定 UI 内に GPU チェックボックスを新設（既定 OFF、CUDA 不在または字幕機能 OFF 時は disabled）。
  4. `src/i18n.py` に `gpu_label` / `log_device` / `log_gpu_unavailable` / `log_gpu_fallback` キーを日英辞書に追加。また、`pipeline.py:211` の cleanup 警告を i18n 経由 (`log_cleanup_failed`) に修正。
  5. 各 `README*.md`（4言語）の動作要件に GPU 要件を追記。
- 検証: `tests/test_pipeline.py` に `cuda_available`、`resolve_device`、GPU フォールバックの単体・統合テストを追加し、既存テストを含む全 19 テストがグリーンであることを検証。
- 関連: `src/subtitles.py`, `src/pipeline.py`, `src/app.py`, `src/i18n.py`, `tests/test_pipeline.py`, `README.md`, `README_JA.md`, `README_KO.md`, `README_ZH.md`, `ROADMAP.md`

## 2026-06-17 04:26 — P2 残2件（GPU対応 / 出力プリセット）の設計（頭脳: Opus 4.8）
- 決定: 即時停止(課題C)の実装完了(commit 0dbe9e9)を受け、P2 残りの2件を設計。設計書を2本作成（実装は🔧Gemini へハンドオフ）: `docs/handoff/P2-gpu-support.md`, `docs/handoff/P2-output-presets.md`。
- GPU判断: CUDA/cuDNN は **EXE 非同梱**（CONTEXT §7 / 配布肥大回避）。**オプトイン（既定OFF）+ `ctranslate2.get_cuda_device_count()` 自動検出 + GPU失敗時CPUフォールバック**。compute_type は GPU時 `int8_float16` / CPU時 `int8`。`PipelineParams.use_gpu`（末尾・既定False＝後方互換）で意図のみ渡し、`subtitles.resolve_device()` で解決（UI非依存維持）。新規依存なし（torch等足さない）。
- プリセット設計: 新規 `src/presets.py`（Tk非依存・JSON I/O のみ）に store 操作を閉じ、UI が Tk変数⇄dict 変換を担当。永続先 `%APPDATA%/SnipSync/presets.json`（utf-8/ensure_ascii=False）。名前付きプリセット 保存/読込/削除 + 前回設定の自動復元(last_used, WM_DELETE_WINDOW)。壊れ/不在JSONでも落ちず既定構造。
- 並列性: 2件とも `app.py` 設定UI + `i18n.py` を編集 → **実装は直列**（後発リベース）。設計(本タスク)は衝突なしで両方先行。GPUの `gpu` キーはプリセットの「存在キーだけ読む」設計で順序非依存。
- 発見(未修正・Geminiへ申し送り): `pipeline.py:211` の `"Temp file cleanup failed: {e}"` は**ハードコードEN文字列**（AGENTS §4.1 / P-1 違反）。即時停止実装の取りこぼし。次の実装タスクで i18n キー化推奨。
- 協業: 設計=Opus（本コミット）、実装=Gemini（AGENTS §6.1 作者一致）。
- 関連: `docs/handoff/P2-gpu-support.md`, `docs/handoff/P2-output-presets.md`, ROADMAP P2, `src/pipeline.py`, `src/subtitles.py`, `src/app.py`, `src/i18n.py`

## 2026-06-17 — P2 課題C: 即時停止の実装（作業: Gemini 3.5）
- 決定: 設計書 `docs/handoff/P2-immediate-stop.md` に従い、`src/pipeline.py` に `_run_streaming` と `_kill_tree` を実装し、`run_pipeline` の外部プロセス呼び出し（メインカットおよび一時WAV抽出）を `subprocess.Popen` によるストリーミングに移行。
- 理由: ユーザーが停止ボタンを押した際に、実行中の外部プロセス（auto-editor/ffmpeg）を即座に強制終了し、無駄な処理を防止するため。
- 実装詳細: Windows では `creationflags=CREATE_NEW_PROCESS_GROUP` でプロセスグループを作成し、停止時に `taskkill /F /T /PID` で子プロセスを含めたプロセスツリーを強制終了。非 Windows では `proc.terminate()` 後に必要に応じて `proc.kill()` を呼び出す。i18n キー違反（ハードコード3箇所）を `log_stop_requested`/`log_srt_enabled`/`log_lang_detected` に置き換え。
- テスト: `tests/test_pipeline.py` を Popen モック用に全面改修。リアルタイムログストリーミング、中途停止時のプロセスツリー終了、エラーハンドリング、正常動作等の計19テストが全パス。
- 関連: `src/pipeline.py`, `src/app.py`, `src/i18n.py`, `tests/test_pipeline.py`


## 2026-06-17 — P2 課題C: 即時停止の設計（頭脳: Opus 4.8）
- 決定: P1 完了を受け P2 先頭「即時停止対応」を設計。設計書 `docs/handoff/P2-immediate-stop.md` を作成（実装は 🔧Gemini へハンドオフ）。
- 設計判断1: `pipeline.run_pipeline` の auto-editor 呼出を `subprocess.run`→`Popen` ストリーミング化し、`should_stop()` 監視で実行中プロセスを kill。`run_pipeline` の公開シグネチャは不変（内部ヘルパ `_run_streaming`/`_kill_tree` 追加）。kill は pipeline 内に閉じ、UI `_stop_process` は従来どおりフラグ立てのみ＝UI 非依存維持。
- 設計判断2: auto-editor は ffmpeg を子に持つため `terminate()` では孤児化。Windows は `CREATE_NEW_PROCESS_GROUP` + `taskkill /F /T /PID`（ツリー kill）で対応。**psutil 等の新規依存は足さない**（配布 EXE 肥大回避／要承認）。
- 設計判断3: 着手時に発見した i18n 違反3箇所（`app.py:458` SRT生成ログ, `app.py:501` 停止ログ, `pipeline.py:138` 音声検出ログ＝Gemini の P1 実装の取りこぼし）を、触る範囲なので本タスクで同時修正。i18n キー `log_stop_requested`/`log_srt_enabled`/`log_lang_detected` を ja/en 追加。
- 影響/トレードオフ: 停止が即時化。ただし `for line in proc.stdout` のブロッキング上、auto-editor 無出力ハング時のみ次行まで遅延（実用上ほぼ即時。完全即時=別スレッドポンプは非対象）。課題C は実装完了時に「解消」へ更新する。
- 協業: 設計=Opus（本コミット）、実装=Gemini（AGENTS §6.1 作者一致）。
- 関連: `docs/handoff/P2-immediate-stop.md`, `src/pipeline.py`, `src/app.py`, `src/i18n.py`, `tests/test_pipeline.py`, ROADMAP P2

## 2026-06-17 — P1 stage2: pipeline 抽出（コールバックI/F化）完了（作業: Gemini 3.5）
- 決定: `src/app.py` の `_worker` に同居していた処理オーケストレーションを UI 非依存の `src/pipeline.py` に `run_pipeline` として切り出した。
- 理由: モノリスを分割し、UI 非依存とすることで subprocess や transcribe をモックした単体テストを可能にするため。
- 実装: `run_pipeline` と `PipelineParams`/`PipelineResult` を `src/pipeline.py` に実装し、ログ・停止確認・翻訳はコールバック (`on_log`/`should_stop`/`tr`) で外から渡す。テスト `tests/test_pipeline.py` を追加し、6つの検証項目（SRT生成/不生成、途中停止、コマンド失敗、一時WAV不在/削除）をモックで検証 (全 green)。
- 影響/トレードオフ: `app.py` の `_worker` は `run_pipeline` を呼ぶ薄いラッパーになり、画面非表示やCLIからも再利用可能になった。
- 関連: `src/app.py`, `src/pipeline.py`, `tests/test_pipeline.py`, `ROADMAP.md`

## 2026-06-17 — P1 大半を実装（頭脳兼作業: Opus 4.8）
- 決定: P0 を PR#1 で main にマージ後、P1 を着手。並列性分析の結論「app.py 書込競合で #1/#2/#3 は直列、#4(pyproject) のみ独立」に基づき直列実装。
- 実装: 分割段階1 = `version.py`/`i18n.py`/`theme.py` を `src/app.py` から抽出（flat配置・PyInstaller の pathex=src で読込可、build/app.spec は無変更）。段階2(一部) = `autoeditor.py`(コマンド組立 `build_cut_cmd`/`build_extract_wav_cmd`)・`subtitles.py`(`format_timestamp`)。単体テスト `tests/test_unit.py`(7件 green)。`pyproject.toml`(直接依存)。
- 設計判断: 完全パッケージ化(`src/snipsync/`)は見送り。app.py を移すと build.spec / test import を壊すため、flat 配置で「一度に壊さない」を優先（ARCHITECTURE §2 目標へは段階移行）。`format_timestamp` は `app` から re-export し test_p0 を温存。
- 協業逸脱: 本来 🧠Opus=設計/🔧Gemini=実装 だが、セッション内に Gemini 不在かつユーザー「進めて」指示のため Opus が実装も実施。次回以降の分担は要再確認。
- 残: 段階2 の pipeline オーケストレーション抽出（`_worker` は UI/ログ結合のためコールバック設計が必要）。
- 検証: `pytest tests/`=7 passed、GUI 構築スモーク(build→言語切替→destroy)=OK。**人間の目視確認は未**（プログラム的スモークのみ）。
- 関連: `src/{version,i18n,theme,autoeditor,subtitles,app}.py`, `tests/test_unit.py`, `pyproject.toml`, ROADMAP P1

## 2026-06-16 — P0 タスク実装完了（作業: Gemini 3.5）
- 決定: 設計判断に沿って、バージョン一元化（v1.0.0への統一とI18Nへの適用）、Whisperの自動判定化（language=None）、READMEバッジの検証を完了。テスト（tests/test_p0.py）を作成し、floating pointによるミリ秒丸め誤差の修正を含めて全 green とした。
- 関連: `src/app.py` (format_timestamp, APP_VERSION, I18N, worker), `tests/test_p0.py`

## 2026-06-16 — P0 設計判断（頭脳: Opus 4.8）
- 決定1: 正準バージョンを **`1.0.0`** とする（ユーザー指定。README を正とし、コード側 title の `v1.3.1` 表示を下げる）。`APP_VERSION = "1.0.0"` 定数を `I18N` 定義前に置き、`title` を `f"SnipSync  v{APP_VERSION}"` 化。`src/snipsync/__init__.py` への移動はパッケージ分割（P1）まで遅延。
- 決定2: Whisper 言語ハードコード（課題B）の P0 対応は **`language=None`（自動判定）に変更するのみ**。検出言語は既存の `info.language` ログで可視。UI 言語セレクタは要求外の作り込みのため P2 へ（ROADMAP 更新）。
- 決定3: README 4 言語のバージョンバッジは既に `v1.0.0` で正準と一致 → **変更不要・検証のみ**。
- 理由: 既知の不整合・バグを最小差分で潰し、過剰実装を避ける（協業ポリシー「要求外の作り込み禁止」）。
- 影響: 実装・テスト実装・README 修正は作業役（Gemini 3.5）へ引き継ぐ。テストは本決定（設計）から作成し実装からは作成しない。
- 関連: `src/app.py` 43/98行(title), 684行(transcribe), `README*.md` 12行, CONTRIBUTING.md ワークフロー

## 2026-06-16 — AI 駆動開発用ドキュメント群を整備
- 決定: ルートに `AGENTS.md` / `CLAUDE.md` / `CONTEXT.md` / `ARCHITECTURE.md` / `DESIGN.md` / `MEMORY.md` / `PITFALLS.md` を新設。`AGENTS.md` を正典、`CLAUDE.md` はそれを `@import` するポインタとした。
- 理由: 752 行のモノリス `src/app.py` に対し AI が安全に部分編集するための文脈・ルールが欠如していた。役割を分離して参照負荷を下げる。
- 影響: ドキュメント保守コストが増えるが、編集衝突・仕様逸脱のリスクを下げる。
- 関連: ルート直下 markdown 群、`src/app.py`

---

## （既知の課題・未決定事項）

以下は発見済みだが本タスクでは未修正。着手時にこのセクションを更新すること。

### 課題A: バージョン番号の不整合
- 状態: 未修正。
- 内容: コード（`src/app.py` の `I18N["ja"|"en"]["title"]`）は `v1.3.1`、README 各言語は `v1.0.0`。
- 方針: `src/snipsync/__init__.py` に `__version__` を一元化し、UI とドキュメントが参照する形に統一する（ARCHITECTURE.md §5 TODO #1）。

### 課題B: Whisper の言語ハードコード
- 状態: 未修正（既知バグ）。
- 内容: `model.transcribe(str(temp_wav), beam_size=5, language="ja")` が日本語固定。英語など他言語動画で誤った文字起こしになる。
- 方針: `language=None` で自動判定にするか、UI に言語セレクタを追加（既存の `info.language_probability` ログと整合）。i18n の言語切替とは別概念なので混同しないこと。
- 関連: `src/app.py` `_worker` 2b ブロック（684 行付近）

### 課題C: 停止が即時でない
### 課題C: 停止が即時でない
- 状態: 解消。
- 内容: `subprocess.run` から `subprocess.Popen` へ移行し、`_run_streaming` 内で `should_stop()` を監視。停止時は `taskkill /F /T` によるプロセスツリーの即時強制終了を Windows で行い、非 Windows では `terminate()` と `kill()` で終了。
- 関連: `src/pipeline.py`, `src/app.py`, `tests/test_pipeline.py`
