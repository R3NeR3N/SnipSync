# ARCHITECTURE.md — 構造と処理フロー

> ディレクトリ構造と、処理パイプラインを定義する。
> 構造を変えたら必ず更新。

---

## 1. ディレクトリ構造

```
SnipSync/
├── src/
│   └── snipsync/                 # パッケージ（`python -m snipsync` で起動）
│       ├── __init__.py           # __version__（version.APP_VERSION から）
│       ├── __main__.py           # 入口（PyInstaller の起動スクリプトも、これ）
│       ├── version.py            # APP_VERSION（バージョンの唯一の定義）
│       ├── i18n.py / i18n_tips.py  # 文言の辞書（ja / en）と、簡易ヘルプの文言
│       ├── presets.py            # 設定の保存・呼び出し
│       ├── assets/               # 同梱フォント（BIZ UD ゴシック, SIL OFL）・アイコン（.ico / .png。scripts/make_icon.py で生成）
│       ├── core/                 # 画面に依存しない処理（ui を import しない）
│       │   ├── pipeline.py       # 処理全体のオーケストレーション（run_pipeline）
│       │   ├── aebin.py          # auto-editor 31.x バイナリの取得・SHA-256 検証・同梱版の解決
│       │   ├── autoeditor.py     # auto-editor コマンド組み立て / fps・長さ・解像度の取得（PyAV 代替あり）
│       │   ├── subtitles.py      # 字幕: 境界計算・文節改行・話者付与・時刻補正・Cue/SRT
│       │   ├── subtitle_edit.py  # 字幕の編集ロジック（CueEditor・書き出し文字列の生成）
│       │   ├── transcript.py     # .txt / .md 生成・SRT 読み込み
│       │   ├── vad.py            # 音声読み込み（全トラック加算）・VAD・v1 chunks 生成
│       │   ├── audiocut.py       # chunks から字幕用のカット後音声を自前で組み立てる
│       │   ├── diarize.py        # 話者分離（sherpa-onnx・モデル取得と SHA-256 検証）
│       │   ├── models.py         # Whisper モデル登録（kotoba の alignment_heads 補正を含む）
│       │   ├── markers.py        # マーカー（FCPXML / xmeml へ挿入。Resolve 向けは .edl に書く）
│       │   ├── safexml.py        # XML を defusedxml で読む（DOCTYPE・エンティティを拒否）
│       │   ├── waveform.py       # 波形ピーク・カット統計（描画は ui/widgets.CutMap）
│       │   ├── preview.py        # カットマップ用の計算（auto-editor の区間を取得）
│       │   ├── player.py         # 編集後の音の再生（EditedAudio・倍速変換・Player）
│       │   └── cudalibs.py       # GPU 用の NVIDIA ライブラリ（cuBLAS・cuDNN）の取得（版・SHA-256 固定）
│       └── ui/                   # 画面（core を使う）
│           ├── app.py            # メインウィンドウ（モニター・設定タブ・実行・ログ）+ バッチ実行
│           ├── subtitle_editor.py  # 字幕の確認・編集ウィンドウ（表 + 編集欄 + txt/md/srt タブ）
│           ├── widgets.py        # 部品（Btn / Choice / CutMap / Legend ほか）。色・書体は theme から
│           └── theme.py          # デザイントークン（色・書体・角丸・間隔。理由は DESIGN.md）
├── tests/                  # pytest（subprocess / transcribe はモック）
├── build/app.spec          # PyInstaller（budoux / sherpa_onnx を collect_all、auto-editor は build/vendor、フォントは src/snipsync/assets から同梱）
├── scripts/fetch_auto_editor.py  # 同梱用の auto-editor を取得（SHA-256 検証）
├── scripts/make_icon.py    # アプリアイコンの生成（Pillow。実行時は不要）
├── pyproject.toml          # 直接依存の単一ソース
└── requirements.txt        # 再現用フルフリーズ
```

### 残っている課題
1. auto-editor は 31.7.2 に固定（`aebin.AE_VERSION`）。ライセンスキー無しではレンダリングが 3200×1800 に縮小される（タイムライン出力は無制限）。版を上げるときは SHA-256・フラグ・カット結果・NLE 出力を再検証する。

---

## 2. 構造の方針

- **依存の向きは `ui → core` だけ。** `core` は `ui`（画面）を import しない。`tests/test_architecture.py` が検査する。
- **import は、パッケージの絶対パスで書く**（`from snipsync.core import vad`）。相対 import は使わない。PyInstaller と、試験の `monkeypatch`（`"snipsync.core.pipeline.xxx"`）の指定を、単純に保つため。
- **起動は `python -m snipsync`**（`pip install -e .` のあと）。PyInstaller は `src/snipsync/__main__.py` を起動スクリプトにする。起動時に静的には見つからない import（関数の中で読み込むもの）は、`build/app.spec` の `hiddenimports` に、モジュール名を足す。
- **アセットは `snipsync/assets/`。** `ui/theme.asset_path()` が、開発時は `snipsync/` の直下、EXE では `sys._MEIPASS` から探す。アセットを足したら、`build/app.spec` の `datas` と、`pyproject.toml` の `package-data` を確認する。
- **当初の目標案との違い**: `config.py`（定数の集約）は作っていない。定数は、使う側（`app.py` の `EXPORT_KEYS`、`pipeline` の出力の拡張子）にあり、共有の必要が出たら集約する。`core/` には、案の 3 モジュールのほか、画面に依存しない処理をすべて置いた。`tests/fixtures/` は作っていない。再現用のフルフリーズは、`requirements.txt` のまま。

---

## 3. 処理パイプライン（現状の実データフロー）

`pipeline.run_pipeline`。音量方式の例（VAD 方式は 0 で区間を自前生成し、以降の auto-editor 呼び出しへ v1 JSON として渡す）。

```
[入力 動画/音声]
   │ 0. （VAD 方式のみ）decode_mix → Silero VAD → v1 chunks JSON（全体を隙間なく覆う区間）
   │ 1. auto-editor でカット → NLE タイムライン（.fcpxml / .xml）またはカット済みメディア
   │      ・fcpxml は _tracks を移動して参照を書換え、音声トラック順を Resolve 向けに整列
   │      ・メディア書き出しは auto-editor のレンダリング。音声のみ入力は wav/flac/ogg/opus、それ以外は WAV
   ▼
[成果物①]
   │ 2a. chunks（auto-editor の v1 export、または VAD 区間）→ カット後音声を自前で組み立て（16kHz mono）
   │     組み立てられなければ従来どおり auto-editor で WAV を書き出す
   │ 2b. faster-whisper（単語時刻つき）。モデルは model_cache で使い回し。用語辞書は hotwords
   │ 2b'. （任意）sherpa-onnx で話者分離（カット後音声＝タイムライン基準）
   │ 2d. 字幕整形: カット境界 ∪ 文境界 ∪ 話者交代で分割 → BudouX 文節改行 → SRT
   │ 2e. 字幕の時刻補正: カット後音声の VAD（Silero）で、遅い開始・短い終わりを声の区間に合わせる（subtitles.refine_cue_times）
   ▼
[成果物② .srt]（+ 任意で .txt / .md）
   │ 4. （任意）カット点・話者交代のマーカー。Premiere / FCP は xmeml / FCPXML へ追加。
   │    Resolve は .fcpxml のマーカーを読まないので、<名前>_markers.edl に書く（字幕の保存後に、話者交代を足して書き直す）
```

### 設計上の要点
- **同期の肝**: タイムラインも字幕用音声もマーカーも**同じ chunks** から作る。以前は auto-editor を別々に3回走らせて margin / threshold を揃えていた（P-2）。
- **チャンクの正準ソース**: auto-editor は v1 JSON を**入力**として受け取れる。直接実行と同じ出力になる（31.7.2 は全形式・複数トラック・29.97fps で完全一致を実測）。FCPXML のトラック順は `_reorder_fcpxml_tracks` で Resolve 向けに整列する。
- **スレッド分離**: 処理は `threading.Thread(daemon=True)`。UI ログは `self.after(0, ...)`。
- **出力先**: 既定で、保存先の中に、1 回の処理ごとの `日時_モデル名` フォルダーを作る（`app._worker` が作り、pipeline には、そのフォルダーを `out_dir` として渡す）。`.fcpxml` が音声（`_tracks`）を絶対パスで参照するため、処理後に出力を移すと参照が切れる。それを避けるための決めごと。
- **停止**: `Popen` + `taskkill /F /T` で即時 kill。バッチは次のファイルへ進まない。

---

## 4. 技術的 TODO（優先度順）

1. **Whisper の言語を、画面から指定できるようにする** — いまは自動判定のみ（`language=None`）。判定を外したいときの逃げ道がない。
2. **定数の集約（`config.py`）** — `EXPORT_KEYS` などが、`app.py` と `pipeline` に分かれている。共有の必要が出たら、1 か所にまとめる。
