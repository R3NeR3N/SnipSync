<div align="center">

<h1>✂ SnipSync</h1>
<p><strong>为专业视频剪辑师打造的静音自动剪辑与字幕生成工具</strong></p>

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

## 关于 SnipSync

**SnipSync** 是一款适用于 Windows 的独立桌面应用程序，旨在自动处理视频剪辑中最繁琐的部分。只需将素材拖入，SnipSync 将：

1. **自动检测并移除静音片段** — 使用可配置的音频阈值，由 `auto-editor` 驱动。
2. **导出可直接导入的实时时间线** — 以您选择的格式（.fcpxml 或 .xml）导出，无需渲染。
3. **生成完美同步的字幕文件 (.srt)** — 使用内置的 AI 转录引擎 `faster-whisper`。

由于字幕管道是在**已剪辑**的音频（而不是原始素材）上运行转录，因此 `.srt` 文件中的时间码始终与导出的时间线完美同步，这彻底解决了困扰大多数同类工具的音画不同步问题。

无需安装 Python 环境。SnipSync 作为单个 `.exe` 文件发布，开箱即用。

---

## ✨ 主要特性

| 特性 | 详情 |
|---|---|
| 🔇 **自动静音剪辑** | 自动检测并移除任何视频中的无音部分 |
| 🎬 **NLE 时间线导出** | 导出适用于 DaVinci Resolve, Final Cut Pro, 以及 Premiere Pro 的时间线 |
| 📝 **AI 字幕生成** | 使用 `faster-whisper` 生成 `.srt` 文件 — 时间码零偏移 |
| ⚙️ **精细控制** | 支持调节音量阈值 (%) 和静音边距 (秒) |
| 🤖 **AI 模型选择** | 提供 `tiny` / `base` / `small` / `medium` 多种 Whisper 模型以供选择 |
| 🌐 **多语言 UI** | 运行时支持英语、日语界面的自由切换 |
| 📁 **拖放支持** | 只需将视频文件拖到应用程序窗口中即可 |
| 📦 **零配置** | 单个 `.exe` 文件发布 — 免安装 Python 及任何依赖包 |

### 支持的导出格式

| 格式 | 目标应用程序 | 文件扩展名 |
|---|---|---|
| `resolve` | DaVinci Resolve | `.fcpxml` |
| `final-cut-pro` | Final Cut Pro | `.fcpxml` |
| `premiere` | Adobe Premiere Pro | `.xml` |

### 支持的输入格式

`.mp4` · `.mov` · `.avi` · `.mkv` · `.wmv` · `.flv` · `.webm` · `.m4v`

---

## 🚀 安装与使用

### 方法 A: 运行预编译的 EXE（推荐）

> 无需 Python 或任何其他软件。

1. 从 [Releases](https://github.com/R3NeR3N/SnipSync/releases/latest) 页面下载 `SnipSync.exe`。
2. 将其放置在您电脑上的任何位置（例如，桌面）。
3. 双击 `SnipSync.exe` 启动。

**首次使用时的 Whisper 模型下载：**
当您首次启用字幕生成功能时，所选的 AI 模型将自动从 Hugging Face 下载。请确保您在此时连接了互联网。模型将在本地缓存，供后续离线使用。

> **💡 模型缓存位置与卸载清理**
> 下载的模型数据不会保存在 `.exe` 文件所在位置，而是缓存在系统的用户目录中：
> `C:\Users\<您的用户名>\.cache\huggingface\hub`
>
> 如果您将来不再使用 SnipSync，仅删除 `.exe` 文件不会清理这些模型数据。为释放磁盘空间（模型可能占用数 GB），您可以安全地手动删除该文件夹。

---

### 方法 B: 从源码运行（开发环境）

#### 前置要求

- Python **3.10 或更高版本**
- 已安装 [FFmpeg](https://ffmpeg.org/download.html) 并将其添加至环境变量 `PATH`

#### 步骤 1 — 克隆仓库

```bash
git clone https://github.com/R3NeR3N/SnipSync.git
cd SnipSync
```

#### 步骤 2 — 创建并激活虚拟环境

```bash
python -m venv venv
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# Windows (命令提示符)
venv\Scripts\activate.bat
```

#### 步骤 3 — 安装依赖

```bash
pip install auto-editor faster-whisper customtkinter tkinterdnd2
```

#### 步骤 4 — 运行应用

```bash
python app.py
```

---

### 方法 C: 自行打包 EXE (PyInstaller)

#### 步骤 1 — 安装打包依赖

```bash
pip install pyinstaller
```

#### 步骤 2 — 编辑 `app.spec`

打开 `app.spec` 并更新 `WORK_DIR` 路径以匹配您的本地项目目录：

```python
WORK_DIR = Path(r'C:\path\to\your\SnipSync')
```

#### 步骤 3 — 执行构建

```bash
pyinstaller app.spec
```

生成的独立可执行文件将保存在 `dist\SnipSync.exe`。

---

## ⚙️ 使用指南

1. **启动** `SnipSync.exe`（或运行 `python app.py`）。
2. **拖放** 您的视频文件到放置区，或点击浏览文件。
3. **配置** 您的设置：
   - **静音边距 (Silence Margin)** — 在每个剪辑点周围保留的额外缓冲时间（默认：`0.20 秒`）
   - **音量阈值 (Volume Threshold)** — 音量低于该值将被视为静音（默认：`4.0%`）
   - **导出格式 (Export Format)** — 选择您的剪辑软件（DaVinci Resolve, Final Cut Pro, 或 Premiere Pro）
   - **生成字幕 (Generate .srt)** — 开启/关闭 AI 字幕生成
   - **AI 模型大小 (AI Model Size)** — 在处理速度与准确率之间取得平衡（`tiny` → `medium`）
4. **点击** `▶ 开始处理 (Start Processing)`。
5. 处理完成后，应用会提示您打开输出文件夹。您的 `_snipsynced.fcpxml`（或 `.xml`）以及 `.srt` 文件将准备就绪，可直接导入。

---

## 🖥️ 系统要求

### 运行环境（EXE 用户）
- **操作系统:** Windows 10 / 11 (64-bit)
- **内存 (RAM):** 最低 4 GB；如果使用 `medium` 模型，推荐 8 GB 以上
- **磁盘空间:** 首次运行需预留 2–4 GB 空间用于缓存 Whisper 模型
- **网络连接:** 仅首次运行下载 Whisper 模型时需要

### 开发环境（源码用户）

| 包名 | 用途 |
|---|---|
| `auto-editor` | 静音检测剪辑与 NLE XML 导出引擎 |
| `faster-whisper` | AI 语音转文本 (基于 CTranslate2 后端) |
| `customtkinter` | 现代深色主题 GUI 框架 |
| `tkinterdnd2` | 提供拖放文件的支持 |
| `pyinstaller` | *(仅打包)* 将应用打包为单一的 `.exe` |

---

## 📜 开源协议 (License)

本项目基于 **MIT License** 许可协议开源。

> **免责声明：** SnipSync 按“原样”提供，没有任何保证。对于因使用本软件而导致的任何数据丢失、文件损坏或其他问题，作者概不负责。请务必保留原始素材的备份。

> SnipSync 内部使用了 [auto-editor](https://github.com/WyattBlue/auto-editor) (MIT) 和 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT)。有关它们各自的许可协议，请参阅各个项目的官方主页。

---

<div align="center">

Made with ❤️ for video creators who hate silence.

</div>
