"""パイプラインの新機能（VAD・倍速・メディア書き出し・自前音声・話者・マーカー・txt/md）。

auto-editor / faster-whisper / sherpa-onnx は実物を使わず、subprocess と DI でモックする。
実物での通し検証は docs/handoff/verification-2026-10.md を参照。
"""
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import pipeline as pl  # noqa: E402
from test_pipeline import DummySegment, DummyWord, make_mock_popen, stub_tr  # noqa: E402

np = pytest.importorskip("numpy")

XMEML = ('<?xml version="1.0"?><xmeml version="5"><sequence><name>s</name><duration>100</duration>'
         '<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate><media><video/></media></sequence></xmeml>')


@pytest.fixture
def dirs(tmp_path):
    inp = tmp_path / "input.mp4"
    inp.write_bytes(b"dummy")
    out = tmp_path / "out"
    out.mkdir()
    return inp, out


class Recorder:
    """Popen のコマンドを記録し、--output にダミー（または v1 JSON / XML）を書く。"""

    def __init__(self, v1_chunks=None, xml=False):
        self.cmds = []
        self.v1_chunks = v1_chunks
        self.xml = xml
        self.seen_inputs = {}

    def __call__(self, cmd):
        self.cmds.append(list(cmd))
        if "--output" not in cmd:
            return
        out = Path(cmd[cmd.index("--output") + 1])
        if "v1" in cmd and self.v1_chunks is not None:
            out.write_text(json.dumps({"chunks": self.v1_chunks}), encoding="utf-8")
        elif self.xml and out.suffix == ".xml":
            out.write_text(XMEML, encoding="utf-8")
        else:
            out.write_bytes(b"dummy")
        # 入力が JSON のときは、その時点の中身を覚えておく（後で削除されるため）
        src = Path(cmd[1])
        if src.suffix == ".json" and src.exists():
            self.seen_inputs[src.name] = json.loads(src.read_text(encoding="utf-8"))


def run(dirs, monkeypatch, params, rec, transcribe=None, **kw):
    inp, out = dirs
    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(stdout_lines=["x"], write_output=rec))
    return run_pipeline_with(inp, out, params, transcribe, **kw)


def run_pipeline_with(inp, out, params, transcribe=None, **kw):
    logs = []
    res = pl.run_pipeline("ae", inp, out, params, on_log=lambda m, lvl="": logs.append((m, lvl)),
                          should_stop=lambda: False, tr=stub_tr, transcribe=transcribe, **kw)
    return res, logs


def base_params(**kw):
    d = dict(margin=0.2, threshold=4.0, export_key="premiere", do_srt=False, model_size="small")
    d.update(kw)
    return pl.PipelineParams(**d)


# ── ヘルパ ──────────────────────────────────────────────────────────────────────

def test_output_ext_for_media_and_timelines():
    assert pl._output_ext("media", Path("a.mp4")) == ".mp4"
    assert pl._output_ext("media", Path("a.MOV")) == ".mov"
    assert pl._output_ext("media", Path("a.avi")) == ".mp4"            # 互換性の高い mp4 へ
    assert pl._output_ext("media", Path("talk.m4a")) == ".wav"         # 同梱の auto-editor に m4a/mp3/aac のエンコーダーが無い
    assert pl._output_ext("media", Path("talk.mp3")) == ".wav"
    assert pl._output_ext("media", Path("talk.flac")) == ".flac"       # 書き出せる形式は拡張子を保つ
    assert pl._output_ext("resolve", Path("a.mp4")) == ".fcpxml"
    assert pl._output_ext("premiere", Path("a.mp4")) == ".xml"


def test_hotwords_normalization():
    assert pl._hotwords("SnipSync, DaVinci\nResolve、 ") == "SnipSync, DaVinci, Resolve"
    assert pl._hotwords("  ,\n ") is None


# ── コマンド組み立て ────────────────────────────────────────────────────────────

def test_silent_speed_reaches_cut_command(dirs, monkeypatch):
    rec = Recorder()
    res, _ = run(dirs, monkeypatch, base_params(silent_speed=8), rec)
    assert res.ok
    cmd = rec.cmds[0]
    assert cmd[cmd.index("--when-inactive") + 1] == "speed:8"


def test_media_export_has_no_export_flag_and_keeps_extension(dirs, monkeypatch):
    rec = Recorder()
    res, _ = run(dirs, monkeypatch, base_params(export_key="media"), rec)
    assert res.ok and res.timeline_path.name == "input_snipsynced.mp4"
    assert "--export" not in rec.cmds[0] and "-an" not in rec.cmds[0]   # 音声ありの動画(判別不能=非モノラル)


def test_out_stem_renames_outputs(dirs, monkeypatch):
    rec = Recorder()
    res, _ = run(dirs, monkeypatch, base_params(out_stem="input_2"), rec)
    assert res.timeline_path.name == "input_2_snipsynced.xml"


# ── VAD 方式 ────────────────────────────────────────────────────────────────────

def test_vad_mode_feeds_chunks_json_and_cleans_up(dirs, monkeypatch):
    inp, out = dirs
    monkeypatch.setattr(pl, "probe_fps", lambda p: 30.0)
    monkeypatch.setattr(pl, "probe_duration", lambda p: 10.0)
    monkeypatch.setattr(pl, "decode_mix", lambda p, sr=16000: np.zeros(160000, dtype=np.float32))
    monkeypatch.setattr(pl, "detect_speech", lambda s: [(1.0, 2.0), (4.0, 6.0)])
    rec = Recorder()
    res, logs = run(dirs, monkeypatch, base_params(cut_mode="vad", margin=0.2), rec)
    assert res.ok
    cmd = rec.cmds[0]
    assert cmd[1].endswith("input_cuts_vad.json")
    assert "--margin" not in cmd and "--edit" not in cmd               # 区間は JSON が持つ
    assert cmd[cmd.index("-tb") + 1] == "30"
    chunks = rec.seen_inputs["input_cuts_vad.json"]["chunks"]
    assert [c[2] for c in chunks] == [99999.0, 1.0, 99999.0, 1.0, 99999.0]
    assert not (out / "input_cuts_vad.json").exists()                   # 一時 JSON は消える


def test_vad_mode_falls_back_to_threshold_when_decoding_fails(dirs, monkeypatch):
    monkeypatch.setattr(pl, "probe_fps", lambda p: 30.0)

    def boom(*a, **k):
        raise RuntimeError("decode failed")
    monkeypatch.setattr(pl, "decode_mix", boom)
    rec = Recorder()
    res, logs = run(dirs, monkeypatch, base_params(cut_mode="vad"), rec)
    assert res.ok
    assert "--edit" in rec.cmds[0] and rec.cmds[0][1].endswith("input.mp4")
    assert any(lvl == "error" for _, lvl in logs)


def test_vad_mode_falls_back_when_no_speech_found(dirs, monkeypatch):
    monkeypatch.setattr(pl, "probe_fps", lambda p: 30.0)
    monkeypatch.setattr(pl, "probe_duration", lambda p: 10.0)
    monkeypatch.setattr(pl, "decode_mix", lambda p, sr=16000: np.zeros(160000, dtype=np.float32))
    monkeypatch.setattr(pl, "detect_speech", lambda s: [])
    rec = Recorder()
    res, logs = run(dirs, monkeypatch, base_params(cut_mode="vad"), rec)
    assert res.ok and "--edit" in rec.cmds[0]
    assert any(m == "log_vad_none" for m, _ in logs)


# ── 字幕用の音声を chunks から自前で作る ───────────────────────────────────────────

def test_subtitle_audio_is_built_from_chunks_without_extra_ae_render(dirs, monkeypatch):
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    monkeypatch.setattr(pl, "decode_mix", lambda p, sr=16000: np.zeros(20 * sr, dtype=np.float32))
    seen = {}

    def transcribe(wav, model):
        with wave.open(str(wav)) as w:
            seen["dur"] = w.getnframes() / w.getframerate()
            seen["rate"] = w.getframerate()
        return iter([DummySegment(0.0, 1.0, "Hi")]), type("I", (), {"language": "en", "language_probability": 1.0})()

    rec = Recorder(v1_chunks=[[0, 30, 1.0], [30, 60, 99999.0], [60, 90, 1.0]])
    res, _ = run(dirs, monkeypatch, base_params(do_srt=True, snap_srt=False), rec, transcribe=transcribe)
    assert res.ok and res.srt_path.exists()
    assert seen["rate"] == 16000 and seen["dur"] == pytest.approx(6.0)  # 3s + 3s
    assert not any("-vn" in c for c in rec.cmds)                        # AE の WAV 書き出しは走らない


def test_subtitle_audio_falls_back_to_auto_editor_wav_when_unbuildable(dirs, monkeypatch):
    # ダミー動画はデコードできない -> 従来どおり auto-editor で WAV を作る
    seen = {}

    def transcribe(wav, model):
        seen["exists"] = Path(wav).exists()
        return iter([DummySegment(0.0, 1.0, "Hi")]), type("I", (), {"language": "en", "language_probability": 1.0})()

    rec = Recorder()
    res, _ = run(dirs, monkeypatch, base_params(do_srt=True, snap_srt=False), rec, transcribe=transcribe)
    assert res.ok and seen["exists"]
    assert any("-vn" in c for c in rec.cmds)


# ── メディア書き出し（31.x はモノラルも正しく書くので、auto-editor にそのまま任せる）──────────

def test_audio_only_media_export_uses_auto_editor_render(tmp_path, monkeypatch):
    inp = tmp_path / "talk.wav"
    inp.write_bytes(b"dummy")
    out = tmp_path / "out"
    out.mkdir()
    rec = Recorder()
    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(stdout_lines=["x"], write_output=rec))
    res, _ = run_pipeline_with(inp, out, base_params(export_key="media"))
    assert res.ok and res.timeline_path.name == "talk_snipsynced.wav"
    assert "--export" not in rec.cmds[0] and rec.cmds[0][1].endswith("talk.wav")


def test_unsupported_audio_format_is_rendered_as_wav(tmp_path, monkeypatch):
    inp = tmp_path / "talk.m4a"
    inp.write_bytes(b"dummy")
    out = tmp_path / "out"
    out.mkdir()
    rec = Recorder()
    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(stdout_lines=["x"], write_output=rec))
    res, _ = run_pipeline_with(inp, out, base_params(export_key="media"))
    assert res.ok and res.timeline_path.name == "talk_snipsynced.wav"


def test_media_export_warns_when_resolution_exceeds_unlicensed_limit(dirs, monkeypatch):
    monkeypatch.setattr(pl, "probe_resolution", lambda p: (3840, 2160))
    rec = Recorder()
    res, logs = run(dirs, monkeypatch, base_params(export_key="media"), rec)
    assert res.ok
    assert any(m == "log_media_downscale:3840,2160" and lvl == "warn" for m, lvl in logs)


def test_timeline_export_does_not_warn_about_resolution(dirs, monkeypatch):
    monkeypatch.setattr(pl, "probe_resolution", lambda p: (3840, 2160))
    rec = Recorder()
    res, logs = run(dirs, monkeypatch, base_params(export_key="premiere"), rec)
    assert res.ok and not any(m.startswith("log_media_downscale") for m, _ in logs)   # XML 出力は制限なし


# ── 話者・txt/md・マーカー ─────────────────────────────────────────────────────────

def _transcribe_two_speakers(wav, model):
    segs = [
        DummySegment(0.0, 2.0, "こんにちは", [DummyWord(0.0, 1.0, "こんにちは")]),
        DummySegment(3.0, 5.0, "お願いします", [DummyWord(3.0, 4.0, "お願いします")]),
    ]
    return iter(segs), type("I", (), {"language": "ja", "language_probability": 1.0})()


def test_diarize_labels_srt_and_transcripts_and_markers(dirs, monkeypatch):
    inp, out = dirs
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    monkeypatch.setattr(pl, "decode_mix", lambda p, sr=16000: np.zeros(20 * sr, dtype=np.float32))
    monkeypatch.setattr(pl, "sherpa_available", lambda: True)
    monkeypatch.setattr(pl, "diarize", lambda samples, **k: [(0.0, 2.5, 5), (2.5, 6.0, 9)])
    rec = Recorder(v1_chunks=[[0, 60, 1.0]], xml=True)
    params = base_params(do_srt=True, snap_srt=False, diarize=True, txt=True, md=True, markers=True)
    res, logs = run(dirs, monkeypatch, params, rec, transcribe=_transcribe_two_speakers)
    assert res.ok
    srt = res.srt_path.read_text(encoding="utf-8")
    assert "話者1：こんにちは" in srt and "話者2：お願いします" in srt
    assert [p.name for p in res.extra_paths] == ["input.txt", "input.md"]
    assert "[00:00:03] 話者2：お願いします" in (out / "input.txt").read_text(encoding="utf-8")
    xml = (out / "input_snipsynced.xml").read_text(encoding="utf-8")
    assert xml.count("<marker>") == res.markers_added == 2              # 話者交代2件（終端はカット点ではない）
    assert "話者2" in xml


def test_diarize_failure_continues_without_labels(dirs, monkeypatch):
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    monkeypatch.setattr(pl, "decode_mix", lambda p, sr=16000: np.zeros(20 * sr, dtype=np.float32))
    monkeypatch.setattr(pl, "sherpa_available", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("model download failed")
    monkeypatch.setattr(pl, "diarize", boom)
    rec = Recorder(v1_chunks=[[0, 60, 1.0]])
    res, logs = run(dirs, monkeypatch, base_params(do_srt=True, snap_srt=False, diarize=True), rec,
                    transcribe=_transcribe_two_speakers)
    assert res.ok and res.srt_path.exists()
    assert "話者" not in res.srt_path.read_text(encoding="utf-8")
    assert any(m.startswith("log_speaker_fail") for m, _ in logs)


def test_diarize_skipped_when_sherpa_missing(dirs, monkeypatch):
    monkeypatch.setattr(pl, "sherpa_available", lambda: False)
    rec = Recorder()
    res, logs = run(dirs, monkeypatch, base_params(do_srt=True, snap_srt=False, diarize=True), rec,
                    transcribe=_transcribe_two_speakers)
    assert res.ok and any(m == "log_diar_unavailable" for m, _ in logs)


def test_cut_point_markers_without_subtitles(dirs, monkeypatch):
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    rec = Recorder(v1_chunks=[[0, 30, 1.0], [30, 60, 99999.0], [60, 90, 1.0]], xml=True)
    res, _ = run(dirs, monkeypatch, base_params(markers=True), rec)
    assert res.ok and res.markers_added == 1                            # カット点は 3.0s だけ（6.0s は終端）
    xml = (dirs[1] / "input_snipsynced.xml").read_text(encoding="utf-8")
    assert xml.count("<marker>") == 1


def test_markers_are_not_added_for_media_export(dirs, monkeypatch):
    rec = Recorder()
    res, _ = run(dirs, monkeypatch, base_params(export_key="media", markers=True), rec)
    assert res.ok and res.markers_added == 0


def test_line_chars_wraps_subtitles_even_without_cut_alignment(dirs, monkeypatch):
    pytest.importorskip("budoux")
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    monkeypatch.setattr(pl, "decode_mix", lambda p, sr=16000: np.zeros(20 * sr, dtype=np.float32))
    text = "今日はスニプシンクの新機能について説明します"
    words = [DummyWord(i * 0.2, i * 0.2 + 0.15, c) for i, c in enumerate(text)]

    def transcribe(wav, model):
        return iter([DummySegment(0.0, 5.0, text, words)]), type("I", (), {"language": "ja", "language_probability": 1.0})()

    rec = Recorder(v1_chunks=[[0, 60, 1.0]])
    res, _ = run(dirs, monkeypatch, base_params(do_srt=True, snap_srt=False, line_chars=10), rec,
                 transcribe=transcribe)
    body = res.srt_path.read_text(encoding="utf-8")
    assert "\n" in body.split("-->")[1].strip().split("\n", 1)[1].strip()   # 本文が複数行に整形される
    assert "".join(body.split("\n")[2:3]) != text


# ── 字幕を保存前に確認する（hold_subtitles） ──────────────────────────────────────

def test_hold_subtitles_writes_no_subtitle_files_and_returns_destinations(dirs, monkeypatch):
    inp, out = dirs
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    rec = Recorder(v1_chunks=[[0, 60, 1.0]])
    params = base_params(do_srt=True, snap_srt=False, txt=True, md=True, hold_subtitles=True)
    res, logs = run(dirs, monkeypatch, params, rec, transcribe=_transcribe_two_speakers)
    assert res.ok and res.cues
    assert not list(out.glob("*.srt")) and not list(out.glob("*.txt")) and not list(out.glob("*.md"))
    assert list(out.glob("input_snipsynced.*"))                       # カット結果のタイムラインは書く
    assert res.pending_paths == {"srt": out / "input.srt", "txt": out / "input.txt", "md": out / "input.md"}
    assert any(m == "log_srt_held" for m, _ in logs) and not any(m.startswith("log_srt_done") for m, _ in logs)
    assert res.extra_paths == []


def test_without_hold_subtitles_files_are_written_as_before(dirs, monkeypatch):
    inp, out = dirs
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    rec = Recorder(v1_chunks=[[0, 60, 1.0]])
    res, _ = run(dirs, monkeypatch, base_params(do_srt=True, snap_srt=False, txt=True), rec,
                 transcribe=_transcribe_two_speakers)
    assert (out / "input.srt").exists() and (out / "input.txt").exists()
    assert res.pending_paths == {}


# ── 文字起こしの途中停止と進捗 ──────────────────────────────────────────────────

def _lazy_transcribe(counter, n=50):
    def gen():
        for i in range(n):
            counter["pulled"] = i + 1
            yield DummySegment(i * 1.0, i * 1.0 + 0.9, f"文{i}")
    return lambda wav, size: (gen(), type("I", (), {"language": "ja", "language_probability": 1.0, "duration": float(n)})())


def test_stop_during_transcription_is_honored_per_segment_and_leaves_no_partial_srt(dirs, monkeypatch):
    inp, out = dirs
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    counter = {"pulled": 0}
    stop = {"now": False}

    def should_stop():
        stop["now"] = stop["now"] or counter["pulled"] >= 3          # 3 つ目を受け取ったら「停止」が押された
        return stop["now"]

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(stdout_lines=["x"], write_output=Recorder(v1_chunks=[[0, 60, 1.0]])))
    logs = []
    res = pl.run_pipeline("ae", inp, out, base_params(do_srt=True, snap_srt=False),
                          on_log=lambda m, lvl="": logs.append((m, lvl)), should_stop=should_stop, tr=stub_tr,
                          transcribe=_lazy_transcribe(counter))
    assert res.stopped and res.srt_path is None
    assert counter["pulled"] == 3                                     # 残りの 47 件を待たずに止まる
    assert not list(out.glob("*.srt"))
    assert any(m == "log_stopped" for m, _ in logs) and not any("log_unexpected" in m for m, _ in logs)


def test_transcription_progress_is_reported_in_seconds_and_closed(dirs, monkeypatch):
    inp, out = dirs
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    seen = []
    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(stdout_lines=["x"], write_output=Recorder(v1_chunks=[[0, 60, 1.0]])))
    res = pl.run_pipeline("ae", inp, out, base_params(do_srt=True, snap_srt=False),
                          on_log=lambda m, lvl="": None, should_stop=lambda: False, tr=stub_tr,
                          transcribe=_lazy_transcribe({"pulled": 0}, n=5),
                          on_progress=lambda kind, d, t: seen.append((kind, d, t)))
    assert res.ok and res.srt_path
    assert seen[0] == ("transcribe", 0.9, 5.0) and ("transcribe", 4.9, 5.0) in seen
    assert seen[-1] == ("transcribe", None, None)


def test_gpu_failure_falls_back_to_cpu_and_the_log_says_why(dirs, monkeypatch):
    inp, out = dirs
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    monkeypatch.setattr(pl, "resolve_device", lambda use_gpu: ("cuda", "int8_float16"))
    monkeypatch.setattr(pl, "add_cuda_dll_dirs", lambda: None)
    calls = []

    def transcribe(wav, size):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return iter([DummySegment(0, 1, "ok")]), type("I", (), {"language": "ja", "language_probability": 1.0, "duration": 1.0})()

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(stdout_lines=["x"], write_output=Recorder(v1_chunks=[[0, 60, 1.0]])))
    logs = []
    res = pl.run_pipeline("ae", inp, out, base_params(do_srt=True, snap_srt=False, use_gpu=True),
                          on_log=lambda m, lvl="": logs.append((m, lvl)), should_stop=lambda: False, tr=stub_tr,
                          transcribe=transcribe)
    assert res.ok and res.srt_path and len(calls) == 2
    assert any(m.startswith("log_gpu_fallback:") and "cublas64_12.dll" in m for m, _ in logs)


def test_failed_media_export_does_not_leave_a_half_written_file(dirs, monkeypatch):
    inp, out = dirs
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)

    def write_partial(cmd):
        Path(cmd[cmd.index("--output") + 1]).write_bytes(b"partial")

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(stdout_lines=["x"], returncode=1, write_output=write_partial))
    res, logs = run_pipeline_with(inp, out, base_params(export_key="media"))
    assert not res.ok and any(m.startswith("log_error") for m, _ in logs)
    assert not list(out.glob("*_snipsynced.*"))


def test_failed_timeline_export_is_left_for_the_user_to_inspect(dirs, monkeypatch):
    """タイムライン（小さな XML）の失敗は従来どおり。消すのは、再生できない書きかけのメディアだけ。"""
    inp, out = dirs
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)

    def write_partial(cmd):
        Path(cmd[cmd.index("--output") + 1]).write_bytes(b"partial")

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(stdout_lines=["x"], returncode=1, write_output=write_partial))
    res, _ = run_pipeline_with(inp, out, base_params(export_key="premiere"))
    assert not res.ok and list(out.glob("*_snipsynced.*"))


# ── 話者交代のマーカーは、保存前の確認があるときは、編集後の字幕から入れる ─────────────────

def test_speaker_markers_are_deferred_to_after_the_review_when_subtitles_are_held(dirs, monkeypatch):
    inp, out = dirs
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    monkeypatch.setattr(pl, "decode_mix", lambda p, sr=16000: np.zeros(20 * sr, dtype=np.float32))
    monkeypatch.setattr(pl, "sherpa_available", lambda: True)
    monkeypatch.setattr(pl, "diarize", lambda samples, **k: [(0.0, 2.5, 5), (2.5, 6.0, 9)])
    rec = Recorder(v1_chunks=[[0, 30, 1.0], [30, 40, 99999.0], [40, 90, 1.0]], xml=True)
    params = base_params(do_srt=True, snap_srt=False, diarize=True, markers=True, hold_subtitles=True)
    res, _ = run(dirs, monkeypatch, params, rec, transcribe=_transcribe_two_speakers)
    assert res.ok and res.speaker_markers_pending and res.pending_paths
    xml = (out / "input_snipsynced.xml").read_text(encoding="utf-8")
    assert xml.count("<marker>") == res.markers_added == 1             # カット点だけ。話者交代は、まだ入れない
    assert "話者" not in xml


def test_speaker_markers_are_still_added_at_once_without_a_review(dirs, monkeypatch):
    """確認を使わない（従来どおり）なら、処理の中で入れる。"""
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    monkeypatch.setattr(pl, "decode_mix", lambda p, sr=16000: np.zeros(20 * sr, dtype=np.float32))
    monkeypatch.setattr(pl, "sherpa_available", lambda: True)
    monkeypatch.setattr(pl, "diarize", lambda samples, **k: [(0.0, 2.5, 5), (2.5, 6.0, 9)])
    rec = Recorder(v1_chunks=[[0, 60, 1.0]], xml=True)
    res, _ = run(dirs, monkeypatch, base_params(do_srt=True, snap_srt=False, diarize=True, markers=True), rec,
                 transcribe=_transcribe_two_speakers)
    assert not res.speaker_markers_pending and res.markers_added == 2


def test_no_deferred_markers_when_the_option_is_off(dirs, monkeypatch):
    monkeypatch.setattr(pl, "probe_fps", lambda p: 10.0)
    rec = Recorder(v1_chunks=[[0, 60, 1.0]], xml=True)
    res, _ = run(dirs, monkeypatch, base_params(do_srt=True, snap_srt=False, hold_subtitles=True), rec,
                 transcribe=_transcribe_two_speakers)
    assert not res.speaker_markers_pending
