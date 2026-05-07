<div align="center">

<h1>✂ SnipSync</h1>
<p><strong>Silent Auto-Cutter & Subtitle Generator for Professional Video Editors</strong></p>

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-6C63FF?style=for-the-badge)](https://github.com/TomSchimansky/CustomTkinter)
[![faster-whisper](https://img.shields.io/badge/AI-faster--whisper-00A67E?style=for-the-badge)](https://github.com/SYSTRAN/faster-whisper)
[![auto-editor](https://img.shields.io/badge/Engine-auto--editor-FF6B6B?style=for-the-badge)](https://github.com/WyattBlue/auto-editor)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Version](https://img.shields.io/badge/Version-v1.3.1-success?style=for-the-badge)](https://github.com/)

[English](README.md) | [日本語](README_JA.md) | [简体中文](README_ZH.md) | [한국어](README_KO.md)

</div>

---

## About SnipSync

**SnipSync** is a standalone desktop application for Windows that automates the most tedious parts of video editing. Drop in your footage, and SnipSync will:

1. **Detect and remove silent segments** using a configurable audio threshold — powered by `auto-editor`.
2. **Export a ready-to-import timeline** in the format of your choice (.fcpxml or .xml) — no rendering required.
3. **Generate a perfectly-synced subtitle file** (.srt) using the built-in AI transcription engine `faster-whisper`.

Because the subtitle pipeline runs transcription on the *already-cut* audio (not the raw source), timecodes in the `.srt` file are always in perfect sync with the exported timeline — a problem that plagues most other tools.

No Python installation required. SnipSync ships as a single `.exe` file.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔇 **Auto Silent Cut** | Automatically detects and removes silent portions from any video |
| 🎬 **NLE Timeline Export** | Exports cut-ready timelines for DaVinci Resolve, Final Cut Pro, and Premiere Pro |
| 📝 **AI Subtitle Generation** | Generates `.srt` files with `faster-whisper` — no timecode drift |
| ⚙️ **Fine-grained Controls** | Adjustable volume threshold (%) and silence margin (seconds) |
| 🤖 **Model Size Selection** | Choose from `tiny` / `base` / `small` / `medium` Whisper models |
| 🌐 **Multilingual UI** | Full Japanese / English interface switchable at runtime |
| 📁 **Drag & Drop** | Simply drag your video file onto the app window |
| 📦 **Zero Setup** | Ships as a single `.exe` — no Python, no dependencies to install |

### Supported Export Formats

| Format | Target Application | File Extension |
|---|---|---|
| `resolve` | DaVinci Resolve | `.fcpxml` |
| `final-cut-pro` | Final Cut Pro | `.fcpxml` |
| `premiere` | Adobe Premiere Pro | `.xml` |

### Supported Input Formats

`.mp4` · `.mov` · `.avi` · `.mkv` · `.wmv` · `.flv` · `.webm` · `.m4v`

---

## 🚀 Installation / Usage

### Option A: Run the Pre-built EXE (Recommended)

> No Python or any other software needed.

1. Download `SnipSync.exe` from the [Releases](https://github.com/) page.
2. Place it anywhere on your PC (e.g., your Desktop).
3. Double-click `SnipSync.exe` to launch.

**First-time Whisper model download:**
When you first enable subtitle generation, the selected AI model will be downloaded automatically from Hugging Face. Ensure you have an internet connection for this step. The model is cached locally for all subsequent uses.

> **💡 Model Cache Location & Removal**
> The downloaded models are NOT stored next to the `.exe` file. Instead, they are cached in your system's user directory:
> `C:\Users\<YourUsername>\.cache\huggingface\hub`
>
> If you decide to uninstall or stop using SnipSync, deleting the `.exe` file will not remove these models. To free up disk space (models can be several GBs), you can safely delete that folder manually.

---

### Option B: Run from Source (Python Environment)

#### Prerequisites

- Python **3.10 or later**
- [FFmpeg](https://ffmpeg.org/download.html) installed and accessible from your `PATH`

#### Step 1 — Clone the repository

```bash
git clone https://github.com/your-username/SnipSync.git
cd SnipSync
```

#### Step 2 — Create and activate a virtual environment

```bash
python -m venv venv
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# Windows (Command Prompt)
venv\Scripts\activate.bat
```

#### Step 3 — Install dependencies

```bash
pip install auto-editor faster-whisper customtkinter tkinterdnd2
```

#### Step 4 — Run the application

```bash
python app.py
```

---

### Option C: Build the EXE yourself (PyInstaller)

#### Step 1 — Install build dependencies

```bash
pip install pyinstaller
```

#### Step 2 — Edit `app.spec`

Open `app.spec` and update the `WORK_DIR` path to match your local project directory:

```python
WORK_DIR = Path(r'C:\path\to\your\SnipSync')
```

#### Step 3 — Build

```bash
pyinstaller app.spec
```

The standalone executable will be output to `dist\SnipSync.exe`.

---

## ⚙️ How to Use

1. **Launch** `SnipSync.exe` (or run `python app.py`).
2. **Drop** your video file into the drop zone, or click to browse.
3. **Configure** your settings:
   - **Silence Margin** — Extra buffer kept around each cut point (default: `0.20 sec`)
   - **Volume Threshold** — Audio level below which a segment is considered silent (default: `4.0%`)
   - **Export Format** — Choose your NLE (DaVinci Resolve, Final Cut Pro, or Premiere Pro)
   - **Generate .srt** — Toggle AI subtitle generation on/off
   - **AI Model Size** — Balance between speed and accuracy (`tiny` → `medium`)
4. **Click** `▶ Start Processing`.
5. When done, the app will prompt you to open the output folder. Your `_snipsynced.fcpxml` (or `.xml`) and `.srt` files will be ready to import.

---

## 🖥️ Requirements

### Runtime (EXE users)
- **OS:** Windows 10 / 11 (64-bit)
- **RAM:** 4 GB minimum; 8 GB+ recommended for `medium` model
- **Disk:** ~2–4 GB free space for Whisper model cache (first run only)
- **Internet:** Required only on first run to download the selected Whisper model

### Development (Source users)

| Package | Purpose |
|---|---|
| `auto-editor` | Silent cut detection & NLE XML export engine |
| `faster-whisper` | AI speech-to-text transcription (CTranslate2 backend) |
| `customtkinter` | Modern dark-theme GUI framework |
| `tkinterdnd2` | Drag-and-drop support for the file drop zone |
| `pyinstaller` | *(Build only)* Packages the app into a single `.exe` |

---

## 📜 License

This project is licensed under the **MIT License**.

> **Disclaimer:** SnipSync is provided "as-is" without any warranty. The author is not responsible for any data loss, file corruption, or other issues arising from the use of this software. Always keep backups of your original source footage.

> SnipSync internally uses [auto-editor](https://github.com/WyattBlue/auto-editor) (MIT) and [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT). Please refer to each project for their respective licenses.

---

<div align="center">

Made with ❤️ for video creators who hate silence.

</div>
