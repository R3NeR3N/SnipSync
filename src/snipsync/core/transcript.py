"""字幕（Cue 列）を読みやすい .txt / .md の文字起こしにする。"""
import re
from dataclasses import dataclass, field

from snipsync.core.subtitles import Cue, speaker_label


def hms(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def join_text(a: str, b: str) -> str:
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
            turns[-1].text = join_text(turns[-1].text, text)
            turns[-1].end = c.end
        else:
            turns.append(Cue(c.start, c.end, text, c.speaker))
    return turns


@dataclass
class Passage:
    """読みやすく整えた発言。同じ話者の続きの字幕と、間に挟まれたあいづちを、1 つにまとめたもの。"""
    speaker: int | None
    start: float
    end: float
    paras: list = field(default_factory=list)       # [(段落の開始秒, 本文)]


SENTENCE_END = "。？！?!"
BACKCHANNELS = ("bracket", "drop", "keep")          # あいづちを、（）で本文に入れる／省く／そのまま別の行に


def reading_turns(cues: list[Cue], *, names: dict | None = None, ui_lang: str = "ja", backchannel: str = "bracket",
                  interject_chars: int = 8, para_chars: int = 240, para_gap: float = 2.0) -> list[Passage]:
    """字幕を、読み物として整えた発言の列にする（.txt / .md 用。字幕 .srt には使わない）。

    - 同じ話者の字幕は、つなげる。
    - 別の話者の短い発言（interject_chars 字以下）が、同じ話者の発言に挟まれているときは、あいづちとみなす。
      backchannel="bracket" は、挟まれた位置の本文に「（話者2：はい）」と入れる。"drop" は省く。"keep" は、特別扱いしない。
      これで、「…廃棄物を。」「うまい。」「こと処理したい」のように、1 つの文が、あいづちで割れなくなる。
    - 長い発言は、文の終わり（。？！）で、段落に分ける。文字数が para_chars 以上たまったとき、または、字幕の間が
      para_gap 秒以上あいたとき。
    話者が付いていない字幕も、つなげて段落にする。
    """
    items = [(c.start, c.end, " ".join(c.text.split("\n")).strip(), c.speaker) for c in cues if c.text.strip()]
    runs: list[list] = []                              # [話者, [字幕...]]
    for it in items:
        if runs and runs[-1][0] == it[3]:
            runs[-1][1].append(it)
        else:
            runs.append([it[3], [it]])
    inter = set()
    if backchannel != "keep":
        for k in range(1, len(runs) - 1):
            before, mid, after = runs[k - 1], runs[k], runs[k + 1]
            if (before[0] is not None and before[0] == after[0] and mid[0] != before[0]
                    and sum(len(x[2]) for x in mid[1]) <= interject_chars):
                inter.add(k)

    sep = "：" if ui_lang == "ja" else ": "
    turns: list[dict] = []                             # {speaker, start, end, pieces}
    for k, (speaker, group) in enumerate(runs):
        if k in inter:
            if backchannel == "bracket" and turns:
                text = " ".join(x[2] for x in group)
                label = speaker_label(speaker, ui_lang, names) if speaker is not None else ""
                turns[-1]["pieces"].append(("i", group[0][0], f"（{label}{sep}{text}）" if ui_lang == "ja"
                                            else f" ({label}{sep}{text})"))
            if turns:
                turns[-1]["end"] = max(turns[-1]["end"], group[-1][1])
            continue
        if turns and turns[-1]["speaker"] == speaker:
            turns[-1]["end"] = group[-1][1]
        else:
            turns.append({"speaker": speaker, "start": group[0][0], "end": group[-1][1], "pieces": []})
        turns[-1]["pieces"] += [("t", x[0], x[2], x[1]) for x in group]

    out: list[Passage] = []
    for t in turns:
        paras: list[list] = []                         # [開始秒, 本文]
        last_text, last_end, chars = "", 0.0, 0
        for piece in t["pieces"]:
            if piece[0] == "i":
                if paras:
                    paras[-1][1] += piece[2]
                continue
            _kind, start, text, end = piece
            if (paras and last_text[-1:] in tuple(SENTENCE_END)
                    and (chars >= para_chars or start - last_end >= para_gap)):
                paras.append([start, text])
                chars = 0
            elif paras:
                paras[-1][1] = join_text(paras[-1][1], text)
            else:
                paras.append([start, text])
            chars += len(text)
            last_text, last_end = text, end
        out.append(Passage(t["speaker"], t["start"], t["end"], [(p[0], p[1]) for p in paras]))
    return out


def cues_to_txt(cues: list[Cue], *, timestamps: bool = True, speakers: bool = True,
                ui_lang: str = "ja", names: dict | None = None, reading: bool = False,
                backchannel: str = "bracket") -> str:
    sep = "：" if ui_lang == "ja" else ": "
    lines = []
    if reading:
        for t in reading_turns(cues, names=names, ui_lang=ui_lang, backchannel=backchannel):
            for start, text in t.paras:                # 段落ごとに 1 行。話者名は、毎行つける（どの行だけを写しても、誰の発言か分かる）
                head = f"[{hms(start)}] " if timestamps else ""
                if speakers and t.speaker is not None:
                    head += f"{speaker_label(t.speaker, ui_lang, names)}{sep}"
                lines.append(head + text)
        return "\n".join(lines) + ("\n" if lines else "")
    for t in merge_turns(cues):
        head = ""
        if timestamps:
            head += f"[{hms(t.start)}] "
        if speakers and t.speaker is not None:
            head += f"{speaker_label(t.speaker, ui_lang, names)}{sep}"
        lines.append(head + t.text)
    return "\n".join(lines) + ("\n" if lines else "")


def cues_to_md(cues: list[Cue], *, title: str, timestamps: bool = True, speakers: bool = True,
               ui_lang: str = "ja", names: dict | None = None, reading: bool = False,
               backchannel: str = "bracket") -> str:
    turns = reading_turns(cues, names=names, ui_lang=ui_lang, backchannel=backchannel) if reading else merge_turns(cues)
    ids = sorted({t.speaker for t in turns if t.speaker is not None})
    out = [f"# {title}", ""]
    if speakers and ids:
        who = "、".join(speaker_label(n, ui_lang, names) for n in ids)
        out.append(f"- 話者: {who}" if ui_lang == "ja" else f"- Speakers: {who}")
    out.append(f"- 字幕数: {len(cues)}" if ui_lang == "ja" else f"- Cues: {len(cues)}")
    out.append("")
    for t in turns:
        stamp = f"`{hms(t.start)}`" if timestamps else ""
        texts = [p[1] for p in t.paras] if reading else [t.text]
        if speakers and t.speaker is not None:
            out.append(f"## {speaker_label(t.speaker, ui_lang, names)} {stamp}".rstrip())
            for text in texts:
                out += ["", text]
            out.append("")
        else:
            for k, text in enumerate(texts):
                out.append(f"{stamp if k == 0 else ''} {text}".strip())
                out.append("")
    return "\n".join(out).rstrip() + "\n"


def write_transcripts(cues, base_path, *, title: str, want_txt: bool, want_md: bool,
                      timestamps: bool = True, speakers: bool = True, ui_lang: str = "ja", reading: bool = False):
    """base_path（拡張子なし）に .txt / .md を書き、作ったパスのリストを返す。"""
    from pathlib import Path
    base = Path(base_path)
    written = []
    if want_txt:
        p = base.with_suffix(".txt")
        p.write_text(cues_to_txt(cues, timestamps=timestamps, speakers=speakers, ui_lang=ui_lang, reading=reading),
                     encoding="utf-8")
        written.append(p)
    if want_md:
        p = base.with_suffix(".md")
        p.write_text(cues_to_md(cues, title=title, timestamps=timestamps, speakers=speakers,
                                ui_lang=ui_lang, reading=reading), encoding="utf-8")
        written.append(p)
    return written


_SPEAKER_PREFIX = re.compile(r"^(?:話者|Speaker )(\d+)(?:：|: ?)", re.IGNORECASE)


def split_speaker_prefix(text: str):
    """本文の頭の「話者N：」/「Speaker N: 」を (話者の番号（0 始まり）, 残りの本文) にする。無ければ (None, text)。"""
    m = _SPEAKER_PREFIX.match(text)
    if not m or int(m.group(1)) < 1:
        return None, text
    return int(m.group(1)) - 1, text[m.end():]


def parse_srt(text: str, speakers: bool = False) -> list[Cue]:
    """SRT 文字列 -> Cue 列。speakers=False（プレビュー用）は、本文をそのまま保つ。
    speakers=True は、本文の頭の「話者N：」を話者として読み、本文から外す（書き出した字幕を開き直して、続きを編集する用）。
    話者名を付けた字幕（「山田：」など）は、番号に戻せないので、本文のまま。"""
    from snipsync.core.subtitles import parse_timestamp
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
        body = "\n".join(lines[time_idx + 1:])
        speaker = None
        if speakers:
            speaker, body = split_speaker_prefix(body)
        cues.append(Cue(start, end, body, speaker))
    return cues
