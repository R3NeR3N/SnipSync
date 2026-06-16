# P3 — code-review 指摘の修正（設計: Opus 4.8 → 実装: Gemini）

> 出典: `feat/p1-refactor` への /code-review high。確定5件。実装は本書に従う。
> i18n は **ja/en 両方**を必ず追加（AGENTS §4.1 / PITFALLS P-1）。完了後 `python src/app.py` で目視確認。

優先度: #1（実バグ）> #2（i18n違反）> #3 #5（軽微）> #4（将来用ガード）。
#1 と #3 は同じブロック（`pipeline.py` 2b）を触るので**まとめて実装**する。

---

## 修正#1 + #3 — GPUフォールバックの取りこぼし & compute_type 未使用（`src/pipeline.py` 172–209）

### 問題
- faster-whisper の `model.transcribe()` は**遅延ジェネレータ**を返す。実デコードは `segments` を**反復するとき**（L213 の SRT 書き込みループ）に起きる。
- 現状 GPU フォールバックの `try/except`（L195–201）は **model 構築と transcribe() 呼び出しまで**しか覆っていない。CUDA の実行時エラー（OOM 等、デコード途中で多発）は L213 で送出され、外側 except（L231）に落ちて `log_unexpected` で握りつぶされる → **CPU 再試行が走らない**。「GPU失敗時CPUフォールバック」の約束がよくある失敗形で破れている。
- 加えて L176 で `device, compute_type = resolve_device(...)` と受けているのに、実パス（非DI）は L196=`"int8_float16"` / L203=`"int8"` を**ハードコード**して `compute_type` を捨てている（#3）。フォールバックで `device="cpu"` にしても compute_type は cuda 用のまま残る潜在ズレもある。

### 設計
2b ブロックを「**デコードを try 内で完了させてからSRTを書く**」構造に直す。デバイス選択ヘルパを1つにまとめ、フォールバック時は **device と compute_type を同時に CPU 用へ**切り替える。

```python
# 2b. Transcribe Temp WAV
if temp_success and not result.stopped:
    on_log(tr("log_srt_analyze", params.model_size), "info")
    try:
        device, compute_type = resolve_device(params.use_gpu)

        def _decode(dev, ctype):
            # transcribe を呼び、ジェネレータをリスト化して“この場で”デコードを完走させる。
            # → CUDA 実行時エラーをこの try 内で確実に捕捉できる。
            if transcribe is not None:
                seg_iter, inf = transcribe(temp_wav, params.model_size)
            else:
                from faster_whisper import WhisperModel
                model = WhisperModel(params.model_size, device=dev, compute_type=ctype)
                seg_iter, inf = model.transcribe(str(temp_wav), beam_size=5, language=None)
            return list(seg_iter), inf   # ← list() でデコード完走（例外はここで出る）

        try:
            if device == "cuda":
                segments, info = _decode("cuda", compute_type)
                on_log(tr("log_device", "cuda"), "muted")
            else:
                segments, info = _decode("cpu", compute_type)
                on_log(tr("log_device", "cpu"), "muted")
        except Exception:
            if device == "cuda":
                on_log(tr("log_gpu_fallback"), "warn")
                device, compute_type = "cpu", "int8"   # ← device/compute_type を同時に CPU へ
                segments, info = _decode("cpu", compute_type)
                on_log(tr("log_device", "cpu"), "muted")
            else:
                raise   # CPU でも失敗なら外側 except へ（log_unexpected）

        on_log(tr("log_lang_detected", info.language, info.language_probability), "muted")

        # SRT 書き込み（segments は確定済みリスト）
        with open(output_srt, "w", encoding="utf-8") as srt_file:
            for i, segment in enumerate(segments, start=1):
                if should_stop():
                    result.stopped = True
                    break
                start = format_timestamp(segment.start)
                end = format_timestamp(segment.end)
                text = segment.text.strip()
                srt_file.write(f"{i}\n{start} --> {end}\n{text}\n\n")
                on_log(f"  [{start} -> {end}] {text}", "muted")

        if should_stop() or result.stopped:
            result.stopped = True
            on_log(tr("log_stopped"), "warn")
        else:
            on_log(tr("log_srt_done"), "success")
            on_log(f"   {output_srt.name}", "success")
            result.srt_path = output_srt
    except Exception:
        on_log(tr("log_unexpected", traceback.format_exc()), "error")
```

### トレードオフ（要記録）
- `list(seg_iter)` で**デコードを一括完走**させるため、これまで「デコードしながら1字幕ずつ出ていたログ（L222）」が**デコード完了後にまとめて出る**ようになる。DESIGN「進捗を隠さない」を満たすため、`log_srt_analyze` の直後にデコード中である旨が伝わるログ（既存 `log_srt_analyze` で可）を残す。GPU は opt-in かつ稀なので、フォールバック健全性（正確性）を優先する。この判断を MEMORY に残すこと。
- `compute_type` を両 WhisperModel 呼び出しに渡す（#3 解消）。フォールバック時は `"cpu","int8"` を同時設定。

### テスト（`tests/test_pipeline.py`）
- 既存 DI フォールバックテストを、**「最初の反復で例外」**ではなく **`list()` 時に例外**を出すモックでも通るよう確認（モック transcribe が返すジェネレータ／リストの消費時に raise）。
- 追加: cuda 指定 → `_decode` が例外 → CPU 再試行で成功 → `segments` 確定・`info` 取得・SRT 生成、を検証。両デバイス失敗時は `log_unexpected`。

---

## 修正#2 — whisper 未導入メッセージのハードコード（`src/app.py:702` / `src/i18n.py`）

### 問題
`main()` で `app._log("⚠ faster-whisper がインストールされていない…", "warn")` と**日本語直書き**。i18n キー無し（grep 確認済）。英語UIでも日本語のまま出る。AGENTS §4.1 / PITFALLS P-1 違反。

### 設計
i18n に `log_whisper_unavailable` を ja/en 追加し、呼び出しを差し替え。

- `src/i18n.py`（ja, `log_welcome` 付近）:
  - `"log_whisper_unavailable": "⚠ faster-whisper がインストールされていないため、字幕機能は利用できません。",`
- `src/i18n.py`（en）:
  - `"log_whisper_unavailable": "⚠ faster-whisper is not installed; subtitle generation is unavailable.",`
- `src/app.py:702`:
  - `app._log(app.t("log_whisper_unavailable"), "warn")`

> 注: このログは UI 言語確定後（`main()` 内 `app` 生成後）に出るため `app.t(...)` で正しく言語反映される。

---

## 修正#5 — `log_error` の空 detail（`src/i18n.py` / `src/pipeline.py:138,164`）

### 問題
`tr("log_error", rc, "")` の第2引数が常に空。テンプレは `…\n詳細:\n{}`（ja）/`…\nDetails:\n{}`（en）で、空の「詳細:」だけが残る。stderr は `stderr=STDOUT`（pipeline L34）で **stdout にマージされ既にライブ表示**されているため、detail プレースホルダは不要。

### 設計
テンプレを単一プレースホルダ化し、呼び出しを `tr("log_error", rc)` に。

- `src/i18n.py` ja L41: `"log_error": "❌ エラーが発生しました（終了コード: {}）",`
- `src/i18n.py` en L111: `"log_error": "❌ Error occurred (exit code: {})",`
- `src/pipeline.py` L138, L164: `on_log(tr("log_error", rc), "error")` / `on_log(tr("log_error", rc_temp), "error")`

---

## 修正#4 — プリセットの無効モデルガード（`src/app.py:449–453`）

### 問題
`_apply_settings` は `s["model"]` を**無条件で** `model_key_var` にセットし、`model_options` に無いキーでも表示用 `model_display_var` だけ更新をスキップ → 表示が古いまま無効キーが WhisperModel に渡り得る。発火条件はモデル一覧の改名/削除（将来）。

### 設計
キーが有効なときだけ key と display を**両方**セット。無効なら現状維持（変更しない）。

```python
if "model" in s:
    opts_dict = self.t("model_options")
    if s["model"] in opts_dict:
        self.model_key_var.set(s["model"])
        self.model_display_var.set(opts_dict[s["model"]])
    # 無効キーは無視（現在の選択を維持）
```

---

## 完了条件
1. `pytest tests/` 全green（#1 の新テスト含む）。
2. `python src/app.py` 起動 → 言語切替で whisper 未導入ログ（#2）が ja/en 切替できる目視確認。
3. i18n ja/en 両方追加済み。
4. MEMORY に実装メモ＋#1 のトレードオフ（ライブログ→一括ログ）を追記。
5. PITFALLS に「faster-whisper transcribe は遅延ジェネレータ。例外はジェネレータ消費時に出る」を追記（本レビューで発見）。
