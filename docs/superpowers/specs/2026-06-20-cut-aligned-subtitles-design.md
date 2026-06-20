# 設計書 — カット整合字幕（Cut-Aligned Subtitles）

> 🧠頭脳(Opus) → 🔧作業(Gemini) ハンドオフ設計書。実装着手前に AGENTS.md（§4 / §6.1）と
> PITFALLS.md を必読。本設計は **2026-06-20 の SRT-snap(後処理) を「字幕生成モデルの作り直し」へ置換**する。
> 関連: MEMORY 2026-06-20 03:15 / 12:30 / 14:30、PITFALLS 2026-06-20(margin-inset)。

---

## 0. 一行サマリ

字幕を **whisper の word-level timestamp** で生成し、**全カット境界に必ず字幕境界が乗る**よう
再分割する。カット境界は **auto-editor `--export v1`** から NLE 形式非依存に取得する。
結果、DaVinci / Premiere / FCP のどれでも同一の `.srt` が、各カット開始に整合する。

---

## 1. 背景・なぜ作り直すか

### 1.1 ユーザーが求める動作（確定）
- 「カットが N 分割されたら、各カット開始タイミングに字幕境界が乗る」。
- 1 カットクリップ内に長い発話があれば、**カット境界では必ず分割**しつつ、クリップ内は
  whisper の文単位でさらに分割してよい（**字幕数 ≥ カット数**）。
- どの NLE（DaVinci / Premiere / FCP）でも同じ出力になること。

### 1.2 旧方式（SRT-snap・2026-06-20 14:30 実装）の限界
- 旧方式は whisper の自然分割結果を、近いカット境界へ **tolerance 内で吸着(nudge)** する後処理。
- 限界: ①字幕境界とカット境界が 1:1 にならない（whisper が決めた分割数のまま）。
  ②tolerance を外れたカットには乗らない。③fcpxml 専用（premiere 非対応）。
- ユーザーの要求は「カット境界を起点に字幕を切る」＝**分割そのものを作り直す**必要があり、
  後処理の吸着では原理的に満たせない。→ 本設計で置換する。

### 1.3 同期の前提（不変）
- 字幕は **カット後音声**（pipeline 2a で抽出する `{stem}_temp_audio.wav`）に対して生成する。
  whisper の word timestamp は **カット後タイムライン座標の秒**であり、NLE タイムライン・
  カット境界(fcpxml offset)と同一座標にある（CONTEXT §1 / ARCHITECTURE §3）。
- 2a と step1（カット）は margin/threshold を一致させること（P-2 厳守・不変）。

---

## 2. カット境界の取得（v1 正準化）

### 2.1 方式
- NLE 形式に依存しない正準ソースとして **`auto-editor --export v1`** の JSON を使う。
- 出力例（実測 / auto-editor 29.3.1）:

```json
{ "version": "1", "source": "...", "chunks": [ [0, 22, 1.0], [22, 30, 99999.0] ] }
```

- 各 chunk = `[start_frame, end_frame, speed]`（フレームは timebase=tb のグリッド）。
  - `speed == 99999.0` … 無音として**カット（除去）** → タイムラインに出ない。
  - それ以外（`1.0` 等）… **保持(kept)** → タイムラインに 1 クリップとして出る。

### 2.2 タイムライン境界の算出
- 保持 chunk を出現順に連結したものがタイムライン。各保持 chunk の尺 = `(end-start)/tb` 秒。
- 境界集合（秒・昇順）:
  ```
  boundaries = [0.0]
  acc = 0.0
  for chunk in chunks where speed != 99999.0:
      acc += (chunk.end - chunk.start) / tb
      boundaries.append(acc)   # 各保持クリップの終端 = 次クリップ開始 = カット境界
  ```
  - `boundaries[0]=0.0`(先頭) … `boundaries[-1]`(全長)。隣接保持クリップは連続（gap無し）。

### 2.3 timebase(tb) の取得とピン留め
- v1 の frame→秒 変換に tb が要るが、v1 JSON は tb を含まない。
- **`ffprobe` で source の fps を読む**（`r_frame_rate`、例 `60/1`→60.0）。
  - 実装: `autoeditor.probe_fps(inp) -> float`。`ffprobe -v error -select_streams v:0
    -show_entries stream=r_frame_rate -of default=...` を `subprocess.run(encoding="utf-8",
    errors="replace")`（P-6）で呼び、`"60/1"` を有理数評価。失敗時 `None`。
- **v1 export 実行時に `-tb <fps>` を明示**してグリッドを固定する。
  - step1（ユーザー指定形式の出力）の tb はデフォルト（=source fps）なので、同じ fps を
    v1 にも渡せば両者のフレームグリッドが一致 → v1 境界が取込タイムラインと厳密一致する。
  - ⚠ **step1 のコマンドは一切変えない**（既存の出力挙動を壊さない）。tb のピン留めは
    v1 export 側だけに行う。
- 前提: **CFR**（固定フレームレート）。VFR や fps 不一致は既知の対象外（MEMORY 2026-06-20 03:15）。

### 2.4 失敗時フォールバック
- `probe_fps` が None / v1 export 失敗 / chunks 解析不能 / 境界 0 個 のいずれでも、
  **再分割をやめて whisper 自然分割の字幕をそのまま採用**（字幕を壊さない・後述 §4 トグルOFF相当）。

---

## 3. 字幕再構成アルゴリズム（`src/subtitles.py`）

### 3.1 入力
- `words: list[tuple[float,float,str]]` … whisper word-level（`(start, end, word)` 秒・昇順）。
- `natural_segments: list[tuple[float,float]]` … whisper の自然セグメント境界（文区切り由来の
  break を得るため。各 segment の `start` を文境界候補に使う）。
- `boundaries: list[float]` … §2 のカット境界（昇順・重複除去済み）。

### 3.2 手順（`build_cut_aligned_srt(words, natural_segments, boundaries) -> str`）
1. **break points** を作る:
   `breaks = sorted(set(boundaries) | set(seg.start for seg in natural_segments))`。
   - 数値の微小ゆらぎ吸収のため、ミリ秒丸め（`round(t,3)`）で集合化する。
2. 連続する `breaks[i] … breaks[i+1]` を字幕区間とし、**word.start が `[breaks[i], breaks[i+1])`
   に入る単語**を連結（前後 strip・単語間は半角空白、日本語は whisper 出力の語片をそのまま連結）。
3. その区間の字幕:
   - `start = breaks[i]`（**カット境界由来なら offset と厳密一致**。文境界由来なら whisper 時刻）。
   - `end   = min(区間内の最終 word.end, breaks[i+1])`（末尾無音/margin に字幕を残さない）。
4. **空区間スキップ**: 単語ゼロの区間は字幕を作らない（カット間が無音の場合など）。
5. **ガード**:
   - `start >= end` になる字幕は作らない（ゼロ/負尺の排除）。
   - 連番は 1 から振り直す。本文・改行は whisper 語をそのまま。
6. `format_timestamp` で `HH:MM:SS,mmm --> HH:MM:SS,mmm` を構築して返す。

> contiguous は **共有 break 値**で自然に保たれる（前字幕 end ≤ 次字幕 start。end をクランプ
> するため末尾無音中は字幕無し＝微小 gap は許容＝可読性優先）。
> ⚠ 字幕の**個数・順序は break で決まる**。本文は word の機械的連結（whisper の語順を維持）。

### 3.3 単語の区間割当の堅牢性
- カット境界は無音（margin 部）に位置するため、単語がカット境界を跨ぐことは通常無い。
  割当は **word.start 基準**で行い、跨ぎは無視してよい（start が属す区間へ）。

### 3.4 旧コードの扱い
- 削除: `snap_srt_to_boundaries` / `parse_fcpxml_cut_boundaries` / `_fcpxml_time_to_seconds`
  / 定数 `SRT_SNAP_TOLERANCE_EXTRA`（v1 方式で不要）。
- 流用: `parse_timestamp` / `format_timestamp` / `add_cuda_dll_dirs` / `resolve_device` 等は不変。
- pipeline の旧 2d（snap ブロック）は §4 の新 2d へ差し替える。

---

## 4. pipeline 統合（`src/pipeline.py`）

### 4.1 パラメータ
- `PipelineParams.snap_srt: bool = True` を**流用**（名前は据置で意味を「カット整合再分割」に変更。
  リネームは presets 互換の都合で行わない。コメントで意味を明記）。

### 4.2 2b（transcribe）の変更
- `snap_srt and is_cut_align_possible` のとき **`word_timestamps=True`** で transcribe し、
  word-level を集める。OFF のときは現行どおり（word_timestamps 無し・自然分割をそのまま .srt 化）。
- DI フック `transcribe` の戻りは現行 `(seg_iter, info)`。word を取れるよう **セグメントの
  `.words` を使う**（faster-whisper は `word_timestamps=True` 時に各 segment へ `words` を付与）。
  - 実 whisper 経路: `model.transcribe(str(temp_wav), beam_size=5, language=None,
    word_timestamps=True)`。
  - PITFALLS 2026-06-17（遅延ジェネレータ）に従い `list(seg_iter)` で**デコードを完走**させてから
    words/segments を取り出す（GPU フォールバックの try 内で完走）。
- 自然分割の .srt（OFF 用・フォールバック用）も従来どおり作れるよう、segments の
  `(start,end,text)` は引き続き保持する。

### 4.3 2d（新・カット整合再分割）
旧 snap ブロックを置換。字幕生成成功時かつトグル ON のとき:
```
if params.snap_srt and result.srt_path and not result.stopped:
    try:
        fps = probe_fps(inp)
        boundaries = []
        if fps:
            v1_json = out_dir / f"{inp.stem}_cuts_v1.json"   # 一時ファイル
            cmd = build_v1_export_cmd(ae_path, inp, params.margin, params.threshold, v1_json, fps)
            # 既存の _run_streaming で実行（停止監視・即時kill 踏襲）
            ok = _run_streaming(cmd, on_log, should_stop, ...)
            if ok and v1_json.exists():
                boundaries = parse_v1_boundaries(v1_json, fps)
        if boundaries:
            srt = build_cut_aligned_srt(words, natural_segments, boundaries)
            if srt.strip():
                result.srt_path.write_text(srt, encoding="utf-8")
                on_log(tr("log_srt_cut_aligned"), "muted")
        # boundaries 空 → 何もしない（2b の自然分割 .srt をそのまま採用＝フォールバック）
    except Exception:
        on_log(tr("log_unexpected", traceback.format_exc()), "error")
    finally:
        # 一時 v1 json を掃除
        try:
            if v1_json.exists(): v1_json.unlink()
        except Exception: pass
```
- **配置**: 2b（字幕書込）後、`finally`（`_tracks` 掃除）より前。premiere でも実行（形式非依存）。
- **`is_fcpxml` ガードは付けない**（v1 は全形式共通）。`is_fcpxml` を使う既存処理
  （relocate / `_tracks`）は不変。
- v1 一時 json は `out_dir` に出し、必ず掃除（`_tracks` と同様、入力隣を汚さない）。

### 4.4 autoeditor.py
- `build_v1_export_cmd(ae_path, inp, margin, threshold, out_json, tb) -> list[str]`:
  `[ae_path, str(inp), "--margin", f"{margin}s", "--edit", f"audio:threshold={threshold}%",
   "--export", "v1", "-tb", str(int(tb)), "--output", str(out_json), "--no-open"]`
  - margin/threshold は step1/2a と一致（P-2）。パスは `.resolve()`（P-3）。
- `probe_fps(inp) -> float | None`: §2.3。

---

## 5. UI / presets / i18n

### 5.1 app.py（チェックボックス流用）
- 既存 `snap_srt_checkbox` を流用。**premiere 時の disabled を撤廃**（全形式で有効）。
  → `_update_*` の disable 条件は「字幕 OFF のときだけ disabled」に変更（`is_fcpxml` 分岐削除）。
- 既定 ON 維持。`_collect_settings`/`_apply_settings` の `snap_srt` 往復は不変。

### 5.2 presets.py
- `SETTING_KEYS` の `"snap_srt"` は不変（意味が変わるだけ・保存互換維持）。

### 5.3 i18n（ja/en 両方・§4 必須）
- 文言は流用しつつ、意味に合わせ微修正してよい:
  - `snap_srt_label`: ja `字幕をカット境界で分割する` / en `Split subtitles at cut boundaries`
    （旧「合わせる」より動作が正確。変更する場合は ja/en 同時）。
- ログキー追加:
  - `log_srt_cut_aligned`: ja `  字幕をカット境界で分割しました` / en `  Split subtitles at cut boundaries`
- 旧 `log_srt_snapped` は未使用なら削除（i18n の両言語から）。

---

## 6. テスト（`tests/`・実 whisper/auto-editor 無し）

`src/subtitles.py` の純関数を中心に DI/合成データで検証。
1. `parse_v1_boundaries`: 合成 chunks（kept/cut 混在）→ 境界が kept 累積尺・cut 除外・先頭0/末尾全長を含む。
   - 例 `chunks=[[0,30,1.0],[30,40,99999],[40,70,1.0]], tb=10` → `[0.0, 3.0, 6.0]`。
2. `build_cut_aligned_srt`:
   - ①**カット境界で必ず分割**: 1 つの whisper 自然セグメント内にカット境界がある → 2 字幕に割れ、
     2 つ目の start == カット境界（厳密一致）。
   - ②**文内追加分割**: 1 カット内に whisper 文境界が 2 つ → 字幕数 > カット数。
   - ③**カット由来 start の厳密一致**: start がカット境界値とビット一致（round(3) 一致）。
   - ④**空区間スキップ**: 単語ゼロのカット間 → 字幕を作らない。
   - ⑤**contiguous/反転ガード**: 共有 break で前 end ≤ 次 start、ゼロ尺字幕を作らない。
   - ⑥**境界空フォールバック**: `boundaries=[]` → （pipeline 側で）自然分割が採用される＝再構成しない。
3. `probe_fps`: ffprobe をモック（`"60/1\n"`→60.0、異常→None）。
4. pipeline:
   - `snap_srt=True` + boundaries 取得成功（v1/ffprobe をモック）→ 出力 srt がカット整合（境界で分割）。
   - `snap_srt=False` → word_timestamps 経路を通らず自然分割 srt（現行）と一致。
   - v1 失敗/`probe_fps`=None → 自然分割 srt のまま（フォールバック・字幕不変）。
   - 既存テスト（reorder / relocate / tracks 掃除 / gpu fallback）は不変で全 green。

`./.venv/Scripts/python.exe -m pytest tests/ -q` 全 green ＋ `ruff check src/ tests/` クリーン
（W293/I001 を残さない・PITFALLS 2026-06-20 lint）。

---

## 7. 完了の定義（DoD）

1. 上記テスト追加＋既存全 green、ruff クリーン。
2. `python src/app.py` 起動・目視: チェックボックスが出る／字幕 OFF で disabled／**premiere 選択でも
   enabled**（旧仕様からの変化点）。
3. 実機検証（ユーザー・素材 `2026-06-20 10-56-29.mp4`・resolve 出力 → DaVinci 取込）:
   - **各カット開始に字幕境界が乗る**（全カット）。長い発話のクリップ内では文単位の追加字幕が
     出てよいが、**カット位置の字幕は必ずカット開始と一致**。
   - 可能なら premiere(.xml) 出力でも同じ .srt が整合することを確認（同一 srt のため原理上一致）。
4. `subtitles.py` / `pipeline.py` が customtkinter / `self` を参照しない（UI 非依存）を維持。
5. MEMORY.md に決定追記。新たな失敗は PITFALLS.md。CHANGELOG `[Unreleased]` を更新
   （SRT-snap を本方式へ置換した旨。MINOR 機能。未リリースなので Added の差し替えで可）。

---

## 8. 対象外・非変更
- VFR / fps 不一致（CFR 前提・既知の対象外）。
- `_reorder_fcpxml_tracks` / relocate / `_tracks` 掃除 / GPU 経路 / margin·threshold 同期は不変。
- premiere(.xml) の境界**パース**は不要（v1 で代替）。

## 9. コミット（AGENTS §6.1）
Gemini が書いた実装/テストは **Gemini がコミット**。Conventional Commits・1 論理変更・
生成物は含めない。設計と実コードに矛盾があれば勝手に直さず MEMORY.md に記録し Opus/ユーザーへ確認。
