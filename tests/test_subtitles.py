import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from subtitles import parse_timestamp


def test_parse_timestamp():
    assert parse_timestamp("00:00:15,300") == 15.300
    assert parse_timestamp("01:02:03,456") == 3600.0 + 120.0 + 3.0 + 0.456
    # comma/period check
    assert parse_timestamp("00:00:15.300") == 15.300

    with pytest.raises(ValueError):
        parse_timestamp("invalid")
    with pytest.raises(ValueError):
        parse_timestamp("00:00:15")




def test_parse_v1_boundaries_basic(tmp_path):
    import json

    from subtitles import parse_v1_boundaries
    # kept(30f) / cut(10f) / kept(30f)  @ tb=10  -> 境界 [0.0, 3.0, 6.0]
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"chunks": [[0, 30, 1.0], [30, 40, 99999.0], [40, 70, 1.0]]}), encoding="utf-8")
    assert parse_v1_boundaries(p, 10) == [0.0, 3.0, 6.0]


def test_parse_v1_boundaries_excludes_cut(tmp_path):
    import json

    from subtitles import parse_v1_boundaries
    # 全 cut -> kept 無し -> []
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"chunks": [[0, 30, 99999.0]]}), encoding="utf-8")
    assert parse_v1_boundaries(p, 10) == []


def test_parse_v1_boundaries_bad_json(tmp_path):
    from subtitles import parse_v1_boundaries
    p = tmp_path / "c.json"
    p.write_text("not json", encoding="utf-8")
    assert parse_v1_boundaries(p, 10) == []


def test_parse_v1_boundaries_no_tb(tmp_path):
    import json

    from subtitles import parse_v1_boundaries
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"chunks": [[0, 30, 1.0]]}), encoding="utf-8")
    assert parse_v1_boundaries(p, 0) == []


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
    from subtitles import build_cut_aligned_srt
    # 1つの自然セグメント [0,4) 内にカット境界 2.0 がある -> 2字幕に割れる
    words = [(0.0, 0.9, "A"), (1.0, 1.9, "B"), (2.0, 2.9, "C"), (3.0, 3.9, "D")]
    natural = [(0.0, 4.0)]
    boundaries = [0.0, 2.0]
    blocks = _parse_blocks(build_cut_aligned_srt(words, natural, boundaries))
    assert len(blocks) == 2
    # 2つ目の字幕開始 = カット境界 2.0 に厳密一致
    assert blocks[1][0] == "00:00:02,000"


def test_sentence_split_within_cut():
    from subtitles import build_cut_aligned_srt
    # 1カット [0,4) 内に文境界が2つ(0.0, 2.0) -> 字幕数 > カット数(1)
    words = [(0.0, 0.9, "A"), (1.0, 1.9, "B"), (2.0, 2.9, "C")]
    natural = [(0.0, 2.0), (2.0, 4.0)]
    boundaries = [0.0, 4.0]
    blocks = _parse_blocks(build_cut_aligned_srt(words, natural, boundaries))
    assert len(blocks) == 2  # カット1個でも文境界で2字幕


def test_empty_interval_skipped():
    from subtitles import build_cut_aligned_srt
    # カット境界 [0,2,4] だが [2,4) に単語なし -> その字幕は作らない
    words = [(0.0, 0.9, "A"), (1.0, 1.9, "B")]
    natural = [(0.0, 2.0)]
    boundaries = [0.0, 2.0, 4.0]
    blocks = _parse_blocks(build_cut_aligned_srt(words, natural, boundaries))
    assert len(blocks) == 1


def test_no_zero_length_entries():
    from subtitles import build_cut_aligned_srt
    words = [(0.0, 0.5, "A")]
    natural = [(0.0, 0.5)]
    boundaries = [0.0, 0.5]
    blocks = _parse_blocks(build_cut_aligned_srt(words, natural, boundaries))
    for s, e, _ in blocks:
        assert s != e  # ゼロ尺なし


def test_empty_boundaries_returns_empty():
    from subtitles import build_cut_aligned_srt
    words = [(0.0, 0.5, "A")]
    assert build_cut_aligned_srt(words, [(0.0, 0.5)], []) == ""


def test_empty_words_returns_empty():
    from subtitles import build_cut_aligned_srt
    assert build_cut_aligned_srt([], [(0.0, 0.5)], [0.0, 0.5]) == ""
