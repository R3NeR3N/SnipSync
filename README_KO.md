<div align="center">

<h1>✂ SnipSync</h1>
<p><strong>전문 비디오 편집자를 위한 무음 자동 컷 편집 및 자막 생성 도구</strong></p>

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

## SnipSync 소개

**SnipSync**는 비디오 편집에서 가장 번거로운 작업을 자동화하는 Windows용 독립 실행형 데스크톱 애플리케이션입니다. 비디오 파일을 드래그 앤 드롭하기만 하면 SnipSync가 다음을 수행합니다:

1. **무음 구간 자동 감지 및 제거** — `auto-editor`로 구동되며, 설정 가능한 오디오 임계값을 사용합니다.
2. **바로 가져올 수 있는 타임라인 내보내기** — 렌더링 없이 선택한 형식(.fcpxml 또는 .xml)으로 내보냅니다.
3. **완벽하게 동기화된 자막 파일(.srt) 생성** — 내장된 AI 음성 인식 엔진 `faster-whisper`를 사용합니다.

자막 생성 파이프라인은 원본 소스가 아닌 **이미 컷 편집된** 오디오에 대해 음성 인식을 실행하므로, `.srt` 파일의 타임코드가 내보낸 타임라인과 항상 완벽하게 동기화됩니다. 타 도구에서 발생하는 오디오와 자막의 싱크 어긋남 문제를 근본적으로 해결했습니다.

Python을 설치할 필요가 없습니다. SnipSync는 단일 `.exe` 파일로 실행됩니다.

---

## ✨ 주요 기능

| 기능 | 세부 정보 |
|---|---|
| 🔇 **무음 자동 컷 편집** | 모든 비디오에서 무음 구간을 자동으로 감지하고 제거합니다. |
| 🎬 **NLE 타임라인 내보내기** | DaVinci Resolve, Final Cut Pro 및 Premiere 파이널 컷용 타임라인을 내보냅니다. |
| 📝 **AI 자막 생성** | `faster-whisper`를 통해 타임코드 어긋남 없는 `.srt` 파일을 생성합니다. |
| ⚙️ **세밀한 설정 제어** | 오디오 임계값(%)과 무음 여백(초)을 세밀하게 조정할 수 있습니다. |
| 🤖 **AI 모델 크기 선택** | 용도에 맞게 `tiny` / `base` / `small` / `medium` 모델 중 선택할 수 있습니다. |
| 🌐 **다국어 UI 지원** | 런타임에 영어 / 일본어 인터페이스를 전환할 수 있습니다. |
| 📁 **드래그 앤 드롭** | 비디오 파일을 앱 창에 끌어다 놓기만 하면 됩니다. |
| 📦 **제로 설정** | 단일 `.exe` 파일로 실행되며, Python이나 종속성을 설치할 필요가 없습니다. |

### 지원하는 내보내기 형식

| 형식 | 대상 애플리케이션 | 파일 확장자 |
|---|---|---|
| `resolve` | DaVinci Resolve | `.fcpxml` |
| `final-cut-pro` | Final Cut Pro | `.fcpxml` |
| `premiere` | Adobe Premiere Pro | `.xml` |

### 지원하는 입력 형식

`.mp4` · `.mov` · `.avi` · `.mkv` · `.wmv` · `.flv` · `.webm` · `.m4v`

---

## 🚀 설치 및 사용 방법

### 옵션 A: 빌드된 EXE 실행 (권장)

> Python이나 다른 소프트웨어가 필요하지 않습니다.

1. [Releases](https://github.com/R3NeR3N/SnipSync/releases/latest) 페이지에서 `SnipSync.exe`를 다운로드합니다.
2. PC의 원하는 위치(예: 바탕화면)에 배치합니다.
3. `SnipSync.exe`를 더블 클릭하여 실행합니다.

**첫 실행 시 Whisper 모델 다운로드:**
자막 생성을 처음 활성화하면 선택한 AI 모델이 Hugging Face에서 자동으로 다운로드됩니다. 이 단계에서는 인터넷 연결이 필요합니다. 모델은 이후 오프라인에서 사용할 수 있도록 로컬에 캐시됩니다.

> **💡 모델 캐시 저장 위치 및 삭제 방법**
> 다운로드된 모델은 앱(`.exe`)과 같은 위치가 아닌 시스템 사용자 폴더에 저장됩니다:
> `C:\Users\<사용자이름>\.cache\huggingface\hub`
>
> 향후 SnipSync 사용을 중단할 경우, `.exe` 파일을 삭제하더라도 이 모델 데이터는 남아 있습니다. 저장 공간(최대 수 GB)을 확보하려면 해당 폴더를 수동으로 삭제해야 합니다(삭제해도 PC에 악영향을 주지 않습니다).

---

### 옵션 B: 소스에서 실행 (개발자용)

#### 사전 요구 사항

- Python **3.10 이상**
- [FFmpeg](https://ffmpeg.org/download.html)이 설치되어 있고 환경 변수 `PATH`에 추가되어 있어야 합니다.

#### 1단계 — 저장소 클론

```bash
git clone https://github.com/R3NeR3N/SnipSync.git
cd SnipSync
```

#### 2단계 — 가상 환경 생성 및 활성화

```bash
python -m venv venv
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# Windows (명령 프롬프트)
venv\Scripts\activate.bat
```

#### 3단계 — 종속성 설치

```bash
pip install auto-editor faster-whisper customtkinter tkinterdnd2
```

#### 4단계 — 애플리케이션 실행

```bash
python app.py
```

---

### 옵션 C: 직접 EXE 빌드하기 (PyInstaller)

#### 1단계 — 빌드 종속성 설치

```bash
pip install pyinstaller
```

#### 2단계 — `app.spec` 편집

`app.spec`을 열고 로컬 프로젝트 디렉터리와 일치하도록 `WORK_DIR` 경로를 업데이트합니다:

```python
WORK_DIR = Path(r'C:\path\to\your\SnipSync')
```

#### 3단계 — 빌드 실행

```bash
pyinstaller app.spec
```

빌드가 완료되면 단일 실행 파일이 `dist\SnipSync.exe`에 생성됩니다.

---

## ⚙️ 사용 가이드

1. `SnipSync.exe`를 **실행**합니다(또는 `python app.py`를 실행합니다).
2. 비디오 파일을 드롭 존으로 **드래그 앤 드롭**하거나 클릭하여 탐색합니다.
3. 설정을 **구성**합니다:
   - **무음 여백 (Silence Margin)** — 각 컷 지점 주위에 유지할 추가 버퍼 (기본값: `0.20 초`)
   - **음량 임계값 (Volume Threshold)** — 무음으로 간주될 기준 오디오 레벨 (기본값: `4.0%`)
   - **내보내기 형식 (Export Format)** — 사용 중인 NLE(DaVinci Resolve, Final Cut Pro 또는 Premiere Pro)를 선택합니다.
   - **자막 생성 (Generate .srt)** — AI 자막 생성을 켜거나 끕니다.
   - **AI 모델 크기 (AI Model Size)** — 속도와 정확도의 균형을 선택합니다 (`tiny` → `medium`).
4. **`▶ 처리 시작 (Start Processing)`**을 클릭합니다.
5. 처리가 완료되면 출력 폴더를 열 것인지 묻는 창이 표시됩니다. `_snipsynced.fcpxml`(또는 `.xml`)과 `.srt` 파일을 즉시 편집기에 가져올 수 있습니다.

---

## 🖥️ 시스템 요구 사항

### 런타임 (EXE 사용자)
- **OS:** Windows 10 / 11 (64비트)
- **RAM:** 최소 4GB, `medium` 모델 사용 시 8GB 이상 권장
- **디스크 여유 공간:** Whisper 모델 캐시를 위해 2~4GB의 여유 공간 필요(첫 실행 시에만 해당)
- **인터넷:** 선택한 Whisper 모델을 다운로드하기 위한 첫 실행 시에만 필요

### 개발 환경 (소스 사용자)

| 패키지 | 목적 |
|---|---|
| `auto-editor` | 무음 감지 및 컷 편집, NLE XML 내보내기 엔진 |
| `faster-whisper` | AI 음성 텍스트 변환 (CTranslate2 백엔드) |
| `customtkinter` | 최신 다크 테마 GUI 프레임워크 |
| `tkinterdnd2` | 파일 드래그 앤 드롭 지원 |
| `pyinstaller` | *(빌드용)* 앱을 단일 `.exe`로 패키징 |

---

## 📜 라이선스 (License)

이 프로젝트는 **MIT License** 조건에 따라 라이선스가 부여됩니다.

> **면책 조항:** SnipSync는 어떠한 보증도 없이 "있는 그대로(as-is)" 제공됩니다. 작성자는 이 소프트웨어의 사용으로 인해 발생하는 데이터 손실, 파일 손상 또는 기타 문제에 대해 책임을 지지 않습니다. 항상 원본 소스 영상의 백업을 보관하시기 바랍니다.

> SnipSync는 내부적으로 [auto-editor](https://github.com/WyattBlue/auto-editor) (MIT 라이선스) 및 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT 라이선스)를 사용합니다. 각 라이선스에 대한 자세한 내용은 해당 프로젝트를 참조하십시오.

---

<div align="center">

Made with ❤️ for video creators who hate silence.

</div>
