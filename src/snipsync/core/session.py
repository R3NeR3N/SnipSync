"""字幕の編集の途中経過（セッション）を、出力のそばのファイル（``<名前>.snipsync.json``）に保存・復元する。

なぜ必要か: .srt / .txt / .md だけでは、アプリを閉じたあとに、話者名・元の字幕との差（変更の印）・元に戻す前の
状態・「どの動画の、どのカット設定か」が失われ、続きの編集も、時刻を押しての再生もできない。
セッションには、編集中の字幕と元の字幕、話者名、元の動画のパス、カットの設定を入れる。
壊れたファイル・別の形式のファイルは、SessionError にして、画面は落とさない。
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

FORMAT = 1
SUFFIX = ".snipsync.json"
MAX_BYTES = 256 * 1024 * 1024        # 想定より大きなファイルは、読まない（誤って別のファイルを開いたとき）

# セッションに残す、カットの設定（再生のために、元の動画から同じカット区間を作り直す）
SETTING_KEYS = ("margin", "threshold", "cut_mode", "silence", "speed", "line_chars")


class SessionError(Exception):
    """セッションを読めない。利用者に見せてよい原因が入っている。"""


@dataclass
class Session:
    title: str = ""
    source: str = ""                                     # 元の動画のパス（無ければ空）
    settings: dict = field(default_factory=dict)
    editor: dict = field(default_factory=dict)           # CueEditor.export_state() の結果
    saved_at: str = ""


def session_path(output_path) -> Path:
    """出力ファイルのそばに置く、セッションのパス（``名前.srt`` -> ``名前.snipsync.json``）。"""
    p = Path(output_path)
    return p.with_name(p.stem + SUFFIX)


def is_session_path(path) -> bool:
    return str(path).lower().endswith(SUFFIX)


def pick_settings(settings: dict) -> dict:
    return {k: settings[k] for k in SETTING_KEYS if k in settings}


def write_session(path, session: Session) -> Path:
    """path へ書く（書きかけのファイルが残らないよう、別名で書いてから置き換える）。"""
    path = Path(path)
    data = {
        "format": FORMAT, "title": session.title, "source": session.source,
        "settings": pick_settings(session.settings), "editor": session.editor,
        "saved_at": session.saved_at or datetime.now().isoformat(timespec="seconds"),
    }
    tmp = path.with_name(path.name + ".part")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def _check_cue_row(row, *, with_ids: bool) -> None:
    need = 5 if with_ids else 4
    if not isinstance(row, list) or len(row) != need:
        raise SessionError("a subtitle row has an unexpected shape")
    start, end, text, speaker = row[:4]
    ok = (isinstance(start, (int, float)) and isinstance(end, (int, float)) and math.isfinite(start)
          and math.isfinite(end) and isinstance(text, str)
          and (speaker is None or (isinstance(speaker, int) and not isinstance(speaker, bool) and speaker >= 0)))
    if not ok:
        raise SessionError("a subtitle row has an unexpected value")
    if with_ids and not (isinstance(row[4], list) and row[4] and all(isinstance(i, int) and i >= 0 for i in row[4])):
        raise SessionError("a subtitle row has an unexpected origin")


def read_session(path) -> Session:
    """path のセッションを読む。形式が合わなければ SessionError。"""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise SessionError("the file is too large to be a session")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except SessionError:
        raise
    except (OSError, ValueError) as exc:
        raise SessionError(str(exc) or type(exc).__name__) from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise SessionError("this is not a SnipSync session of a supported version")
    ed = data.get("editor")
    if not isinstance(ed, dict) or not isinstance(ed.get("items"), list) or not isinstance(ed.get("original"), list):
        raise SessionError("the session has no subtitles")
    for row in ed["original"]:
        _check_cue_row(row, with_ids=False)
    for row in ed["items"]:
        _check_cue_row(row, with_ids=True)
        if any(i >= len(ed["original"]) for i in row[4]):
            raise SessionError("a subtitle points to a missing original")
    names = ed.get("names", {})
    if not isinstance(names, dict) or not all(isinstance(v, str) and str(k).isdigit() for k, v in names.items()):
        raise SessionError("the speaker names are malformed")
    settings = data.get("settings")
    return Session(
        title=str(data.get("title") or ""), source=str(data.get("source") or ""),
        settings=pick_settings(settings) if isinstance(settings, dict) else {},
        editor=ed, saved_at=str(data.get("saved_at") or ""))
