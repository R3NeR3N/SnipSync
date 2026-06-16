# MEMORY.md — 意思決定ログ

> 「なぜそうしたか」を時系列で残す。実装を変えたら追記する。新しいものを上に。
> 失敗した手順そのものは PITFALLS.md、ここには**採用した決定とその理由**を書く。

書式:
```
## YYYY-MM-DD — タイトル
- 決定:
- 理由:
- 影響/トレードオフ:
- 関連: ファイル/関数
```

---

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
- 状態: 仕様（暫定）。
- 内容: `subprocess.run` を使用しているため、停止押下後も実行中の外部プロセスは完了を待つ。`stop_requested` フラグで次ステージをスキップするのみ。
- 方針: 即時停止が要件化したら `subprocess.Popen` + `terminate()` への移行を検討。トレードオフはログのストリーミング実装が必要になる点。
- 関連: `src/app.py` `_stop_process`, `_worker`
