# Changelog

本プロジェクトの主要な変更を記録する。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)、
バージョニングは [Semantic Versioning](https://semver.org/lang/ja/) に従う。

> バージョンは `src/version.py` の `APP_VERSION = "1.0.0"` に一元化済み（UI タイトル・README バッジと一致）。

---

## [Unreleased]

### Added
- AI 駆動開発用ドキュメント群を追加: `AGENTS.md` / `CLAUDE.md` / `CONTEXT.md` / `ARCHITECTURE.md` / `DESIGN.md` / `MEMORY.md` / `PITFALLS.md` / `CHANGELOG.md` / `ROADMAP.md` / `CONTRIBUTING.md`。
- 出力プリセット: 名前付きプリセットの保存/読込/削除 + 前回終了時設定の自動復元（`%APPDATA%/SnipSync/presets.json`）。
- GPU (CUDA) 対応: オプトイン（既定OFF）。GPU 失敗時は CPU へ自動フォールバック。
- 単体テスト導入（`tests/`）と `pyproject.toml`（直接依存の切り出し）。

### Changed
- 即時停止: 外部プロセス呼び出しを `subprocess.Popen` 化し、停止時にプロセスツリーを `taskkill /F /T` で即時 kill。ログをストリーミング表示。
- モノリス分割: `src/app.py` から `version.py` / `i18n.py` / `theme.py` / `autoeditor.py` / `subtitles.py` / `pipeline.py` を分離（flat 配置）。

### Fixed
- バージョン番号の一元化 (APP_VERSION = "1.0.0" としてコード側の表示を README と統一)
- Whisper 音声認識の言語を自動判定化 (language=None に変更)

---

## [1.0.0] — 初回リリース

- 無音自動カット（auto-editor）。
- NLE タイムライン出力（DaVinci Resolve / Final Cut Pro / Premiere Pro）。
- AI 字幕生成（faster-whisper、tiny/base/small/medium）。
- 日本語／英語 UI 切替、ドラッグ＆ドロップ、単一 `.exe` 配布。

[Unreleased]: https://github.com/R3NeR3N/SnipSync/compare/v1.0.0...HEAD
