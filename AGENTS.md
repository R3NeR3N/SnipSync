# AGENTS.md — AIエージェント運用ガイド

> このファイルは SnipSync を AI 駆動開発するすべてのエージェント（Claude Code / Codex / Copilot 等）の
> **唯一の正典 (single source of truth)** です。`CLAUDE.md` はこのファイルを読み込むだけのポインタです。

---

## 0. まず読む順序

1. **AGENTS.md**（本書）— 作業ルール・禁止事項
2. **CONTEXT.md** — プロダクトの目的・ドメイン知識・用語（なぜ作るか）
3. **ARCHITECTURE.md** — 現状構造と目標構造（どう作るか）
4. **DESIGN.md** — UI/UX デザイン指標（どう見せるか）
5. **MEMORY.md** — 過去の意思決定ログ（なぜそうなったか）
6. **PITFALLS.md** — 過去に失敗した手順（同じ轍を踏まないため）

実装前に該当ファイルへ必ず目を通すこと。矛盾を見つけたら勝手に直さず MEMORY.md に記録し、ユーザーへ確認する。
**作業を始める前に必ず PITFALLS.md を確認**し、既知の失敗手順を繰り返さない。

---

## 1. プロダクト 1 行説明

SnipSync = 動画の無音区間を自動カットし、NLE 用タイムライン（XML/FCPXML）と同期字幕（.srt）を出力する Windows スタンドアロン GUI アプリ。

詳細は CONTEXT.md。

---

## 2. 技術スタック

| 領域 | 採用技術 | 備考 |
|---|---|---|
| 言語 | Python 3.10+ | |
| GUI | CustomTkinter 5.x | ダークテーマ固定 |
| D&D | tkinterdnd2 | 任意（無くても起動可） |
| 無音カット/XML出力 | auto-editor 29.x | 外部プロセス呼び出し |
| 字幕生成 (ASR) | faster-whisper 1.x | CPU / int8 |
| 配布 | PyInstaller 6.x | 単一 `.exe` |
| 前提 | FFmpeg が PATH に必要 | |

---

## 3. ビルド・実行コマンド

```bash
# 仮想環境（venv）作成 — ホストを汚さない隔離境界。初回のみ
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # PowerShell（cmd は .venv\Scripts\activate.bat）

# 依存導入 — pyproject.toml を単一ソースに（直接依存＋開発ツール pytest/ruff）
pip install -e ".[dev]"

# 開発実行（GUI 目視確認はホストの venv 内で行う）
python src/app.py

# EXE ビルド
pip install -e ".[build]"
pyinstaller build/app.spec       # → dist/SnipSync.exe
```

> ⚠ 依存は `pyproject.toml` の `dependencies` / `optional-dependencies` が**単一ソース**。`pip install -e ".[dev]"` で直接依存（auto-editor / faster-whisper / customtkinter / tkinterdnd2）＋開発ツール（pytest / ruff）が入る。新規依存は **`pyproject.toml` だけ**に足せばよい（3箇所手書きのドリフトを防ぐ）。`requirements.txt` は再現用フルフリーズ（生成ロック扱い）。
> ⚠ **venv はホスト汚染を止める隔離境界**。ランタイムを PC 本体へ直入れせず `.venv` 内に閉じ込める（`.gitignore` 済）。不要になれば `.venv` を消すだけで本体は元通り。
> ⚠ **ホスト venv とコンテナの役割分担**: GUI 目視確認（§8 DoD #1）と実パイプライン実行は **ホストの `.venv`**（重依存フル導入）で行う。Dev Container は test/lint/AI エージェント用で **意図的に lean**（subprocess/transcribe をモックするため重依存を入れない）。詳細は `.devcontainer/devcontainer.json` のコメント参照。

---

## 4. 作業ルール（厳守）

### 4.1 やること
- **小さく変更し、変更ごとに `python src/app.py` で起動確認**する。GUI アプリのため自動テストだけでは不足。
- 文字列は**必ず i18n 辞書 (`I18N`) 経由**。`ja` と `en` の両方を同時に追加する。片方だけはバグ扱い。
- パスは `Path(...).resolve()` で絶対パス化（既存方針）。
- 外部プロセス呼び出しは `subprocess.run(..., encoding="utf-8", errors="replace")` を踏襲。
- 変更の理由・トレードオフを **MEMORY.md に追記**してから完了とする。
- 試して**失敗した手順は PITFALLS.md に追記**する（成功しなくても記録は残す）。
- 🔧 作業(Gemini) が出力する **"Implementation Plan" / "Walkthrough" は日本語で記述する**（レビュー効率・チーム言語統一のため）。見出し名は英語のままでも本文は日本語。

### 4.2 やらないこと
- ❌ ハードコードした日本語/英語文字列を UI に直接埋め込む。
- ❌ `language="ja"` のような言語ハードコード追加（既知バグ。修正方針は MEMORY.md）。
- ❌ `build/` `dist/` `venv/` をコミット（`.gitignore` 済。生成物）。
- ❌ ユーザー確認なしに `requirements.txt` 全行を書き換える。
- ❌ バージョン番号を一箇所だけ更新する（コードと README/CHANGELOG を必ず揃える。§5）。
- ❌ PITFALLS.md に記録済みの失敗手順を再試行する。

---

## 5. バージョニング規則

### 5.1 方式: Semantic Versioning 2.0（`MAJOR.MINOR.PATCH`）

現行 `1.0.0` から継続。各桁の意味は SnipSync 固有に以下で定義する。

| 桁 | 上げる条件 | 例 |
|---|---|---|
| **MAJOR** | ユーザーの互換性が壊れる変更（前のやり方が通じなくなる） | 出力 XML/FCPXML の構造変更で既存 NLE が取込不可 / エクスポート形式の削除 / `presets.json` スキーマ破壊 / 対応 NLE の廃止 / 最低要件（Python・FFmpeg）の引上げ |
| **MINOR** | 後方互換のある機能追加（既存はそのまま動く） | GPU 対応 / プリセット / 新エクスポート形式 / 新 Whisper モデル / 新 UI 言語 / バッチ処理 |
| **PATCH** | 機能追加なしのバグ修正のみ | 無音検出のズレ修正 / i18n 誤訳 / クラッシュ修正 / 文字化け修正 |

判断補助:
- 内部リファクタ・テスト追加・依存整理など**ユーザーに見えない変更**は単独では桁を動かさない（次の MINOR/PATCH に相乗り）。
- 1リリースに複数種が混在したら**最も大きい桁**を採用（機能追加＋修正 → MINOR）。
- 配布前テストはプレリリース接尾辞 `-rc.1` / `-beta.1` を付ける（例 `1.1.0-rc.1`）。本番は接尾辞なし。

### 5.2 単一ソース

`src/version.py` の `APP_VERSION` が**唯一の真実**。UI（`src/i18n.py` の `title`）は `APP_VERSION` を参照するのみ（ハードコード禁止）。

### 5.3 リリース手順（順守）

1. `src/version.py` の `APP_VERSION` を上げる。
2. `CHANGELOG.md`: `[Unreleased]` を `[X.Y.Z] — YYYY-MM-DD` に確定し、新しい空の `[Unreleased]` を追加。比較リンクも更新。
3. README バッジ4言語（`README.md` / `README_JA.md` / `README_ZH.md` / `README_KO.md`）を同期。
4. `chore(release): vX.Y.Z` でコミット。
5. `git tag vX.Y.Z` を打つ。
6. `pyinstaller build/app.spec` で exe 生成。

> ❌ バージョン番号を一箇所だけ更新しない（上記 1〜3 は必ずセットで揃える。§4.2）。

---

## 6. コミット規約

- Conventional Commits 準拠: `feat:` `fix:` `docs:` `refactor:` `build:` `chore:`
- 例: `fix: whisper の言語自動判定対応`、`docs: CONTEXT.md 追加`
- 1 コミット = 1 論理変更。生成物は含めない。

### 6.1 コミットの担当（作者一致の原則）

- **変更を書いたエージェントがコミットする**（authorship = commit author を一致させる）。
  - 実装（コード）= 🔧 作業(Gemini) が書く → **Gemini がコミット**。
  - 設計書・ドキュメント = 🧠 頭脳(Opus) が書く → **Opus がコミット**。
- ❌ 他エージェントの未コミット差分を盲目的にコミットしない（意図・文脈が著者と乖離し、誤帰属になる）。1 コミット=1 論理変更（§6）も作者が最も正しく切れる。
- 例外的に分担を越えて書いた場合（例: Opus が実装した）は、整合性のため**その作者がコミット**し、次の変更から通常分担へ戻す。
- 担当の境界は MEMORY（Opusは設計のみ・実装はGeminiへ）に従う。逸脱したら理由を MEMORY.md に残す。

---

## 7. ルート Markdown 一覧（役割分担）

| ファイル | 役割 | 更新頻度 |
|---|---|---|
| `AGENTS.md` | エージェント運用ルール（本書・正典） | ルール変更時 |
| `CLAUDE.md` | Claude Code 用ポインタ（AGENTS.md を読込） | ほぼ不変 |
| `CONTEXT.md` | プロダクト目的・ドメイン・用語集 | 仕様変更時 |
| `ARCHITECTURE.md` | 現状/目標のディレクトリ構造・処理パイプライン | 構造変更時 |
| `DESIGN.md` | UI/UX デザイン指標（配色・タイポ・余白） | UI 変更時 |
| `MEMORY.md` | 意思決定・学びの追記ログ | 変更ごと |
| `PITFALLS.md` | 失敗した手順・ハマりどころの記録 | 失敗ごと |
| `CHANGELOG.md`（**作成推奨**） | リリース履歴（Keep a Changelog） | リリース時 |
| `ROADMAP.md`（任意） | 今後の機能・優先度 | 計画時 |
| `CONTRIBUTING.md`（任意） | 開発手順・PR 手順 | 体制変更時 |

---

## 8. 完了の定義 (Definition of Done)

1. `python src/app.py` が起動し、対象機能が手動で動作する。
2. i18n が ja/en 両方そろっている。
3. MEMORY.md に意思決定を追記した。失敗があれば PITFALLS.md にも追記した。
4. バージョン整合（§5）を崩していない。
5. 生成物・秘匿情報をコミットに含めていない。
