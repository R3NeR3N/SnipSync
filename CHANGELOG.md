# Changelog

本プロジェクトの主要な変更を記録する。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)、
バージョニングは [Semantic Versioning](https://semver.org/lang/ja/) に従う。

> ⚠ **バージョン整合性の注意**: 現状コード（`src/app.py` のタイトル）は `v1.3.1` を表示しているが、
> README 各言語のバッジは `v1.0.0` のまま。`v1.0.0`〜`v1.3.1` 間の変更履歴は未整理。
> 次回リリース時に `src/snipsync/__init__.py` の `__version__` 一元化と合わせて履歴を確定すること（AGENTS.md §5）。

---

## [Unreleased]

### Added
- AI 駆動開発用ドキュメント群を追加: `AGENTS.md` / `CLAUDE.md` / `CONTEXT.md` / `ARCHITECTURE.md` / `DESIGN.md` / `MEMORY.md` / `PITFALLS.md` / `CHANGELOG.md` / `ROADMAP.md` / `CONTRIBUTING.md`。

### Fixed
- バージョン番号の一元化 (APP_VERSION = "1.0.0" としてコード側の表示を README と統一)
- Whisper 音声認識の言語を自動判定化 (language=None に変更)

### Known Issues
- 停止操作が即時でない（MEMORY.md 課題C）。

---

## [1.3.1] — 未確定

- コード上の現行バージョン。詳細な変更履歴は未整理（上記注意参照）。

## [1.0.0] — 初回リリース

- 無音自動カット（auto-editor）。
- NLE タイムライン出力（DaVinci Resolve / Final Cut Pro / Premiere Pro）。
- AI 字幕生成（faster-whisper、tiny/base/small/medium）。
- 日本語／英語 UI 切替、ドラッグ＆ドロップ、単一 `.exe` 配布。

[Unreleased]: https://github.com/R3NeR3N/SnipSync/compare/v1.3.1...HEAD
