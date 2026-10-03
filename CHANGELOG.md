# Changelog

本プロジェクトの主要な変更を記録する。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)、
バージョニングは [Semantic Versioning 2.0](https://semver.org/lang/ja/) に従う。

> バージョンは `src/version.py` の `APP_VERSION` に一元化している（UI タイトル・README バッジ・`pyproject.toml` と一致させる）。
> **現在は初期開発段階（MAJOR = 0）**。0.y.z の間は、機能追加と互換性を壊す変更は MINOR、バグ修正は PATCH を上げる（AGENTS.md §5）。
> 旧表記: 最初の公開版（GitHub のタグ `v1.0.0`）は、この体系では **0.1.0** に相当する。

---

## [Unreleased]

### Added
- **字幕を保存する前に編集できる**: 処理後の「字幕を確認・編集」ウィンドウで、本文・話者の修正、分割、結合、削除、元に戻すができる。変えた行には印が付き、.txt / .md / .srt のタブで書き出される内容をそのまま確認できる。保存は直前の出力を上書き、または名前を付けて保存。未保存のまま閉じようとすると確認する。
- **カットマップ**: ファイルを選ぶと、切られる場所（赤）・倍速になる場所（青）を波形に自動で重ねる。設定を変えると 700 ms 後に再計算し、それまでは「設定が変わりました」の札で古い結果だと示す。旧「波形プレビュー」の窓は廃止し、メイン画面に統合した。
- 同梱フォント BIZ UD ゴシック / BIZ UDPゴシック（SIL OFL 1.1）。
- テスト: デザインの主張（コントラスト比・色と書体をテーマ以外に直書きしない・補足文の長さ・文言キーの過不足）と、画面の煙テスト。

### Changed
- **UI を全面的に作り直し**: 紺と紫の配色を廃止し、編集ソフトに近い無彩色のグレーと、「黄色は操作、赤・青は素材に起きたこと」の規則に統一した。設定を「カット／字幕／書き出し」のタブに分け、モニターを最上部に置いた。全ての決定の理由は DESIGN.md に書いた。
- UI 文言から絵文字を除き、補足文を 1 行にした。ログには、ファイルのフルパスではなくファイル名だけを出す。
- DESIGN.md を書き直した（旧版の値は現行実装と合わなくなっていた）。
- README（4言語）: ソースからの実行・ビルド手順を、標準の `python -m venv` + `pip` だけで動く環境非依存の手順に変更（特定のツールの記載を削除）。使い方を、実機のスクリーンショット（番号つきの注釈）と流れ図で説明する形に刷新。
- README（4言語）の冒頭に目次（ToC）を追加し、各項へジャンプできるようにした。

### Fixed
- 処理完了ログの「文字起こしを書き出しました」に、書き出したファイル名が表示されていなかった（文言に `{}` が無く、引数が捨てられていた）。全メッセージの引数の数を検査するテストを追加。

---

## [0.2.0] — 2026-10-03

### Added
- **音声区間検出（VAD）カット**: 音量しきい値の代わりに Silero VAD（faster-whisper 同梱）で発話区間を求める。区間は auto-editor の v1 JSON 経由で全出力に共有される。
- **無音の倍速化**: 無音をカットせず N 倍速にする（`--when-inactive speed:N`）。字幕のカット境界も倍速後の尺で計算する。
- **音声ファイル入力とメディア書き出し**: `.wav/.mp3/.m4a/.flac/.aac/.ogg/.opus/.wma` を入力可能。出力形式に「カット済みメディア」を追加。音声のみは `.wav/.flac/.ogg/.opus` で書き出し、同梱の auto-editor にエンコーダーが無い `.mp3/.m4a/.aac/.wma` は WAV にする。
- **バッチ処理**: 複数ファイル／フォルダをまとめて処理。Whisper モデルは1回だけ読み込んで使い回す。
- **波形プレビュー**: 処理前に「どこが切られるか」を波形に重ねて表示（赤=削除、橙=倍速）。実際の出力と同じ auto-editor の区間を使うので近似ではない。
- **日本語字幕の文節改行**: BudouX で文節の途中で改行せず、1字幕が2行に収まるよう分割する（1行の文字数は設定可、既定 20。0で無効）。
- **用語辞書**: 固有名詞を Whisper の `hotwords` に渡して認識を寄せる。
- **話者分離**: sherpa-onnx（onnxruntime のみ・PyTorch/トークン不要）。字幕に「話者1：」を前置し、話者交代でも字幕を分割する。モデルは初回のみ公式リリースから取得し SHA-256 を検証。
- **字幕全文のプレビュー／書き出し**: `.txt` / `.md` / `.srt` を表示・コピー・保存。処理時に `.txt` / `.md` も同時出力できる。
- **タイムラインマーカー（任意）**: カット点と話者交代を FCPXML / Premiere XML に追加。**実 NLE への取り込みは未検証**（`docs/handoff/verification-2026-10.md`）。
- **Whisper モデル追加**: large-v3-turbo / large-v3 / kotoba-whisper-v2.0（日本語特化・実験的）/ distil-large-v3（英語専用）。
- 実行環境の自動取得: `src/aebin.py`（auto-editor を公式リリースから取得し SHA-256 を照合）、`scripts/fetch_auto_editor.py`（EXE 同梱用）。
- 出力プリセット: 名前付きプリセットの保存/読込/削除 + 前回終了時設定の自動復元（`%APPDATA%/SnipSync/presets.json`）。
- GPU (CUDA) 対応: オプトイン（既定OFF）。GPU 失敗時は CPU へ自動フォールバック。
- カット整合字幕（Cut-Aligned Subtitles）: 字幕を whisper の word-level timestamp で生成し、全カット境界で再分割することで、どの NLE 形式（DaVinci/Premiere/FCP）でも各カットに整合する字幕 (.srt) を生成する（旧 SRT-snap 方式から置換）。
- AI 駆動開発用ドキュメント群（`AGENTS.md` / `CONTEXT.md` / `ARCHITECTURE.md` / `MEMORY.md` / `PITFALLS.md` ほか）と、単体テスト（`tests/`）・`pyproject.toml`。

### Changed
- **auto-editor を 29.3.1 から 31.7.2 へ移行**（互換性に影響）。PyPI の `auto-editor` は 29.3.1 で止まっているため、pip の依存をやめ、公式リリースの固定版を取得して使う（配布 EXE は同梱）。
  - フラグ名: `--when-silent` → `--when-inactive`。進捗バーを `--progress none` で抑止。
  - **カットの結果が変わる**: 31.x は `--smooth`（既定 0.2s,0.1s）が効き、短すぎるカット／クリップが除かれる。同じ設定でもカット数が減る（例: 27区間 → 19区間）。
  - 31.x の NLE 出力の修正を享受: FCPXML の開始タイムコードずれ、Final Cut Pro が拒否する `audioLayout`、Premiere XML の重複 `clipitem` と参照切れ、モノラル素材、NTSC 1000/1001、ドロップフレーム。
  - **ライセンスキー無しの制限**（31.4.0〜）: 単一入力のタイムライン出力は制限なし。**メディア書き出しは 3200×1800 を超えると自動で縮小**される（開始前に警告を出す）。複数入力の結合は要キー（SnipSync は使わない）。
- 字幕用のカット後音声を、カット区間（v1 chunks）から**自前で組み立てる**ように変更。タイムラインと厳密に揃い、auto-editor による音声の再レンダリングが不要になる（書き出せなかったときだけ従来の auto-editor 抽出へ戻る）。
- 倍速モードのカット境界は、区間の長さを小数のまま累積してフレームへ丸める（31.7.2 の XML のクリップ位置と最大1フレーム以内で一致）。
- `pyproject.toml`: `av>=17,<18`（19 系は faster-whisper 1.2.1 の `decode_audio` が落ちる）、`numpy` / `budoux` / `sherpa-onnx` / `defusedxml` を追加。
- `ffprobe` が PATH に無くても fps を PyAV で取得する。**FFmpeg の PATH 設定は不要**。
- 設定画面を整理し、設定部分をスクロール可能にした。プリセットに新設定を保存する。
- 即時停止: 外部プロセス呼び出しを `subprocess.Popen` 化し、停止時にプロセスツリーを `taskkill /F /T` で即時 kill。ログをストリーミング表示。
- モノリス分割: `src/app.py` から各モジュールを分離（flat 配置）。
- バージョン表記を SemVer 2.0 の初期開発段階（MAJOR = 0）へ変更。

### Security
- XML（FCPXML / Premiere XML）の読み込みを `defusedxml` に変更し、DOCTYPE・外部エンティティを拒否（XXE / billion laughs 対策）。
- 外部ファイルの取得は https のみ。auto-editor と話者分離モデルは SHA-256 を照合し、不一致なら破棄。kotoba-whisper は Hugging Face のコミットを固定。
- Hugging Face のテレメトリを無効化（`HF_HUB_DISABLE_TELEMETRY`）。
- GitHub Actions: サードパーティのアクションをコミット SHA で固定、`persist-credentials: false`、リリースの書き込み権限を build ジョブだけに限定。
- 検査結果: pip-audit で既知の脆弱性 0 件、bandit は高 0・中 0（低 14 件は後始末の握りつぶしと、引数リスト形式の外部コマンド起動で意図どおり）、秘密情報の混入なし。

### Fixed
- **29.97fps / 59.94fps 動画のカット境界ずれ**: v1 export の `-tb` を整数へ丸めて（30 / 60）いたため、NLE の格子（30000/1001 等）と字幕のカット境界がずれていた。有理数のまま渡す。
- FCPXML の音声トラック整列（多トラック音声のトラック順が元動画のストリーム順と一致しないバグを、元のフラット構造を維持したまま、出現順を元のストリーム順へ整列するように再構成することで修正）。
- Whisper 音声認識の言語を自動判定化（`language=None` に変更）。
- **`.gitignore` の `build/` が `build/app.spec` とフックまで除外**しており、リポジトリに入っていなかった（リリース用ワークフローの `pyinstaller build/app.spec` が GitHub 上で失敗する状態だった）。生成物だけを除外し、spec とフックを追跡する。
- `build/app.spec` が `venv` のパスをハードコードしていたため、実行中のインタプリタの site-packages を使うよう変更（`.venv` / CI でもビルドできる）。

---

## [0.1.0] — 初回リリース（GitHub タグ `v1.0.0`）

- 無音自動カット（auto-editor）。
- NLE タイムライン出力（DaVinci Resolve / Final Cut Pro / Premiere Pro）。
- AI 字幕生成（faster-whisper、tiny/base/small/medium）。
- 日本語／英語 UI 切替、ドラッグ＆ドロップ、単一 `.exe` 配布。

[Unreleased]: https://github.com/R3NeR3N/SnipSync/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/R3NeR3N/SnipSync/compare/v1.0.0...v0.2.0
[0.1.0]: https://github.com/R3NeR3N/SnipSync/releases/tag/v1.0.0
