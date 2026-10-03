"""セキュリティ対策の退行防止（XXE・URL スキーム・取得物の固定・テレメトリ・CI の供給網）。"""
import os
import re
import sys
from pathlib import Path

import pytest
from defusedxml.common import DefusedXmlException

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import aebin  # noqa: E402
import diarize  # noqa: E402
import markers  # noqa: E402
import models  # noqa: E402
import safexml  # noqa: E402

XXE = """<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///C:/Windows/win.ini">]>
<fcpxml version="1.11"><resources><format id="r1" frameDuration="1/30s"/></resources>&xxe;</fcpxml>
"""

BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>
<xmeml version="5"><sequence><name>&b;</name></sequence></xmeml>
"""


@pytest.mark.parametrize("payload", [XXE, BILLION_LAUGHS])
def test_safexml_rejects_doctype_and_entities(tmp_path, payload):
    p = tmp_path / "evil.xml"
    p.write_text(payload, encoding="utf-8")
    with pytest.raises(DefusedXmlException):      # DTDForbidden / EntitiesForbidden
        safexml.parse(p)


def test_safexml_reads_a_normal_timeline(tmp_path):
    p = tmp_path / "ok.fcpxml"
    p.write_text('<?xml version="1.0"?><fcpxml version="1.11"><resources/></fcpxml>', encoding="utf-8")
    assert safexml.parse(p).getroot().tag == "fcpxml"


@pytest.mark.parametrize("payload", [XXE, BILLION_LAUGHS])
def test_marker_insertion_refuses_hostile_xml_without_touching_the_file(tmp_path, payload):
    p = tmp_path / "evil.xml"
    p.write_text(payload, encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    assert markers.add_markers(p, [(1.0, "x")]) == 0
    assert p.read_text(encoding="utf-8") == before


def test_pipeline_xml_helpers_refuse_hostile_xml_without_touching_the_file(tmp_path):
    import pipeline
    p = tmp_path / "evil.fcpxml"
    p.write_text(XXE, encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    assert pipeline._reorder_fcpxml_tracks(p, "clip") is False       # 解析を拒否して何もしない
    assert p.read_text(encoding="utf-8") == before


# ── ダウンロード: https のみ・ハッシュ検証・リビジョン固定 ───────────────────────────────

def test_downloads_refuse_non_https_urls(tmp_path, monkeypatch):
    monkeypatch.setattr(aebin, "asset", lambda: ("x.exe", "file:///C:/Windows/System32/cmd.exe", "0" * 64))
    with pytest.raises(ValueError, match="https"):
        aebin.download(tmp_path / "x.exe")
    with pytest.raises(ValueError, match="https"):
        diarize._download("http://example.com/model.onnx", tmp_path / "m.onnx")
    with pytest.raises(ValueError, match="https"):
        diarize._download("file:///C:/secret.txt", tmp_path / "m.onnx")


def test_all_pinned_urls_are_https_and_hashes_are_sha256():
    for _arch, (name, sha) in aebin._ASSETS.items():
        assert name.endswith(".exe") and re.fullmatch(r"[0-9a-f]{64}", sha)
    assert aebin._RELEASE.startswith("https://github.com/WyattBlue/auto-editor/releases/download/")
    for url in (diarize.SEG_URL, diarize.EMB_URL):
        assert url.startswith("https://github.com/k2-fsa/sherpa-onnx/releases/download/")
    for h in (diarize.SEG_SHA256, diarize.EMB_SHA256):
        assert re.fullmatch(r"[0-9a-f]{64}", h)


def test_kotoba_download_is_pinned_to_a_commit(tmp_path, monkeypatch):
    spec = models.MODELS["kotoba-ja"]
    assert spec.revision and re.fullmatch(r"[0-9a-f]{40}", spec.revision)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    calls = {}

    def fake_snapshot_download(repo, **kw):
        calls.update(kw, repo=repo)
        d = Path(kw["local_dir"])
        (d / "model.bin").write_bytes(b"x")
        (d / "config.json").write_text('{"alignment_heads": [[7, 0]]}', encoding="utf-8")

    # huggingface_hub が無い環境（CI の最小構成）でも検査できるよう、偽のモジュールを差し込む
    import types
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(snapshot_download=fake_snapshot_download))
    models.prepare_model("kotoba-ja")
    assert calls["revision"] == spec.revision and calls["repo"] == spec.source


# ── プライバシー ───────────────────────────────────────────────────────────────

def test_app_disables_hugging_face_telemetry_before_importing_faster_whisper():
    src = (ROOT / "src" / "app.py").read_text(encoding="utf-8")
    assert src.index("HF_HUB_DISABLE_TELEMETRY") < src.index("from faster_whisper import")
    if "HF_HUB_DISABLE_TELEMETRY" not in os.environ:
        pytest.importorskip("customtkinter")
        import app  # noqa: F401
        assert os.environ.get("HF_HUB_DISABLE_TELEMETRY") == "1"


# ── CI / リリースの供給網 ─────────────────────────────────────────────────────────

WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_third_party_actions_are_pinned_to_a_full_commit_sha(wf):
    for line in wf.read_text(encoding="utf-8").splitlines():
        m = re.search(r"uses:\s*([\w.-]+/[\w./-]+)@(\S+)", line)
        if m and not m.group(1).startswith("./"):
            assert re.fullmatch(r"[0-9a-f]{40}", m.group(2)), f"{wf.name}: {m.group(1)}@{m.group(2)} is not a commit SHA"


def test_release_workflow_grants_write_only_to_the_build_job():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    top = text.split("\njobs:")[0]
    assert re.search(r"^permissions:\s*\n\s+contents:\s*read", top, re.M)
    build = text.split("  build:")[1]
    assert re.search(r"permissions:\s*\n\s+contents:\s*write", build)
    assert "scripts/fetch_auto_editor.py" in text and "auto-editor faster-whisper" not in text


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_checkout_does_not_persist_credentials(wf):
    text = wf.read_text(encoding="utf-8")
    assert text.count("actions/checkout@") == text.count("persist-credentials: false")
