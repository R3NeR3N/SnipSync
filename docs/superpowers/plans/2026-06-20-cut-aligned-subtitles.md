# カット整合字幕（Cut-Aligned Subtitles）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **本プロジェクトの分担**: 実装は 🔧Gemini が担当（AGENTS §6.1 作者一致＝Gemini がコミット）。
> 設計書は `docs/superpowers/specs/2026-06-20-cut-aligned-subtitles-design.md`。

**Goal:** 字幕を whisper の word-level timestamp で生成し、全カット境界に必ず字幕境界が乗るよう再分割する（旧 SRT-snap 後処理を置換）。

**Architecture:** カット境界を `auto-editor --export v1`（NLE 形式非依存・ffprobe で fps→`-tb` ピン留め）から取得。whisper word を「カット境界 ∪ 文境界」で再分割し、各カット開始に厳密一致する `.srt` を全 NLE 共通で生成。純ロジックは `src/subtitles.py` / `src/autoeditor.py`、統合は `src/pipeline.py`、UI は `src/app.py`。

**Tech Stack:** Python 3.10+, auto-editor 29.x, faster-whisper 1.x, pytest, ruff, ffprobe(FFmpeg)。

## Global Constraints

- 文字列追加は必ず `I18N` の `ja`/`en` 両方へ（AGENTS §4.1）。
- 外部プロセスは `subprocess.run(..., encoding="utf-8", errors="replace")`（P-6）。パスは `.resolve()`（P-3）。
- margin/threshold は step1(カット)/2a(WAV抽出)/v1 export で必ず一致（P-2）。
- `src/subtitles.py` / `src/pipeline.py` は customtkinter / `self` を参照しない（UI 非依存）。
- 各タスク末で `./.venv/Scripts/python.exe -m pytest tests/ -q` 全 green ＋ `./.venv/Scripts/python.exe -m ruff check src/ tests/` クリーン（W293/I001 を残さない）。
- 1 コミット=1 論理変更（Conventional Commits）。生成物（build/dist/venv/`_tracks`/`*_cuts_v1.json`）はコミットしない。
- 前提: CFR（VFR は対象外・既知）。

---

### Task 1: `probe_fps`（autoeditor.py）

**Files:**
- Modify: `src/autoeditor.py`（末尾に追加）
- Test: `tests/test_autoeditor.py`（無ければ新規）

**Interfaces:**
- Produces: `probe_fps(path) -> float | None` … ffprobe で動画の `r_frame_rate` を読み fps を返す。失敗時 None。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_autoeditor.py`

```python
import subprocess
from autoeditor import probe_fps


def test_probe_fps_parses_rational(monkeypatch):
    class R:
        stdout = "60/1\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert probe_fps("video.mp4") == 60.0


def test_probe_fps_parses_integer(monkeypatch):
    class R:
        stdout = "30\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert probe_fps("video.mp4") == 30.0


def test_probe_fps_empty_returns_none(monkeypatch):
    class R:
        stdout = "\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert probe_fps("video.mp4") is None


def test_probe_fps_zero_denominator_returns_none(monkeypatch):
    class R:
        stdout = "0/0\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    assert probe_fps("video.mp4") is None


def test_probe_fps_exception_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("ffprobe missing")
    monkeypatch.setattr(subprocess, "run", boom)
    assert probe_fps("video.mp4") is None
```

- [ ] **Step 2: テストが落ちることを確認**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_autoeditor.py -q`
Expected: FAIL（`ImportError: cannot import name 'probe_fps'`）

- [ ] **Step 3: 実装** — `src/autoeditor.py` 末尾に追加

```python
def probe_fps(path):
    """ffprobe で動画の r_frame_rate を読み fps(float) を返す。失敗時 None。

    v1 export の frame->秒 変換 timebase に使う（CFR 前提）。
    """
    import subprocess
    from pathlib import Path
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(Path(path).resolve())],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        out = (result.stdout or "").strip()
        if not out:
            return None
        if "/" in out:
            num, den = out.split("/")
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        return float(out)
    except Exception:
        return None
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_autoeditor.py -q`
Expected: PASS（5 件）

- [ ] **Step 5: コミット**

```bash
git add src/autoeditor.py tests/test_autoeditor.py
git commit -m "feat: ffprobeで動画fpsを読むprobe_fpsを追加(v1境界の秒変換用)"
```

---

### Task 2: `build_v1_export_cmd`（autoeditor.py）

**Files:**
- Modify: `src/autoeditor.py`
- Test: `tests/test_autoeditor.py`

**Interfaces:**
- Produces: `build_v1_export_cmd(ae_path, inp, margin, threshold, out_json, tb) -> list[str]` … auto-editor `--export v1 -tb <fps>` コマンドを組む。margin/threshold は他コマンドと一致。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_autoeditor.py` に追記

```python
from autoeditor import build_v1_export_cmd


def test_build_v1_export_cmd_shape():
    cmd = build_v1_export_cmd("auto-editor", "in.mp4", 0.2, 4.0, "out.json", 60.0)
    assert cmd[0] == "auto-editor"
    assert "--export" in cmd and cmd[cmd.index("--export") + 1] == "v1"
    assert "-tb" in cmd and cmd[cmd.index("-tb") + 1] == "60"
    assert "--margin" in cmd and cmd[cmd.index("--margin") + 1] == "0.200s"
    assert "--edit" in cmd and cmd[cmd.index("--edit") + 1] == "audio:threshold=4.0%"
    assert "--no-open" in cmd
    out_i = cmd.index("--output") + 1
    assert cmd[out_i].endswith("out.json")


def test_build_v1_export_cmd_tb_rounds_to_int():
    cmd = build_v1_export_cmd("auto-editor", "in.mp4", 0.2, 4.0, "out.json", 59.94)
    assert cmd[cmd.index("-tb") + 1] == "60"
```

- [ ] **Step 2: テストが落ちることを確認**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_autoeditor.py -q`
Expected: FAIL（`ImportError: cannot import name 'build_v1_export_cmd'`）

- [ ] **Step 3: 実装** — `src/autoeditor.py`（`build_extract_wav_cmd` の後に追加）

```python
def build_v1_export_cmd(ae_path, inp, margin, threshold, out_json, tb):
    """auto-editor command: export cut decisions as v1 JSON (chunks).

    NLE 形式に依存しないカット境界の正準ソース。-tb で frame グリッドを
    source fps に固定し、step1 のデフォルト timebase と一致させる（P-2 と同じ
    margin/threshold）。
    """
    from pathlib import Path
    return [
        str(ae_path), str(inp),
        "--margin", f"{margin:.3f}s",
        "--edit", f"audio:threshold={threshold:.1f}%",
        "--export", "v1",
        "-tb", str(int(round(tb))),
        "--output", str(Path(out_json).resolve()),
        "--no-open",
    ]
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_autoeditor.py -q`
Expected: PASS（7 件）

- [ ] **Step 5: コミット**

```bash
git add src/autoeditor.py tests/test_autoeditor.py
git commit -m "feat: auto-editor v1 export(カット境界JSON)のコマンドビルダを追加"
```

---

### Task 3: `parse_v1_boundaries`（subtitles.py）

**Files:**
- Modify: `src/subtitles.py`
- Test: `tests/test_subtitles.py`

**Interfaces:**
- Produces: `parse_v1_boundaries(json_path, tb) -> list[float]` … v1 JSON の kept chunk 累積尺から境界（秒・昇順・重複除去）。先頭 0.0 含む。失敗/空→ `[]`。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_subtitles.py` に追記

```python
import json
from subtitles import parse_v1_boundaries


def test_parse_v1_boundaries_basic(tmp_path):
    # kept(30f) / cut(10f) / kept(30f)  @ tb=10  -> 境界 [0.0, 3.0, 6.0]
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"chunks": [[0, 30, 1.0], [30, 40, 99999.0], [40, 70, 1.0]]}), encoding="utf-8")
    assert parse_v1_boundaries(p, 10) == [0.0, 3.0, 6.0]


def test_parse_v1_boundaries_excludes_cut(tmp_path):
    # 全 cut -> kept 無し -> []
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"chunks": [[0, 30, 99999.0]]}), encoding="utf-8")
    assert parse_v1_boundaries(p, 10) == []


def test_parse_v1_boundaries_bad_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("not json", encoding="utf-8")
    assert parse_v1_boundaries(p, 10) == []


def test_parse_v1_boundaries_no_tb(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"chunks": [[0, 30, 1.0]]}), encoding="utf-8")
    assert parse_v1_boundaries(p, 0) == []
```

- [ ] **Step 2: テストが落ちることを確認**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_subtitles.py -k v1_boundaries -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 実装** — `src/subtitles.py`（`parse_timestamp` の後・SRT-snap 節に追加）

```python
def parse_v1_boundaries(json_path, tb):
    """auto-editor v1 JSON の kept chunk 累積尺からタイムライン境界(秒)を作る。

    chunk = [start_frame, end_frame, speed]。speed>=99999 は cut(除去)。
    kept chunk の尺 (end-start)/tb を累積し、各境界 + 先頭 0.0 を返す。
    解析不能/tb 無し/kept 無し -> []。
    """
    import json
    from pathlib import Path
    try:
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except Exception:
        return []
    chunks = data.get("chunks", [])
    if not chunks or not tb:
        return []
    boundaries = [0.0]
    acc = 0.0
    for chunk in chunks:
        try:
            start, end, speed = chunk[0], chunk[1], chunk[2]
        except (IndexError, TypeError):
            continue
        if speed >= 99999:
            continue
        acc += (end - start) / tb
        boundaries.append(round(acc, 6))
    if len(boundaries) <= 1:
        return []
    return sorted(set(boundaries))
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_subtitles.py -k v1_boundaries -q`
Expected: PASS（4 件）

- [ ] **Step 5: コミット**

```bash
git add src/subtitles.py tests/test_subtitles.py
git commit -m "feat: v1チャンクからカット境界(秒)を算出するparse_v1_boundariesを追加"
```

---

### Task 4: `build_cut_aligned_srt`（subtitles.py・核）

**Files:**
- Modify: `src/subtitles.py`
- Test: `tests/test_subtitles.py`

**Interfaces:**
- Consumes: `format_timestamp`（既存）。
- Produces: `build_cut_aligned_srt(words, natural_segments, boundaries) -> str`
  - `words: list[tuple[float,float,str]]`（start,end,word・カット後タイムライン秒）
  - `natural_segments: list[tuple[float,float]]`（whisper セグメントの start,end）
  - `boundaries: list[float]`（カット境界秒）
  - 戻り: 再分割した SRT 文字列（`boundaries` か `words` 空なら `""`）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_subtitles.py` に追記

```python
from subtitles import build_cut_aligned_srt


def _parse_blocks(srt):
    """SRT文字列 -> [(start_str, end_str, text), ...]"""
    blocks = []
    for chunk in srt.strip().split("\n\n"):
        lines = chunk.splitlines()
        if len(lines) >= 3:
            s, e = lines[1].split(" --> ")
            blocks.append((s, e, "\n".join(lines[2:])))
    return blocks


def test_cut_boundary_forces_split():
    # 1つの自然セグメント [0,4) 内にカット境界 2.0 がある -> 2字幕に割れる
    words = [(0.0, 0.9, "A"), (1.0, 1.9, "B"), (2.0, 2.9, "C"), (3.0, 3.9, "D")]
    natural = [(0.0, 4.0)]
    boundaries = [0.0, 2.0]
    blocks = _parse_blocks(build_cut_aligned_srt(words, natural, boundaries))
    assert len(blocks) == 2
    # 2つ目の字幕開始 = カット境界 2.0 に厳密一致
    assert blocks[1][0] == "00:00:02,000"


def test_sentence_split_within_cut():
    # 1カット [0,4) 内に文境界が2つ(0.0, 2.0) -> 字幕数 > カット数(1)
    words = [(0.0, 0.9, "A"), (1.0, 1.9, "B"), (2.0, 2.9, "C")]
    natural = [(0.0, 2.0), (2.0, 4.0)]
    boundaries = [0.0, 4.0]
    blocks = _parse_blocks(build_cut_aligned_srt(words, natural, boundaries))
    assert len(blocks) == 2  # カット1個でも文境界で2字幕


def test_empty_interval_skipped():
    # カット境界 [0,2,4] だが [2,4) に単語なし -> その字幕は作らない
    words = [(0.0, 0.9, "A"), (1.0, 1.9, "B")]
    natural = [(0.0, 2.0)]
    boundaries = [0.0, 2.0, 4.0]
    blocks = _parse_blocks(build_cut_aligned_srt(words, natural, boundaries))
    assert len(blocks) == 1


def test_no_zero_length_entries():
    words = [(0.0, 0.5, "A")]
    natural = [(0.0, 0.5)]
    boundaries = [0.0, 0.5]
    blocks = _parse_blocks(build_cut_aligned_srt(words, natural, boundaries))
    for s, e, _ in blocks:
        assert s != e  # ゼロ尺なし


def test_empty_boundaries_returns_empty():
    words = [(0.0, 0.5, "A")]
    assert build_cut_aligned_srt(words, [(0.0, 0.5)], []) == ""


def test_empty_words_returns_empty():
    assert build_cut_aligned_srt([], [(0.0, 0.5)], [0.0, 0.5]) == ""
```

- [ ] **Step 2: テストが落ちることを確認**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_subtitles.py -k cut_aligned -q`
Expected: FAIL（`ImportError`）。`test_empty_*` の名前は上記の通り、`-k cut_aligned` では拾えないため次の Step 4 で全 6 件確認する。

- [ ] **Step 3: 実装** — `src/subtitles.py`（`parse_v1_boundaries` の後に追加）

```python
def build_cut_aligned_srt(words, natural_segments, boundaries):
    """whisper word-level を「カット境界 ∪ 文境界」で再分割した SRT を返す。

    各区間 [b_i, b_{i+1}) に start が入る単語を 1 字幕に連結。
    カット境界由来の b_i は字幕 start に厳密一致する。空区間/ゼロ尺は除外。
    boundaries か words が空なら "" を返す（呼び出し側でフォールバック）。
    """
    if not boundaries or not words:
        return ""

    breaks = {round(b, 3) for b in boundaries}
    for seg_start, _seg_end in natural_segments:
        breaks.add(round(seg_start, 3))
    last_word_end = max(w[1] for w in words)
    breaks.add(round(last_word_end, 3))
    breaks = sorted(breaks)

    entries = []
    for i in range(len(breaks) - 1):
        b0, b1 = breaks[i], breaks[i + 1]
        seg_words = [w for w in words if b0 <= round(w[0], 3) < b1]
        if not seg_words:
            continue
        text = "".join(w[2] for w in seg_words).strip()
        if not text:
            continue
        start = b0
        end = min(max(w[1] for w in seg_words), b1)
        if start >= end:
            continue
        entries.append((start, end, text))

    out = []
    for idx, (start, end, text) in enumerate(entries, start=1):
        out.append(str(idx))
        out.append(f"{format_timestamp(start)} --> {format_timestamp(end)}")
        out.append(text)
        out.append("")
    return "\n".join(out)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_subtitles.py -q`
Expected: PASS（cut-aligned 6 件含む全 subtitles テスト green。※旧 snap テストは Task 5 で削除するためここでは未変更のまま共存）

- [ ] **Step 5: コミット**

```bash
git add src/subtitles.py tests/test_subtitles.py
git commit -m "feat: word-levelをカット境界で再分割するbuild_cut_aligned_srtを追加"
```

---

### Task 5: 旧 SRT-snap ロジックの撤去（subtitles.py / tests）

**Files:**
- Modify: `src/subtitles.py`（削除）
- Modify: `tests/test_subtitles.py`（旧 snap テスト削除）

**Interfaces:**
- Removes: `snap_srt_to_boundaries`, `parse_fcpxml_cut_boundaries`, `_fcpxml_time_to_seconds`, 定数 `SRT_SNAP_TOLERANCE_EXTRA`。
- 注意: これらは Task 6/7 で pipeline 側の import も外す。**Task 5 単独では pipeline がまだ旧名を import しているため `pytest tests/` 全体は一時的に赤になり得る**。本タスクは subtitles 単体（`tests/test_subtitles.py`）の green を確認し、pipeline の import 修正は Task 7 で行う。順序を守ること（Task 5 → 6 → 7 を連続実施）。

- [ ] **Step 1: 旧関数を削除** — `src/subtitles.py`

`snap_srt_to_boundaries` / `parse_fcpxml_cut_boundaries` / `_fcpxml_time_to_seconds` の 3 関数定義と、定数行 `SRT_SNAP_TOLERANCE_EXTRA = 0.15` を削除する。`parse_timestamp` / `format_timestamp` / `parse_v1_boundaries` / `build_cut_aligned_srt` / CUDA 系は残す。

- [ ] **Step 2: 旧 snap テストを削除** — `tests/test_subtitles.py`

`snap_srt_to_boundaries` / `parse_fcpxml_cut_boundaries` / `_fcpxml_time_to_seconds` を参照する全テスト関数（旧 9 ケース）と、それらだけが使う import を削除。`parse_timestamp` 単体テストがあれば残す。Task 3/4 で追加した v1/cut-aligned テストは残す。

- [ ] **Step 3: subtitles 単体テストが green**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_subtitles.py -q`
Expected: PASS（v1 4 + cut-aligned 6 + parse_timestamp 等。旧 snap 参照が残っていれば `NameError`/`ImportError` で落ちる→消し残しを除去）

- [ ] **Step 4: 残骸チェック**

Run: `./.venv/Scripts/python.exe -c "import ast,sys; src=open('src/subtitles.py',encoding='utf-8').read(); assert 'snap_srt_to_boundaries' not in src and 'parse_fcpxml_cut_boundaries' not in src and 'SRT_SNAP_TOLERANCE_EXTRA' not in src; print('clean')"`
Expected: `clean`

- [ ] **Step 5: コミット**

```bash
git add src/subtitles.py tests/test_subtitles.py
git commit -m "refactor: 旧SRT-snap関数(snap/parse_fcpxml/_fcpxml_time)を撤去"
```

---

### Task 6: pipeline 2b — word_timestamps 化＋word/自然セグメント収集

**Files:**
- Modify: `src/pipeline.py`（2b ブロック・上部 import・変数初期化）
- Modify: `tests/test_pipeline.py`（`DummySegment` に words 対応）

**Interfaces:**
- Consumes: `build_cut_aligned_srt`, `parse_v1_boundaries`（subtitles）, `build_v1_export_cmd`, `probe_fps`（autoeditor）。
- Produces: `run_pipeline` 内ローカル `srt_words: list[tuple[float,float,str]]` と `srt_natural_segs: list[tuple[float,float]]` を 2b で構築し 2d（Task 7）へ渡す。実 whisper 呼出に `word_timestamps=params.snap_srt` を付与。

- [ ] **Step 1: import を入れ替え** — `src/pipeline.py` 上部（現在 `from subtitles import (... parse_fcpxml_cut_boundaries ... snap_srt_to_boundaries ... SRT_SNAP_TOLERANCE_EXTRA ...)` と `from autoeditor import build_cut_cmd, build_extract_wav_cmd`）

変更後:
```python
from autoeditor import (
    build_cut_cmd,
    build_extract_wav_cmd,
    build_v1_export_cmd,
    probe_fps,
)
from subtitles import (
    add_cuda_dll_dirs,
    build_cut_aligned_srt,
    format_timestamp,
    parse_v1_boundaries,
    resolve_device,
)
```
（既存 import 群のうち `parse_fcpxml_cut_boundaries` / `snap_srt_to_boundaries` / `parse_timestamp` / `SRT_SNAP_TOLERANCE_EXTRA` は削除。`format_timestamp` / `resolve_device` / `add_cuda_dll_dirs` は残す。`parse_timestamp` が他で未使用なら import しない。）

- [ ] **Step 2: 2b 直前に収集用変数を初期化** — `src/pipeline.py`（`temp_success = False` の直後、`# 2a` の前）

```python
            temp_success = False
            srt_words = []
            srt_natural_segs = []
```

- [ ] **Step 3: 実 whisper 呼出に word_timestamps を付与** — `src/pipeline.py` 2b（現 `seg_iter, inf = model.transcribe(str(temp_wav), beam_size=5, language=None)`）

```python
                            seg_iter, inf = model.transcribe(
                                str(temp_wav), beam_size=5, language=None,
                                word_timestamps=params.snap_srt,
                            )
```

- [ ] **Step 4: segments 確定後に word/自然セグメントを収集** — `src/pipeline.py` 2b（`on_log(tr("log_lang_detected", ...))` の直後・SRT 書き込みループの前）

```python
                    srt_natural_segs = [(s.start, s.end) for s in segments]
                    srt_words = []
                    for s in segments:
                        for w in (getattr(s, "words", None) or []):
                            srt_words.append((w.start, w.end, w.word))
```

- [ ] **Step 5: テスト用 DummySegment に words を持たせる** — `tests/test_pipeline.py`

```python
class DummyWord:
    def __init__(self, start, end, word):
        self.start = start
        self.end = end
        self.word = word


class DummySegment:
    def __init__(self, start, end, text, words=None):
        self.start = start
        self.end = end
        self.text = text
        self.words = words
```

- [ ] **Step 6: 既存テストが green（words=None 既定でも壊れない）**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_pipeline.py -q`
Expected: 2b の word 収集は `getattr(..., None) or []` で None 安全のため既存テストは PASS。`import` 入替で Task 5 の旧名撤去とも整合（pipeline は新名のみ参照）。**もし `ImportError` が出たら Step 1 の import 修正漏れ。**

- [ ] **Step 7: コミット**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline 2bでword-level収集とword_timestamps化(カット整合の前段)"
```

---

### Task 7: pipeline 2d — snap を v1 境界＋再分割へ置換

**Files:**
- Modify: `src/pipeline.py`（旧 2d ブロックを置換）
- Modify: `src/i18n.py`（`log_srt_cut_aligned` 追加・`log_srt_snapped` 削除）
- Test: `tests/test_pipeline.py`（旧 `test_pipeline_srt_snap_gate` を新仕様へ）

**Interfaces:**
- Consumes: `srt_words`, `srt_natural_segs`（Task 6）, `probe_fps`, `build_v1_export_cmd`, `parse_v1_boundaries`, `build_cut_aligned_srt`, `_run_streaming`（既存）。
- i18n: `log_srt_cut_aligned`（muted）。

- [ ] **Step 1: i18n を更新** — `src/i18n.py`

`log_srt_snapped` の ja/en 2 行を削除し、両言語に追加:
```python
        "log_srt_cut_aligned": "  字幕をカット境界で分割しました",   # ja
```
```python
        "log_srt_cut_aligned": "  Split subtitles at cut boundaries",  # en
```
併せて `snap_srt_label` を意味に合わせ更新（ja/en 同時）:
```python
        "snap_srt_label": "字幕をカット境界で分割する",              # ja
        "snap_srt_label": "Split subtitles at cut boundaries",       # en
```

- [ ] **Step 2: 旧 2d を置換** — `src/pipeline.py`（現 `# 2d. 字幕境界をカット境界へスナップ…` ブロック全体 ≒ 14 行を以下で置換）

```python
            # 2d. 字幕をカット境界で分割（カット整合字幕・トグルON時・全形式共通）
            if params.snap_srt and result.srt_path and srt_words and not result.stopped:
                v1_json = output_ae.parent / f"{inp.stem}_cuts_v1.json"
                try:
                    fps = probe_fps(inp)
                    boundaries = []
                    if fps:
                        v1_cmd = build_v1_export_cmd(
                            ae_path, inp, params.margin, params.threshold, v1_json, fps,
                        )
                        rc_v1, stopped_v1 = _run_streaming(
                            v1_cmd, on_log=on_log, should_stop=should_stop,
                        )
                        if not stopped_v1 and rc_v1 == 0 and v1_json.exists():
                            boundaries = parse_v1_boundaries(v1_json, fps)
                    if boundaries:
                        srt = build_cut_aligned_srt(srt_words, srt_natural_segs, boundaries)
                        if srt.strip():
                            result.srt_path.write_text(srt, encoding="utf-8")
                            on_log(tr("log_srt_cut_aligned"), "muted")
                except Exception:
                    on_log(tr("log_unexpected", traceback.format_exc()), "error")
                finally:
                    try:
                        if v1_json.exists():
                            v1_json.unlink()
                    except Exception:
                        pass
```

- [ ] **Step 3: 旧 gate テストを新仕様へ書き換え** — `tests/test_pipeline.py` の `test_pipeline_srt_snap_gate`

旧テスト（fcpxml snap 前提）を削除し、以下 3 テストを追加。`probe_fps` と v1 JSON 生成をモックする（`MockPopen.write_output` が v1 コマンド時に JSON を書く）。

```python
import json as _json
import pipeline as _pipeline_mod


def _v1_writer(v1_path):
    """MockPopen 用: v1 export コマンドを見たら合成 v1 JSON を書く。"""
    def writer(cmd):
        if "v1" in cmd and "--output" in cmd:
            out = cmd[cmd.index("--output") + 1]
            # kept(60f)/cut(?)/kept(...)  @tb=60 -> 境界 [0.0, 1.0, ...]
            _Path = __import__("pathlib").Path
            _Path(out).write_text(
                _json.dumps({"chunks": [[0, 60, 1.0], [60, 120, 99999.0], [120, 180, 1.0]]}),
                encoding="utf-8",
            )
    return writer


def test_pipeline_cut_align_on(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs
    monkeypatch.setattr(_pipeline_mod, "probe_fps", lambda p: 60.0)

    def mock_transcribe(wav_path, model_size):
        seg = DummySegment(0.0, 4.0, "AB", words=[
            DummyWord(0.0, 0.9, "A"), DummyWord(2.0, 2.9, "B"),
        ])
        class Info:
            language = "en"; language_probability = 0.9
        return iter([seg]), Info()

    # MockPopen: cut/extract は通常成功、v1 export 時に JSON を書く
    # （既存 temp_dirs/monkeypatch の Popen パッチ方法に合わせ write_output=_v1_writer を渡す）
    ...  # ← 既存テストの Popen パッチ生成部を流用し、v1 コマンドで _v1_writer を発火させる

    params = PipelineParams(..., do_srt=True, snap_srt=True, transcribe=mock_transcribe)
    result = run_pipeline(params, on_log=stub_log, should_stop=lambda: False, tr=stub_tr)
    srt = result.srt_path.read_text(encoding="utf-8")
    # カット境界 1.0 で 2 字幕に割れ、2 つ目が 00:00:01,000 開始
    assert "00:00:01,000 -->" in srt


def test_pipeline_cut_align_off_keeps_natural(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs

    def mock_transcribe(wav_path, model_size):
        seg = DummySegment(0.0, 4.0, "hello")
        class Info:
            language = "en"; language_probability = 0.9
        return iter([seg]), Info()

    params = PipelineParams(..., do_srt=True, snap_srt=False, transcribe=mock_transcribe)
    result = run_pipeline(params, on_log=stub_log, should_stop=lambda: False, tr=stub_tr)
    srt = result.srt_path.read_text(encoding="utf-8")
    assert "hello" in srt  # 自然分割のまま（再分割しない）


def test_pipeline_cut_align_no_fps_fallback(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs
    monkeypatch.setattr(_pipeline_mod, "probe_fps", lambda p: None)

    def mock_transcribe(wav_path, model_size):
        seg = DummySegment(0.0, 4.0, "hello", words=[DummyWord(0.0, 0.9, "hello")])
        class Info:
            language = "en"; language_probability = 0.9
        return iter([seg]), Info()

    params = PipelineParams(..., do_srt=True, snap_srt=True, transcribe=mock_transcribe)
    result = run_pipeline(params, on_log=stub_log, should_stop=lambda: False, tr=stub_tr)
    srt = result.srt_path.read_text(encoding="utf-8")
    assert "hello" in srt  # fps 取得失敗 -> 自然分割のままフォールバック
```

> 実装者へ: 上記 `...` と `PipelineParams(...)` は、このファイル内の既存パスのテスト
> （例 `test_pipeline_*` で使う `temp_dirs` フィクスチャ・Popen パッチ・`stub_log`・
> `PipelineParams` の必須引数）の書き方を**そのまま流用**して埋めること。新しいモック
> 機構を発明しない。v1 JSON は `MockPopen.write_output=_v1_writer` で生成する。

- [ ] **Step 4: テストが green**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS（cut_align 3 件含む全テスト。旧 snap_gate は削除済み）

- [ ] **Step 5: lint クリーン**

Run: `./.venv/Scripts/python.exe -m ruff check src/ tests/`
Expected: `All checks passed!`（W293/I001 なし）

- [ ] **Step 6: コミット**

```bash
git add src/pipeline.py src/i18n.py tests/test_pipeline.py
git commit -m "feat: 2dをv1境界+word再分割へ置換しカット整合字幕を生成(全形式対応)"
```

---

### Task 8: UI — premiere disable 撤廃＋目視確認

**Files:**
- Modify: `src/app.py`（チェックボックス disable 条件）

**Interfaces:**
- Consumes: `snap_srt_label`（Task 7 で文言更新済み）。

- [ ] **Step 1: disable 条件から is_fcpxml を外す** — `src/app.py`（現 `if is_fcpxml: self.snap_srt_checkbox.configure(state="normal") else: ...disabled` のブロック ≒ 行 586-589）

字幕 ON のとき**常に** normal にする:
```python
            self.snap_srt_checkbox.configure(state="normal")
```
（字幕 OFF 側の `else` ブロックで `disabled` にする既存処理＝行 593 はそのまま残す。`is_fcpxml` 変数が他で未使用になっても削除不要。）

- [ ] **Step 2: 構築スモーク（プログラム的）**

Run:
```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'src'); import app as A; a=A.SnipSyncApp(); a.update(); print('label:', a.snap_srt_checkbox.cget('text')); a.destroy(); print('SMOKE OK')"
```
Expected: `label: 字幕をカット境界で分割する` ／ `SMOKE OK`

- [ ] **Step 3: 目視確認（DoD #2・人手）**

`./.venv/Scripts/python.exe src/app.py` を起動し:
- 出力形式 = Premiere を選んでも「字幕をカット境界で分割する」が**有効**（旧仕様はここで disabled だった）。
- 字幕生成チェックを OFF にするとチェックボックスが disabled。
確認後ウィンドウを閉じる。

- [ ] **Step 4: テスト＆lint 再確認**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -q && ./.venv/Scripts/python.exe -m ruff check src/ tests/`
Expected: 全 PASS / `All checks passed!`

- [ ] **Step 5: コミット**

```bash
git add src/app.py
git commit -m "feat: カット整合字幕のチェックボックスをpremiereでも有効化(disable条件をsrt-OFFのみに)"
```

---

### Task 9: ドキュメント同期（MEMORY / CHANGELOG / 課題）

**Files:**
- Modify: `MEMORY.md`, `CHANGELOG.md`
- (任意) `docs/handoff/P3-srt-snap.md` は歴史として残置（削除しない）。

- [ ] **Step 1: MEMORY 追記** — `MEMORY.md` 先頭（書式は既存に倣い日付＋時刻）

```
## 2026-06-20 HH:MM — SRT-snap後処理を「カット整合字幕」へ置換（実装: Gemini）
- 決定: 設計書 `docs/superpowers/specs/2026-06-20-cut-aligned-subtitles-design.md` に基づき、
  字幕生成を whisper word-level + 全カット境界での再分割に作り直し。カット境界は
  auto-editor `--export v1`（ffprobe fps→`-tb` ピン留め）で NLE 形式非依存に取得。
- 理由: 旧 snap(吸着) は字幕とカットを 1:1 にできず tolerance 外も乗らなかった。
  ユーザー要求「各カット開始に字幕境界を乗せる/全NLE同一出力」を満たすため分割を作り直す。
- 影響: 字幕数 ≥ カット数。トグル流用(既定ON)・premiere でも有効。v1/fps 失敗時は自然分割へ
  フォールバック。旧 snap 関数群を撤去。
- 関連: `src/subtitles.py`, `src/autoeditor.py`(probe_fps/build_v1_export_cmd), `src/pipeline.py`,
  `src/app.py`, `src/i18n.py`, `tests/`
```

- [ ] **Step 2: CHANGELOG 更新** — `CHANGELOG.md` `[Unreleased]`

旧 SRT-snap の Added 記述を「カット整合字幕」へ差し替え（未リリースのため置換でよい）:
```
### Added
- 字幕をカット境界で分割し各カット開始に整合（word-level + auto-editor v1 境界・全NLE共通）。
```

- [ ] **Step 3: 課題セクション確認** — `MEMORY.md` 末尾の課題群に SRT 関連の未解決があれば解消済みへ更新（なければ無変更）。

- [ ] **Step 4: コミット**

```bash
git add MEMORY.md CHANGELOG.md
git commit -m "docs: カット整合字幕への置換をMEMORY/CHANGELOGに記録"
```

---

## Self-Review（この計画の点検結果）

**Spec coverage:**
- §2 v1 取得 → Task 1(probe_fps)/2(build_v1_export_cmd)/3(parse_v1_boundaries)。
- §2.3 tb ピン留め → Task 2(`-tb int`)＋Task 7(2d で fps を渡す)。
- §3 再分割 → Task 4(build_cut_aligned_srt)。エッジ(空区間/反転/フォールバック) → Task 4 テスト＋Task 7。
- §3.4 旧コード削除 → Task 5。
- §4 pipeline 2b/2d → Task 6/7。フォールバック → Task 7 の `no_fps`/OFF テスト。
- §5 UI/i18n/presets → Task 7(i18n)/Task 8(app)。presets は不変（`snap_srt` 据置）で要件充足。
- §6 テスト → 各 Task の TDD ＋ Task 7 pipeline。
- §7 DoD → Task 8 目視・Task 9 docs。

**Placeholder scan:** Task 7 Step 3 に意図的な `...` あり（既存テストのフィクスチャ流用を指示）。
これは「新規モック機構を発明させない」ための明示指示で、流用元（`temp_dirs`/`MockPopen`/
`stub_log`/`PipelineParams` 必須引数）を本文で特定済み。他に TBD/TODO なし。

**Type consistency:** `probe_fps(path)->float|None`、`build_v1_export_cmd(...,tb)->list[str]`、
`parse_v1_boundaries(json_path,tb)->list[float]`、`build_cut_aligned_srt(words,natural_segments,
boundaries)->str`、収集変数 `srt_words`/`srt_natural_segs` の名称・型が Task 1/2/3/4/6/7 間で一致。

---

## 実行ハンドオフ

本プロジェクトの分担（AGENTS §6.1）に従い、**実装は 🔧Gemini が担当**する。
この計画書（`docs/superpowers/plans/2026-06-20-cut-aligned-subtitles.md`）と設計書を Gemini に渡し、
Task 1→9 を順に TDD で実装・コミットさせる。Opus はタスク間レビューと診断を担う。
