import subprocess
import sys
from pathlib import Path

import pytest

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline import PipelineParams, _kill_tree, run_pipeline
from subtitles import cuda_available, resolve_device


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


class MockPopen:
    def __init__(self, cmd, returncode=0, stdout_lines=None, write_output=None):
        self.cmd = cmd
        self.args = cmd
        self.returncode = returncode
        self.stdout_lines = stdout_lines or []
        self.write_output = write_output
        self.pid = 9999
        self.terminated = False
        self.killed = False
        self.wait_called = False
        self.poll_count = 0

        if self.write_output:
            self.write_output(cmd)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def poll(self):
        self.poll_count += 1
        if self.terminated or self.killed:
            return -1
        return None  # running

    def wait(self, timeout=None):
        self.wait_called = True
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def communicate(self, input=None, timeout=None):
        return "", ""

    @property
    def stdout(self):
        for line in self.stdout_lines:
            if self.terminated or self.killed:
                break
            yield line


def make_mock_popen(stdout_lines=None, returncode=0, write_output=None):
    def mock_popen(cmd, **kwargs):
        if cmd and cmd[0] == "taskkill":
            return MockPopen(cmd, returncode=0)
        return MockPopen(cmd, returncode=returncode, stdout_lines=stdout_lines, write_output=write_output)
    return mock_popen


@pytest.fixture
def temp_dirs(tmp_path):
    inp = tmp_path / "input.mp4"
    inp.write_bytes(b"dummy_video_data")
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    return inp, out_dir


def test_pipeline_no_srt(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs

    def mock_write(cmd):
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["line1", "line2"], write_output=mock_write
    ))

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
    assert ("line1", "") in logs
    assert ("line2", "") in logs
    assert not (out_dir / "input_temp_audio.wav").exists()


def test_pipeline_with_srt_success(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs

    def mock_write(cmd):
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["progress line"], write_output=mock_write
    ))

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

    assert res.srt_path.exists()
    content = res.srt_path.read_text(encoding="utf-8")
    expected = (
        "1\n00:00:00,500 --> 00:00:02,300\nHello world\n\n"
        "2\n00:00:03,100 --> 00:00:05,000\nThis is SnipSync\n\n"
    )
    assert content == expected
    assert not (out_dir / "input_temp_audio.wav").exists()


def test_pipeline_should_stop(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs

    def mock_write(cmd):
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["progress"], write_output=mock_write
    ))

    # 3a. Stopped at the very beginning
    params = PipelineParams(
        margin=0.2, threshold=4.0, export_key="resolve", do_srt=True, model_size="small"
    )

    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=lambda m, lvl="": None,
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

    def mock_write_conditional(cmd):
        nonlocal stop_flag
        stop_flag = True
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["progress"], write_output=mock_write_conditional
    ))

    logs_cond = []
    def on_log_cond(msg, level=""):
        logs_cond.append((msg, level))
        print(f"LOG: {msg} ({level})")

    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=on_log_cond,
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
        return call_count >= 8

    segments = [
        DummySegment(0.5, 2.3, "Hello world"),
        DummySegment(3.1, 5.0, "This is SnipSync"),
    ]

    class DummyInfo:
        language = "en"
        language_probability = 0.99

    def mock_transcribe_stop(wav_path, model_size):
        return segments, DummyInfo()

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["progress"], write_output=mock_write
    ))

    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=lambda m, lvl="": None,
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


def test_pipeline_should_stop_mid_stream(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs

    stop_requested = False

    def conditional_should_stop():
        return stop_requested

    kill_called = False
    def mock_kill_tree(proc):
        nonlocal kill_called
        kill_called = True
        proc.terminate()

    monkeypatch.setattr("pipeline._kill_tree", mock_kill_tree)

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["line1", "line2", "line3"]
    ))

    params = PipelineParams(
        margin=0.2, threshold=4.0, export_key="resolve", do_srt=False, model_size="small"
    )

    logs = []
    def on_log(msg, level=""):
        nonlocal stop_requested
        logs.append((msg, level))
        if msg == "line2":
            stop_requested = True

    res = run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=on_log,
        should_stop=conditional_should_stop,
        tr=stub_tr
    )

    assert res.ok is False
    assert res.stopped is True
    assert kill_called is True
    assert ("line1", "") in logs
    assert ("line2", "") in logs
    assert ("line3", "") not in logs


def test_pipeline_ae_failed(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["auto-editor failed with error log"], returncode=127
    ))

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

    assert any("log_error:127" in log[0] for log in logs)
    assert not (out_dir / "input_temp_audio.wav").exists()


def test_pipeline_temp_wav_missing(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs

    run_count = 0
    def mock_write(cmd):
        nonlocal run_count
        run_count += 1
        if run_count == 1:
            output_path = None
            if "--output" in cmd:
                idx = cmd.index("--output")
                output_path = Path(cmd[idx + 1])
            if output_path:
                output_path.write_bytes(b"dummy")

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["progress"], write_output=mock_write
    ))

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
    def mock_write(cmd):
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["progress"], write_output=mock_write
    ))

    def mock_transcribe_error(wav_path, model_size):
        assert temp_wav_path.exists()
        raise RuntimeError("Transcription crash simulation")

    params = PipelineParams(
        margin=0.2, threshold=4.0, export_key="resolve", do_srt=True, model_size="small"
    )

    run_pipeline(
        ae_path="dummy-ae",
        inp=inp,
        out_dir=out_dir,
        params=params,
        on_log=lambda m, lvl="": None,
        should_stop=lambda: False,
        tr=stub_tr,
        transcribe=mock_transcribe_error
    )

    assert not temp_wav_path.exists()


def test_pipeline_ae_not_found(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs

    def mock_popen_fnf(cmd, **kwargs):
        if cmd and cmd[0] == "taskkill":
            return MockPopen(cmd, returncode=0)
        raise FileNotFoundError("[WinError 2] The system cannot find the file specified")

    monkeypatch.setattr(subprocess, "Popen", mock_popen_fnf)

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


def test_kill_tree_windows(monkeypatch):
    proc = MockPopen(["cmd"])

    taskkill_called = []
    def mock_run(cmd, **kwargs):
        taskkill_called.append(cmd)
        class MockCompletedProcess:
            returncode = 0
        return MockCompletedProcess()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(sys, "platform", "win32")

    _kill_tree(proc)

    assert len(taskkill_called) == 1
    assert taskkill_called[0] == ["taskkill", "/F", "/T", "/PID", str(proc.pid)]
    assert proc.wait_called is True


def test_kill_tree_non_windows(monkeypatch):
    proc = MockPopen(["cmd"])

    monkeypatch.setattr(sys, "platform", "darwin")

    _kill_tree(proc)

    assert proc.terminated is True
    assert proc.wait_called is True


def test_kill_tree_already_finished():
    proc = MockPopen(["cmd"])

    def mock_poll():
        return 0
    proc.poll = mock_poll

    _kill_tree(proc)
    assert proc.terminated is False
    assert proc.killed is False
    assert proc.wait_called is False


def test_kill_tree_timeout(monkeypatch):
    proc = MockPopen(["cmd"])

    def mock_wait(timeout=None):
        proc.wait_called = True
        raise subprocess.TimeoutExpired(proc.cmd, timeout)

    proc.wait = mock_wait
    monkeypatch.setattr(sys, "platform", "darwin")

    _kill_tree(proc)

    assert proc.terminated is True
    assert proc.killed is True
    assert proc.wait_called is True


def test_cuda_available(monkeypatch):
    import sys

    # 1. Success case
    class MockCtranslate2:
        @staticmethod
        def get_cuda_device_count():
            return 1

    monkeypatch.setitem(sys.modules, "ctranslate2", MockCtranslate2)
    assert cuda_available() is True

    # 2. No device case
    class MockCtranslate2Zero:
        @staticmethod
        def get_cuda_device_count():
            return 0

    monkeypatch.setitem(sys.modules, "ctranslate2", MockCtranslate2Zero)
    assert cuda_available() is False

    # 3. ImportError case
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
    assert cuda_available() is False

    # 4. Exception case
    class MockCtranslate2Exception:
        @staticmethod
        def get_cuda_device_count():
            raise RuntimeError("CUDA driver error")

    monkeypatch.setitem(sys.modules, "ctranslate2", MockCtranslate2Exception)
    assert cuda_available() is False


def test_resolve_device(monkeypatch):
    # Mock cuda_available to return True
    monkeypatch.setattr("subtitles.cuda_available", lambda: True)
    assert resolve_device(use_gpu=True) == ("cuda", "int8_float16")
    assert resolve_device(use_gpu=False) == ("cpu", "int8")

    # Mock cuda_available to return False
    monkeypatch.setattr("subtitles.cuda_available", lambda: False)
    assert resolve_device(use_gpu=True) == ("cpu", "int8")
    assert resolve_device(use_gpu=False) == ("cpu", "int8")


def test_pipeline_gpu_fallback(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs

    def mock_write(cmd):
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["progress line"], write_output=mock_write
    ))

    # Mock cuda_available to return True
    monkeypatch.setattr("subtitles.cuda_available", lambda: True)

    segments = [
        DummySegment(0.5, 2.3, "Fallback transcription test"),
    ]

    class DummyInfo:
        language = "en"
        language_probability = 0.99

    call_history = []

    def mock_transcribe_with_fallback(wav_path, model_size):
        # We simulate a fallback scenario: the first call (GPU) fails, the second (CPU retry) succeeds.
        call_history.append("called")
        if len(call_history) == 1:
            raise RuntimeError("GPU Out of Memory or CUDA driver error")
        return segments, DummyInfo()

    params = PipelineParams(
        margin=0.2,
        threshold=4.0,
        export_key="premiere",
        do_srt=True,
        model_size="small",
        use_gpu=True  # Opt-in GPU
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
        transcribe=mock_transcribe_with_fallback
    )

    assert res.ok is True
    assert res.stopped is False
    assert res.srt_path == out_dir / "input.srt"
    assert len(call_history) == 2  # First call on GPU failed, second call on CPU succeeded

    # Verify warning and device logging
    assert ("log_gpu_fallback", "warn") in logs
    assert ("log_device:cpu", "muted") in logs


def test_pipeline_gpu_fallback_lazy_generator(temp_dirs, monkeypatch):
    inp, out_dir = temp_dirs

    def mock_write(cmd):
        output_path = None
        if "--output" in cmd:
            idx = cmd.index("--output")
            output_path = Path(cmd[idx + 1])
        if output_path:
            output_path.write_bytes(b"dummy")

    monkeypatch.setattr(subprocess, "Popen", make_mock_popen(
        stdout_lines=["progress line"], write_output=mock_write
    ))

    monkeypatch.setattr("subtitles.cuda_available", lambda: True)

    segments = [
        DummySegment(0.5, 2.3, "Fallback lazy generator test"),
    ]

    class DummyInfo:
        language = "en"
        language_probability = 0.99

    call_history = []

    def mock_transcribe_lazy(wav_path, model_size):
        call_history.append("called")
        if len(call_history) == 1:
            def failing_gen():
                raise RuntimeError("CUDA execution failed during iteration")
                yield # makes it a generator
            return failing_gen(), DummyInfo()

        def success_gen():
            yield from segments
        return success_gen(), DummyInfo()

    params = PipelineParams(
        margin=0.2,
        threshold=4.0,
        export_key="premiere",
        do_srt=True,
        model_size="small",
        use_gpu=True
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
        transcribe=mock_transcribe_lazy
    )

    assert res.ok is True
    assert res.stopped is False
    assert res.srt_path == out_dir / "input.srt"
    assert len(call_history) == 2

    assert ("log_gpu_fallback", "warn") in logs
    assert ("log_device:cpu", "muted") in logs

    assert res.srt_path.exists()
    content = res.srt_path.read_text(encoding="utf-8")
    assert "Fallback lazy generator test" in content


