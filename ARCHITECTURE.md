# ARCHITECTURE.md — 構造と処理フロー

> 現状のディレクトリ構造・処理パイプラインと、AI 駆動開発に適した**目標構造**を定義する。
> 構造を変えたら必ず更新。

---

## 1. 現状のディレクトリ構造

```
SnipSync/
├── src/                    # flat 配置（パッケージ化は未実施）
│   ├── app.py              # メインウィンドウ（モニター・設定タブ・実行・ログ）+ バッチ実行
│   ├── widgets.py          # 部品（Btn / Choice / CutMap / Legend ほか）。色・書体は theme から
│   ├── cudalibs.py         # GPU 用の NVIDIA ライブラリ（cuBLAS・cuDNN）の取得（版・SHA-256 固定。UI に依存しない）
│   ├── player.py           # 編集後の音の再生（EditedAudio・倍速変換・Player。UI に依存しない）
│   ├── preview.py          # カットマップ用の計算（auto-editor の区間を取得。UI に依存しない）
│   ├── subtitle_edit.py    # 字幕の編集ロジック（CueEditor・書き出し文字列の生成。UI に依存しない）
│   ├── subtitle_editor.py  # 字幕の確認・編集ウィンドウ（表 + 編集欄 + txt/md/srt タブ）
│   ├── assets/fonts/       # 同梱フォント（BIZ UD ゴシック, SIL OFL）
│   ├── assets/icon/        # アプリアイコン（.ico / .png）。scripts/make_icon.py で生成
│   ├── pipeline.py         # 処理全体のオーケストレーション（run_pipeline）
│   ├── aebin.py            # auto-editor 31.x バイナリの取得・SHA-256 検証・同梱版の解決
│   ├── autoeditor.py       # auto-editor コマンド組み立て / fps・長さ・解像度の取得（PyAV 代替あり）
│   ├── subtitles.py        # 字幕: 境界計算・文節改行・話者付与・Cue/SRT
│   ├── vad.py              # 音声読み込み（全トラック加算）・VAD・v1 chunks 生成
│   ├── audiocut.py         # chunks から字幕用のカット後音声を自前で組み立てる
│   ├── safexml.py          # XML を defusedxml で読む（DOCTYPE・エンティティを拒否）
│   ├── diarize.py          # 話者分離（sherpa-onnx・モデル取得と SHA-256 検証）
│   ├── models.py           # Whisper モデル登録（kotoba の alignment_heads 補正を含む）
│   ├── markers.py          # マーカー（FCPXML / xmeml へ挿入。Resolve 向けは .edl に書く）
│   ├── transcript.py       # .txt / .md 生成・SRT 読み込み
│   ├── waveform.py         # 波形ピーク・カット統計（描画は widgets.CutMap）
│   ├── theme.py            # デザイントークン（色・書体・角丸・間隔。理由は DESIGN.md）
│   ├── i18n.py / presets.py / version.py
├── tests/                  # pytest（subprocess / transcribe はモック）
├── build/app.spec          # PyInstaller（budoux / sherpa_onnx を collect_all、auto-editor は build/vendor、フォントは src/assets から同梱）
├── scripts/fetch_auto_editor.py  # 同梱用の auto-editor を取得（SHA-256 検証）
├── scripts/make_icon.py    # アプリアイコンの生成（Pillow。実行時は不要）
├── docs/handoff/           # 設計・検証の引き継ぎ書
├── pyproject.toml          # 直接依存の単一ソース
└── requirements.txt        # 再現用フルフリーズ
```

### 残っている課題
1. `src/snipsync/` へのパッケージ化は未実施（§2 の目標構造）。
2. auto-editor は 31.7.2 に固定（`aebin.AE_VERSION`）。ライセンスキー無しではレンダリングが 3200×1800 に縮小される（タイムライン出力は無制限）。版を上げるときは SHA-256・フラグ・カット結果・NLE 出力を再検証する（AGENTS.md §4.2）。

---

## 2. 目標ディレクトリ構造（提案）

責務ごとにモジュール分割し、AI が安全に部分編集できる粒度にする。

```
SnipSync/
├── src/
│   └── snipsync/
│       ├── __init__.py        # __version__ = "0.2.0" を一元管理
│       ├── __main__.py        # エントリポイント（python -m snipsync）
│       ├── config.py          # 定数: EXPORT_MODES, デフォルト値, パス解決
│       ├── i18n.py            # I18N 辞書 + t() ヘルパ（ja/en）
│       ├── core/
│       │   ├── autoeditor.py  # auto-editor 呼び出し（無音カット/XML出力/WAV抽出）
│       │   ├── subtitles.py   # faster-whisper による .srt 生成
│       │   └── pipeline.py    # カット→WAV→文字起こし のオーケストレーション
│       └── ui/
│           ├── app.py         # SnipSyncApp（ウィンドウ・レイアウト）
│           ├── theme.py       # 配色/フォント定数（DESIGN.md と対応）
│           └── widgets.py     # ドロップゾーン等の再利用ウィジェット
├── tests/
│   ├── test_subtitles.py      # format_timestamp 等の単体テスト
│   ├── test_pipeline.py       # コマンド組み立ての検証（subprocess はモック）
│   └── fixtures/              # サンプル wav/動画
├── build/                     # PyInstaller 設定（現状維持）
├── docs/                      # ユーザー向け詳細ドキュメント
├── pyproject.toml             # 直接依存・メタ情報（requirements.txt から移行）
└── requirements-lock.txt      # 再現用フルフリーズ（自動生成）
```

> ⚠ これは**目標**であり、本タスクでは未実施。分割は別タスクで段階的に行う（一度に壊さない）。
> 移行手順・注意は着手時に PITFALLS.md を確認すること。

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

## 4. 主要モジュール責務（現状 app.py 内の論理ブロック）

| 論理ブロック | 現在の場所 | 目標の移動先 |
|---|---|---|
| `resource_path` / `get_auto_editor_path` | app.py 上部 | `config.py` |
| `I18N` 辞書 / `t()` | app.py 上部 | `i18n.py` |
| 配色定数 (`ACCENT` 等) | app.py 上部 | `ui/theme.py` |
| `format_timestamp` | app.py | `core/subtitles.py` |
| `SnipSyncApp._build_*` | app.py | `ui/app.py` + `ui/widgets.py` |
| `_worker`（auto-editor 呼出） | app.py | `core/autoeditor.py` |
| `_worker`（whisper 呼出） | app.py | `core/subtitles.py` |
| オーケストレーション | `_worker` | `core/pipeline.py` |

---

## 5. 技術的 TODO（優先度順）

1. **`__version__` 一元化** — タイトル/README/CHANGELOG のズレを構造的に解消（AGENTS.md §5）。
2. **Whisper 言語の自動判定対応** — `language="ja"` 固定を解除、UI に言語選択を追加（MEMORY.md 参照）。
3. **モノリス分割** — §2 の構造へ段階移行。
4. **単体テスト導入** — `format_timestamp` とコマンド組み立てから着手。
5. **依存管理整理** — `pyproject.toml` に直接依存を切り出し。
