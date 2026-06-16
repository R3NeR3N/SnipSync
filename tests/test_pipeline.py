import sys
import subprocess
from pathlib import Path
import pytest

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline import run_pipeline, PipelineParams, PipelineResult


class DummySegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


# Helper/stub callbacks
def stub_tr(key, *args):
    if args:
        return f"{key}:{','.join(str(a) for a in args)}"
    return key


@pytest.fixture
def temp_dirs(tmp_path):
    # Setup temporary directory and dummy files
    inp = tmp_path / "input.mp4"
    inp.write_bytes(b"dummy_video_data")
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    return inp, out_dir


def test_pipeline_no_srt(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs
    
    # Mock subprocess.run to succeed
    def mock_run(cmd, **kwargs):
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")
            
        class MockCompletedProcess:
            returncode = 0
            stdout = "auto-editor successful run stdout"
            stderr = ""
        return MockCompletedProcess()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    params = PipelineParams(
        margin=0.2,
        threshold=4.0,
        export_key="resolve",
        do_srt=False,
        model_size="small"
    )
    
    logs = []
    def on_log(msg, level=""):
        logs.append((msg, level))
        
    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=on_log,
        should_stop=lambda: False,
        tr=stub_tr
    )
    
    assert res.ok is True
    assert res.stopped is False
    assert res.timeline_path == out_dir / "input_snipsynced.fcpxml"
    assert res.srt_path is None
    assert not (out_dir / "input_temp_audio.wav").exists()


def test_pipeline_with_srt_success(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs
    
    # Mock subprocess.run to simulate successful cut and WAV extraction
    def mock_run(cmd, **kwargs):
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")
            
        class MockCompletedProcess:
            returncode = 0
            stdout = ""
            stderr = ""
        return MockCompletedProcess()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    # Inject dummy transcribe
    segments = [
        DummySegment(0.5, 2.3, "Hello world"),
        DummySegment(3.1, 5.0, "This is SnipSync"),
    ]
    
    class DummyInfo:
        language = "en"
        language_probability = 0.99
        
    def mock_transcribe(wav_path, model_size):
        assert wav_path.exists()
        return segments, DummyInfo()
        
    params = PipelineParams(
        margin=0.2,
        threshold=4.0,
        export_key="premiere",
        do_srt=True,
        model_size="small"
    )
    
    logs = []
    def on_log(msg, level=""):
        logs.append((msg, level))
        
    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=on_log,
        should_stop=lambda: False,
        tr=stub_tr,
        transcribe=mock_transcribe
    )
    
    assert res.ok is True
    assert res.stopped is False
    assert res.timeline_path == out_dir / "input_snipsynced.xml"
    assert res.srt_path == out_dir / "input.srt"
    
    # Check SRT content
    assert res.srt_path.exists()
    content = res.srt_path.read_text(encoding="utf-8")
    expected = (
        "1\n00:00:00,500 --> 00:00:02,300\nHello world\n\n"
        "2\n00:00:03,100 --> 00:00:05,000\nThis is SnipSync\n\n"
    )
    assert content == expected
    
    # Ensure temp WAV is deleted
    assert not (out_dir / "input_temp_audio.wav").exists()


def test_pipeline_should_stop(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs
    
    # Mock subprocess.run
    def mock_run(cmd, **kwargs):
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")
        class MockCompletedProcess:
            returncode = 0
            stdout = ""
            stderr = ""
        return MockCompletedProcess()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    # 3a. Stopped at the very beginning
    params = PipelineParams(
        margin=0.2, threshold=4.0, export_key="resolve", do_srt=True, model_size="small"
    )
    
    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=lambda m, l="": None,
        should_stop=lambda: True,
        tr=stub_tr
    )
    
    assert res.ok is False
    assert res.stopped is True
    assert res.timeline_path is None
    assert res.srt_path is None

    # 3b. Stopped right after auto-editor success (conditional stop)
    stop_flag = False
    
    def conditional_stop():
        return stop_flag

    def mock_run_conditional(cmd, **kwargs):
        nonlocal stop_flag
        stop_flag = True
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")
        class MockCompletedProcess:
            returncode = 0
            stdout = ""
            stderr = ""
        return MockCompletedProcess()

    monkeypatch.setattr(subprocess, "run", mock_run_conditional)

    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=lambda m, l="": None,
        should_stop=conditional_stop,
        tr=stub_tr
    )
    
    assert res.ok is False
    assert res.stopped is True
    assert res.timeline_path is None
    assert res.srt_path is None
    assert not (out_dir / "input_temp_audio.wav").exists()

    # 3c. Stopped during transcription loop
    call_count = 0
    def stateful_should_stop():
        nonlocal call_count
        call_count += 1
        return call_count >= 7
        
    segments = [
        DummySegment(0.5, 2.3, "Hello world"),
        DummySegment(3.1, 5.0, "This is SnipSync"),
    ]
    
    class DummyInfo:
        language = "en"
        language_probability = 0.99
        
    def mock_transcribe_stop(wav_path, model_size):
        return segments, DummyInfo()

    monkeypatch.setattr(subprocess, "run", mock_run)

    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=lambda m, l="": None,
        should_stop=stateful_should_stop,
        tr=stub_tr,
        transcribe=mock_transcribe_stop
    )
    
    assert res.ok is True
    assert res.stopped is True
    assert res.srt_path is None
    assert (out_dir / "input.srt").exists()
    srt_content = (out_dir / "input.srt").read_text(encoding="utf-8")
    assert "Hello world" in srt_content
    assert "This is SnipSync" not in srt_content


def test_pipeline_ae_failed(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs
    
    def mock_run(cmd, **kwargs):
        class MockCompletedProcess:
            returncode = 127
            stdout = ""
            stderr = "Auto-editor error message"
        return MockCompletedProcess()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    params = PipelineParams(
        margin=0.2, threshold=4.0, export_key="resolve", do_srt=True, model_size="small"
    )
    
    logs = []
    def on_log(msg, level=""):
        logs.append((msg, level))
        
    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=on_log,
        should_stop=lambda: False,
        tr=stub_tr
    )
    
    assert res.ok is False
    assert res.stopped is False
    assert res.timeline_path is None
    assert res.srt_path is None
    
    assert any("log_error:127,Auto-editor error message" in log[0] for log in logs)
    assert not (out_dir / "input_temp_audio.wav").exists()


def test_pipeline_temp_wav_missing(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs
    
    run_count = 0
    def mock_run(cmd, **kwargs):
        nonlocal run_count
        run_count += 1
        if run_count == 1:
            output_path = None
            if "--output" in cmd:
                idx = cmd.index("--output")
                output_path = Path(cmd[idx + 1])
            if output_path:
                output_path.write_bytes(b"dummy")
        class MockCompletedProcess:
            returncode = 0
            stdout = ""
            stderr = ""
        return MockCompletedProcess()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    params = PipelineParams(
        margin=0.2, threshold=4.0, export_key="resolve", do_srt=True, model_size="small"
    )
    
    logs = []
    def on_log(msg, level=""):
        logs.append((msg, level))
        
    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=on_log,
        should_stop=lambda: False,
        tr=stub_tr
    )
    
    assert res.ok is True
    assert res.stopped is False
    assert res.srt_path is None
    assert any("log_wav_missing" in log[0] for log in logs)


def test_pipeline_temp_wav_cleanup(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs
    
    temp_wav_path = out_dir / "input_temp_audio.wav"
    def mock_run(cmd, **kwargs):
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")
        class MockCompletedProcess:
            returncode = 0
            stdout = ""
            stderr = ""
        return MockCompletedProcess()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    def mock_transcribe_error(wav_path, model_size):
        assert temp_wav_path.exists()
        raise RuntimeError("Transcription crash simulation")
        
    params = PipelineParams(
        margin=0.2, threshold=4.0, export_key="resolve", do_srt=True, model_size="small"
    )
    
    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=lambda m, l="": None,
        should_stop=lambda: False,
        tr=stub_tr,
        transcribe=mock_transcribe_error
    )
    
    assert not temp_wav_path.exists()


def test_pipeline_ae_not_found(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs
    
    def mock_run_fnf(*args, **kwargs):
        raise FileNotFoundError("[WinError 2] The system cannot find the file specified")
        
    monkeypatch.setattr(subprocess, "run", mock_run_fnf)
    
    params = PipelineParams(
        margin=0.2, threshold=4.0, export_key="resolve", do_srt=False, model_size="small"
    )
    
    logs = []
    def on_log(msg, level=""):
        logs.append((msg, level))
        
    res = run_pipeline(
        ae_path="non-existent-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=on_log,
        should_stop=lambda: False,
        tr=stub_tr
    )
    
    assert res.ok is False
    assert res.stopped is False
    assert any("log_ae_missing:[WinError 2]" in log[0] for log in logs)
