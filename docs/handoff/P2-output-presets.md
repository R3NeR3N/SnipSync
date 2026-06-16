# 設計書 — P2: 出力プリセット保存（設定の記憶・名前付きプリセット）

> 区分: 🧠頭脳(Opus 4.8) 設計 → 🔧作業(Gemini) 実装
> 対象: ROADMAP P2「出力プリセット保存 — よく使う設定の記憶」
> 前提ブランチ: `feat/p1-refactor`

非開発者向け要約: いまは起動するたびに設定（マージン/閾値/出力形式/字幕/モデル）が初期値に戻る。
よく使う組み合わせを**名前を付けて保存**し、ドロップダウンから**ワンタッチで呼び出せる**ようにする。
さらに、**前回終了時の設定を次回起動時に自動復元**して「毎回やり直す」手間を消す。

---

## 1. スコープ

| 含む | 含まない（非対象） |
|---|---|
| 名前付きプリセットの 保存 / 読込 / 削除 | クラウド同期・共有 |
| 前回設定の自動復元（last-used） | プリセットのインポート/エクスポート UI |
| JSON 1ファイルへ永続化（ユーザー設定ディレクトリ） | プリセットの並べ替え/タグ付け |
| 出力先フォルダ(`output_dir`)も記憶 | パスワード等の秘匿情報（保存しない） |

保存対象の設定（= 既存の Tk 変数）:
`margin_var` / `threshold_var` / `export_var` / `srt_var` / `model_key_var` / `output_dir`
（GPU タスクが先に入っていれば `gpu_var` も対象に含める。**キーは存在するものだけ読む**前方/後方互換設計にする）。

## 2. 永続先

- パス: `%APPDATA%\SnipSync\presets.json`（Windows 主。`os.environ.get("APPDATA")` 無ければ `Path.home()/".snipsync"`）。
- 解決は `config.py` 相当が無いため **新規 `presets.py` 内のヘルパ** `_store_path()` に閉じる（`Path(...).resolve()`、PITFALLS P-3）。
- 文字コード: `encoding="utf-8"`（日本語プリセット名対応）。`json.dump(..., ensure_ascii=False, indent=2)`。

### JSON スキーマ
```json
{
  "version": 1,
  "last_used": { "margin": 0.2, "threshold": 4.0, "export": "resolve",
                 "srt": true, "model": "small", "output_dir": "D:/out" },
  "presets": {
    "YouTube用": { "margin": 0.3, "threshold": 5.0, "export": "premiere",
                   "srt": true, "model": "base", "output_dir": "" }
  }
}
```
- `version` で将来のマイグレーション余地を残す（今は 1 固定）。
- 値は **プリミティブのみ**（Tk 変数を直接シリアライズしない）。

## 3. 新規モジュール `src/presets.py`（UI 非依存・テスト可能）

純粋な dict ⇄ ファイルの IO に限定し、Tk 依存ゼロ。

```python
# src/presets.py
from pathlib import Path
import json, os

SCHEMA_VERSION = 1
SETTING_KEYS = ("margin", "threshold", "export", "srt", "model", "output_dir")  # gpu は任意

def _store_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) / "SnipSync" if base else Path.home() / ".snipsync"
    return (root / "presets.json").resolve()

def load_store() -> dict:
    """壊れ/不在でも例外を投げず空ストアを返す（堅牢化）。"""
    p = _store_path()
    if not p.exists():
        return {"version": SCHEMA_VERSION, "last_used": {}, "presets": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data.setdefault("version", SCHEMA_VERSION)
        data.setdefault("last_used", {})
        data.setdefault("presets", {})
        return data
    except Exception:
        return {"version": SCHEMA_VERSION, "last_used": {}, "presets": {}}

def save_store(store: dict) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

def upsert_preset(store, name, settings): store["presets"][name] = settings
def delete_preset(store, name): store["presets"].pop(name, None)
def set_last_used(store, settings): store["last_used"] = settings
```
> `settings` は `{key: value}` の素の dict。**UI 層が Tk 変数 ⇄ dict 変換を担う**（下記 §4 の `_collect_settings`/`_apply_settings`）。境界を分け、`presets.py` は I/O のみ＝テスト容易。

## 4. UI 側（app.py）の変更

### 4.1 設定 ⇄ dict 変換ヘルパ（app.py 内）
```python
def _collect_settings(self) -> dict:
    return {"margin": self.margin_var.get(), "threshold": self.threshold_var.get(),
            "export": self.export_var.get(), "srt": self.srt_var.get(),
            "model": self.model_key_var.get(), "output_dir": self.output_dir}

def _apply_settings(self, s: dict):
    # 存在するキーだけ適用（前方互換）。適用後 _on_*_change 相当でスライダー↔入力同期を更新
    if "margin" in s: self.margin_var.set(s["margin"])
    ...  # 各 var.set + 既存の同期/クランプ関数を呼ぶ
```
> ⚠ スライダーと数値入力は**双方向同期**（DESIGN.md §5）。`_apply_settings` で `var.set` した後、
> 既存の margin/threshold の表示更新ハンドラを必ず呼ぶこと（値ラベルとエントリが古いまま残る事故を防ぐ）。

### 4.2 プリセット UI（設定カード上部に1行）
- `CTkOptionMenu`（プリセット名一覧 + 先頭に「（なし）」）
- `[保存]` ボタン → 名前入力（`CTkInputDialog`）→ `upsert_preset` → `save_store` → メニュー更新。
- `[削除]` ボタン → 選択中プリセットを `delete_preset` → 保存 → メニュー更新。
- メニュー選択 → `_apply_settings(store["presets"][name])`。
- 文言はすべて i18n キー（§5）。

### 4.3 自動復元（last-used）
- `__init__` の var 初期化**後**に `store = load_store()` → `if store["last_used"]: self._apply_settings(store["last_used"])`。
- 終了時に保存: `self.protocol("WM_DELETE_WINDOW", self._on_close)` を設定し、
  ```python
  def _on_close(self):
      store = load_store()
      set_last_used(store, self._collect_settings())
      save_store(store)
      self.destroy()
  ```
  （処理スレッド実行中の終了は既存挙動を尊重。最低限 last_used 保存→destroy で可。）

## 5. 追加する i18n キー（`i18n.py` ja/en 両方・必須）

| key | ja | en |
|---|---|---|
| `preset_label` | `プリセット` | `Preset` |
| `preset_none` | `（なし）` | `(none)` |
| `preset_save` | `保存` | `Save` |
| `preset_delete` | `削除` | `Delete` |
| `preset_name_prompt` | `プリセット名を入力` | `Enter preset name` |
| `log_preset_saved` | `プリセット「{}」を保存しました` | `Preset "{}" saved` |
| `log_preset_deleted` | `プリセット「{}」を削除しました` | `Preset "{}" deleted` |

## 6. テスト計画（`tests/test_presets.py` 新規・Tk 不要）

`presets.py` は UI 非依存なので**実ファイル IO を tmp_path で**検証:
1. `load_store` 不在 → 既定構造を返す。
2. 壊れた JSON → 例外を投げず既定構造（堅牢化）。
3. `upsert_preset` → `save_store` → `load_store` で往復一致（日本語名・`ensure_ascii=False`）。
4. `delete_preset` で消える。存在しない名の delete は no-op。
5. `set_last_used` → 保存往復。
- `_store_path` は `monkeypatch.setenv("APPDATA", str(tmp_path))` で隔離（実ユーザー設定を汚さない）。

## 7. 受け入れ基準（Definition of Done）

1. `python src/app.py`: 設定を変えて「保存」→名前付け→再起動→ドロップダウンから選ぶと設定が**復元**。
2. 何も触らず終了→再起動で**前回設定が自動復元**。
3. 壊れた/無い presets.json でも**起動が落ちない**（既定値で立ち上がる）。
4. プリセット名に日本語を使っても文字化けしない（utf-8）。
5. `tests/`（既存 + `test_presets.py`）全 green。i18n 7キー ja/en 両方。
6. MEMORY.md に決定追記。バージョン整合(§5)不変・生成物未コミット（`presets.json` はユーザー設定ディレクトリ＝リポ外なので無関係）。

## 8. 非対象（やらない）

- プリセットの import/export・共有・クラウド同期。
- 言語(`lang_var`)のプリセット化（UI 言語は別概念。混同しない）。
- 入力ファイルパスの記憶（毎回 D&D する運用のため不要）。

## 9. 変更ファイル

| ファイル | 操作 |
|---|---|
| `src/presets.py` | 新規（store I/O・UI 非依存） |
| `src/app.py` | プリセット UI 行、`_collect_settings`/`_apply_settings`、`_on_close`、起動時復元 |
| `src/i18n.py` | 7キー追加（ja/en） |
| `tests/test_presets.py` | 新規（tmp_path IO テスト） |
| `ROADMAP.md` / `MEMORY.md` | 完了・決定追記 |

## 10. 実装者（Gemini）への注意 — PITFALLS 先読み

- **P-1**: プリセット UI の全文言を i18n 経由に。ハードコード禁止（`_apply_lang` で再設定できる形に）。
- **P-3**: `_store_path` は `.resolve()` で絶対パス化。
- **P-6**: JSON 読書きは `encoding="utf-8"`。`ensure_ascii=False`。
- **double-sync 事故**: `_apply_settings` 後にスライダー値ラベル/エントリの同期更新を忘れない（DESIGN §5）。
- **並列実装の注意**: 本タスクと「GPU 対応」は**どちらも `app.py` 設定UI と `i18n.py` を編集**するため、
  **直列**で実装し後発はリベース。両方入れる場合、プリセットの保存対象に `gpu` キーを足すかは
  「存在するキーだけ読む」設計なので**順序非依存**（先に入った方を壊さない）。
