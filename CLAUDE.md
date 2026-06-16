# CLAUDE.md

このプロジェクトのエージェント運用ルールは **`AGENTS.md` が正典**です。
Claude Code は以下を読み込んでから作業を開始してください。

@AGENTS.md

## 読み込み必須ファイル

- @CONTEXT.md — プロダクトの目的・ドメイン・用語
- @ARCHITECTURE.md — 現状構造と目標構造・処理パイプライン
- @DESIGN.md — UI/UX デザイン指標
- @MEMORY.md — 過去の意思決定ログ
- @PITFALLS.md — 過去に失敗した手順（着手前に確認）

## Claude Code 固有メモ

- OS: Windows。シェルは PowerShell が主、Bash ツールも併用可（それぞれ構文が違う）。
- GUI アプリのため、変更後は `python src/app.py` を起動して**目視確認**するまで「完了」と言わない。
- 文字列追加は必ず `I18N` の `ja`/`en` 両方へ。詳細は AGENTS.md §4。
