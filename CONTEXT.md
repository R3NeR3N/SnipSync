# CONTEXT.md — プロダクト文脈

> AI エージェントが「なぜこの機能が存在するか」を理解するための背景。仕様変更時に更新。

---

## 1. 何を解決するか

動画クリエイターの最も面倒な手作業 ——「無音部分の手動カット」と「字幕付け」—— を自動化する。

従来のワークフローの痛み:
- 編集ソフトで無音をひとつずつ探して削除 → 数時間。
- 字幕生成ツールを別途回すと、**カット前**の音声に対して文字起こしするため、編集後にタイムコードがズレる。

SnipSync の解法:
1. `auto-editor` で無音をカットし、NLE 取り込み用のタイムライン（XML/FCPXML）を出力。
2. 字幕は **カット済みの音声**に対して `faster-whisper` を実行 → `.srt` のタイムコードがタイムラインと**原理的に一致**する。

この「カット後音声に対して文字起こしする」点が本プロダクトの核心的価値。

---

## 2. ターゲットユーザー

- Windows を使うプロ／セミプロの動画クリエイター。
- DaVinci Resolve / Final Cut Pro / Premiere Pro のいずれかを使用。
- Python 環境を持たない層も対象 → **単一 `.exe` で配布**（環境構築不要が必須要件）。

---

## 3. 機能スコープ

### 含む (In Scope)
- 無音自動カット（音量閾値・前後マージン調整可）。
- NLE タイムライン出力（resolve / final-cut-pro / premiere）、またはカット済みメディア（動画／音声）の書き出し。
- 入力は動画に加え音声ファイルも可。複数ファイルのバッチ処理。
- カット方式: 音量しきい値 / 音声区間検出（VAD）。無音のカットまたは倍速化。
- 字幕: 日本語の文節改行、用語辞書、話者分離、`.txt` / `.md` 書き出し、プレビュー。
- タイムラインマーカー（カット点・話者交代・任意）。
- AI 字幕生成（tiny / base / small / medium モデル選択）。
- 日本語／英語 UI 切替（実行中に随時）。
- ドラッグ＆ドロップ入力。

### 含まない (Out of Scope)
- 動画編集そのもの（トランジション・テロップ装飾など）。既定はタイムラインのみ出力で非破壊。メディア書き出しは auto-editor のレンダリングを使うだけで、独自エンコードはしない。
- macOS / Linux 対応（現状 Windows のみ）。
- クラウド処理（完全ローカル。モデル DL 時のみ通信）。

---

## 4. 入出力仕様

| 区分 | 内容 |
|---|---|
| 入力動画 | `.mp4` `.mov` `.avi` `.mkv` `.wmv` `.flv` `.webm` `.m4v` |
| 出力(タイムライン) | `{stem}_snipsynced.fcpxml` または `.xml` |
| 出力(字幕) | `{stem}.srt` |
| 一時ファイル | `{stem}_temp_audio.wav`（字幕生成用、処理後に削除） |

| エクスポート形式 | 対象アプリ | 拡張子 |
|---|---|---|
| `resolve` | DaVinci Resolve | `.fcpxml` |
| `final-cut-pro` | Final Cut Pro | `.fcpxml` |
| `premiere` | Adobe Premiere Pro | `.xml` |

---

## 5. 主要パラメータ（デフォルト値）

| パラメータ | 既定 | 範囲 | 意味 |
|---|---|---|---|
| 無音マージン | `0.20s` | 0.0–2.0 | カット前後に残す余白 |
| 音量閾値 | `4.0%` | 0.0–100.0 | これ以下を無音とみなす |
| 字幕生成 | ON | — | `.srt` 同時生成 |
| AI モデル | `small` | tiny/base/small/medium | 速度↔精度トレードオフ |

---

## 6. 用語集 (Glossary)

| 用語 | 意味 |
|---|---|
| NLE | Non-Linear Editor。動画編集ソフト（Resolve / FCP / Premiere）。 |
| auto-editor | 無音検知・カット・NLE 用 XML 出力を行う外部 CLI エンジン。 |
| faster-whisper | OpenAI Whisper の高速実装（CTranslate2 バックエンド）。ASR に使用。 |
| ASR | Automatic Speech Recognition。音声→テキスト変換。 |
| SRT | SubRip 字幕形式。タイムコード付きテキスト。 |
| FCPXML | Final Cut Pro / Resolve が読むタイムライン XML。 |
| int8 | 量子化された推論精度。GPU 不要で軽量に Whisper を動かすため採用。 |

---

## 7. 制約・前提

- **FFmpeg の PATH 設定は不要**（auto-editor 同梱版が内蔵。fps は ffprobe が無ければ PyAV で取得。FFmpeg も ffprobe も無い PC で通し検証済み 2026-10）。
- Whisper モデルは初回のみ Hugging Face から自動 DL → `C:\Users\<user>\.cache\huggingface\hub` にキャッシュ。
- モデルは大きい（数 GB）ためリポジトリにコミットしない（`.gitignore` で `*.bin` `*.pt` 除外）。
- 字幕生成は既定で CPU + int8。GPU(CUDA) は任意（pip の `[gpu]`）。話者分離は sherpa-onnx（CPU）。
- 話者分離モデル（約35MB）は初回のみ公式 GitHub リリースから `%APPDATA%/SnipSync/models/diarization` へ取得（SHA-256 検証）。
- **auto-editor は 31.7.2 の公式バイナリを固定**（`aebin.AE_VERSION`、SHA-256 照合）。PyPI の版は 29.3.1 で止まっている。ライセンスキー無しでは、**メディア書き出しが 3200×1800 を超えると自動で縮小**される（NLE 用タイムライン出力は無制限）。複数入力の結合は要キーなので使わない。

---

## 8. 関連ファイル

- 実装: `src/`（`app.py` UI / `pipeline.py` 処理 / `autoeditor.py` / `subtitles.py` / `vad.py` / `audiocut.py` / `diarize.py` / `markers.py` / `transcript.py` / `models.py` / `waveform.py`）
- 構造詳細: ARCHITECTURE.md
- UI 指標: DESIGN.md
- 既知の課題・決定: MEMORY.md / PITFALLS.md
