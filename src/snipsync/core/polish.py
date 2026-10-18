"""文字起こしの清書（LLM）の部品。画面は知らない。

文字起こし（読みやすく整えたあとの段落）を、LLM に渡して、句読点・明らかな聞き間違いを直してもらう。方式は 2 つ。
- PC 上の LLM: Ollama・LM Studio・llama.cpp server などの、OpenAI 互換のローカル API に、http://127.0.0.1 宛てだけで接続する。
  文章は、この PC の外へ出ない（宛先がこの PC でなければ、接続しない）。モデルは、利用者が用意する。
- 貼り付け用の出力セット: 長い文章を、チャットに貼れる長さに分け、指示文をつけたファイルにする。結果は、利用者が自分で取り込む。

LLM が、勝手に要約したり、足したりしても、文字起こしが壊れないよう、返ってきた行は検査する（番号が合う・長さが近い）。
合わない行は、元の文のまま使う。
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlparse

from snipsync.core.transcript import Passage
from snipsync.version import APP_VERSION

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/v1"      # Ollama の既定
CHUNK_CHARS = 2500                                   # PC 上の LLM に、1 回で渡す本文の文字数（これを超えない行の区切りで分ける）
PASTE_CHUNK_CHARS = 5000                             # 貼り付け用ファイル 1 つの本文の文字数
CONTEXT_LINES = 2                                    # 各塊の前に付ける、前の文脈（直さない）の行数
MIN_RATIO, MAX_RATIO = 0.6, 1.6                      # 直した文の長さが、元の何倍までなら受け入れるか
REQUEST_TIMEOUT = 600
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

SYSTEM_PROMPTS = {
    "ja": (
        "あなたは、会議・対談・セミナーの文字起こしを整える校正者です。入力は、1 行 1 件の「番号｜話者｜本文」です。"
        "次を守って、本文だけを直してください。\n"
        "1. 句読点（、。？）を補い、読みやすくする。\n"
        "2. 明らかな聞き間違い・誤変換だけを直す。専門用語や固有名詞は、自信がなければ、そのままにする。\n"
        "3. 「えーと」「あのー」などの言い淀みは、意味が変わらない範囲で、省いてよい。\n"
        "4. 要約しない。内容を足さない。行をまとめたり、分けたり、並べ替えたりしない。（）で入っているあいづちも、残す。\n"
        "5. 出力は、入力と同じ番号・同じ行数の「番号｜本文」だけにする。話者名は書かない。説明や前置きも書かない。\n"
        "「前の文脈」の行は、参考です。出力しないでください。"),
    "en": (
        "You are a proofreader for transcripts of meetings, talks and interviews. The input has one item per line: "
        "\"number | speaker | text\". Fix only the text, following these rules.\n"
        "1. Add punctuation so it reads well.\n"
        "2. Correct only obvious mishearings. If unsure about a term or a name, leave it as it is.\n"
        "3. You may drop fillers (\"um\", \"uh\") when the meaning does not change.\n"
        "4. Do not summarise or add content. Do not merge, split or reorder lines. Keep bracketed backchannels.\n"
        "5. Output only \"number | text\" lines with the same numbers and line count. No speaker names, no explanation.\n"
        "Lines under \"Previous context\" are for reference only. Do not output them."),
}
CONTEXT_HEAD = {"ja": "【前の文脈（参考。出力しない）】", "en": "[Previous context (reference only, do not output)]"}
TARGET_HEAD = {"ja": "【直す行】", "en": "[Lines to fix]"}


class PolishError(Exception):
    """清書できなかった。利用者に見せてよい原因が入っている。"""


class PolishCancelled(Exception):
    """利用者の「停止」で、清書をやめた。"""


@dataclass(frozen=True)
class Line:
    id: int
    label: str          # 話者の表示名（無ければ空）
    start: float
    text: str


@dataclass
class Chunk:
    context: list = field(default_factory=list)      # 前の文脈（直さない）
    lines: list = field(default_factory=list)        # 直す行


@dataclass
class PolishResult:
    texts: dict                                      # 番号 -> 直した文（受け入れたものだけ）
    fallbacks: int                                   # 元の文のままにした行の数
    chunks: int


def lines_from_passages(passages: list[Passage], speaker_name) -> list[Line]:
    """段落ごとに 1 行にする。番号は 1 から。speaker_name(話者の番号) は、表示名を返す関数。"""
    out, n = [], 0
    for p in passages:
        label = speaker_name(p.speaker) if p.speaker is not None else ""
        for start, text in p.paras:
            n += 1
            out.append(Line(n, label, start, text))
    return out


def format_line(line: Line) -> str:
    return f"{line.id}｜{line.label}｜{line.text}"


def split_chunks(lines: list[Line], max_chars: int = CHUNK_CHARS, context: int = CONTEXT_LINES) -> list[Chunk]:
    """行の区切りで、本文が max_chars 字をこえない塊に分ける（1 行がこえるときは、その行だけで 1 塊）。
    2 つ目以降の塊には、直前の行を、前の文脈として付ける。"""
    chunks: list[Chunk] = []
    cur, size = [], 0
    for ln in lines:
        if cur and size + len(ln.text) > max_chars:
            chunks.append(Chunk(lines=cur))
            cur, size = [], 0
        cur.append(ln)
        size += len(ln.text)
    if cur:
        chunks.append(Chunk(lines=cur))
    done = 0
    for ch in chunks:
        ch.context = lines[max(0, done - context):done] if done else []
        done += len(ch.lines)
    return chunks


def build_user_message(chunk: Chunk, lang: str = "ja") -> str:
    lang = lang if lang in SYSTEM_PROMPTS else "ja"
    parts = []
    if chunk.context:
        parts += [CONTEXT_HEAD[lang], *map(format_line, chunk.context), ""]
    parts += [TARGET_HEAD[lang], *map(format_line, chunk.lines)]
    return "\n".join(parts)


_LINE = re.compile(r"^\s*(\d+)\s*[｜|\t]\s*(.*?)\s*$")


def parse_response(text: str, wanted: list[int]) -> dict[int, str]:
    """返ってきた文から、「番号｜本文」の行を取り出す。欲しい番号のものだけ。話者名つき（番号｜話者｜本文）も許す。"""
    out: dict[int, str] = {}
    want = set(wanted)
    for raw in text.splitlines():
        m = _LINE.match(raw)
        if not m:
            continue
        num, body = int(m.group(1)), m.group(2)
        if num in want and num not in out:
            out[num] = body
    return out


def acceptable(original: str, fixed: str) -> bool:
    """直した文を、受け入れてよいか。空でなく、長さが元に近いこと（要約や、付け足しを、はじく）。"""
    if not fixed.strip():
        return False
    n = max(1, len(original))
    return MIN_RATIO <= len(fixed) / n <= MAX_RATIO


def merge_result(lines: list[Line], raw: dict[int, str]) -> tuple[dict[int, str], int]:
    """LLM の返事を検査して、受け入れる行だけを返す。(番号 -> 直した文, 受け入れなかった行の数)。
    返事が、話者名を頭に付けて返してきたときは、それを外す。"""
    accepted, fallback = {}, 0
    for ln in lines:
        fixed = raw.get(ln.id)
        if fixed is not None and ln.label and fixed.startswith(f"{ln.label}｜"):
            fixed = fixed[len(ln.label) + 1:]
        if fixed is not None and acceptable(ln.text, fixed):
            accepted[ln.id] = fixed
        else:
            fallback += 1
    return accepted, fallback


# ── PC 上の LLM（OpenAI 互換のローカル API） ───────────────────────────────────────────
def is_local_endpoint(url: str) -> bool:
    u = urlparse(url.strip())
    return u.scheme in ("http", "https") and (u.hostname or "").lower() in LOCAL_HOSTS


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):          # 宛先を、この PC の外へ付け替えさせない
        return None


def _default_open(req, timeout):
    # Windows の「システムのプロキシ」や環境変数のプロキシを、通さない（通すと、文章が、プロキシ経由で PC の外へ出る）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    return opener.open(req, timeout=timeout)  # nosec B310 - 宛先は is_local_endpoint で検査済み


class LocalLLM:
    def __init__(self, endpoint: str, model: str, *, timeout: float = REQUEST_TIMEOUT, opener=_default_open):
        if not is_local_endpoint(endpoint):
            raise PolishError("not a local address (only 127.0.0.1 / localhost is allowed)")
        self.endpoint = endpoint.strip().rstrip("/")
        self.model = model.strip()
        self.timeout = timeout
        self._open = opener

    def _call(self, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.endpoint + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json", "User-Agent": f"SnipSync/{APP_VERSION}"})
        try:
            with self._open(req, self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise PolishError(f"HTTP {exc.code}") from exc
        except (OSError, ValueError) as exc:
            raise PolishError(str(exc) or type(exc).__name__) from exc

    def models(self) -> list[str]:
        """接続を確かめ、使えるモデルの名前を返す。"""
        data = self._call("/models")
        items = data.get("data") if isinstance(data, dict) else None
        return [str(m.get("id")) for m in (items or []) if isinstance(m, dict) and m.get("id")]

    def complete(self, system: str, user: str) -> str:
        data = self._call("/chat/completions", {
            "model": self.model, "temperature": 0.2, "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise PolishError("unexpected response from the model server") from exc


def polish_local(lines: list[Line], client, *, lang: str = "ja", max_chars: int = CHUNK_CHARS,
                 on_progress=None, should_stop=None) -> PolishResult:
    """lines を、塊ごとに client（complete(system, user) を持つもの）へ渡して、直した文を集める。
    on_progress(終わった塊, 全体の塊)。1 塊でも、接続に失敗したら PolishError（途中までの結果は、返さない）。"""
    system = SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS["ja"])
    chunks = split_chunks(lines, max_chars)
    texts: dict[int, str] = {}
    fallbacks = 0
    for i, chunk in enumerate(chunks):
        if should_stop and should_stop():
            raise PolishCancelled()
        reply = client.complete(system, build_user_message(chunk, lang))
        got = parse_response(reply, [ln.id for ln in chunk.lines])
        ok, bad = merge_result(chunk.lines, got)
        texts.update(ok)
        fallbacks += bad
        if on_progress:
            on_progress(i + 1, len(chunks))
    return PolishResult(texts, fallbacks, len(chunks))


def apply_to_passages(passages: list[Passage], lines: list[Line], texts: dict[int, str]) -> list[Passage]:
    """直した文を、段落に戻す（直っていない行は、元のまま）。lines は lines_from_passages の結果。"""
    out, k = [], 0
    for p in passages:
        paras = []
        for start, text in p.paras:
            k += 1
            paras.append((start, texts.get(lines[k - 1].id, text)))
        out.append(replace(p, paras=paras))
    return out


# ── 貼り付け用の出力セット ───────────────────────────────────────────────────────────
HOWTO = {
    "ja": """# 清書の貼り付けセット

この中の `01.txt`、`02.txt`… を、順番に、普段使っているチャット（Claude・ChatGPT など）へ貼って、返事を受け取ってください。
各ファイルは、指示文と本文が入っていて、そのまま貼れます。

- 返事は、「番号｜本文」の行です。番号は、元の文字起こしの行の番号です。
- 返事を、番号の順につなげると、清書した文字起こしになります。
- 長い文字起こしは、複数のファイルに分けています。ファイルごとに、新しい会話にしても、続けて貼っても構いません。
- 文字起こしの文章が、チャットのサービスへ送られます。送ってよい内容か、確認してから貼ってください。

全体: {total} 行、{count} 個のファイル
""",
    "en": """# Polish paste set

Paste `01.txt`, `02.txt`... one by one into the chat you normally use (Claude, ChatGPT, ...) and take the replies.
Each file holds the instructions and the text, so it can be pasted as it is.

- Each reply is made of "number | text" lines. The number is the line number of the original transcript.
- Join the replies in order of the numbers to get the polished transcript.
- A long transcript is split into several files. Use a new conversation per file, or paste them one after another.
- The text of the transcript is sent to the chat service. Check that it is fine to send before pasting.

Total: {total} lines, {count} files
""",
}


def write_paste_set(lines: list[Line], folder, *, lang: str = "ja", max_chars: int = PASTE_CHUNK_CHARS) -> list[Path]:
    """folder に、使い方（00_*.md）と、貼り付け用の塊（01.txt…）を書く。書いたパスを返す（使い方が先頭）。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    lang = lang if lang in SYSTEM_PROMPTS else "ja"
    chunks = split_chunks(lines, max_chars)
    howto = folder / ("00_使い方.md" if lang == "ja" else "00_howto.md")
    howto.write_text(HOWTO[lang].format(total=len(lines), count=len(chunks)), encoding="utf-8")
    written = [howto]
    width = max(2, len(str(len(chunks))))
    for i, chunk in enumerate(chunks, start=1):
        p = folder / f"{i:0{width}d}.txt"
        p.write_text(SYSTEM_PROMPTS[lang] + "\n\n" + build_user_message(chunk, lang) + "\n", encoding="utf-8")
        written.append(p)
    return written


# ── 「PC 上の LLM」の設定方法を調べる ─────────────────────────────────────────────────────
GUIDE_QUERIES = {
    "ja": "Ollama Windows インストール 日本語 モデル 使い方 初心者 OpenAI互換API",
    "en": "Ollama Windows install run a local LLM beginner OpenAI compatible API",
}
GUIDE_PROMPTS = {
    "ja": ("Windows で Ollama をインストールし、日本語の文字起こしの校正に使える LLM（例: Qwen2.5 の 7B〜14B）を、"
           "OpenAI 互換 API（http://127.0.0.1:11434/v1）として使えるようにする手順を、初心者向けに 1 ステップずつ、"
           "確認方法つきで教えて。PC のメモリ・GPU に合うモデルの選び方も。"),
    "en": ("On a Windows PC, how do I install Ollama, run an LLM that is good at proofreading Japanese transcripts "
           "(for example Qwen2.5 7B to 14B), and expose it as an OpenAI-compatible API (http://127.0.0.1:11434/v1) that "
           "another app can use? Explain step by step for a beginner, with a way to check each step worked, and how to "
           "choose a model that fits my PC's memory and GPU."),
}
GUIDE_SITES = {                                   # 名前 -> (検索や質問の宛先, 文を渡す方法)
    "browser": "https://www.google.com/search?q={}",
    "claude": "https://claude.ai/new?q={}",
    "chatgpt": "https://chatgpt.com/?q={}",
}


def guide_links(lang: str = "ja") -> dict:
    """設定方法を調べるための URL。browser はブラウザの検索、claude / chatgpt は、質問を入れた状態で AI の画面を開く。
    質問の文には、個人の情報も、文字起こしも入れない（一般的な手順を聞くだけ）。"""
    from urllib.parse import quote
    lang = lang if lang in GUIDE_QUERIES else "ja"
    return {
        "browser": GUIDE_SITES["browser"].format(quote(GUIDE_QUERIES[lang])),
        "claude": GUIDE_SITES["claude"].format(quote(GUIDE_PROMPTS[lang])),
        "chatgpt": GUIDE_SITES["chatgpt"].format(quote(GUIDE_PROMPTS[lang])),
    }


# ── 設定 ───────────────────────────────────────────────────────────────────────────
def _settings_path() -> Path:
    base = os.environ.get("APPDATA")
    return (Path(base) / "SnipSync" if base else Path.home() / ".snipsync") / "polish.json"


def load_settings() -> dict:
    out = {"mode": "paste", "endpoint": DEFAULT_ENDPOINT, "model": "", "chunk": CHUNK_CHARS}
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if isinstance(data, dict):
        for k, default in out.items():
            if isinstance(data.get(k), type(default)):
                out[k] = data[k]
    if out["mode"] not in ("local", "paste"):
        out["mode"] = "paste"
    return out


def save_settings(settings: dict) -> None:
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
