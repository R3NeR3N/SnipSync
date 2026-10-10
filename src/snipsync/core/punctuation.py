"""句読点（日本語）。字幕（.srt）には付けず、文字起こし（.txt / .md）を読みやすくするためのもの。

Whisper は、会話の録音では、句読点をほとんど出さなくなる（実測: 約 95 分の録音で、100 字あたり 2.5 個。普通の文章は 8〜10 個）。
2 段で補う:
1. 生成時: 句読点入りの見本文（initial_prompt）を渡す。実測（large-v3, 同じ録音の 5 分 × 2 か所）で、句読点が 100 字あたり
   2.95 → 4.54、4.71 → 5.96 に増える。「前の文脈を引き継がない」設定にすると、逆に 0〜2 に減るので使わない。
2. 語の時刻から: 語と語の間の無音の長さと、文末の形（です・ます・ね…）から、「、」「。」「？」を足す。
   語の時刻が要るので、字幕を作る前（生成時）にしか使えない。

字幕（.srt）は、句読点を付けない慣習なので、書き出すときに「、。」を除く（strip_subtitle_punctuation）。
文字起こしと編集画面の本文には、句読点が残る。
"""
from __future__ import annotations

import re

# 日本語の見本文（実測で効果を確かめたもの。他の言語は、確かめていないので使わない）
PROMPTS = {
    "ja": "はい、そうですね。今日は、対話について話します。私は、こう思います。皆さんは、どうですか？",
}

END_MARKS = "、。，．！？!?"           # すでに句読点・文末記号が付いている語は、足さない
SENTENCE_GAP = 0.35                  # 文末の形のあとに、これ以上の間があれば、文の終わり
LONG_GAP = 1.0                       # 文末の形でなくても、これ以上の間があれば、文の終わり
COMMA_GAP = 0.40                     # 文の途中で、これ以上の間があれば、読点
CLAUSE_GAP = 0.15                    # 「けど」「ので」などの接続のあとは、これ以上の間で、読点
LONG_RUN_CHARS = 40                  # 句読点が、これだけ続けて無いときは、短い間（RUN_GAP）でも読点を足す
RUN_GAP = 0.20

_FINAL = re.compile(
    r"(です|ます|でした|ました|ません|ませんでした|でしょう|ましょう|ください|ですね|ますね|ですよ|ますよ|ですよね|ますよね|"
    r"だよ|だね|だな|だよね|よね|かな|かね|ですか|ますか|でしたか|ましたか|だった|である|思う|いる|ある|ない|った|ちゃう|"
    r"ですけどね|よ|ね|ぞ|わ)$")
# 間が無くても、文の終わりと分かる形（「ありがとうございますはい」のように、Whisper が句読点を落としたときのため）
_STRONG_FINAL = re.compile(
    r"(です|ます|でした|ました|ません|でしょう|ください|ですね|ますね|ですよ|ますよ|ですか|ますか|ですよね|ますよね|"
    r"ございます|でしたか|ましたか|だった|ですけど|ますけど)$")
# 新しい文の頭に来やすい語。直前が文末の形なら、そこで文を切る
_STARTERS = ("はい", "あ、", "あの", "えっと", "えーと", "うん", "ああ", "じゃあ", "でも", "だって", "そうですね", "そうそう",
             "ありがとう", "すいません", "すみません", "私", "僕", "俺", "あと", "では", "それでは", "なので", "ちなみに")
_QUESTION = re.compile(r"(ですか|ますか|でしたか|ましたか|かな|かね|のか|だろうか|でしょうか)$")
_CLAUSE = re.compile(r"(けど|けれど|けれども|ですが|ますが|ので|から|のに|ですし|ますし|けども|ながら)$")


def prompt_for(lang: str | None) -> str | None:
    """この言語で、句読点を増やす見本文。効果を確かめていない言語は None。"""
    return PROMPTS.get((lang or "").lower())


def strip_subtitle_punctuation(text: str) -> str:
    """字幕から「、。」を除く（日本語の字幕は、句読点を付けない慣習）。「？」「！」は残す。"""
    return re.sub(r"[、。，．]", "", text)


def normalize_marks(text: str) -> str:
    """日本語の文にまじった半角の「,」「.」「?」「!」を、全角にする（前後が数字・英字のときは、そのまま）。"""
    text = re.sub(r"(?<![0-9A-Za-z]),(?![0-9A-Za-z])", "、", text)
    text = re.sub(r"(?<![0-9A-Za-z])\.(?![0-9A-Za-z])", "。", text)
    return text.replace("?", "？").replace("!", "！")


def _ends_with_mark(text: str) -> bool:
    t = text.rstrip()
    return bool(t) and t[-1] in END_MARKS


def punctuate_words(words, lang: str | None = None):
    """(start, end, text[, speaker]) の語列に、「、」「。」「？」を足して返す（語の数・時刻・話者は変えない）。
    日本語（lang が ja、または日本語の文字を含む）のときだけ働く。Whisper がすでに付けた句読点は、そのまま残す。"""
    if not words:
        return list(words)
    text_all = "".join(w[2] for w in words)
    if (lang or "").lower() != "ja" and not any("぀" <= c <= "ヿ" for c in text_all):
        return list(words)
    out = [list(w) for w in words]
    for i, w in enumerate(out):
        w[2] = normalize_marks(w[2])
    n = len(out)
    tail = ""                                               # 直前の文の切れ目から、ここまでの文字（文末の形の判定用）
    run = 0                                                 # 最後の句読点から、ここまでの文字数
    for i, w in enumerate(out):
        tail = (tail + w[2].strip())[-12:]
        run += len(w[2])
        last = i == n - 1
        nxt = out[i + 1] if not last else None
        marked = _ends_with_mark(w[2])
        gap = max(0.0, nxt[0] - w[1]) if nxt else 0.0
        turn_end = last or (len(w) > 3 and nxt is not None and nxt[3] != w[3])
        if marked:
            tail, run = "", 0
            continue
        final = bool(_FINAL.search(tail))
        ahead = "".join(x[2] for x in out[i + 1:i + 4]) if nxt else ""
        starts_sentence = bool(_STRONG_FINAL.search(tail)) and ahead.startswith(_STARTERS)
        if turn_end or (final and gap >= SENTENCE_GAP) or gap >= LONG_GAP or starts_sentence:
            w[2] = w[2] + ("？" if _QUESTION.search(tail) else "。")
            tail, run = "", 0
        elif gap >= COMMA_GAP or (gap >= CLAUSE_GAP and _CLAUSE.search(tail)) or (run >= LONG_RUN_CHARS and gap >= RUN_GAP):
            w[2] = w[2] + "、"
            run = 0
    return [tuple(w) for w in out]
