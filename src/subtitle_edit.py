"""字幕（Cue 列）を編集するためのロジック。画面（tkinter）には依存しない。

編集の単位は「字幕1件」。時刻は読み取り専用（字幕とカットの同期を壊さない）。変更できるのは
テキストと話者で、件の分割・結合・削除もできる。分割した時刻は、カーソル位置の文字数に比例して決める。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from subtitles import Cue, format_srt
from transcript import cues_to_md, cues_to_txt, join_text

FORMATS = ("txt", "md", "srt")


@dataclass
class _Item:
    cue: Cue
    original: str          # 読み込んだときのテキスト（「この字幕を元に戻す」用）


class CueEditor:
    """字幕の編集セッション。`cues` が現在の内容、`dirty` が未保存の変更の有無。"""

    def __init__(self, cues=()):
        self._items = [_Item(Cue(c.start, c.end, c.text, c.speaker), c.text) for c in cues]
        self.dirty = False

    # ── 参照 ──
    def __len__(self) -> int:
        return len(self._items)

    @property
    def cues(self) -> list[Cue]:
        return [Cue(i.cue.start, i.cue.end, i.cue.text, i.cue.speaker) for i in self._items]

    def cue(self, index: int) -> Cue:
        return self._items[index].cue

    def is_changed(self, index: int) -> bool:
        return self._items[index].cue.text != self._items[index].original

    def speakers(self) -> list[int]:
        return sorted({i.cue.speaker for i in self._items if i.cue.speaker is not None})

    # ── 編集 ──
    def set_text(self, index: int, text: str) -> bool:
        """テキストを置き換える。変わったら True。空にはできない（空なら削除を使う）。"""
        item = self._items[index]
        if text == item.cue.text:
            return False
        item.cue.text = text
        self.dirty = True
        return True

    def set_speaker(self, index: int, speaker: int | None) -> bool:
        item = self._items[index]
        if speaker == item.cue.speaker:
            return False
        item.cue.speaker = speaker
        self.dirty = True
        return True

    def revert(self, index: int) -> bool:
        return self.set_text(index, self._items[index].original)

    def delete(self, index: int) -> None:
        del self._items[index]
        self.dirty = True

    def merge_next(self, index: int) -> bool:
        """index と次の字幕を1件にする。最後の字幕では何もしない。"""
        if index < 0 or index >= len(self._items) - 1:
            return False
        a, b = self._items[index], self._items[index + 1]
        a.cue.text = join_text(a.cue.text, b.cue.text)
        a.cue.end = b.cue.end
        a.original = join_text(a.original, b.original)
        del self._items[index + 1]
        self.dirty = True
        return True

    def split(self, index: int, offset: int) -> bool:
        """テキストの offset 文字目で2件に分ける。時刻は文字数に比例して配分する。"""
        item = self._items[index]
        text = item.cue.text
        left, right = text[:offset].rstrip(), text[offset:].lstrip()
        if not left or not right:
            return False
        c = item.cue
        total = len(left) + len(right)
        t = round(c.start + (c.end - c.start) * len(left) / total, 3)
        if not (c.start < t < c.end):
            return False
        first = _Item(Cue(c.start, t, left, c.speaker), left)
        second = _Item(Cue(t, c.end, right, c.speaker), right)
        self._items[index:index + 1] = [first, second]
        self.dirty = True
        return True

    def mark_saved(self) -> None:
        self.dirty = False


def render(cues, fmt: str, *, timestamps: bool = True, line_chars: int = 0, ui_lang: str = "ja",
           title: str = "") -> str:
    """現在の字幕を txt / md / srt の文字列にする（プレビューと保存で同じ関数を使う）。"""
    cues = [c for c in cues if c.text.strip()]
    speakers = any(c.speaker is not None for c in cues)
    if fmt == "srt":
        return format_srt(cues, max_chars=line_chars, speaker_labels=speakers, ui_lang=ui_lang)
    if fmt == "md":
        return cues_to_md(cues, title=title or "subtitles", timestamps=timestamps, speakers=speakers,
                          ui_lang=ui_lang)
    if fmt == "txt":
        return cues_to_txt(cues, timestamps=timestamps, speakers=speakers, ui_lang=ui_lang)
    raise ValueError(f"unknown format: {fmt}")


def format_for_path(path) -> str:
    """保存先の拡張子から形式を決める。未知の拡張子は srt。"""
    ext = Path(path).suffix.lower().lstrip(".")
    return ext if ext in FORMATS else "srt"


def save(cues, path, *, timestamps: bool = True, line_chars: int = 0, ui_lang: str = "ja") -> str:
    """拡張子に合わせた形式で path に書く。書いた形式を返す。"""
    fmt = format_for_path(path)
    text = render(cues, fmt, timestamps=timestamps, line_chars=line_chars, ui_lang=ui_lang,
                  title=Path(path).stem)
    Path(path).write_text(text, encoding="utf-8")
    return fmt
