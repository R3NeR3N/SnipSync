"""手動のカット・倍速（core/manualcuts.py）と、プレビュー・処理への組み込み。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core import manualcuts as mc  # noqa: E402
from snipsync.core.autoeditor import CUT_SPEED  # noqa: E402
from snipsync.core.manualcuts import CUT, SPEED, ManualEdit, apply_manual_edits  # noqa: E402

TB = 30.0
# 0〜10 秒 残す / 10〜20 秒 カット / 20〜60 秒 残す（30fps）
BASE = [(0, 300, 1.0), (300, 600, CUT_SPEED), (600, 1800, 1.0)]


def secs(chunks):
    return [(round(a / TB, 2), round(b / TB, 2), sp) for a, b, sp in chunks]


def test_a_manual_cut_inside_a_kept_span_splits_it():
    out = apply_manual_edits(BASE, TB, [ManualEdit(30.0, 35.0, CUT)])
    assert secs(out) == [(0, 10, 1.0), (10, 20, CUT_SPEED), (20, 30, 1.0), (30, 35, CUT_SPEED), (35, 60, 1.0)]


def test_a_manual_cut_that_touches_an_existing_cut_merges_with_it():
    out = apply_manual_edits(BASE, TB, [ManualEdit(18.0, 25.0, CUT)])
    assert secs(out) == [(0, 10, 1.0), (10, 25, CUT_SPEED), (25, 60, 1.0)]


def test_a_manual_speed_up_changes_only_the_kept_part():
    out = apply_manual_edits(BASE, TB, [ManualEdit(5.0, 25.0, SPEED, 4.0)])
    assert secs(out) == [(0, 5, 1.0), (5, 10, 4.0), (10, 20, CUT_SPEED), (20, 25, 4.0), (25, 60, 1.0)]


def test_a_manual_speed_up_over_a_silence_that_is_already_sped_changes_its_rate():
    base = [(0, 300, 1.0), (300, 600, 8.0), (600, 900, 1.0)]
    out = apply_manual_edits(base, TB, [ManualEdit(12.0, 16.0, SPEED, 2.0)])
    assert secs(out) == [(0, 10, 1.0), (10, 12, 8.0), (12, 16, 2.0), (16, 20, 8.0), (20, 30, 1.0)]


def test_a_cut_wins_over_a_speed_up_on_the_same_span():
    out = apply_manual_edits(BASE, TB, [ManualEdit(30.0, 40.0, SPEED, 4.0), ManualEdit(33.0, 36.0, CUT)])
    assert (33.0, 36.0, CUT_SPEED) in secs(out) and (30.0, 33.0, 4.0) in secs(out)


def test_the_result_covers_the_same_frames_without_gaps_or_overlaps():
    out = apply_manual_edits(BASE, TB, [ManualEdit(3, 7, CUT), ManualEdit(40, 41.5, SPEED, 3.0), ManualEdit(0, 1, CUT)])
    assert out[0][0] == 0 and out[-1][1] == 1800
    assert all(a[1] == b[0] for a, b in zip(out, out[1:], strict=False))
    assert all(c[0] < c[1] for c in out)


def test_edits_past_the_end_or_too_short_are_ignored():
    assert apply_manual_edits(BASE, TB, [ManualEdit(100.0, 120.0, CUT)]) == [tuple(c) for c in BASE]
    assert apply_manual_edits(BASE, TB, [ManualEdit(5.0, 5.01, CUT)]) == [tuple(c) for c in BASE]
    assert apply_manual_edits(BASE, TB, []) == [tuple(c) for c in BASE]


def test_cutting_everything_is_refused_and_the_original_is_kept():
    assert apply_manual_edits(BASE, TB, [ManualEdit(0.0, 60.0, CUT)]) == [tuple(c) for c in BASE]


def test_normalize_sorts_clamps_and_drops_bad_rows():
    out = mc.normalize([ManualEdit(20, 25, CUT), ManualEdit(-5, 3, CUT), ManualEdit(9, 9.01, CUT),
                        ManualEdit(1, 2, "bogus"), ManualEdit(30, 31, SPEED, 0.5)])
    assert [(e.start, e.end, e.action) for e in out] == [(0.0, 3.0, CUT), (20.0, 25.0, CUT), (30.0, 31.0, SPEED)]
    assert out[-1].speed == mc.DEFAULT_SPEED                         # 1 倍以下の倍率は、使えないので、既定に


def test_json_roundtrip_and_malformed_input():
    edits = [ManualEdit(1.0, 2.0, CUT), ManualEdit(5.0, 9.0, SPEED, 4.0)]
    assert mc.from_json(mc.to_json(edits)) == [ManualEdit(1.0, 2.0, CUT, mc.DEFAULT_SPEED), ManualEdit(5.0, 9.0, SPEED, 4.0)]
    assert mc.from_json("nope") == [] and mc.from_json([[1, 2], ["a", "b", "cut", 1]]) == []


# ── プレビューへの組み込み ───────────────────────────────────────────────────────────────
def test_the_preview_applies_manual_edits_to_regions_stats_and_chunks(monkeypatch, tmp_path):
    import numpy as np

    from snipsync.core import preview

    monkeypatch.setattr(preview, "probe_fps", lambda p: TB)
    monkeypatch.setattr(preview, "is_audio_only", lambda p: False)
    monkeypatch.setattr(preview, "decode_mix", lambda p, sr: np.zeros(60 * sr, dtype=np.float32))
    monkeypatch.setattr(preview, "detect_speech", lambda s: [(0.0, 10.0), (20.0, 60.0)])
    plain = preview.compute_preview("x.mp4", preview.CutSettings(0.0, 4.0, "vad"), None)
    with_manual = preview.compute_preview(
        "x.mp4", preview.CutSettings(0.0, 4.0, "vad", None, (ManualEdit(30.0, 40.0, CUT),)), None)
    assert with_manual.stats["result"] < plain.stats["result"] - 9.0
    assert any(k == "cut" and s <= 30.5 and e >= 39.5 for s, e, k in with_manual.regions)
    assert not any(k == "cut" and s <= 30.5 and e >= 39.5 for s, e, k in plain.regions)
    assert any(sp >= CUT_SPEED and a == 900 for a, b, sp in with_manual.chunks)


@pytest.mark.parametrize("edits", [(), (ManualEdit(1.0, 2.0, CUT),)])
def test_pipeline_params_carry_the_edits(edits):
    from snipsync.core.pipeline import PipelineParams
    p = PipelineParams(margin=0.2, threshold=4.0, export_key="resolve", do_srt=False, model_size="small", manual_edits=edits)
    assert p.manual_edits == edits
    assert PipelineParams.__dataclass_fields__["manual_edits"].default == ()


# ── 時刻の読み書き ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("90", 90.0), ("90.5", 90.5), ("1:30", 90.0), ("1:30.25", 90.25), ("0:01:30.250", 90.25), ("1:00:00", 3600.0),
    (" 1:30 ", 90.0), ("１：３０", 90.0), ("1：30", 90.0), (":30", 30.0), ("0", 0.0),
])
def test_parse_time_reads_the_usual_forms(text, expected):
    assert mc.parse_time(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "abc", "1:75", "-5", "1:2:3:4", "1:30:99", "nan", "1,5", "1:-3"])
def test_parse_time_refuses_what_it_cannot_read(text):
    assert mc.parse_time(text) is None


def test_format_precise_and_parse_time_roundtrip():
    for sec in (0.0, 0.001, 5.0, 90.25, 3599.999, 3600.0, 7325.5):
        assert mc.parse_time(mc.format_precise(sec)) == pytest.approx(sec, abs=0.0006)
    assert mc.format_precise(90.25) == "0:01:30.250" and mc.format_precise(-3) == "0:00:00.000"
