"""VAD のカット区間生成・カット後音声の組み立て・波形統計・話者分離の周辺処理。"""
import hashlib
import json
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

np = pytest.importorskip("numpy")

from snipsync.core import diarize  # noqa: E402
from snipsync.core.audiocut import render_cut_audio, write_wav  # noqa: E402
from snipsync.core.autoeditor import CUT_SPEED  # noqa: E402
from snipsync.core.vad import read_v1_chunks, speech_to_chunks, write_v1  # noqa: E402
from snipsync.core.waveform import chunk_regions, compute_peaks, preview_stats  # noqa: E402

# ── speech_to_chunks ───────────────────────────────────────────────────────────


def test_chunks_cover_whole_timeline_without_gaps_and_alternate_keep_cut():
    chunks = speech_to_chunks([(1.0, 2.0), (5.0, 6.0)], total_sec=10.0, fps=30, margin=0.2)
    assert chunks[0][0] == 0 and chunks[-1][1] == 300
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert a[1] == b[0]                      # 隙間なし
    kinds = [c[2] for c in chunks]
    assert kinds == [CUT_SPEED, 1.0, CUT_SPEED, 1.0, CUT_SPEED]
    assert chunks[1][:2] == [24, 66]             # 1.0-0.2=0.8s -> 24f, 2.0+0.2=2.2s -> 66f


def test_chunks_merge_gaps_shorter_than_min_cut():
    chunks = speech_to_chunks([(1.0, 2.0), (2.3, 3.0)], 10.0, 30, margin=0.0, min_cut=0.5)
    assert [c[2] for c in chunks] == [CUT_SPEED, 1.0, CUT_SPEED]   # 0.3s の隙間は切らず1つに結合


def test_chunks_silent_speed_replaces_cut():
    chunks = speech_to_chunks([(2.0, 3.0)], 6.0, 30, margin=0.0, silent_speed=8)
    assert [c[2] for c in chunks] == [8.0, 1.0, 8.0]


def test_chunks_empty_when_no_speech_or_bad_args():
    assert speech_to_chunks([], 10.0, 30) == []
    assert speech_to_chunks([(1, 2)], 0, 30) == []
    assert speech_to_chunks([(1, 2)], 10.0, 0) == []


def test_chunks_clamp_margin_to_timeline_edges():
    chunks = speech_to_chunks([(0.05, 9.95)], 10.0, 30, margin=0.5)
    assert chunks == [[0, 300, 1.0]]


def test_write_and_read_v1_roundtrip(tmp_path):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    p = write_v1(tmp_path / "c.json", src, [[0, 30, 1.0], [30, 60, CUT_SPEED]])
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == "1" and Path(data["source"]).is_absolute()
    assert read_v1_chunks(p) == [(0, 30, 1.0), (30, 60, CUT_SPEED)]
    assert read_v1_chunks(tmp_path / "missing.json") == []


# ── render_cut_audio / write_wav ───────────────────────────────────────────────

def test_render_cut_audio_concatenates_kept_ranges():
    sr = 1000
    samples = np.arange(10 * sr, dtype=np.float32) / (10 * sr)       # 0..1 の傾き（位置が判別できる）
    out = render_cut_audio(samples, [(0, 10, 1.0), (10, 20, CUT_SPEED), (20, 30, 1.0)], tb=10, sr=sr)
    assert len(out) == 2 * sr                                         # 1s残す + 1s除去 + 1s残す
    assert out[0] == samples[0] and out[sr] == samples[2 * sr]        # 2つ目は元の2.0s位置


def test_render_cut_audio_speeds_up_silent_chunk_length():
    sr = 1000
    samples = np.zeros(10 * sr, dtype=np.float32)
    out = render_cut_audio(samples, [(0, 10, 1.0), (10, 90, 8.0)], tb=10, sr=sr)
    assert len(out) == sr + (8 * sr) // 8                             # 80f=8s を8倍速 -> 1s


def test_render_cut_audio_pads_with_silence_beyond_the_source_end_and_handles_all_cut():
    samples = np.ones(1000, dtype=np.float32)
    out = render_cut_audio(samples, [(0, 100, 1.0)], tb=10, sr=1000)
    # 元音声（1s）より長い区間（10s）: 引き伸ばさず無音で埋める（以降の字幕の時刻を保つ）
    assert len(out) == 10000 and out[:1000].min() == 1.0 and out[1000:].max() == 0.0
    assert len(render_cut_audio(samples, [(0, 10, CUT_SPEED)], tb=10, sr=1000)) == 0


def test_write_wav_is_16bit_mono_with_expected_length(tmp_path):
    p = write_wav(tmp_path / "a.wav", np.array([0.0, 0.5, -0.5, 2.0], dtype=np.float32), 16000)
    with wave.open(str(p)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 4)
        pcm = np.frombuffer(w.readframes(4), dtype=np.int16)
    assert pcm[3] == 32767                                             # クリップされる


# ── waveform ───────────────────────────────────────────────────────────────────

def test_compute_peaks_takes_max_abs_per_bin():
    samples = np.array([0.1, -0.9, 0.2, 0.3, -0.4, 0.5], dtype=np.float32)
    assert compute_peaks(samples, 3).tolist() == pytest.approx([0.9, 0.3, 0.5])
    assert len(compute_peaks(np.zeros(0, dtype=np.float32), 10)) == 0
    assert len(compute_peaks(samples, 100)) == 6                       # bins は標本数を超えない


def test_chunk_regions_and_stats():
    chunks = [(0, 30, 1.0), (30, 90, CUT_SPEED), (90, 330, 8.0), (330, 360, 1.0)]
    assert [r[2] for r in chunk_regions(chunks, 30)] == ["keep", "cut", "speed", "keep"]
    st = preview_stats(chunks, 30)
    assert st["original"] == pytest.approx(12.0)
    assert st["result"] == pytest.approx(1.0 + 1.0 + 1.0)              # 1s + 8s/8 + 1s
    assert st["cuts"] == 1 and st["saved_pct"] == pytest.approx(75.0)


# ── diarize（モデル無しで検証できる部分）────────────────────────────────────────

def test_diarize_pinned_hashes_are_sha256_hex():
    for h in (diarize.EMB_SHA256, diarize.SEG_SHA256):
        assert len(h) == 64 and int(h, 16) >= 0
    assert diarize.EMB_URL.startswith("https://github.com/k2-fsa/sherpa-onnx/releases/")
    assert diarize.SEG_MEMBER.endswith("model.onnx")


def test_models_ready_reflects_files(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert diarize.models_ready() is False
    d = diarize.diarization_dir()
    d.mkdir(parents=True)
    (d / diarize.SEG_FILE).write_bytes(b"x")
    (d / diarize.EMB_FILE).write_bytes(b"x")
    assert diarize.models_ready() is True


def test_ensure_models_downloads_and_verifies_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    emb_bytes = b"embedding-model"
    monkeypatch.setattr(diarize, "EMB_SHA256", hashlib.sha256(emb_bytes).hexdigest())
    seg_bytes = b"segmentation-model"
    monkeypatch.setattr(diarize, "SEG_SHA256", hashlib.sha256(seg_bytes).hexdigest())

    import io
    import tarfile

    def fake_download(url, dest):
        if url == diarize.EMB_URL:
            Path(dest).write_bytes(emb_bytes)
        else:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:bz2") as tf:
                info = tarfile.TarInfo(diarize.SEG_MEMBER)
                info.size = len(seg_bytes)
                tf.addfile(info, io.BytesIO(seg_bytes))
            Path(dest).write_bytes(buf.getvalue())

    monkeypatch.setattr(diarize, "_download", fake_download)
    seg, emb = diarize.ensure_models()
    assert seg.read_bytes() == seg_bytes and emb.read_bytes() == emb_bytes
    assert not (seg.parent / "segmentation.tar.bz2").exists()          # アーカイブは残さない


def test_ensure_models_rejects_tampered_download(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(diarize, "_download", lambda url, dest: Path(dest).write_bytes(b"tampered"))
    with pytest.raises(RuntimeError, match="ハッシュ"):
        diarize.ensure_models()
    assert not (diarize.diarization_dir() / diarize.EMB_FILE).exists()  # 不一致のファイルは消す


def test_render_cut_audio_places_sped_chunks_by_cumulative_frames():
    sr = 3000
    samples = np.zeros(10 * sr, dtype=np.float32)
    # 29f を 8倍速 = 3.625f、2f を 8倍速 = 0.25f、30f 等速: 合計 33.875f = 1.12917s
    out = render_cut_audio(samples, [(0, 29, 8.0), (29, 31, 8.0), (31, 61, 1.0)], tb=30, sr=sr)
    assert len(out) == round(33.875 / 30 * sr)
