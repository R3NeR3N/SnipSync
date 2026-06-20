import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from subtitles import (
    parse_timestamp,
    _fcpxml_time_to_seconds,
    parse_fcpxml_cut_boundaries,
    snap_srt_to_boundaries,
)

def test_parse_timestamp():
    assert parse_timestamp("00:00:15,300") == 15.300
    assert parse_timestamp("01:02:03,456") == 3600.0 + 120.0 + 3.0 + 0.456
    # comma/period check
    assert parse_timestamp("00:00:15.300") == 15.300
    
    with pytest.raises(ValueError):
        parse_timestamp("invalid")
    with pytest.raises(ValueError):
        parse_timestamp("00:00:15")

def test_fcpxml_time_to_seconds():
    assert _fcpxml_time_to_seconds("27/60s") == 0.45
    assert _fcpxml_time_to_seconds("0s") == 0.0
    assert _fcpxml_time_to_seconds("5s") == 5.0
    assert _fcpxml_time_to_seconds("15") == 15.0

def test_parse_fcpxml_cut_boundaries(tmp_path):
    # Setup dummy FCPXML file containing multiple tracks (video track with hasVideo="1" and some WAV tracks)
    fcpxml_content = """<?xml version="1.0" encoding="utf-8"?>
<fcpxml version="1.9">
    <resources>
        <asset id="r1" name="test.mp4" hasVideo="1" />
        <asset id="r2" name="test_1.wav" hasAudio="1" />
    </resources>
    <library>
        <event name="test">
            <project name="test">
                <sequence duration="100s" format="r1">
                    <spine>
                        <asset-clip offset="0s" duration="27/60s" start="108/60s" ref="r1" name="test" />
                        <asset-clip offset="27/60s" duration="34/60s" start="231/60s" ref="r2" name="test_1" />
                        <asset-clip offset="27/60s" duration="34/60s" start="231/60s" ref="r1" name="test" />
                        <asset-clip offset="61/60s" duration="36/60s" start="365/60s" ref="r1" name="test" />
                    </spine>
                </sequence>
            </project>
        </event>
    </library>
</fcpxml>
"""
    xml_path = tmp_path / "test.fcpxml"
    xml_path.write_text(fcpxml_content, encoding="utf-8")

    boundaries = parse_fcpxml_cut_boundaries(xml_path, "test")
    # Expected video clips:
    # 1. offset=0s, duration=27/60s (0.45s). offset = 0.0
    # 2. offset=27/60s (0.45s), duration=34/60s (0.5666...). offset = 0.45
    # 3. offset=61/60s (1.0166...), duration=36/60s (0.6s). offset = 1.0166...
    # Final clip boundary: 61/60 + 36/60 = 97/60s (1.6166...)
    # Unique sorted boundaries: [0.0, 0.45, 1.0166666666666666, 1.6166666666666667]
    assert len(boundaries) == 4
    assert abs(boundaries[0] - 0.0) < 1e-6
    assert abs(boundaries[1] - 0.45) < 1e-6
    assert abs(boundaries[2] - 61/60.0) < 1e-6
    assert abs(boundaries[3] - 97/60.0) < 1e-6

def test_parse_fcpxml_cut_boundaries_invalid_xml(tmp_path):
    assert parse_fcpxml_cut_boundaries(tmp_path / "non_existent.fcpxml", "test") == []
    
    xml_path = tmp_path / "empty.fcpxml"
    xml_path.write_text("<invalid>", encoding="utf-8")
    assert parse_fcpxml_cut_boundaries(xml_path, "test") == []

def test_snap_srt_to_boundaries():
    # 1. カット隣接は snap
    # 2. カット無しは不動 (20.640 は 21.117 との差が 0.477 > tol=0.35)
    # 3. 境界上は不動
    # 4. 超過の解消 (45.600 > 最終境界 45.533, 差0.067 <= 0.35 -> 45.533にスナップ)
    boundaries = [0.0, 15.300, 21.117, 25.133, 45.533]
    tolerance = 0.35
    
    srt_text = """1
00:00:00,000 --> 00:00:15,360
Hello World

2
00:00:20,640 --> 00:00:25,280
This is a test.

3
00:00:25,280 --> 00:00:45,600
Last subtitle.
"""
    
    expected = """1
00:00:00,000 --> 00:00:15,300
Hello World

2
00:00:20,640 --> 00:00:25,133
This is a test.

3
00:00:25,133 --> 00:00:45,533
Last subtitle.
"""
    
    snapped = snap_srt_to_boundaries(srt_text, boundaries, tolerance)
    assert snapped.strip().replace("\r\n", "\n") == expected.strip().replace("\r\n", "\n")

def test_snap_srt_to_boundaries_no_boundaries():
    srt_text = "1\n00:00:01,000 --> 00:00:05,000\nHello"
    assert snap_srt_to_boundaries(srt_text, [], 0.35) == srt_text

def test_snap_srt_to_boundaries_contiguous_maintenance():
    # 前 end == 次 start の共有時刻 15.360 -> 両方 15.300 へスナップされ、共有関係が維持される
    boundaries = [15.300]
    tolerance = 0.35
    srt_text = """1
00:00:05,000 --> 00:00:15,360
First

2
00:00:15,360 --> 00:00:20,000
Second
"""
    expected = """1
00:00:05,000 --> 00:00:15,300
First

2
00:00:15,300 --> 00:00:20,000
Second
"""
    snapped = snap_srt_to_boundaries(srt_text, boundaries, tolerance)
    assert snapped.strip().replace("\r\n", "\n") == expected.strip().replace("\r\n", "\n")

def test_snap_srt_to_boundaries_reversal_guard():
    # start (15.250) と end (15.350) が共に境界 15.300 にスナップされると、start >= end となる。
    # この場合、同一字幕スナップの反転ガードによって end が元値に戻る
    boundaries = [15.300]
    tolerance = 0.15
    srt_text = """1
00:00:15,250 --> 00:00:15,350
Short Text
"""
    snapped = snap_srt_to_boundaries(srt_text, boundaries, tolerance)
    # パースして start < end であることを確認
    lines = snapped.strip().split("\n")
    assert "1" in lines[0]
    ts_line = lines[1]
    start_str, end_str = ts_line.split(" --> ")
    assert parse_timestamp(start_str) < parse_timestamp(end_str)

def test_snap_srt_to_boundaries_overlap_revert():
    # 隣接する字幕でスナップした結果、前end > 次start になるのを防ぐテスト。
    # 前：10.000 --> 15.000 (境界 15.100 に end がスナップされて 15.100 に)
    # 次：15.050 --> 20.000 (境界 14.950 に start がスナップされて 14.950 に)
    # これにより前end(15.100) > 次start(14.950) となりオーバーラップが発生する。
    # スナップの競合解消ループによって、競合したスナップが元値に戻されること。
    boundaries = [14.950, 15.100]
    tolerance = 0.15
    srt_text = """1
00:00:10,000 --> 00:00:15,000
First

2
00:00:15,050 --> 00:00:20,000
Second
"""
    snapped = snap_srt_to_boundaries(srt_text, boundaries, tolerance)
    # 元々の順序が維持されていること（前end <= 次start）
    lines = snapped.strip().replace("\r\n", "\n").split("\n\n")
    curr_ts = lines[0].split("\n")[1]
    nxt_ts = lines[1].split("\n")[1]
    curr_end = parse_timestamp(curr_ts.split(" --> ")[1])
    nxt_start = parse_timestamp(nxt_ts.split(" --> ")[0])
    assert curr_end <= nxt_start
