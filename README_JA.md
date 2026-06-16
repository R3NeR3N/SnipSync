<div align="center">

<h1>✂ SnipSync</h1>
<p><strong>プロの動画クリエイター向け 無音自動カット＆字幕生成ツール</strong></p>

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-6C63FF?style=for-the-badge)](https://github.com/TomSchimansky/CustomTkinter)
[![faster-whisper](https://img.shields.io/badge/AI-faster--whisper-00A67E?style=for-the-badge)](https://github.com/SYSTRAN/faster-whisper)
[![auto-editor](https://img.shields.io/badge/Engine-auto--editor-FF6B6B?style=for-the-badge)](https://github.com/WyattBlue/auto-editor)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Version](https://img.shields.io/badge/Version-v1.0.0-success?style=for-the-badge)](https://github.com/R3NeR3N/SnipSync/releases/latest)

[English](README.md) | [日本語](README_JA.md) | [简体中文](README_ZH.md) | [한국어](README_KO.md)

</div>

---

## SnipSyncについて

**SnipSync** は、動画編集の最も面倒な作業を自動化するWindows向けのスタンドアロン・デスクトップアプリケーションです。動画ファイルをドロップするだけで、SnipSyncが以下の処理を全自動で行います。

1. **無音部分を自動検知・除去** — `auto-editor` を使用し、設定可能な音量閾値で無音区間を検出します。
2. **そのままインポートできるタイムラインデータを出力** — レンダリング不要で、選択した形式（.fcpxml / .xml）を書き出します。
3. **完全同期された字幕ファイル（.srt）を自動生成** — 内蔵AIエンジン `faster-whisper` が高精度な字幕を出力します。

字幕パイプラインは「カット済みの音声」に対してWhisperを実行するため、`.srt` のタイムコードがタイムラインと完全に同期します。他ツールでよく問題になるタイムコードのズレが原理的に発生しません。

Pythonのインストール不要。SnipSyncは単一の `.exe` ファイルとして動作します。

---

## ✨ 主な特徴

| 機能 | 詳細 |
|---|---|
| 🔇 **無音自動カット** | あらゆる動画ファイルの無音部分を自動検知・除去 |
| 🎬 **NLEタイムライン出力** | DaVinci Resolve / Final Cut Pro / Premiere Pro向けのタイムラインを即時出力 |
| 📝 **AI字幕自動生成** | `faster-whisper` で `.srt` を生成 — タイムコードのズレはゼロ |
| ⚙️ **詳細な設定** | 音量閾値（%）と無音マージン（秒）を細かく調整可能 |
| 🤖 **AIモデルサイズ選択** | `tiny` / `base` / `small` / `medium` から用途に応じて選択 |
| 🌐 **多言語対応UI** | 実行中にいつでも日本語・英語を切り替え可能 |
| 📁 **ドラッグ＆ドロップ** | 動画ファイルをウィンドウにドロップするだけで選択完了 |
| 📦 **環境構築不要** | 単一の `.exe` で動作 — Python不要、依存関係のインストール不要 |

### 対応エクスポート形式

| 形式 | 対象アプリケーション | 拡張子 |
|---|---|---|
| `resolve` | DaVinci Resolve | `.fcpxml` |
| `final-cut-pro` | Final Cut Pro | `.fcpxml` |
| `premiere` | Adobe Premiere Pro | `.xml` |

### 対応入力形式

`.mp4` · `.mov` · `.avi` · `.mkv` · `.wmv` · `.flv` · `.webm` · `.m4v`

---

## 🚀 インストール・実行方法

### 方法A: ビルド済みEXEを実行する（推奨）

> Pythonやその他のソフトウェアは一切不要です。

1. [Releases](https://github.com/R3NeR3N/SnipSync/releases/latest) ページから `SnipSync.exe` をダウンロードします。
2. PC上の任意の場所（例: デスクトップ）に配置します。
3. `SnipSync.exe` をダブルクリックして起動します。

**初回起動時のWhisperモデルダウンロードについて:**
字幕生成を初めて有効にした際、選択したAIモデルがHugging Faceから自動的にダウンロードされます。この手順にはインターネット接続が必要です。モデルはローカルにキャッシュされるため、次回以降はオフラインで利用可能です。

> **💡 キャッシュの保存先と削除について**
> モデルデータはアプリ本体の場所ではなく、以下のシステムフォルダに保存されます：
> `C:\Users\<ユーザー名>\.cache\huggingface\hub`
> 
> 今後SnipSyncを使用しなくなった場合、アプリの `.exe` を削除しただけではこのモデルデータは残り続けます。数GBのストレージ容量を解放したい場合は、上記フォルダを手動で削除してください（削除してもPCの動作に影響はありません）。

---

### 方法B: Pythonソースから実行する（開発者向け）

#### 前提条件

- Python **3.10以降**
- [FFmpeg](https://ffmpeg.org/download.html) がインストールされ、環境変数 `PATH` に通っていること

#### Step 1 — リポジトリをクローン

```bash
git clone https://github.com/R3NeR3N/SnipSync.git
cd SnipSync
```

#### Step 2 — 仮想環境を作成・有効化

```bash
python -m venv venv
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# Windows (コマンドプロンプト)
venv\Scripts\activate.bat
```

#### Step 3 — 依存ライブラリをインストール

```bash
pip install auto-editor faster-whisper customtkinter tkinterdnd2
```

#### Step 4 — アプリを起動

```bash
python src/app.py
```

---

### 方法C: EXEを自分でビルドする（PyInstaller）

#### Step 1 — ビルド用依存ライブラリをインストール

```bash
pip install pyinstaller
```

#### Step 2 — ビルド実行

```bash
pyinstaller build/app.spec
```

ビルドが成功すると、`dist\SnipSync.exe` にスタンドアロンの実行ファイルが生成されます。

---

## ⚙️ 使用方法

1. `SnipSync.exe` を**起動**します（またはPython環境では `python app.py`）。
2. 動画ファイルをドロップゾーンに**ドラッグ＆ドロップ**するか、クリックしてファイルを選択します。
3. 各**設定**を調整します。
   - **無音マージン（秒）** — カット前後に残す余白時間（デフォルト: `0.20 秒`）
   - **音量閾値（%）** — この値以下の音量を無音とみなす基準値（デフォルト: `4.0%`）
   - **出力形式** — 使用するNLE（DaVinci Resolve / Final Cut Pro / Premiere Pro）を選択
   - **字幕自動生成** — `.srt` ファイルのAI生成をON/OFFで切り替え
   - **AIモデル精度** — 速度と精度のバランスを選択（`tiny` → `medium`）
4. **`▶ 処理を開始する`** をクリックします。
5. 処理完了後、出力フォルダを開くか確認するダイアログが表示されます。`_snipsynced.fcpxml`（または `.xml`）と `.srt` ファイルが生成されています。

---

## 🖥️ 動作環境・依存ライブラリ

### EXEをご利用の方（実行環境）
- **OS:** Windows 10 / 11（64ビット）
- **メモリ:** 最低4GB、`medium` モデル使用時は8GB以上を推奨
- **ストレージ:** Whisperモデルのキャッシュ用に2〜4GBの空き容量（初回起動時のみ）
- **インターネット:** Whisperモデルのダウンロード時（初回のみ）に必要

### ソースコードから実行する方（開発環境）

| パッケージ | 用途 |
|---|---|
| `auto-editor` | 無音検知・カット処理・NLE向けXMLエクスポートエンジン |
| `faster-whisper` | AI音声テキスト変換（CTranslate2バックエンド） |
| `customtkinter` | モダンなダークテーマGUIフレームワーク |
| `tkinterdnd2` | ファイルのドラッグ＆ドロップサポート |
| `pyinstaller` | *（ビルド時のみ）* アプリを単一の `.exe` にパッケージング |

---

## 📜 ライセンス

本プロジェクトは **MIT License** の下で公開されています。

> **免責事項:** SnipSyncは「現状のまま（as-is）」で提供されます。本ソフトウェアの使用によって生じたデータの損失、ファイルの破損、その他いかなる損害についても、作者は一切の責任を負いません。必ず元のソース映像のバックアップを保管した上でご使用ください。

> SnipSyncは内部で [auto-editor](https://github.com/WyattBlue/auto-editor)（MITライセンス）および [faster-whisper](https://github.com/SYSTRAN/faster-whisper)（MITライセンス）を使用しています。各プロジェクトのライセンスについては、それぞれの公式ページをご確認ください。

---

<div align="center">

Made with ❤️ for video creators who hate silence.

</div>
