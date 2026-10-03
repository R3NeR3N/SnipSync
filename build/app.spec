# -*- mode: python ; coding: utf-8 -*-
# SnipSync - PyInstaller Spec File
# --onefile モード: FFmpeg内蔵の auto-editor.exe と faster-whisper をバンドル
# 事前に `python scripts/fetch_auto_editor.py` で auto-editor を build/vendor/ へ取得しておく（SHA-256 検証つき）。

import sysconfig
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

# ── パス定義
WORK_DIR = Path(SPECPATH).parent.resolve()
# いま PyInstaller を動かしているインタプリタの site-packages を使う（.venv / venv / CI のどれでも動く）。
SITE     = Path(sysconfig.get_paths()['purelib'])
# auto-editor は PyPI の版が古い（29.3.1 止まり）ため、公式リリースを固定版で取得して同梱する。
AE_BIN   = WORK_DIR / 'build' / 'vendor' / 'auto-editor.exe'
CTK_DIR  = SITE / 'customtkinter'
DND_DIR  = SITE / 'tkinterdnd2'

if not AE_BIN.exists():
    raise SystemExit(f"auto-editor が見つかりません: {AE_BIN}\n先に `python scripts/fetch_auto_editor.py` を実行してください。")

# ── 依存関係の収集 (faster-whisper)
fw_datas, fw_binaries, fw_hiddenimports = collect_all('faster_whisper')
ct_datas, ct_binaries, ct_hiddenimports = collect_all('ctranslate2')
tk_datas, tk_binaries, tk_hiddenimports = collect_all('tokenizers')
av_datas, av_binaries, av_hiddenimports = collect_all('av')
tr_datas, tr_binaries, tr_hiddenimports = collect_all('transformers')
# 日本語字幕の文節改行（BudouX のモデル JSON）と話者分離（sherpa-onnx のネイティブ DLL）
bx_datas, bx_binaries, bx_hiddenimports = collect_all('budoux')
sh_datas, sh_binaries, sh_hiddenimports = collect_all('sherpa_onnx')

all_datas = [
    (str(CTK_DIR), 'customtkinter'),
    (str(DND_DIR), 'tkinterdnd2'),
] + fw_datas + ct_datas + tk_datas + av_datas + tr_datas + bx_datas + sh_datas

all_binaries = [
    (str(AE_BIN), '.'),
] + fw_binaries + ct_binaries + tk_binaries + av_binaries + tr_binaries + bx_binaries + sh_binaries

all_hiddenimports = [
    'customtkinter',
    'darkdetect',
    'tkinterdnd2',
    'packaging',
    'packaging.version',
    'packaging.specifiers',
    'packaging.requirements',
    'filelock',
    'fsspec',
    'huggingface_hub',
    'tqdm',
    'numpy',
    'vad', 'audiocut', 'diarize', 'models', 'markers', 'transcript', 'waveform', 'aebin',
] + (fw_hiddenimports + ct_hiddenimports + tk_hiddenimports + av_hiddenimports + tr_hiddenimports
      + bx_hiddenimports + sh_hiddenimports)

a = Analysis(
    [str(WORK_DIR / 'src' / 'app.py')],
    pathex=[str(WORK_DIR / 'src')],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=list(set(all_hiddenimports)), # 重複排除
    hookspath=[str(WORK_DIR / 'build' / 'build_hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SnipSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUIアプリなのでコンソール非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
