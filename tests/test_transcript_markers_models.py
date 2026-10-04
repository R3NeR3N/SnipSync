"""文字起こし(.txt/.md)・マーカー挿入・モデル登録・i18n 整合。"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from markers import (
    add_fcpxml_markers,
    add_markers,
    add_xmeml_markers,
    cut_point_markers,
    speaker_turn_markers,
)
from models import (
    DEFAULT_MODEL,
    DISTIL_ALIGNMENT_HEADS,
    MODELS,
    get_spec,
    lang_hint,
    needs_download,
    patch_alignment_heads,
)
from subtitles import Cue
from transcript import cues_to_md, cues_to_txt, hms, merge_turns, parse_srt, write_transcripts

CUES = [
    Cue(0.0, 2.0, "こんにちは、", 0),
    Cue(2.0, 5.0, "今日は説明します。", 0),
    Cue(5.4, 7.0, "お願いします。", 1),
]


# ── transcript ─────────────────────────────────────────────────────────────────
def test_hms():
    assert hms(0) == "00:00:00" and hms(3661.9) == "01:01:01"


def test_merge_turns_joins_same_speaker_only():
    turns = merge_turns(CUES)
    assert [(t.speaker, t.text) for t in turns] == [(0, "こんにちは、今日は説明します。"), (1, "お願いします。")]
    assert turns[0].start == 0.0 and turns[0].end == 5.0


def test_merge_turns_without_speaker_keeps_each_cue():
    cues = [Cue(0, 1, "a\nb", None), Cue(1, 2, "c", None)]
    assert [t.text for t in merge_turns(cues)] == ["a b", "c"]


def test_cues_to_txt_with_and_without_timestamps_speakers():
    txt = cues_to_txt(CUES)
    assert txt.splitlines()[0] == "[00:00:00] 話者1：こんにちは、今日は説明します。"
    assert txt.splitlines()[1].startswith("[00:00:05] 話者2：")
    plain = cues_to_txt(CUES, timestamps=False, speakers=False)
    assert plain.splitlines()[0] == "こんにちは、今日は説明します。"
    assert "Speaker 1: " in cues_to_txt(CUES, ui_lang="en")


def test_cues_to_md_structure():
    md = cues_to_md(CUES, title="sample")
    assert md.startswith("# sample\n")
    assert "- 話者: 話者1、話者2" in md and "- 字幕数: 3" in md
    assert "## 話者1 `00:00:00`" in md and "## 話者2 `00:00:05`" in md
    assert "## " not in cues_to_md([Cue(0, 1, "x", None)], title="t")


def test_write_transcripts_creates_requested_files(tmp_path):
    paths = write_transcripts(CUES, tmp_path / "talk", title="talk", want_txt=True, want_md=False)
    assert [p.name for p in paths] == ["talk.txt"] and paths[0].read_text(encoding="utf-8")
    assert write_transcripts(CUES, tmp_path / "x", title="x", want_txt=False, want_md=False) == []


def test_parse_srt_roundtrip():
    from subtitles import format_srt
    parsed = parse_srt(format_srt(CUES))
    assert [(c.start, c.end, c.text) for c in parsed] == [(c.start, c.end, c.text) for c in CUES]
    multi = parse_srt("1\n00:00:01,000 --> 00:00:02,500\nline1\nline2\n\n2\nbroken\n")
    assert len(multi) == 1 and multi[0].text == "line1\nline2"
    assert parse_srt("") == []


# ── markers ────────────────────────────────────────────────────────────────────
FCPXML = """<?xml version='1.0' encoding='utf-8'?>
<fcpxml version="1.11">
  <resources>
    <format id="r1" frameDuration="1/30s" width="320" height="240"/>
    <asset id="r2" name="clip" hasVideo="1" hasAudio="1" start="0s" duration="40s"/>
  </resources>
  <library><event name="e"><project name="p"><sequence format="r1"><spine>
    <asset-clip offset="0s" duration="60/30s" start="30/30s" name="clip" ref="r2"/>
    <asset-clip offset="60/30s" duration="90/30s" start="300/30s" name="clip" ref="r2"/>
  </spine></sequence></project></event></library>
</fcpxml>
"""


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_fcpxml_markers_land_on_frame_boundaries_inside_clip_source_time(tmp_path):
    p = _write(tmp_path, "t.fcpxml", FCPXML)
    # 2.5s はタイムライン上の2つ目のクリップ(offset 2s)の 0.5s 目 -> ソース時刻 10s + 0.5s
    assert add_fcpxml_markers(p, [(2.5, "mark"), (0.0, "head")]) == 2
    clips = ET.parse(p).getroot().findall(".//asset-clip")
    m_head = clips[0].find("marker")
    assert m_head.get("value") == "head"
    assert m_head.get("start") == "30/30s" and m_head.get("duration") == "1/30s"   # 元XMLと同じ N/fps 形式
    m = clips[1].find("marker")
    assert m.get("value") == "mark"
    assert m.get("start") == "315/30s"       # クリップのソース開始 300f + クリップ内 15f


def test_fcpxml_marker_at_clip_boundary_goes_to_the_later_clip_despite_rounding(tmp_path):
    # 境界の秒数は丸め済み。2つ目のクリップの頭 (2.0s = 60/30) が 1.999999 になっても、
    # 直前クリップの末尾ではなく 2つ目のクリップの先頭へ付く（以前は範囲外のマーカーになった）。
    p = _write(tmp_path, "t.fcpxml", FCPXML)
    assert add_fcpxml_markers(p, [(1.999999, "cut")]) == 1
    clips = ET.parse(p).getroot().findall(".//asset-clip")
    assert clips[0].find("marker") is None
    assert clips[1].find("marker").get("start") == "300/30s"        # 2つ目のクリップのソース開始


def test_fcpxml_markers_out_of_range_are_skipped(tmp_path):
    p = _write(tmp_path, "t.fcpxml", FCPXML)
    assert add_fcpxml_markers(p, [(99.0, "late")]) == 0


XMEML = """<?xml version='1.0' encoding='utf-8'?>
<xmeml version="5"><sequence><name>s</name><duration>100</duration>
<rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate><media><video/></media></sequence></xmeml>
"""


def test_xmeml_markers_follow_official_element_order_and_frames(tmp_path):
    p = _write(tmp_path, "t.xml", XMEML)
    assert add_xmeml_markers(p, [(1.0, "cut 1")]) == 1
    seq = ET.parse(p).getroot().find("sequence")
    tags = [c.tag for c in seq]
    assert tags.index("marker") > tags.index("media")          # 公式の並び: ... media, marker
    m = seq.find("marker")
    assert m.findtext("name") == "cut 1"
    frame = int(m.findtext("in"))
    assert frame == round(1.0 * 30 * 1000 / 1001)               # ntsc=TRUE は 29.97fps
    assert int(m.findtext("out")) > frame                       # 公式仕様: in < out


def test_add_markers_dispatches_and_never_raises_on_bad_input(tmp_path):
    assert add_markers(_write(tmp_path, "a.fcpxml", FCPXML), [(0.0, "x")]) == 1
    assert add_markers(_write(tmp_path, "b.xml", XMEML), [(0.0, "x")]) == 1
    assert add_markers(_write(tmp_path, "c.xml", "not xml"), [(0.0, "x")]) == 0
    assert add_markers(_write(tmp_path, "d.xml", "<other/>"), [(0.0, "x")]) == 0
    assert add_markers(tmp_path / "missing.xml", [(0.0, "x")]) == 0
    assert add_markers(_write(tmp_path, "e.xml", XMEML), []) == 0


def test_marker_builders():
    # 先頭(0秒)と終端(7.5秒)はカット点ではない
    assert cut_point_markers([0.0, 3.0, 5.0, 7.5], "カット") == [(3.0, "カット 1"), (5.0, "カット 2")]
    assert cut_point_markers([0.0, 6.0]) == [] and cut_point_markers([]) == []
    marks = speaker_turn_markers(CUES)
    assert marks == [(0.0, "話者1"), (5.4, "話者2")]
    assert speaker_turn_markers([Cue(0, 1, "x", None)]) == []


# ── models ─────────────────────────────────────────────────────────────────────
def test_model_registry_is_consistent_with_i18n():
    from i18n import I18N
    for lang in ("ja", "en"):
        assert set(MODELS) <= set(I18N[lang]["model_options"]), lang
        assert set(I18N[lang]["model_options"]) <= set(MODELS), lang
    assert DEFAULT_MODEL in MODELS


def test_get_spec_falls_back_for_unknown_keys():
    assert get_spec("no-such-model").key == DEFAULT_MODEL


def test_kotoba_requires_local_dir_and_patched_alignment_heads_and_fixed_language():
    spec = MODELS["kotoba-ja"]
    assert spec.local_dir and spec.patch_alignment_heads and spec.langs == "ja"
    assert lang_hint("kotoba-ja") == "ja" and lang_hint("small") is None
    assert spec.transcribe_kwargs["condition_on_previous_text"] is False


def test_turbo_and_distil_map_to_faster_whisper_names():
    assert MODELS["turbo"].source == "large-v3-turbo"
    assert MODELS["distil-en"].source == "distil-large-v3" and MODELS["distil-en"].langs == "en"


def test_patch_alignment_heads_is_idempotent(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"alignment_heads": [[7, 0], [10, 17]], "other": 1}), encoding="utf-8")
    assert patch_alignment_heads(cfg) is True
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["alignment_heads"] == DISTIL_ALIGNMENT_HEADS and data["other"] == 1
    assert patch_alignment_heads(cfg) is False


def test_needs_download_reflects_local_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert needs_download("kotoba-ja") is True
    d = tmp_path / "SnipSync" / "models" / "kotoba-whisper-v2.0-faster"
    d.mkdir(parents=True)
    (d / "model.bin").write_bytes(b"x")
    (d / "config.json").write_text("{}", encoding="utf-8")
    assert needs_download("kotoba-ja") is False
    # 名前指定のモデルは Hugging Face のキャッシュに揃っているかで決まる（ここでは偽の確認に差し替える）
    monkeypatch.setattr("models._hf_cached", lambda repo: True)
    assert needs_download("small") is False


# ── i18n ──────────────────────────────────────────────────────────────────────
def test_i18n_ja_en_have_identical_keys():
    from i18n import I18N
    assert set(I18N["ja"]) == set(I18N["en"])


@pytest.mark.parametrize("key", ["method_options", "silence_options", "export_options", "model_options"])
def test_i18n_option_dicts_have_same_keys(key):
    from i18n import I18N
    assert set(I18N["ja"][key]) == set(I18N["en"][key])


def test_presets_keep_new_settings():
    from presets import SETTING_KEYS, upsert_preset
    store = {}
    upsert_preset(store, "p", {k: 1 for k in SETTING_KEYS} | {"junk": 2})
    assert set(store["presets"]["p"]) == set(SETTING_KEYS)
    for k in ("cut_mode", "silence", "speed", "hotwords", "diarize", "speakers", "markers", "line_chars"):
        assert k in SETTING_KEYS


def test_every_logged_message_has_a_placeholder_for_each_argument_passed():
    """tr("key", arg) に渡した引数が、文言の {} に入らず捨てられていないこと（完了ログからファイル名が消えていた不具合の再発防止）。"""
    import re

    from i18n import I18N
    src = Path(__file__).parent.parent / "src"
    bad = []
    for f in src.glob("*.py"):
        for m in re.finditer(r'(?:tr|self\.t)\(\s*"(\w+)"\s*((?:,[^()]*(?:\([^()]*\))?[^()]*?)*)\)', f.read_text(encoding="utf-8")):
            key, rest = m.group(1), m.group(2)
            if key not in I18N["ja"] or not rest.strip():
                continue
            nargs = len([a for a in re.split(r",(?![^()]*\))", rest) if a.strip()])
            for lang in ("ja", "en"):
                text = I18N[lang][key]
                if isinstance(text, str) and text.count("{") < nargs:
                    bad.append((f.name, key, lang))
    assert not bad, bad


# ── 話者名つきのマーカーと、あとから足す話者交代のマーカー ───────────────────────────────
def test_speaker_turn_markers_use_custom_names():
    from markers import speaker_turn_markers
    from subtitles import Cue
    cues = [Cue(0, 1, "a", 0), Cue(1, 2, "b", 0), Cue(2, 3, "c", 1)]
    assert speaker_turn_markers(cues, "ja", {0: "山田"}) == [(0, "山田"), (2, "話者2")]
    assert speaker_turn_markers(cues, "en") == [(0, "Speaker 1"), (2, "Speaker 2")]


def test_add_speaker_markers_to_an_existing_timeline_keeps_the_cut_markers(tmp_path):
    from markers import add_markers, add_speaker_markers
    from subtitles import Cue
    xml = tmp_path / "t.xml"
    xml.write_text('<?xml version="1.0"?><xmeml version="5"><sequence><name>s</name><duration>300</duration>'
                   '<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate><media><video/></media></sequence></xmeml>',
                   encoding="utf-8")
    assert add_markers(xml, [(1.0, "カット 1")]) == 1
    cues = [Cue(0.0, 2.0, "a", 0), Cue(2.0, 4.0, "b", 1)]
    assert add_speaker_markers(xml, cues, "ja", {1: "佐藤"}) == 2
    text = xml.read_text(encoding="utf-8")
    assert text.count("<marker>") == 3 and "カット 1" in text and "話者1" in text and "佐藤" in text


def test_add_speaker_markers_without_speakers_adds_nothing(tmp_path):
    from markers import add_speaker_markers
    from subtitles import Cue
    xml = tmp_path / "t.xml"
    xml.write_text("<xmeml/>", encoding="utf-8")
    assert add_speaker_markers(xml, [Cue(0, 1, "a", None)], "ja") == 0


# ── Resolve 用: マーカーの EDL（Resolve は .fcpxml のマーカーを読み込まない）───────────────────
def _timeline_60(tmp_path, *, frame="1/60s", tc="0s"):
    return _write(tmp_path, "t.fcpxml", f"""<?xml version='1.0' encoding='utf-8'?>
<fcpxml version="1.11"><resources><format id="r1" frameDuration="{frame}"/></resources>
<library><event name="e"><project name="p"><sequence tcStart="{tc}" format="r1"><spine/></sequence></project></event></library>
</fcpxml>""")


def _edl_lines(path):
    return Path(path).read_bytes().decode("utf-8").split("\r\n")


def test_marker_edl_has_resolves_own_layout_with_color_name_and_one_frame_duration(tmp_path):
    from markers import resolve_marks, write_marker_edl
    tl = _timeline_60(tmp_path)
    marks = resolve_marks([(1.5, "カット 1")], [(0.0, "話者1"), (4.0, "山田")])
    edl = tmp_path / "t_markers.edl"
    assert write_marker_edl(edl, tl, marks, title="demo") == 3
    lines = _edl_lines(edl)
    assert lines[0] == "TITLE: demo" and lines[1] == "FCM: NON-DROP FRAME"
    assert lines[3] == "001  001      V     C        00:00:00:00 00:00:00:01 00:00:00:00 00:00:00:01 "
    assert lines[4] == " |C:ResolveColorYellow |M:話者1 |D:1"                     # 話者交代は黄
    assert lines[6].startswith("002  001      V     C        00:00:01:30 00:00:01:31 ")   # 1.5 秒 = 90 フレーム = 1 秒 + 30
    assert lines[7] == " |C:ResolveColorBlue |M:カット 1 |D:1"                    # カット点は青。時刻順に並ぶ
    assert lines[9].startswith("003  001      V     C        00:00:04:00 ") and "|M:山田 " in lines[10]


def test_marker_edl_follows_the_timeline_start_and_rate(tmp_path):
    from markers import write_marker_edl
    one_hour = _timeline_60(tmp_path, tc="3600s")                               # 開始 01:00:00:00 のタイムライン
    write_marker_edl(tmp_path / "a.edl", one_hour, [(1.0, "x", "ResolveColorBlue")])
    assert "01:00:01:00 01:00:01:01" in _edl_lines(tmp_path / "a.edl")[3]
    ntsc = _write(tmp_path, "n.fcpxml", Path(one_hour).read_text(encoding="utf-8")
                  .replace("1/60s", "1001/30000s").replace('tcStart="3600s"', 'tcStart="0s"'))
    write_marker_edl(tmp_path / "b.edl", ntsc, [(1.0, "x", "ResolveColorBlue")])
    assert "00:00:01:00 00:00:01:01" in _edl_lines(tmp_path / "b.edl")[3]       # 29.97 は、30 を単位に数える（ノンドロップ）


def test_marker_edl_keeps_names_on_one_line_and_skips_when_nothing_to_write(tmp_path):
    from markers import write_marker_edl
    tl = _timeline_60(tmp_path)
    write_marker_edl(tmp_path / "c.edl", tl, [(1.0, "a|b\nc", "ResolveColorBlue")])
    assert " |C:ResolveColorBlue |M:a/b c |D:1" in _edl_lines(tmp_path / "c.edl")      # 区切りの | と改行は入れない
    assert write_marker_edl(tmp_path / "d.edl", tl, []) == 0 and not (tmp_path / "d.edl").exists()
    assert write_marker_edl(tmp_path / "e.edl", _write(tmp_path, "x.fcpxml", "<fcpxml/>"), [(1.0, "x", "c")]) == 0
