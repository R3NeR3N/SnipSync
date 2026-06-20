# P3 — 字幕境界をカット境界へスナップする後処理（SRT-snap）

> 🧠頭脳(Opus) → 🔧作業(Gemini) ハンドオフ設計書。
> 実装着手前に AGENTS.md（§4 禁止事項 / §6.1 コミット担当）と PITFALLS.md を必読。
> 特に **PITFALLS 2026-06-20「字幕切替えがカットに乗らない＝margin由来の恒常仕様」** が本タスクの背景。

---

## 0. 一行サマリ

字幕(.srt)生成後に、**字幕の境界時刻を、生成済み fcpxml の既知カット境界(offset)へ
tolerance 内なら吸着(snap)する純後処理**を追加する。margin(0.2s)分の内側インセットを
吸収し、「字幕切替えをカットに乗せる」を実現する。**カットに対応しない字幕境界
（発話中の文区切り）は動かさない**＝tolerance ゲートが肝。

これは**機能追加(MINOR)**。バグ修正ではない（非リグレッションは実測確定済み・MEMORY 2026-06-20 03:15）。

---

## 1. 背景・課題（実測根拠）

- auto-editor は発話の**前後に margin(0.2s) を残して**カットする。whisper はカット音声の
  **発話部分**を字幕化するので、字幕境界は各クリップ境界から **margin 分内側**に入る。
- 結果、DaVinci 取込で「字幕切替えが映像カットに乗らない」。**v1.0.0 でも現行でも同一**
  （バイト等価／非リグレッション）。バージョンを下げても直らない＝**後処理が必要**。
- 字幕とカットは**同一タイムライン座標**にある（カット音声を連結したもの＝NLEタイムライン）。
  fcpxml の `asset-clip` の `offset` がカット境界そのもの → これに字幕境界を寄せればよい。

### 1.1 実測データ（検証素材 `2026-06-20 10-56-29.mp4` / 44カット・45境界・総45.533s）

| SRT 遷移(s) | 最寄りカット境界(s) | 差(s) | 判定 |
|---|---|---|---|
| 0.000 | 0.000 | +0.000 | 既に境界（不動） |
| 15.360 | 15.300 | **-0.060** | カット隣接 → snap |
| 20.640 | 21.117 | **+0.477** | **カット無し（発話中の文区切り）→ 動かさない** |
| 25.280 | 25.133 | **-0.147** | カット隣接 → snap |
| 45.600 | 45.533 | **-0.067** | 最終境界（whisper が 0.067s 超過）→ snap で超過も解消 |

- **真のカット隣接の差は ≤0.147s、偽（カット無し）の差は 0.477s** → 分離帯域が広い。
- tolerance を **margin + 0.15 ≈ 0.35s** にすれば、隣接3点を拾い 0.477 を確実に除外できる。
- **教訓**: 全字幕遷移がカットに対応するわけではない。20.640 を遠いカットへ寄せたら
  逆に音とズレる。**必ず tolerance でゲートし、近いものだけ吸着**する。

### 1.2 fcpxml の時刻表現（実測）

```
<sequence tcStart="0s" format="r1" tcFormat="NDF" ...>
 <spine>
  <asset-clip offset="0s"     duration="27/60s"  start="108/60s" name="…" ref="r8" />
  <asset-clip offset="27/60s" duration="34/60s"  start="231/60s" name="…" ref="r8" />
  <asset-clip offset="61/60s" duration="36/60s"  start="365/60s" name="…" ref="r8" />
  ...
```
- 時刻は有理数 `N/D s`（例 `27/60s`）または `0s`。`N/60s` は 60fps 量子化。
- **`offset` = タイムライン位置（カット境界）。`start` = ソース内 in 点 → snap には使わない**。
- 映像トラック(`ref==r8`, `hasVideo=1`)の asset-clip が **1カットセグメント=1個**。
  各 `offset` がカット境界。セグメントは連続（offset_i + dur_i == offset_{i+1}）。
- カット境界集合 = 映像 asset-clip の全 `offset` ＋ 最後の `offset+duration`（sorted・重複除去）。
  音声トラックも同じ offset を共有するので、**映像トラックだけ**から取れば重複しない。

---

## 2. 設計

### 2.1 配置

- **純ロジックは `src/subtitles.py`** に追加（SRT 関連の既存モジュール。UI 非依存）。
- **pipeline 統合は `src/pipeline.py`** の **新ステップ 2d**（字幕書込 2b の後、`_tracks` 掃除より前）。
- premiere(`.xml`) は対象外（`is_fcpxml` ガード内のみ。理由 §2.6）。

### 2.2 新規関数（`src/subtitles.py`）

3つに分けて純度とテスト容易性を確保する:

```python
# (a) fcpxml からカット境界（秒・昇順・重複除去）を取り出す
def parse_fcpxml_cut_boundaries(timeline_path: Path, stem: str) -> list[float]:
    """映像 asset-clip(hasVideo=1 の ref)の offset 群 ＋ 最終 offset+duration を
    秒に直して sorted・重複除去で返す。取得不能/単トラック不問→ 解析できた境界のみ。
    パースできない/境界0個なら [] を返す（呼び出し側で no-op）。"""

# (b) 有理数時刻 "N/Ds" / "Ns" / "0s" → float 秒
def _fcpxml_time_to_seconds(text: str) -> float:
    """末尾 's' を除去。'/' があれば 分子/分母、無ければ float。例 '27/60s'→0.45, '0s'→0.0"""

# (c) SRT テキストを境界へスナップ（純文字列変換・最重要・テストの主対象）
def snap_srt_to_boundaries(srt_text: str, boundaries: list[float], tolerance: float) -> str:
    """SRT 内の各字幕の start/end 時刻のうち、最寄り境界との差が tolerance 以内のものを
    その境界へ吸着して再構築した SRT テキストを返す。boundaries 空なら srt_text をそのまま返す。"""
```

オーケストレーション（ファイル I/O）は pipeline 側に薄く置く（§2.4）。

### 2.3 スナップ・アルゴリズム（`snap_srt_to_boundaries`）

**「distinct 時刻」モデル**で start/end を統一的に扱い、contiguous（前字幕の end == 次字幕の
start）を壊さない:

1. SRT をパースし `entries = [(index, start_sec, end_sec, text), ...]`。
   - 時刻パースは `HH:MM:SS,mmm`。既存 `format_timestamp`（`src/subtitles.py`）の**逆変換**を
     新ヘルパ `parse_timestamp(str)->float` として用意（format_timestamp と対で置く）。
2. `times = sorted(set(全 start と 全 end))`。
3. 各 `t` について最寄り境界 `nb = min(boundaries, key=lambda b: abs(b-t))`。
   - `abs(nb - t) <= tolerance` なら `remap[t] = nb`、そうでなければ `remap[t] = t`。
4. **衝突/反転ガード**（順に適用）:
   - 同一字幕で `remap[start] >= remap[end]` になる場合 → その字幕は **end を元値に戻す**
     （start 優先。ゼロ/負 duration を作らない）。
   - それでも `start >= end` なら、その字幕の start/end を**両方元値に戻す**（安全側）。
   - 字幕列の時刻が**非減少**を保つこと（隣接字幕で remap 後に前字幕 end > 次字幕 start に
     なる場合は、その snap を取りやめ元値維持）。
5. `format_timestamp(remap値)` で SRT を再構築して返す（番号・本文・空行は原型維持）。

> ⚠ `boundaries` が空 → 即 `return srt_text`（fcpxml 解析失敗時に字幕を壊さない）。
> ⚠ snap は**時刻のみ**変更。字幕の**個数・順序・本文は不変**。

### 2.4 pipeline 統合（`src/pipeline.py` 新ステップ 2d）

`run_pipeline` 内、字幕書込（2b で `result.srt_path` を設定）後・`finally` の前に挿入:

```python
# 2d. 字幕境界をカット境界へスナップ（fcpxml かつ字幕生成成功時のみ）
if (params.snap_srt and is_fcpxml and result.srt_path
        and result.timeline_path and result.timeline_path.exists()
        and not result.stopped):
    try:
        boundaries = parse_fcpxml_cut_boundaries(result.timeline_path, inp.stem)
        if boundaries:
            tolerance = params.margin + SRT_SNAP_TOLERANCE_EXTRA  # 既定 0.15
            text = result.srt_path.read_text(encoding="utf-8")
            snapped = snap_srt_to_boundaries(text, boundaries, tolerance)
            if snapped != text:
                result.srt_path.write_text(snapped, encoding="utf-8")
                on_log(tr("log_srt_snapped"), "muted")
    except Exception:
        on_log(tr("log_unexpected", traceback.format_exc()), "error")
```

- `SRT_SNAP_TOLERANCE_EXTRA = 0.15` は `src/subtitles.py`（または pipeline 上部）の定数。
- **2c（temp WAV 掃除）との順序**: snap は temp WAV に依存しない。2b 完了後ならどこでもよいが、
  可読性のため 2c の直前か直後に置く（実装者判断。`finally` の `_tracks` 掃除より前であること）。

### 2.5 UI / パラメータ（既定 ON のオプトアウト）

- `PipelineParams` に **`snap_srt: bool = True` を末尾に追加**（`use_gpu` と同じ後方互換パターン）。
- `src/app.py` の設定カードに**チェックボックス「字幕をカット境界に合わせる」既定 ON** を追加。
  - **字幕生成 OFF または 出力形式が premiere のとき disabled**（gpu_checkbox の disable パターンに倣う）。
  - DESIGN §5「字幕 OFF → 関連メニュー disabled」の規約に合わせる。
- `src/presets.py` の `SETTING_KEYS` に **`"snap_srt"` を追加**（存在キーだけ読む前方/後方互換設計を維持）。
- `_collect_settings`/`_apply_settings` に snap_srt を往復させる（gpu と同じ要領）。

> スコープ削減が必要なら UI/preset を省き「fcpxml 時は常時 ON・ログのみ」でも可だが、
> **時刻が変わる挙動なのでオプトアウトを設ける方を推奨**（既定 ON）。

### 2.6 対象外・非変更

- premiere(`.xml`) は対象外（境界構造が異なる。`is_fcpxml` ガードのまま）。将来別タスク。
- `_reorder_fcpxml_tracks` / relocate / `_tracks` 掃除は**一切触らない**。
- カット結果・whisper 呼び出し・margin/threshold 同期（P-2）は不変。

---

## 3. i18n（`src/i18n.py`・ja/en 両方／§4 必須）

- `snap_srt_label`（チェックボックス文言）:
  - ja: `字幕をカット境界に合わせる`
  - en: `Snap subtitles to cut boundaries`
- `log_srt_snapped`（muted ログ）:
  - ja: `  字幕の境界をカット位置へ整列しました`
  - en: `  Snapped subtitle boundaries to cut positions`

---

## 4. テスト（`tests/`）

`snap_srt_to_boundaries` / `parse_fcpxml_cut_boundaries` / `_fcpxml_time_to_seconds` /
`parse_timestamp` を**実 whisper・実 auto-editor 無し**で純検証する。`test_subtitles.py`
（無ければ新規）か `test_pipeline.py` に追加。

必須ケース（**実測データ §1.1 を固定値で再現**）:
1. **カット隣接は snap**: 境界 `[0, 15.30, 25.133, 45.533, ...]`、字幕 start/end が
   15.360/25.280/45.600 → それぞれ 15.30/25.133/45.533 に吸着。
2. **カット無しは不動**: 20.640（最寄り境界 21.117・差0.477 > tol）→ **変化しない**（最重要・回帰防止）。
3. **境界上は不動**: 0.000 → 0.000（差0・no-op）。
4. **超過の解消**: end 45.600 > 最終境界 45.533（差0.067 ≤ tol）→ 45.533 に吸着。
5. **contiguous 維持**: 前字幕 end == 次字幕 start の共有時刻が snap される場合、両方が同一境界へ
   動き、前end == 次start を保つ（隙間/重なりを作らない）。
6. **反転ガード**: 短い字幕で start と end が同一境界へ寄る → start>=end を作らず元値維持。
7. **境界空 / パース不能**: `boundaries=[]` → SRT 文字列そのまま返す。
8. `_fcpxml_time_to_seconds`: `'27/60s'→0.45`, `'0s'→0.0`, `'5s'→5.0`。
9. `parse_fcpxml_cut_boundaries`: 合成 fcpxml 文字列（映像 ref と wav ref 混在・同 offset 重複）から
   **映像トラックのみ**で境界を取り、重複が無いこと・最終 offset+duration を含むことを確認。
10. **pipeline ゲート**: `snap_srt=False` または premiere(`is_fcpxml=False`)では SRT が**不変**
    （DI モックで `run_pipeline` を回し、出力 SRT がスナップ前と一致）。

`venv/Scripts/python.exe -m pytest tests/ -q` で全 green。

---

## 5. 完了の定義（DoD）

1. 上記テスト追加 + 既存テスト全 green。
2. `python src/app.py` 起動・目視: チェックボックスが出る／字幕OFF・premiere選択で disabled。
3. **実機 DaVinci**（検証素材 `2026-06-20 10-56-29.mp4`・resolve 出力 → 取込）:
   - 字幕切替え **15.36→15.30 / 25.28→25.133 / 45.60→45.533** が**カット境界に乗る**。
   - **20.64 の遷移は動かない**（発話中＝カット無し。音とズレないこと）を目視確認。
   - ※実機目視はユーザー側で 1 回（合成テストで機構は証明済みの前提）。
4. `pipeline.py` / `subtitles.py` が customtkinter / `self` を参照しない（UI 非依存）を維持。
5. MEMORY.md に決定追記。新たな失敗は PITFALLS.md。CHANGELOG `[Unreleased]` の Added に
   「字幕をカット境界へスナップ」を追記（MINOR 機能。バージョン確定はリリース時）。

---

## 6. コミット（AGENTS §6.1）

Gemini が書いた実装/テストは **Gemini がコミット**。Conventional Commits・1論理変更・
生成物（build/dist/venv/`_tracks`）は含めない。設計と実コードに矛盾があれば勝手に直さず
MEMORY.md に記録し Opus/ユーザーへ確認。

---

## 付録: 実測スナップ結果（期待値の根拠）

```
検証素材 2026-06-20 10-56-29.mp4 / margin=0.2 / tolerance=0.35
カット: 44 clip / 45 boundary / total 45.533s
  srt 0.000  -> 0.0000  (+0.000) 不動（境界上）
  srt 15.360 -> 15.3000 (-0.060) snap
  srt 20.640 -> 21.1167 (+0.477) 不動（tol超＝カット無し・発話中）
  srt 25.280 -> 25.1333 (-0.147) snap
  srt 45.600 -> 45.5333 (-0.067) snap（超過も解消）
真のカット隣接差 ≤0.147 / 偽の差 0.477 → tol 0.35 で完全分離
```
