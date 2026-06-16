# ROADMAP.md — 開発計画

> 今後の作業と優先度。完了したら CHANGELOG.md へ移し、ここから消す。
> 各項目に「担当モデル（頭脳/作業）」を明記する（CONTRIBUTING.md の協業方針に対応）。

凡例: 担当 = 🧠 頭脳(Opus 4.8) / 🔧 作業(Gemini) / 🧠→🔧 設計は頭脳・実装は作業

---

## P0（整合性・既知バグ。早めに潰す）

- [x] **バージョン一元化** — `src/snipsync/__init__.py` に `__version__="1.3.1"` を作り、UI タイトルと README/CHANGELOG を同期。担当: 🧠→🔧（設計1点・実装単純）
- [x] **Whisper 言語ハードコード解除** — `language="ja"` を自動判定 or UI 言語セレクタ化. 担当: 🧠→🔧（設計は頭脳、実装は作業）
- [x] **README バージョンバッジ修正** — 4言語の `v1.0.0` を実バージョンへ。担当: 🔧

## P1（品質・保守性）

- [x] **単体テスト導入** — `tests/test_unit.py`: `format_timestamp` + `build_cut_cmd`/`build_extract_wav_cmd`（純関数なので subprocess モック不要）。P-2同期も検証。
- [x] **モノリス分割（段階1）** — `version.py` / `i18n.py` / `theme.py` を `src/app.py` から切り出し（flat配置・pathex=src で読込）。
- [~] **モノリス分割（段階2）** — `autoeditor.py`(コマンド組立) / `subtitles.py`(`format_timestamp`) を分離済み。**残**: `_worker` の pipeline オーケストレーション抽出（UI/ログ結合のため要コールバック設計、別途）。
- [x] **依存管理整理** — `pyproject.toml` に直接依存を切り出し。`requirements.txt` はロックとして据え置き（全行書換は §4.2 で禁止）。

## P2（機能・UX）

- [ ] **即時停止対応** — `subprocess.Popen` + `terminate()` 化、ログのストリーミング。担当: 🧠(設計)→🔧(実装)
- [ ] **GPU 対応の検討** — CUDA 環境で `compute_type` 切替（配布サイズとのトレードオフ）。担当: 🧠(判断)→🔧
- [ ] **出力プリセット保存** — よく使う設定の記憶。担当: 🧠→🔧

## アイデア（未精査・優先度未定）

- バッチ処理（複数動画の連続投入）。
- macOS 対応の可否調査。

---

> 優先度・担当の変更は MEMORY.md に理由を残すこと。
