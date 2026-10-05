"""NLE タイムラインへのマーカー追加（カット点・話者交代）。

仕様の根拠:
- FCPXML: ``marker`` は asset-clip などの子要素。属性 ``start`` / ``duration`` / ``value``。
  ``start`` はクリップ内（ソース側）の時刻で、フレーム境界に揃える必要がある。
- Premiere(xmeml): ``marker`` の親は ``sequence``。子要素 ``name`` / ``in`` / ``out``
  （フレーム整数）。Apple 公式「Final Cut Pro 7 XML Interchange Format」に従う。
  Premiere は取り込み時にシーケンスマーカーを保持する（Adobe ヘルプ）。

- DaVinci Resolve: .fcpxml のマーカー（clip marker）は取り込まれない（Resolve 21 で、18 件入れて、マーカー
  一覧が空だった）。公式マニュアルにも、FCPXML のマーカー取り込みの記載はない。代わりに、タイムラインマーカーを
  EDL で取り込む（メディアプールでタイムラインを右クリック → Timelines → Import → Timeline Markers from EDL）。
  書式は、Resolve 自身が書き出すマーカー EDL（イベント行 + `|C:色 |M:名前 |D:長さ` の行）に合わせる。

Resolve 21（日本語表示）での EDL 取り込みは、実機で確認済み（2026-10-05: 18 件が、名前つきでマーカー一覧に出た）。
Premiere / Final Cut Pro への取り込みは、この環境では未検証。既定OFFのオプションとして提供する。

XML は標準ライブラリで読む。対象は SnipSync 自身が auto-editor で直前に生成したローカル
ファイルだけで、外部から受け取った XML は扱わない（XXE 等の攻撃経路が無い）。
"""
import xml.etree.ElementTree as ET  # nosec B405 - 要素の組み立てと書き出しのみ。読み込みは safexml
from fractions import Fraction
from pathlib import Path

import safexml
from subtitles import speaker_label


def _frac(text: str) -> Fraction:
    """FCPXML の時間表記 ``31/30s`` / ``5s`` を Fraction(秒) にする。"""
    t = text.strip().rstrip("s")
    if "/" in t:
        n, d = t.split("/")
        return Fraction(int(n), int(d))
    return Fraction(t)


def _fmt_frames(frames: int, fd: Fraction) -> str:
    """フレーム数 -> auto-editor が書くのと同じ「N/fps s」形式（約分しない）。"""
    return f"{frames * fd.numerator}/{fd.denominator}s"


def cut_point_markers(boundaries, label: str = "カット") -> list[tuple[float, str]]:
    """タイムライン上のカット点をマーカー化する。先頭(0秒)と終端は「カット点」ではないので除く。"""
    ordered = sorted(set(boundaries))
    inner = [b for b in ordered[:-1] if b > 0]
    return [(b, f"{label} {i}") for i, b in enumerate(inner, start=1)]


def speaker_turn_markers(cues, ui_lang: str = "ja", names: dict | None = None) -> list[tuple[float, str]]:
    """話者が切り替わる字幕の開始時刻をマーカー化する（最初の発話も含む）。names は話者番号 -> 表示名。"""
    out, prev = [], object()
    for c in cues:
        if c.speaker is not None and c.speaker != prev:
            out.append((c.start, speaker_label(c.speaker, ui_lang, names)))
        prev = c.speaker
    return out


RESOLVE_CUT_COLOR = "ResolveColorBlue"
RESOLVE_SPEAKER_COLOR = "ResolveColorYellow"


def resolve_marks(cut_marks=(), speaker_marks=()) -> list[tuple[float, str, str]]:
    """カット点と話者交代のマーカーを、色つきで、時刻順に並べる（Resolve の EDL 用）。"""
    marks = [(t, n, RESOLVE_CUT_COLOR) for t, n in cut_marks] + \
            [(t, n, RESOLVE_SPEAKER_COLOR) for t, n in speaker_marks]
    return sorted(marks, key=lambda m: m[0])


def _timecode(frames: int, nominal_fps: int) -> str:
    """フレーム番号 -> HH:MM:SS:FF（ノンドロップ。nominal_fps は 30 / 60 などの整数）。"""
    s, ff = divmod(frames, nominal_fps)
    m, ss = divmod(s, 60)
    h, mm = divmod(m, 60)
    return f"{h:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def write_marker_edl(edl_path, timeline_path, marks, title: str = "") -> int:
    """Resolve の「Timeline Markers from EDL」で読み込める EDL を書く。書いた件数を返す（0 のときは書かない）。

    marks は (秒, 名前, 色) の列。時刻は、タイムライン（.fcpxml）の開始タイムコードとフレームレートで、
    タイムコードにする。1 件 = 1 フレーム長のイベント。
    """
    if not marks:
        return 0
    root = safexml.parse(timeline_path).getroot()
    fmt = root.find(".//resources/format")
    seq = root.find(".//sequence")
    if fmt is None or seq is None or not fmt.get("frameDuration"):
        return 0
    fd = _frac(fmt.get("frameDuration"))
    nominal = round(1 / fd)
    base = round(_frac(seq.get("tcStart", "0s")) / fd)
    lines = [f"TITLE: {title or 'SnipSync markers'}", "FCM: NON-DROP FRAME", ""]
    for n, (t, name, color) in enumerate(marks, start=1):
        frame = base + round(Fraction(t).limit_denominator(100000) / fd)
        a, b = _timecode(frame, nominal), _timecode(frame + 1, nominal)
        label = " ".join(str(name).replace("|", "/").split())        # 区切りの | と改行は、名前に入れない
        lines += [f"{n:03d}  001      V     C        {a} {b} {a} {b} ", f" |C:{color} |M:{label} |D:1", ""]
    Path(edl_path).write_bytes("\r\n".join(lines).encode("utf-8"))
    return len(marks)


def add_fcpxml_markers(path, markers) -> int:
    """FCPXML の asset-clip に marker を追加する。追加した件数を返す（対象外は数えない）。"""
    tree = safexml.parse(path)
    root = tree.getroot()
    fmt = root.find(".//resources/format")
    spine = root.find(".//sequence/spine")
    if fmt is None or spine is None or not fmt.get("frameDuration"):
        return 0
    fd = _frac(fmt.get("frameDuration"))
    video_ids = {a.get("id") for a in root.findall(".//resources/asset") if a.get("hasVideo") == "1"}
    clips = [c for c in spine.findall("asset-clip") if not video_ids or c.get("ref") in video_ids]
    if not clips:
        return 0

    spans = []
    for c in clips:
        off, dur = _frac(c.get("offset", "0s")), _frac(c.get("duration", "0s"))
        spans.append((off, off + dur, c))

    added = 0
    for t, name in markers:
        # 境界の秒数は丸め済み（例: 523/30 が 17.433333）で、クリップの境目ぴったりの値が
        # わずかに小さくなり直前のクリップに入ってしまう。先にフレーム格子へ丸める。
        tf = round(Fraction(t).limit_denominator(100000) / fd) * fd
        # 倍速モードでは境界の計算値がクリップ位置と1フレームずれることがある。
        # クリップ末尾の1フレーム以内なら、次のクリップの先頭（本来のカット点）へ寄せる。
        for off, end, _clip in spans:
            if off - fd <= tf < off:
                tf = off
                break
        for off, end, clip in spans:
            if not (off <= tf < end):
                continue
            k = round((tf - off) / fd)
            if clip.find("timeMap") is not None and k != 0:
                break      # 速度変更クリップ内部の位置はソース時刻へ素直に写せないので付けない
            start_frames = round(_frac(clip.get("start", "0s")) / fd) + k
            ET.SubElement(clip, "marker", {"start": _fmt_frames(start_frames, fd),
                                           "duration": _fmt_frames(1, fd), "value": name})
            added += 1
            break
    if added:
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return added


def add_xmeml_markers(path, markers) -> int:
    """Premiere(xmeml) の sequence 直下に marker を追加する。追加した件数を返す。"""
    tree = safexml.parse(path)
    root = tree.getroot()
    seq = root.find("sequence")
    if seq is None:
        return 0
    rate = seq.find("rate")
    if rate is None or rate.findtext("timebase") is None:
        return 0
    fps = float(rate.findtext("timebase"))
    if (rate.findtext("ntsc") or "").upper() == "TRUE":
        fps = fps * 1000 / 1001
    children = list(seq)
    media = seq.find("media")
    insert_at = children.index(media) + 1 if media is not None else len(children)
    for n, (t, name) in enumerate(markers):
        frame = int(round(t * fps))
        m = ET.Element("marker")
        ET.SubElement(m, "name").text = name
        ET.SubElement(m, "in").text = str(frame)
        ET.SubElement(m, "out").text = str(frame + 1)      # 公式仕様: in < out
        seq.insert(insert_at + n, m)
    if markers:
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return len(markers)


def add_speaker_markers(path, cues, ui_lang: str = "ja", names: dict | None = None) -> int:
    """字幕（編集後のもの）から話者交代のマーカーを作って、すでにあるタイムラインへ追加する。件数を返す。"""
    return add_markers(path, speaker_turn_markers(cues, ui_lang, names))


def add_markers(path, markers) -> int:
    """拡張子と根要素から形式を判断して追加する。非対応・失敗は 0 を返す（タイムラインは壊さない）。"""
    if not markers:
        return 0
    try:
        root_tag = safexml.parse(path).getroot().tag
        if root_tag == "fcpxml":
            return add_fcpxml_markers(path, markers)
        if root_tag == "xmeml":
            return add_xmeml_markers(path, markers)
    except Exception:
        return 0
    return 0
