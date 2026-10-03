"""Subtitle (.srt) helpers."""
import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_cuda_dll_registered = False

# v1 JSON の chunk で「カット」を表す速度値（auto-editor 仕様）
_CUT_SPEED = 99999


def add_cuda_dll_dirs() -> None:
    """Register pip-installed CUDA libs so ctranslate2 can load cuBLAS/cuDNN.

    The GPU libs ship as ``nvidia-*`` wheels under ``site-packages/nvidia/*/bin``
    (kept inside the venv, not on the host) but ctranslate2 does not auto-discover
    them on Windows -> a CUDA WhisperModel fails with ``cublas64_12.dll ... cannot
    be loaded``. Add each ``bin`` dir to the DLL search path AND PATH *before* the
    model is built. No-op off Windows, when the wheels are absent, or if already run.
    """
    global _cuda_dll_registered
    if _cuda_dll_registered or sys.platform != "win32":
        return
    try:
        import nvidia
    except ImportError:
        return
    base = Path(list(nvidia.__path__)[0])
    for sub in base.iterdir():
        bind = sub / "bin"
        if bind.is_dir():
            os.add_dll_directory(str(bind))
            if str(bind) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(bind) + os.pathsep + os.environ.get("PATH", "")
    _cuda_dll_registered = True


def format_timestamp(seconds: float) -> str:
    """Seconds -> SRT timestamp ``HH:MM:SS,mmm``.

    Rounds to whole milliseconds first to avoid float truncation errors.
    """
    total_ms = int(round(seconds * 1000))
    hrs = total_ms // 3600000
    mins = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    ms = total_ms % 1000
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def cuda_available() -> bool:
    """Check if ctranslate2 can find at least one CUDA device. Return False on error."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def resolve_device(use_gpu: bool) -> tuple[str, str]:
    """Resolve (device, compute_type) based on GPU preference and availability."""
    if use_gpu and cuda_available():
        return "cuda", "int8_float16"
    return "cpu", "int8"


def parse_timestamp(ts_str: str) -> float:
    """SRT timestamp ``HH:MM:SS,mmm`` -> seconds (float)."""
    ts_str = ts_str.strip().replace(".", ",")
    parts = ts_str.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format: {ts_str}")
    hrs = int(parts[0])
    mins = int(parts[1])
    secs_parts = parts[2].split(",")
    if len(secs_parts) != 2:
        raise ValueError(f"Invalid timestamp format: {ts_str}")
    secs = int(secs_parts[0])
    ms = int(secs_parts[1])
    return hrs * 3600.0 + mins * 60.0 + secs + ms / 1000.0


def chunks_to_boundaries(chunks, tb):
    """v1 chunks [(start_frame, end_frame, speed)] -> タイムライン境界(秒)。

    speed>=99999 は cut(除去)。残る chunk の長さ (end-start)/speed を小数のまま累積し、
    境界ごとに最も近いフレームへ丸める。先頭 0.0 と終端を含む。

    倍速モードでは、auto-editor 31.7.2 の XML 上のクリップ位置と最大1フレーム以内で一致する（実測）。
    クリップごとの丸め規則は誤差を全体へ配分する方式で単純には再現できないが、累積して丸める
    この方式なら誤差が溜まらない。等速のみの場合は完全に一致する。
    tb 無し/残る区間無し -> []。
    """
    if not chunks or not tb:
        return []
    boundaries = [0.0]
    acc = 0.0
    for chunk in chunks:
        try:
            start, end, speed = chunk[0], chunk[1], chunk[2]
        except (IndexError, TypeError):
            continue
        if speed >= _CUT_SPEED:
            continue
        if speed <= 0:
            speed = 1.0
        acc += (end - start) / speed
        boundaries.append(round(int(acc + 0.5) / tb, 6))      # 四捨五入（.5 は切り上げ。実測の XML と同じ）
    if len(boundaries) <= 1:
        return []
    return sorted(set(boundaries))


def parse_v1_boundaries(json_path, tb):
    """auto-editor v1 JSON の chunks からタイムライン境界(秒)を作る。解析不能 -> []。"""
    import json
    try:
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except Exception:
        return []
    return chunks_to_boundaries(data.get("chunks", []), tb)


# ── 日本語向けの改行・字幕分割 ─────────────────────────────────────────────────────
# BudouX（Google 製・純Python）で文節境界を求め、文節の途中で改行しない。

_parsers: dict = {}


def _is_kana(ch: str) -> bool:
    return "぀" <= ch <= "ヿ"


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿" or _is_kana(ch)


def detect_cjk_lang(text: str, hint: str | None = None) -> str | None:
    """BudouX が使える言語コード(ja / zh-hans)を返す。使えなければ None。"""
    if hint:
        h = hint.lower()
        if h == "ja":
            return "ja"
        if h in ("zh", "zh-hans", "zh-cn"):
            return "zh-hans"
        if h == "zh-hant":
            return "zh-hant"
        return None
    if any(_is_kana(c) for c in text):
        return "ja"
    return None


def _get_parser(lang: str):
    if lang in _parsers:
        return _parsers[lang]
    parser = None
    try:
        import budoux
        loader = {
            "ja": "load_default_japanese_parser",
            "zh-hans": "load_default_simplified_chinese_parser",
            "zh-hant": "load_default_traditional_chinese_parser",
        }.get(lang)
        if loader:
            parser = getattr(budoux, loader)()
    except Exception:
        parser = None
    _parsers[lang] = parser
    return parser


def display_width(text: str) -> int:
    """半角=1・全角=2 で数えた表示幅。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def _phrases(text: str, lang: str | None) -> list[str]:
    """文節（BudouX）または空白区切りの塊に分ける。結合すると元の text に戻る。"""
    cjk = detect_cjk_lang(text, lang)
    if cjk:
        parser = _get_parser(cjk)
        if parser is not None:
            return parser.parse(text)
        return list(text)
    # 空白区切り語（空白は直前の語へ付ける）
    out, cur = [], ""
    for ch in text:
        cur += ch
        if ch == " ":
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def wrap_text(text: str, max_chars: int, lang: str | None = None) -> str:
    """text を 1行 max_chars 全角文字（表示幅 max_chars*2）以内に改行する。

    max_chars<=0 は無加工。文節の途中では改行しない（1文節が1行を超える場合のみ強制分割）。
    """
    text = text.strip()
    limit = max_chars * 2
    if max_chars <= 0 or display_width(text) <= limit:
        return text
    lines: list[str] = []
    cur = ""
    for ph in _phrases(text, lang):
        if cur and display_width(cur + ph) > limit:
            lines.append(cur.strip())
            cur = ""
        while display_width(ph) > limit:           # 1文節が1行を超える
            head = ""
            for i, ch in enumerate(ph):
                if display_width(head + ch) > limit:
                    break
                head += ch
            lines.append((cur + head).strip())
            cur = ""
            ph = ph[len(head):]
        cur += ph
    if cur.strip():
        lines.append(cur.strip())
    return "\n".join(lines)


# ── 話者 ────────────────────────────────────────────────────────────────────────

def speaker_label(index: int, lang: str = "ja") -> str:
    return f"話者{index + 1}" if lang == "ja" else f"Speaker {index + 1}"


def normalize_turns(turns):
    """[(start, end, raw_id)] を開始順に並べ、話者番号を登場順の 0,1,2.. に振り直す。"""
    ordered = sorted(turns, key=lambda t: (t[0], t[1]))
    mapping: dict = {}
    out = []
    for s, e, raw in ordered:
        if raw not in mapping:
            mapping[raw] = len(mapping)
        out.append((s, e, mapping[raw]))
    return out


def speaker_for_span(start: float, end: float, turns, max_gap: float = 1.0):
    """[start,end] と最も重なる話者。重なりが無ければ max_gap 秒以内で最寄りの話者、無ければ None。"""
    best, best_ov = None, 0.0
    for s, e, spk in turns:
        ov = min(end, e) - max(start, s)
        if ov > best_ov:
            best, best_ov = spk, ov
    if best is not None:
        return best
    mid = (start + end) / 2
    near, near_d = None, max_gap
    for s, e, spk in turns:
        d = 0.0 if s <= mid <= e else min(abs(mid - s), abs(mid - e))
        if d <= near_d:
            near, near_d = spk, d
    return near


def tag_words(words, turns):
    """(start, end, text) の単語列へ話者番号を付け (start, end, text, speaker) にする。"""
    return [(w[0], w[1], w[2], speaker_for_span(w[0], w[1], turns)) for w in words]


# ── 字幕（Cue）の生成 ───────────────────────────────────────────────────────────

@dataclass
class Cue:
    start: float
    end: float
    text: str
    speaker: int | None = None


def _spk(word):
    return word[3] if len(word) > 3 else None


def _group_by_speaker(words):
    groups: list[list] = []
    for w in words:
        if groups and _spk(groups[-1][-1]) == _spk(w):
            groups[-1].append(w)
        else:
            groups.append([w])
    return groups


def _split_words_by_length(words, max_chars: int, max_lines: int, lang: str | None):
    """1つの字幕が長すぎるとき、文節境界を優先して単語列を複数の字幕に分ける。

    1字幕の上限は「max_chars 全角文字で文節改行して max_lines 行に収まる長さ」。
    上限を超える直前で、直近の文節終端（BudouX）に切る。ただし極端に短い字幕を作らないよう、
    文節終端が現在の長さの 1/3 未満の位置にしか無いときは単語境界で切る。
    """
    if max_chars <= 0:
        return [words]

    def fits(ws):
        txt = "".join(w[2] for w in ws)
        return wrap_text(txt, max_chars, lang).count("\n") + 1 <= max_lines

    text = "".join(w[2] for w in words)
    if fits(words):
        return [words]
    ends, pos = set(), 0
    for ph in _phrases(text, lang):
        pos += len(ph)
        ends.add(pos)
    offs, pos = [], 0
    for w in words:
        pos += len(w[2])
        offs.append(pos)
    groups, start_i, last_ok, i = [], 0, None, 0
    while i < len(words):
        if i > start_i and not fits(words[start_i:i + 1]):
            use_phrase = last_ok is not None and (last_ok - start_i) * 3 >= (i - start_i)
            cut = last_ok if use_phrase else i
            groups.append(words[start_i:cut])
            start_i, last_ok, i = cut, None, cut
            continue
        if offs[i] in ends:
            last_ok = i + 1
        i += 1
    groups.append(words[start_i:])
    return groups


def _cues_from_word_groups(groups, first_start, hard_end):
    """単語グループ列 -> Cue 列。最初の Cue だけ first_start に揃え、重なりを除く。"""
    cues: list[Cue] = []
    for idx, g in enumerate(groups):
        text = "".join(w[2] for w in g).strip()
        if not text:
            continue
        start = first_start if idx == 0 else g[0][0]
        end = min(max(w[1] for w in g), hard_end)
        cues.append(Cue(start, end, text, _spk(g[0])))
    for a, b in zip(cues, cues[1:], strict=False):
        if a.end > b.start:
            a.end = b.start
    return [c for c in cues if c.start < c.end]


def build_cut_aligned_cues(words, natural_segments, boundaries, *,
                           max_chars: int = 0, max_lines: int = 2, lang: str | None = None):
    """whisper word-level を「カット境界 ∪ 文境界」で再分割した Cue 列を返す。

    各区間 [b_i, b_{i+1}) に start が入る単語を 1 字幕に連結。
    カット境界由来の b_i は字幕 start に厳密一致する。空区間/ゼロ尺は除外。
    単語が (start, end, text, speaker) の4要素なら、話者が変わる所でも字幕を分ける。
    max_chars>0 のとき、長い字幕は文節境界で複数に分ける。
    boundaries か words が空なら [] を返す（呼び出し側でフォールバック）。
    """
    if not boundaries or not words:
        return []

    breaks = {round(b, 3) for b in boundaries}
    for seg_start, _seg_end in natural_segments:
        breaks.add(round(seg_start, 3))
    last_word_end = max(w[1] for w in words)
    breaks.add(round(last_word_end, 3))
    breaks = sorted(breaks)

    cues: list[Cue] = []
    for i in range(len(breaks) - 1):
        b0, b1 = breaks[i], breaks[i + 1]
        seg_words = [w for w in words if b0 <= round(w[0], 3) < b1]
        if not seg_words:
            continue
        groups: list[list] = []
        for sg in _group_by_speaker(seg_words):
            groups.extend(_split_words_by_length(sg, max_chars, max_lines, lang))
        cues.extend(_cues_from_word_groups(groups, b0, b1))
    return cues


def cues_from_segments(segments, turns=None, *, max_chars: int = 0, max_lines: int = 2,
                       lang: str | None = None):
    """自然な whisper セグメントから Cue 列を作る（カット整合を使わない経路）。

    segments: [(start, end, text, words|None)]。turns があれば話者を付ける。
    話者も分割も不要な場合は、セグメントをそのまま 1 字幕にする（従来と同じ出力）。
    """
    cues: list[Cue] = []
    for start, end, text, words in segments:
        text = text.strip()
        if not text:
            continue
        if words and (turns or max_chars > 0):
            w4 = tag_words(words, turns) if turns else words
            groups: list[list] = []
            for sg in _group_by_speaker(w4):
                groups.extend(_split_words_by_length(sg, max_chars, max_lines, lang))
            made = _cues_from_word_groups(groups, start, end)
            if made:
                cues.extend(made)
                continue
        spk = speaker_for_span(start, end, turns) if turns else None
        cues.append(Cue(start, end, text, spk))
    return cues


def format_srt(cues, *, max_chars: int = 0, lang: str | None = None,
               speaker_labels: bool = False, ui_lang: str = "ja") -> str:
    """Cue 列 -> SRT 文字列。max_chars>0 で日本語の文節改行、speaker_labels で話者名を前置。"""
    out = []
    for idx, c in enumerate(cues, start=1):
        text = wrap_text(c.text, max_chars, lang) if max_chars > 0 else c.text
        if speaker_labels and c.speaker is not None:
            sep = "：" if ui_lang == "ja" else ": "
            text = f"{speaker_label(c.speaker, ui_lang)}{sep}{text}"
        out.append(str(idx))
        out.append(f"{format_timestamp(c.start)} --> {format_timestamp(c.end)}")
        out.append(text)
        out.append("")
    return "\n".join(out)


def build_cut_aligned_srt(words, natural_segments, boundaries):
    """build_cut_aligned_cues を SRT 文字列にしたもの（従来の呼び出し口を維持）。"""
    return format_srt(build_cut_aligned_cues(words, natural_segments, boundaries))
