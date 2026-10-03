"""字幕（Cue 列）を編集するためのロジック。画面（tkinter）には依存しない。

編集の単位は「字幕1件」。時刻は読み取り専用（字幕とカットの同期を壊さない）。変更できるのは
テキストと話者で、件の分割・結合・削除もできる。分割した時刻は、カーソル位置の文字数に比例して決める。

どの操作も「元に戻す／やり直す」できる（状態ごと保存する）。各件は、元の字幕のどれに由来するか（ids）を持ち、
結合や分割のあとでも「この字幕を元に戻す」で元の字幕へ戻せる。話者名は番号とは別に付けられる。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from subtitles import Cue, format_srt
from transcript import cues_to_md, cues_to_txt, join_text

FORMATS = ("txt", "md", "srt")
MAX_HISTORY = 200


@dataclass
class _Item:
    cue: Cue
    ids: tuple          # 元の字幕の番号。結合した件は複数、分割した件は同じ番号を共有する


class CueEditor:
    """字幕の編集セッション。`cues` が現在の内容、`dirty` が未保存の変更の有無。"""

    def __init__(self, cues=()):
        self._orig = [Cue(c.start, c.end, c.text, c.speaker) for c in cues]
        self._items = [_Item(Cue(c.start, c.end, c.text, c.speaker), (i,)) for i, c in enumerate(self._orig)]
        self.names: dict[int, str] = {}                 # 話者番号 -> 表示名（無ければ「話者N」）
        self._undo: list = []
        self._redo: list = []
        self._last_key = None                            # 直前の操作の種類（文字入力をひとまとめにするため）
        self._saved = self._state()
        self._force_dirty = False

    # ── 状態の保存・復元 ──
    def _state(self):
        return (tuple((i.cue.start, i.cue.end, i.cue.text, i.cue.speaker, i.ids) for i in self._items),
                tuple(sorted(self.names.items())))

    def _restore(self, state):
        items, names = state
        self._items = [_Item(Cue(s, e, t, sp), ids) for s, e, t, sp, ids in items]
        self.names = dict(names)

    def _push(self, key=None):
        """変更の直前に呼ぶ。key が前回と同じ（同じ件の文字入力が続いている）ときは、まとめて1回分にする。"""
        if key is not None and key == self._last_key:
            return
        self._undo.append(self._state())
        del self._undo[:-MAX_HISTORY]
        self._redo.clear()
        self._last_key = key

    def _break(self):
        self._last_key = None

    def end_typing(self) -> None:
        """文字入力のまとまりをここで区切る（次の入力は、元に戻すで別の1回分になる）。"""
        self._last_key = None

    # ── 参照 ──
    def __len__(self) -> int:
        return len(self._items)

    @property
    def cues(self) -> list[Cue]:
        return [Cue(i.cue.start, i.cue.end, i.cue.text, i.cue.speaker) for i in self._items]

    def cue(self, index: int) -> Cue:
        return self._items[index].cue

    def is_changed(self, index: int) -> bool:
        """元の字幕と違うか（文・話者・時刻、結合や分割も含む）。"""
        item = self._items[index]
        if len(item.ids) != 1:
            return True
        o, c = self._orig[item.ids[0]], item.cue
        return (c.text, c.speaker, c.start, c.end) != (o.text, o.speaker, o.start, o.end)

    def speakers(self) -> list[int]:
        return sorted({i.cue.speaker for i in self._items if i.cue.speaker is not None})

    def speaker_name(self, speaker: int | None, default: str) -> str:
        return self.names.get(speaker, default) if speaker is not None else ""

    @property
    def dirty(self) -> bool:
        return self._force_dirty or self._state() != self._saved

    @dirty.setter
    def dirty(self, value: bool) -> None:
        if value:
            self._force_dirty = True
        else:
            self.mark_saved()

    def mark_saved(self) -> None:
        self._saved = self._state()
        self._force_dirty = False

    # ── 元に戻す・やり直す ──
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._state())
        self._restore(self._undo.pop())
        self._break()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._state())
        self._restore(self._redo.pop())
        self._break()
        return True

    # ── 編集 ──
    def set_text(self, index: int, text: str) -> bool:
        """テキストを置き換える。変わったら True。同じ件への続けての入力は、元に戻すとき1回分になる。"""
        item = self._items[index]
        if text == item.cue.text:
            return False
        self._push(("text", item.ids, index))
        item.cue.text = text
        return True

    def set_speaker(self, index: int, speaker: int | None) -> bool:
        return self.set_speakers([index], speaker)

    def set_speakers(self, indices, speaker: int | None) -> bool:
        """複数の件の話者をまとめて変える（元に戻すは1回分）。1件でも変わったら True。"""
        targets = [i for i in indices if self._items[i].cue.speaker != speaker]
        if not targets:
            return False
        self._push()
        for i in targets:
            self._items[i].cue.speaker = speaker
        self._break()
        return True

    def rename_speaker(self, speaker: int, name: str) -> bool:
        """話者の表示名を付ける（その話者のすべての字幕に効く）。空にすると「話者N」に戻る。"""
        name = name.strip()
        if name == self.names.get(speaker, ""):
            return False
        self._push()
        if name:
            self.names[speaker] = name
        else:
            self.names.pop(speaker, None)
        self._break()
        return True

    def revert(self, index: int) -> bool:
        """この字幕を、取り込んだときの状態に戻す。結合・分割したものは、元の字幕へ戻す。"""
        if not self.is_changed(index):
            return False
        ids = set(self._items[index].ids)
        lo = hi = index
        while lo > 0 and ids & set(self._items[lo - 1].ids):          # 同じ元の字幕に由来する、つながった範囲
            lo -= 1
        while hi < len(self._items) - 1 and ids & set(self._items[hi + 1].ids):
            hi += 1
        for k in range(lo, hi + 1):
            ids |= set(self._items[k].ids)
        self._push()
        restored = [_Item(Cue(o.start, o.end, o.text, o.speaker), (n,))
                    for n in sorted(ids) for o in [self._orig[n]]]
        self._items[lo:hi + 1] = restored
        self._break()
        return True

    def delete(self, index: int) -> None:
        self._push()
        del self._items[index]
        self._break()

    def merge_next(self, index: int) -> bool:
        """index と次の字幕を1件にする。最後の字幕では何もしない。"""
        if index < 0 or index >= len(self._items) - 1:
            return False
        self._push()
        a, b = self._items[index], self._items[index + 1]
        a.cue.text = join_text(a.cue.text, b.cue.text)
        a.cue.end = b.cue.end
        a.ids = tuple(sorted(set(a.ids) | set(b.ids)))
        del self._items[index + 1]
        self._break()
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
        self._push()
        first = _Item(Cue(c.start, t, left, c.speaker), item.ids)
        second = _Item(Cue(t, c.end, right, c.speaker), item.ids)
        self._items[index:index + 1] = [first, second]
        self._break()
        return True


def render(cues, fmt: str, *, timestamps: bool = True, line_chars: int = 0, ui_lang: str = "ja",
           title: str = "", names: dict | None = None) -> str:
    """現在の字幕を txt / md / srt の文字列にする（プレビューと保存で同じ関数を使う）。"""
    cues = [c for c in cues if c.text.strip()]
    speakers = any(c.speaker is not None for c in cues)
    if fmt == "srt":
        return format_srt(cues, max_chars=line_chars, speaker_labels=speakers, ui_lang=ui_lang, names=names)
    if fmt == "md":
        return cues_to_md(cues, title=title or "subtitles", timestamps=timestamps, speakers=speakers,
                          ui_lang=ui_lang, names=names)
    if fmt == "txt":
        return cues_to_txt(cues, timestamps=timestamps, speakers=speakers, ui_lang=ui_lang, names=names)
    raise ValueError(f"unknown format: {fmt}")


def format_for_path(path) -> str:
    """保存先の拡張子から形式を決める。未知の拡張子は srt。"""
    ext = Path(path).suffix.lower().lstrip(".")
    return ext if ext in FORMATS else "srt"


def save(cues, path, *, timestamps: bool = True, line_chars: int = 0, ui_lang: str = "ja",
         names: dict | None = None) -> str:
    """拡張子に合わせた形式で path に書く。書いた形式を返す。"""
    fmt = format_for_path(path)
    text = render(cues, fmt, timestamps=timestamps, line_chars=line_chars, ui_lang=ui_lang,
                  title=Path(path).stem, names=names)
    Path(path).write_text(text, encoding="utf-8")
    return fmt
