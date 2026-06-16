# ARCHITECTURE.md — 構造と処理フロー

> 現状のディレクトリ構造・処理パイプラインと、AI 駆動開発に適した**目標構造**を定義する。
> 構造を変えたら必ず更新。

---

## 1. 現状のディレクトリ構造

```
SnipSync/
├── src/
│   └── app.py            # 752行モノリス（UI + i18n + 処理 すべて混在）
├── tests/
│   ├── test.wav          # サンプル音声（実テストではない）
│   └── dummy.wav
├── build/
│   ├── app.spec          # PyInstaller 設定
│   └── build_hooks/
│       └── hook-tkinterdnd2.py
├── dist/
│   └── SnipSync.exe       # 配布物（生成物・gitignore）
├── docs/                  # 空
├── venv/                  # 仮想環境（生成物・gitignore）
├── requirements.txt       # フルフリーズ（直接/間接依存が混在）
├── README*.md             # en / ja / zh / ko の4言語
└── LICENSE                # MIT
```

### 現状の問題点
1. **`app.py` がモノリス**。UI 構築・i18n 辞書・処理パイプラインが 1 ファイルに同居 → AI が部分編集する際に無関係箇所と衝突しやすい。
2. **実テストが無い**（`tests/` は wav サンプルのみ）。
3. **バージョン定数が無い**。タイトル文字列に `v1.3.1` がハードコードされ README とズレている。
4. **`requirements.txt` がフルフリーズ**。直接依存が埋もれ、更新判断が難しい。
5. **`docs/` が空**。

---

## 2. 目標ディレクトリ構造（提案）

責務ごとにモジュール分割し、AI が安全に部分編集できる粒度にする。

```
SnipSync/
├── src/
│   └── snipsync/
│       ├── __init__.py        # __version__ = "1.3.1" を一元管理
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

`src/app.py` の `_start_process` → `_worker` の流れ。

```
[入力動画]
   │
   │ ① auto-editor（メイン）
   │   cmd: auto-editor <in> --margin <m>s --edit audio:threshold=<t>%
   │        --export <mode> --output <stem>_snipsynced.<ext> --no-open
   ▼
[NLE タイムライン: .fcpxml / .xml]   ← 成果物①
   │
   │ ②（字幕ON時のみ）auto-editor で音声のみ抽出
   │   cmd: auto-editor <in> --margin <m>s --edit audio:threshold=<t>%
   │        -vn -sn -dn --mix-audio-streams --output <stem>_temp_audio.wav --no-open
   ▼
[一時 WAV（カット済み音声）]
   │
   │ ③ faster-whisper で文字起こし
   │   WhisperModel(model_size, device="cpu", compute_type="int8")
   │   model.transcribe(wav, beam_size=5, language="ja")  ← ⚠言語ハードコード（既知バグ）
   ▼
[字幕: .srt]   ← 成果物②（タイムコードはカット後音声基準＝タイムラインと同期）
   │
   ▼
[一時 WAV を削除] → 完了ダイアログ
```

### 設計上の要点
- **同期の肝**: 字幕は①と同じ `margin`/`threshold` で再カットした音声（②）に対して生成するため、タイムコードがタイムラインと一致する。①と②でパラメータを必ず一致させること。
- **スレッド分離**: 処理は `threading.Thread(daemon=True)` でバックグラウンド実行し、UI ログは `self.after(0, ...)` でメインスレッドへ反映。
- **停止**: `subprocess.run` は外部から即時 kill できないため、`stop_requested` フラグで**次ステージをスキップ**する方式。実行中プロセス自体は完了を待つ。

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
