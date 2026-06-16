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
- NLE タイムライン出力（resolve / final-cut-pro / premiere）。
- AI 字幕生成（tiny / base / small / medium モデル選択）。
- 日本語／英語 UI 切替（実行中に随時）。
- ドラッグ＆ドロップ入力。

### 含まない (Out of Scope)
- 動画の再エンコード／レンダリング（タイムラインデータのみ出力、非破壊）。
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

- 実行には **FFmpeg が PATH に通っている**ことが前提（auto-editor が内部利用）。
- Whisper モデルは初回のみ Hugging Face から自動 DL → `C:\Users\<user>\.cache\huggingface\hub` にキャッシュ。
- モデルは大きい（数 GB）ためリポジトリにコミットしない（`.gitignore` で `*.bin` `*.pt` 除外）。
- 字幕生成は CPU + int8 固定（配布 EXE に巨大な GPU バイナリを同梱しないため）。

---

## 8. 関連ファイル

- 実装: `src/app.py`
- 構造詳細: ARCHITECTURE.md
- UI 指標: DESIGN.md
- 既知の課題・決定: MEMORY.md / PITFALLS.md
