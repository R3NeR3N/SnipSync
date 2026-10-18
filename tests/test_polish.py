"""文字起こしの清書（core/polish.py）。PC 上の LLM は、127.0.0.1 の偽のサーバーで代える。"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core import polish  # noqa: E402
from snipsync.core.subtitles import Cue  # noqa: E402
from snipsync.core.transcript import reading_turns  # noqa: E402


def cues():
    return [Cue(0.0, 5.0, "今日は説明します次に進みます", 0), Cue(5.0, 9.0, "はいどうぞ", 1),
            Cue(20.0, 25.0, "それはちょっと違うと思います", 0)]


def material():
    passages = reading_turns(cues(), para_gap=2.0)
    lines = polish.lines_from_passages(passages, lambda s: f"話者{s + 1}")
    return passages, lines


# ── 行・塊・指示文 ──────────────────────────────────────────────────────────────────────
def test_lines_are_one_per_paragraph_numbered_from_one():
    passages, lines = material()
    assert [ln.id for ln in lines] == list(range(1, len(lines) + 1)) and lines[0].label == "話者1"
    assert polish.format_line(lines[0]) == f"1｜話者1｜{lines[0].text}"


def test_chunks_split_on_line_boundaries_and_carry_the_previous_lines_as_context():
    lines = [polish.Line(i, "話者1", float(i), "あ" * 40) for i in range(1, 8)]
    chunks = polish.split_chunks(lines, max_chars=100, context=2)
    assert [len(c.lines) for c in chunks] == [2, 2, 2, 1]
    assert chunks[0].context == [] and [ln.id for ln in chunks[1].context] == [1, 2] and [ln.id for ln in chunks[3].context] == [5, 6]
    assert [ln.id for c in chunks for ln in c.lines] == list(range(1, 8))          # 順序も、欠けも無い
    assert [len(c.lines) for c in polish.split_chunks([polish.Line(1, "", 0, "あ" * 500)], 100)] == [1]   # 長い 1 行は、そのまま 1 塊
    assert polish.split_chunks([], 100) == []


def test_the_user_message_separates_context_from_the_lines_to_fix():
    lines = [polish.Line(i, "話者1", float(i), f"本文{i}") for i in range(1, 5)]
    chunk = polish.split_chunks(lines, max_chars=8, context=1)[1]
    msg = polish.build_user_message(chunk)
    assert msg.index("前の文脈") < msg.index("直す行") and "2｜話者1｜本文2" in msg.split("【直す行】")[0]
    assert "3｜話者1｜本文3" in msg.split("【直す行】")[1]


# ── 返事の検査 ──────────────────────────────────────────────────────────────────────────
def test_parse_response_reads_numbered_lines_and_ignores_the_rest():
    reply = "はい、直しました。\n1｜今日は、説明します。\n2|はい、どうぞ。\n3\t続きです\nおわり\n99｜関係ない"
    assert polish.parse_response(reply, [1, 2, 3]) == {1: "今日は、説明します。", 2: "はい、どうぞ。", 3: "続きです"}


def test_parse_response_keeps_the_first_of_a_repeated_number():
    assert polish.parse_response("1｜一つ目\n1｜二つ目", [1]) == {1: "一つ目"}


@pytest.mark.parametrize("original,fixed,ok", [
    ("今日は説明します次に進みます", "今日は、説明します。次に、進みます。", True),       # 句読点が足された
    ("えーと今日は説明します", "今日は説明します", True),                                    # 言い淀みを省いた
    ("今日は説明します次に進みます", "", False), ("今日は説明します次に進みます", "概要です", False),   # 要約
    ("短い", "短い文に、たくさんの内容を付け足してしまった長い文章になりました。", False),          # 付け足し
])
def test_acceptable_rejects_empty_summarised_or_padded_lines(original, fixed, ok):
    assert polish.acceptable(original, fixed) is ok


def test_merge_result_falls_back_per_line_and_strips_an_echoed_speaker_name():
    lines = [polish.Line(1, "話者1", 0, "今日は説明します"), polish.Line(2, "話者2", 1, "はいどうぞ"),
             polish.Line(3, "話者1", 2, "続きです")]
    got = {1: "話者1｜今日は、説明します。", 2: "要約"}                                  # 3 は、返ってこなかった
    ok, bad = polish.merge_result(lines, got)
    assert ok == {1: "今日は、説明します。"} and bad == 2


def test_apply_to_passages_replaces_only_the_fixed_paragraphs():
    passages, lines = material()
    fixed = polish.apply_to_passages(passages, lines, {1: "直した一行目。"})
    assert fixed[0].paras[0][1] == "直した一行目。"
    assert [p.paras for p in fixed[1:]] == [p.paras for p in passages[1:]]
    assert passages[0].paras[0][1] != "直した一行目。"                                   # 元は変えない


# ── 接続先は、この PC だけ ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("url,ok", [
    ("http://127.0.0.1:11434/v1", True), ("http://localhost:1234/v1", True), ("http://[::1]:8080/v1", True),
    ("https://api.example.com/v1", False), ("http://192.168.0.5:11434/v1", False), ("http://127.0.0.1.evil.com/v1", False),
    ("ftp://127.0.0.1/", False), ("", False), ("127.0.0.1:11434", False),
])
def test_only_local_endpoints_are_allowed(url, ok):
    assert polish.is_local_endpoint(url) is ok
    if not ok:
        with pytest.raises(polish.PolishError):
            polish.LocalLLM(url, "m")


class FakeLLM(BaseHTTPRequestHandler):
    mode = "echo"
    seen: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send(200, {"data": [{"id": "qwen2.5:14b"}, {"id": "gemma"}]})
        else:
            self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n).decode("utf-8"))
        FakeLLM.seen.append(req)
        if FakeLLM.mode == "error":
            self._send(500, {"error": "boom"})
            return
        user = req["messages"][1]["content"]
        target = user.split("【直す行】")[1].strip().splitlines()
        out = []
        for ln in target:
            num, _label, text = ln.split("｜", 2)
            out.append(f"{num}｜{text}。" if FakeLLM.mode == "echo" else f"{num}｜要約")
        self._send(200, {"choices": [{"message": {"content": "\n".join(out)}}]})


@pytest.fixture
def server():
    FakeLLM.mode, FakeLLM.seen = "echo", []
    srv = HTTPServer(("127.0.0.1", 0), FakeLLM)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def test_models_lists_what_the_local_server_has(server):
    assert polish.LocalLLM(server, "x").models() == ["qwen2.5:14b", "gemma"]


def test_polish_local_sends_chunks_and_collects_accepted_lines(server):
    _passages, lines = material()
    progress = []
    result = polish.polish_local(lines, polish.LocalLLM(server, "qwen2.5:14b"), max_chars=20,
                                 on_progress=lambda d, t: progress.append((d, t)))
    assert result.chunks == len(FakeLLM.seen) == progress[-1][1] and progress[-1][0] == progress[-1][1]
    assert result.fallbacks == 0 and set(result.texts) == {ln.id for ln in lines}
    assert all(FakeLLM.seen[0]["model"] == "qwen2.5:14b" and r["stream"] is False for r in FakeLLM.seen)
    assert FakeLLM.seen[0]["messages"][0]["role"] == "system" and "校正者" in FakeLLM.seen[0]["messages"][0]["content"]


def test_a_reply_that_summarises_is_not_accepted(server):
    FakeLLM.mode = "summarise"
    _passages, lines = material()
    result = polish.polish_local(lines, polish.LocalLLM(server, "m"))
    assert result.texts == {} and result.fallbacks == len(lines)


def test_a_server_error_becomes_a_polish_error(server):
    FakeLLM.mode = "error"
    _passages, lines = material()
    with pytest.raises(polish.PolishError, match="500"):
        polish.polish_local(lines, polish.LocalLLM(server, "m"))


def test_polish_can_be_stopped_between_chunks(server):
    _passages, lines = material()
    with pytest.raises(polish.PolishCancelled):
        polish.polish_local(lines, polish.LocalLLM(server, "m"), should_stop=lambda: True)
    assert FakeLLM.seen == []


def test_a_server_that_is_not_running_is_reported_not_crashed_on():
    with pytest.raises(polish.PolishError):
        polish.LocalLLM("http://127.0.0.1:9/v1", "m", timeout=2).models()


def test_a_redirect_to_another_host_is_not_followed():
    class Redirector(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://example.com/")
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), Redirector)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(polish.PolishError):
            polish.LocalLLM(f"http://127.0.0.1:{srv.server_address[1]}/v1", "m", timeout=3).models()
    finally:
        srv.shutdown()


# ── 貼り付け用の出力セット ──────────────────────────────────────────────────────────────
def test_paste_set_has_a_howto_and_self_contained_numbered_files(tmp_path):
    lines = [polish.Line(i, "話者1", float(i), "あ" * 40) for i in range(1, 8)]
    written = polish.write_paste_set(lines, tmp_path / "talk_polish", max_chars=100)
    assert [p.name for p in written] == ["00_使い方.md", "01.txt", "02.txt", "03.txt", "04.txt"]
    first = written[1].read_text(encoding="utf-8")
    assert "校正者" in first and "【直す行】" in first and "1｜話者1｜" in first
    assert "【前の文脈" in written[2].read_text(encoding="utf-8")
    assert "7 行、4 個" in written[0].read_text(encoding="utf-8")
    all_ids = [int(s.split("｜")[0]) for p in written[1:] for s in p.read_text(encoding="utf-8").split("【直す行】")[1].strip().splitlines()]
    assert all_ids == list(range(1, 8))


def test_paste_set_in_english(tmp_path):
    written = polish.write_paste_set([polish.Line(1, "Speaker 1", 0, "hello")], tmp_path / "x", lang="en")
    assert written[0].name == "00_howto.md" and "proofreader" in written[1].read_text(encoding="utf-8")


# ── 設定 ───────────────────────────────────────────────────────────────────────────────
def test_settings_roundtrip_default_and_broken_file(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert polish.load_settings() == {"mode": "paste", "endpoint": polish.DEFAULT_ENDPOINT, "model": "", "chunk": polish.CHUNK_CHARS}
    polish.save_settings({"mode": "local", "endpoint": "http://127.0.0.1:1234/v1", "model": "gemma", "chunk": 2000})
    assert polish.load_settings()["model"] == "gemma" and polish.load_settings()["mode"] == "local"
    polish._settings_path().write_text('{"mode": "evil", "model": 5}', encoding="utf-8")
    got = polish.load_settings()
    assert got["mode"] == "paste" and got["model"] == ""
    polish._settings_path().write_text("{broken", encoding="utf-8")
    assert polish.load_settings()["mode"] == "paste"


# ── 設定方法を調べるリンク ─────────────────────────────────────────────────────────────────
def test_guide_links_open_a_search_and_two_ai_pages_with_the_question_filled_in():
    from urllib.parse import parse_qs, urlparse
    links = polish.guide_links("ja")
    assert set(links) == {"browser", "claude", "chatgpt"}
    hosts = {k: urlparse(v).hostname for k, v in links.items()}
    assert hosts == {"browser": "www.google.com", "claude": "claude.ai", "chatgpt": "chatgpt.com"}
    assert all(urlparse(v).scheme == "https" for v in links.values())
    asked = parse_qs(urlparse(links["claude"]).query)["q"][0]
    assert "Ollama" in asked and "127.0.0.1:11434" in asked and "初心者" in asked
    assert parse_qs(urlparse(links["chatgpt"]).query)["q"][0] == asked
    assert "Ollama" in parse_qs(urlparse(links["browser"]).query)["q"][0]


def test_guide_text_carries_no_personal_data_or_transcript_text():
    for lang in ("ja", "en"):
        links = polish.guide_links(lang)
        text = polish.GUIDE_PROMPTS[lang] + polish.GUIDE_QUERIES[lang]
        assert "@" not in text and "\\" not in text and "C:" not in text
        assert all(len(u) < 1500 for u in links.values())
    assert "Ollama" in polish.guide_links("en")["claude"] and polish.guide_links("xx") == polish.guide_links("ja")


def test_the_local_llm_request_ignores_system_and_environment_proxies(monkeypatch):
    import urllib.request
    seen = {}

    class FakeOpener:
        def open(self, req, timeout=None):
            seen["opened"] = True
            return "response"

    def fake_build_opener(*handlers):
        seen["handlers"] = handlers
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    assert polish._default_open(object(), 1) == "response"
    proxies = [h for h in seen["handlers"] if isinstance(h, urllib.request.ProxyHandler)]
    assert len(proxies) == 1 and proxies[0].proxies == {}      # 空の ProxyHandler: プロキシを通さない
