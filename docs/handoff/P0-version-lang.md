# 引継書 — SnipSync P0 実装（作業役: Gemini 3.5 / Antigravity）

- 日付: 2026-06-16
- 頭脳(設計): Claude Opus 4.8 / 作業(実装): Gemini 3.5
- 配置: `docs/handoff/P0-version-lang.md`（Claude Code CLI / Antigravity 双方が参照・更新する共有ファイル）
- リポジトリ: `F:\10_Development\11_Software_Dev\AI_Driven\SnipSync`（ブランチ `main`）
- 本体: `src/app.py`（752行モノリス、CustomTkinter GUI）

> このファイルは双方向の引継ボード。作業役は進捗・結果・つまずきを「## 作業ログ」に追記し、
> 頭脳はレビュー結果・指示を「## 頭脳メモ」に追記する。設計判断の本体は変更しない。

## このセッションの位置づけ
頭脳側で P0 の**設計・判断・テスト仕様まで確定済み**。作業役は本書の実装タスクをそのまま実装し、自動テストを green にする。設計判断は変更しない（異論はエスカレ）。

## 必読（共有設計書 = 各リクエスト先頭に固定）
- `AGENTS.md`（正典・運用ルール）, `CONTEXT.md`（目的・用語）, `ARCHITECTURE.md`（構造・処理パイプライン）
- `CONTRIBUTING.md`（協業ワークフロー・Git/GitHub 運用 §5）, `MEMORY.md`（意思決定。最新の「P0 設計判断」エントリ）, `PITFALLS.md`（着手前に一読）
- これらは重複転記しない。パスを参照すること。

## 確定済みの設計判断（変更不可）
1. **正準バージョン = `1.0.0`**（README を正とし、コード title の `v1.3.1` 表示を下げる）。
2. **Whisper 言語 = `language=None`（自動判定）** のみ。UI 言語セレクタは作らない（P2 送り）。
3. **README バッジは変更不要**（既に `v1.0.0`、検証のみ）。

---

## 実装タスク（依存なし・並列可）

### T1: バージョン一元化 — `src/app.py`
1. import 群直後（`resource_path` 定義より前 / `I18N` より前）に追加:
   ```python
   APP_VERSION = "1.0.0"
   ```
2. 43行 `"title": "SnipSync  v1.3.1",` → `"title": f"SnipSync  v{APP_VERSION}",`
3. 98行（en側）も同様に f-string 化。
   - 制約: `APP_VERSION` は `I18N` 辞書より前で定義（NameError 防止）。

### T2: Whisper 言語自動判定 — `src/app.py` 684行
- `model.transcribe(str(temp_wav), beam_size=5, language="ja")` の `language="ja"` → `language=None`
- 他引数（`beam_size=5` 等）は維持。

### T3: README バッジ検証（編集なし）
- `README.md / README_JA.md / README_KO.md / README_ZH.md` 各12行が `badge/Version-v1.0.0-success` であることを確認。差異があれば `v1.0.0` に揃える。

---

## テスト実装タスク（設計から作成。実装の値を正解にしない）
新規 `tests/test_p0.py`（pytest）。冒頭で `src` を `sys.path` に追加して `from app import ...`。

### TC1 `test_format_timestamp`
| 入力(秒) | 期待 |
|---|---|
| `0.0` | `"00:00:00,000"` |
| `3661.5` | `"01:01:01,500"` |
| `59.999` | `"00:00:59,999"` |
| `7322.004` | `"02:02:02,004"` |

### TC2 `test_version_consistency`（AGENTS §5 ドリフト防止）
- `from app import APP_VERSION, I18N`
- `I18N["ja"]["title"]` と `I18N["en"]["title"]` が `APP_VERSION`（= `"1.0.0"`）を含む。
- 4 つの README テキストが `f"Version-v{APP_VERSION}-"`（= `Version-v1.0.0-`）を含む。

### TC3 `test_no_hardcoded_transcribe_language`（回帰ガード）
- `src/app.py` テキストに `language="ja"` を**含まない**かつ `language=None` を**含む**。

---

## 受け入れ条件 (Definition of Done)
1. `python src/app.py` 起動 → タイトルバーが `SnipSync  v1.0.0`。
2. `pytest tests/test_p0.py` 全 green。失敗時はログを読み自己修正（**上限3回**、超えたら頭脳エスカレ）。
3. ja/en title 整合・README バッジ4件一致。
4. 生成物（`build/ dist/ venv/`）コミットなし。
5. テスト通過後: `CHANGELOG.md` Unreleased に「version 一元化 / Whisper 言語自動判定」追記、`ROADMAP.md` P0 該当2件をチェック、`MEMORY.md` に実装完了を1行追記。

## エスカレ条件（頭脳 Opus へ）
- 正準バージョン値への異論、`language=None` での誤判定多発、import 時の GUI 副作用でテスト不能、自己修正3回で未解決。

## ハマりどころ（PITFALLS.md 抜粋）
- P-1: UI 文字列は直書きせず `I18N` + `t()`、ja/en 両方。
- P-6: subprocess は `encoding="utf-8", errors="replace"`（既存維持）。
- P-7: `build/ dist/` 内を直接編集しない。ソースは `src/`。

## コミット規約
- Conventional Commits。例: `fix: バージョン表示を正準 v1.0.0 に統一`、`fix: Whisper 言語を自動判定に変更`、`test: P0 回帰テスト追加`。1コミット=1論理変更。

## 作業環境メモ（重要）
- **Antigravity には次のプラグイン未インストール: `code-review` / `frontend-design` / `security-guidance` / `superpowers`。** これらの skill / slash コマンドを呼び出さない（存在しない）。
- 相当する規律は手順として直接実行する:
  1. テスト駆動: テストは設計（TC1–TC3）から先に書く。
  2. 自己修正ループ: pytest ログを読み原因を1つ特定→最小修正→再実行。推測で複数同時変更しない。上限3回で頭脳エスカレ。
  3. 完了前検証: 「完了」前に `python src/app.py` 起動確認と `pytest` 出力を実際に確認。
  4. レビュー: テスト通過後、main 向け PR を作成し頭脳(Opus)の最終レビューへ。

---

## 頭脳メモ（Opus が追記）
- 2026-06-16: P0 設計確定・本引継書発行。

## 作業ログ（作業役が追記）
- 2026-06-16: ブランチ `fix/p0-version-lang` を作成。
- 2026-06-16: TDDに基づいて `tests/test_p0.py`（TC1, TC2, TC3）を新規作成。実行時、期待通りインポートエラーで失敗することを確認。
- 2026-06-16: `src/app.py` に `APP_VERSION = "1.0.0"` を定義し、I18Nのタイトルに f-string で適用。
- 2026-06-16: `src/app.py` 内の Whisper 音声認識における `language="ja"` を `language=None`（自動判定）に修正。
- 2026-06-16: `README*.md` 4ファイルのバージョンバッジが `v1.0.0` であることを検証（変更なし）。
- 2026-06-16: テスト実行時に `test_format_timestamp` で `7322.004` の浮動小数点誤差によるミリ秒切り捨てが発生（`02:02:02,003` となりアサーションエラー）。
  - 原因: `seconds - int(seconds)` の計算で浮動小数点演算誤差が生じ、ミリ秒部分が切り捨てられていた。
  - 回避策: `format_timestamp` の実装を「総ミリ秒数に変換して `round()` してから時分秒ミリ秒を計算する」ように変更。これによって誤差が解消。
- 2026-06-16: `pytest tests/test_p0.py` を実行し、全テストケースが green になったことを確認。
- 2026-06-16: アプリ起動テスト（`python src/app.py`）を行い、正常に起動することを確認。
- 2026-06-16: `CHANGELOG.md` / `ROADMAP.md` / `MEMORY.md` に結果を反映。
