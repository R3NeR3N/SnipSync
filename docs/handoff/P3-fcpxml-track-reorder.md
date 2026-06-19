# P3 — fcpxml 多トラック順序の正規化（`_reorder_fcpxml_tracks` 作り直し）

> 🧠頭脳(Opus) → 🔧作業(Gemini) ハンドオフ設計書。
> 旧試作（破壊的）は `git stash@{0}` に退避済み。本書はその**作り直し**設計。
> 実装着手前に AGENTS.md（§4 禁止事項 / §6.1 コミット担当）と PITFALLS.md を必読。

---

## 0. 一行サマリ

多トラック音声の resolve/final-cut-pro fcpxml で、auto-editor が spine に
**フラット列挙する音声トラックを `lane` ネストへ並べ替え、元のストリーム順を明示**する。
**全カットセグメントを必ず保持**すること（旧試作はここで全滅させた）。

---

## 1. 背景・課題

- OBS 等の多トラック収録動画を resolve 出力 → DaVinci 取込で **トラック順が元動画と一致しない**。
- relocate（B案・commit 5908ae4）で `_tracks/*.wav` の参照切れは解決済み・再生も可能。
  残るのは**トラックの並び順**だけ。
- Opus が試作した `_reorder_fcpxml_tracks` は構造を誤解しており、実機検証で
  **31セグメント中30個を消滅**させた（2.2秒1クリップに崩壊）。退避済み。本書で作り直す。

---

## 2. 真因（実測済み・本設計の根拠）

検証素材: `2026-06-19 22-55-03.mp4`（4トラック音声、5271/60s ≈ 87.8s）。
`auto-editor … --export resolve` の**素の出力**を XML 実検査した結果:

### 2.1 素の auto-editor fcpxml の spine 構造
- spine 直下に **`asset-clip` が 124 個**フラットに並ぶ。
- 内訳 = **31 セグメント × 4 トラック**。`(offset, duration)` でグループ化すると
  **31 グループ、各グループちょうど 4 ref**（1トラックずつ）。
- **`lane` は一切無い／ネストも無い**（各 `asset-clip` は子を持たない）。
- 4トラック分が primary spine 上で **offset を重複**させて積まれる
  → Resolve が取込時にトラック割当を独自推測 → **順序ズレの真因**。

### 2.2 asset とストリーム順の対応（重要・id順ではない）
```
id=r2 name="…_1"  hasVideo=0   ← wav stream1
id=r4 name="…_3"  hasVideo=0   ← wav stream3
id=r6 name="…_2"  hasVideo=0   ← wav stream2
id=r8 name="…"    hasVideo=1   ← mp4（映像 + ミックス音声 = stream0 / T1）
```
- **asset id は名前順でない**。順序判定は必ず **asset の `name` suffix**（`{stem}_N` の N）で行う。
- 元ストリーム順 = `hasVideo=1` の asset（=ミックス/T1）を先頭、続いて `_1, _2, _3 …` 昇順。
- アプリは**用途非依存**（OBSのどのトラックが何かは関知しない）。意味名を付けず番号 `{stem}_A{n}` のみ。

### 2.3 旧試作のバグ（`stash@{0}` に退避、再現禁止パターン）
```python
clips = spine.findall("asset-clip")   # 124個（=31セグ×4トラック）取得
tmpl  = clips[0]                       # ← 先頭1個だけをテンプレ化（致命的誤解）
for c in clips: spine.remove(c)        # 全削除
primary = ET.SubElement(spine, ...)    # ← 1個だけ再生成
```
- 「4 asset-clip = 1トラックずつ」と仮定したが、実体は「124 = 31セグ×4トラック」。
- → 先頭セグメントだけ残り 30 セグメント消滅。**セグメント次元を完全に無視**していた。

---

## 3. 設計（正しい実装）

`_reorder_fcpxml_tracks(timeline_path: Path, stem: str) -> bool` を作り直す。
ET 操作のみの純関数（UI 非依存）。`pipeline.run_pipeline` の呼び出し位置（step1直後・
字幕WAV抽出 step2 の前、`is_fcpxml` ガード内）は旧実装と同じでよい。

### 3.1 アルゴリズム
1. `resources/asset` を走査し
   - `hasVideo=="1"` の asset id = **video_id**（primary 候補）。
   - `name == f"{stem}_{N}"`（N が数字）の wav を `wavs[int(N)] = asset_id` に収集。
2. `video_id` 無し or `wavs` 空 → **単トラック等。何もせず `return False`**（native 維持）。
3. `sequence/spine` の **`asset-clip`（top-level）を全取得**。
4. **`(offset, duration)` でグループ化**（= セグメント）。グループは出現順（offset 昇順）を維持。
   - 実装は `dict` 挿入順 or 明示ソートで offset 昇順を保証すること。
5. 既存 `asset-clip` を spine から全 remove（**ただし `gap` 等 `asset-clip` 以外は触らない**）。
6. **各セグメントごとに** primary + ネストを 1 組み立てて spine へ追加:
   - primary = そのセグメント内の **`ref==video_id` のクリップ**。属性
     `offset / duration / start / tcFormat` は**そのクリップ自身の値を保持**。`name=f"{stem}_A1"`。
   - 残りの wav を **`wavs` の stream 番号昇順**で `lane = -1, -2, -3, …` の
     connected `asset-clip` として primary の**子**に追加。各ネストの
     `duration / start / tcFormat` は**そのトラックのクリップ自身の値**を使う。
     ネストの `offset` は primary 相対なので **`"0s"`**。`name=f"{stem}_A{2,3,4,…}"`。
7. `tree.write(timeline_path, encoding="utf-8", xml_declaration=True)` → `return True`。

### 3.2 厳守事項（旧バグ回帰防止）
- ❌ `clips[0]` を全セグメントのテンプレにしない。**セグメント数 = 入力の top-level クリップを
  `(offset,duration)` でまとめた数**。出力セグメント数 == 入力セグメント数 を必ず満たす。
- ❌ primary の `start` をネストへ流用しない。**各 ref のクリップ自身の `start` を使う**
  （ソース in 点はトラックごとに異なり得る。実測では一致するが、依存しない実装にする）。
- セグメント内に `video_id` のクリップが 0 個 or 複数 → 異常。そのセグメントは
  **並べ替えず native のまま残す**か、安全側で関数全体 `return False`（native 全保持）。
  どちらか一方に決め、コメントで明示すること（推奨: 異常検知時は `return False` で native 全保持）。

### 3.3 対象外
- premiere(`.xml`) は対象外（既存 `is_fcpxml` ガードのまま）。
- `_tracks` の relocate/掃除ロジック（commit 5908ae4）は**変更しない**。本タスクは順序のみ。

---

## 4. i18n

- `log_tracks_reordered`（ja/en）を `src/i18n.py` に追加（退避 stash に文言あり・流用可）:
  - ja: `  タイムラインの音声トラックを元の順序へ整列しました`
  - en: `  Reordered timeline audio tracks to match the original order`
- 並べ替え成功時（`True`）に `on_log(tr("log_tracks_reordered"), "muted")`。

---

## 5. テスト（`tests/test_pipeline.py`）

実 auto-editor を呼ばず、**合成 fcpxml 文字列**を fixture にして純関数を検証する。
最低限 native 相当（**2セグメント × 3トラック**程度、id順を name順とズラす・gap1個混在）を用意し:

1. **セグメント数維持**: reorder 後の top-level `asset-clip` 数 == 入力セグメント数
   （= 旧バグ「1個化」の回帰テスト。**必須**）。
2. **primary が映像 asset**: 各 top-level clip の `ref` == `hasVideo=1` の id。
3. **lane 順 = ストリーム順**: 各 primary の子 lane が `-1,-2,…` で、`ref` が name suffix 昇順。
4. **属性保持**: 各セグメントの primary/ネストの `duration`・`start` が入力値と一致
   （primary の start をネストへ流用していないことを、start を意図的に変えた fixture で検出）。
5. **gap 非破壊**: 入力 spine に `gap` があれば出力にも残る。
6. **単トラック no-op**: wav 無し fcpxml では `False` を返し XML 不変。

`venv/Scripts/python.exe -m pytest tests/ -q` 全 green。

---

## 6. 完了の定義（DoD）

1. 上記テスト追加 + 既存テスト全 green。
2. `python src/app.py` 起動・目視（GUI 必須）。
3. **実機 DaVinci**: 検証素材を resolve 出力 → 取込で
   **(a) 全セグメントが存在**（タイムラインが 2.2 秒で終わらない）
   **(b) トラック順が元順**（T1=ミックス, A2=_1, A3=_2, A4=_3）で展開、を目視確認。
4. `pipeline.py` が customtkinter / `self` を参照しない（UI 非依存）を維持。
5. MEMORY.md に決定追記・失敗は PITFALLS.md。退避 `stash@{0}` は本実装マージ後に破棄可
   （`git stash drop` はユーザー確認のうえ）。

---

## 7. コミット（AGENTS §6.1）

Gemini が書いた実装/テストは **Gemini がコミット**。Conventional Commits・1論理変更・
生成物（build/dist/venv/`_tracks`）は含めない。設計と実コードに矛盾があれば勝手に直さず
MEMORY.md に記録し Opus/ユーザーへ確認。

---

## 付録: 実測ログ（証拠）

```
素の auto-editor resolve fcpxml（2026-06-19 22-55-03.mp4）:
  spine top-level asset-clip = 124, gaps = 0
  distinct (offset,duration) = 31  / every segment has exactly 4 refs = True
  assets: r2="…_1"(hasVideo=0) r4="…_3"(0) r6="…_2"(0) r8="…"(hasVideo=1)
  group例: ('0s','133/60s') -> [r8, r6, r4, r2]

旧試作出力（破損 fcpxml, 2779B）:
  spine top-level asset-clip = 1（duration 133/60s だけ残存。30セグ消滅）
```
