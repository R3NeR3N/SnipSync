"""字幕（Cue 列）を読みやすい .txt / .md の文字起こしにする。"""
from subtitles import Cue, speaker_label


def hms(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _join(a: str, b: str) -> str:
    """日本語など CJK の続きは詰め、空白区切りの言語は半角スペースで繋ぐ。"""
    if not a:
        return b
    if a[-1] >= "　" or b[:1] >= "　":
        return a + b
    return a + " " + b


def merge_turns(cues: list[Cue]) -> list[Cue]:
    """連続する同一話者の字幕を1つの発話にまとめる（話者なしは1字幕=1発話のまま）。"""
    turns: list[Cue] = []
    for c in cues:
        text = " ".join(c.text.split("\n")).strip()
        if turns and c.speaker is not None and turns[-1].speaker == c.speaker:
            turns[-1].text = _join(turns[-1].text, text)
            turns[-1].end = c.end
        else:
            turns.append(Cue(c.start, c.end, text, c.speaker))
    return turns


def cues_to_txt(cues: list[Cue], *, timestamps: bool = True, speakers: bool = True,
                ui_lang: str = "ja") -> str:
    sep = "：" if ui_lang == "ja" else ": "
    lines = []
    for t in merge_turns(cues):
        head = ""
        if timestamps:
            head += f"[{hms(t.start)}] "
        if speakers and t.speaker is not None:
            head += f"{speaker_label(t.speaker, ui_lang)}{sep}"
        lines.append(head + t.text)
    return "\n".join(lines) + ("\n" if lines else "")


def cues_to_md(cues: list[Cue], *, title: str, timestamps: bool = True, speakers: bool = True,
               ui_lang: str = "ja") -> str:
    turns = merge_turns(cues)
    names = sorted({t.speaker for t in turns if t.speaker is not None})
    out = [f"# {title}", ""]
    if speakers and names:
        who = "、".join(speaker_label(n, ui_lang) for n in names)
        out.append(f"- 話者: {who}" if ui_lang == "ja" else f"- Speakers: {who}")
    out.append(f"- 字幕数: {len(cues)}" if ui_lang == "ja" else f"- Cues: {len(cues)}")
    out.append("")
    for t in turns:
        stamp = f"`{hms(t.start)}`" if timestamps else ""
        if speakers and t.speaker is not None:
            out.append(f"## {speaker_label(t.speaker, ui_lang)} {stamp}".rstrip())
            out += ["", t.text, ""]
        else:
            out.append(f"{stamp} {t.text}".strip())
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def write_transcripts(cues, base_path, *, title: str, want_txt: bool, want_md: bool,
                      timestamps: bool = True, speakers: bool = True, ui_lang: str = "ja"):
    """base_path（拡張子なし）に .txt / .md を書き、作ったパスのリストを返す。"""
    from pathlib import Path
    base = Path(base_path)
    written = []
    if want_txt:
        p = base.with_suffix(".txt")
        p.write_text(cues_to_txt(cues, timestamps=timestamps, speakers=speakers, ui_lang=ui_lang),
                     encoding="utf-8")
        written.append(p)
    if want_md:
        p = base.with_suffix(".md")
        p.write_text(cues_to_md(cues, title=title, timestamps=timestamps, speakers=speakers,
                                ui_lang=ui_lang), encoding="utf-8")
        written.append(p)
    return written


def parse_srt(text: str) -> list[Cue]:
    """SRT 文字列 -> Cue 列（プレビュー用。話者は解釈せず、本文はそのまま保つ）。"""
    from subtitles import parse_timestamp
    cues: list[Cue] = []
    for block in text.replace("\r\n", "\n").strip().split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if len(lines) < 2:
            continue
        # 1行目が連番、2行目が時刻。連番の無い SRT も許す。
        time_idx = 1 if "-->" not in lines[0] and len(lines) > 2 else 0
        if "-->" not in lines[time_idx]:
            continue
        try:
            a, b = lines[time_idx].split("-->")
            start, end = parse_timestamp(a), parse_timestamp(b)
        except ValueError:
            continue
        cues.append(Cue(start, end, "\n".join(lines[time_idx + 1:]), None))
    return cues
