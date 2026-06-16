import traceback
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

from autoeditor import build_cut_cmd, build_extract_wav_cmd
from subtitles import format_timestamp, resolve_device


CREATE_NEW_PROCESS_GROUP = 0x00000200 if sys.platform == "win32" else 0

def _kill_tree(proc):
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

def _run_streaming(cmd, *, on_log, should_stop) -> tuple[int, bool]:
    """auto-editor を Popen で起動し stdout を1行ずつ on_log。
    should_stop() が真になったらプロセスツリーを kill して打ち切る。
    戻り値: (returncode, stopped)。stopped=True のとき returncode は不定(kill)。
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NEW_PROCESS_GROUP
    )
    
    stopped = False
    
    try:
        for line in proc.stdout:
            if should_stop():
                _kill_tree(proc)
                stopped = True
                break
            
            line = line.rstrip()
            if not line:
                continue
                
            # Log classification
            if any(k in line.lower() for k in ("error", "failed", "exception")):
                on_log(line, "error")
            elif any(k in line.lower() for k in ("warning", "warn")):
                on_log(line, "warn")
            else:
                on_log(line)
    except Exception as e:
        _kill_tree(proc)
        raise e
        
    if stopped:
        return -1, True
        
    rc = proc.wait()
    
    if should_stop():
        _kill_tree(proc)
        return -1, True
        
    return rc, False


@dataclass
class PipelineParams:
    margin: float
    threshold: float
    export_key: str          # "resolve" | "premiere" | "final-cut-pro"
    do_srt: bool
    model_size: str          # "tiny" | "base" | "small" | "medium"
    use_gpu: bool = False


@dataclass
class PipelineResult:
    ok: bool                 # メインカット成功（完了ダイアログ可否の判定に使用）
    stopped: bool            # 停止要求で中断したか
    timeline_path: Path | None
    srt_path: Path | None


def run_pipeline(
    ae_path,                 # auto-editor 実行パス
    inp: Path,               # 入力動画（解決済み絶対パス）
    out_dir: Path,           # 出力先（解決済み絶対パス）
    params: PipelineParams,
    *,
    on_log,                  # (msg: str, level: str="") -> None
    should_stop,             # () -> bool
    tr,                      # (key: str, *args) -> str
    transcribe=None,         # DI用フック（既定 None→内部で faster_whisper を使用）
) -> PipelineResult:
    result = PipelineResult(ok=False, stopped=False, timeline_path=None, srt_path=None)
    
    # Resolve output paths based on export_key
    ext = {
        "resolve": ".fcpxml",
        "premiere": ".xml",
        "final-cut-pro": ".fcpxml",
    }.get(params.export_key, ".xml")
    
    output_ae = out_dir / f"{inp.stem}_snipsynced{ext}"
    output_srt = out_dir / f"{inp.stem}.srt"
    
    try:
        # 1. Auto-Editor Processing
        if should_stop():
            result.stopped = True
            on_log(tr("log_stopped"), "warn")
            return result

        cmd = build_cut_cmd(ae_path, inp, params.margin, params.threshold, params.export_key, output_ae)
        
        try:
            rc, stopped = _run_streaming(cmd, on_log=on_log, should_stop=should_stop)
            if stopped:
                result.stopped = True
                on_log(tr("log_stopped"), "warn")
            elif rc == 0:
                on_log(tr("log_done_ae"), "success")
                on_log(f"   {output_ae.name}", "success")
                result.ok = True
                result.timeline_path = output_ae
            else:
                on_log(tr("log_error", rc), "error")
        except FileNotFoundError as e:
            on_log(tr("log_ae_missing", e), "error")
        except Exception as e:
            on_log(tr("log_unexpected", traceback.format_exc()), "error")

        # 2. Faster-Whisper Processing via Temp WAV
        if result.ok and params.do_srt and not result.stopped:
            temp_wav = output_ae.parent / f"{inp.stem}_temp_audio.wav"
            temp_success = False
            
            # 2a. Generate Temp WAV
            on_log(tr("log_srt_temp_start"), "info")
            temp_cmd = build_extract_wav_cmd(ae_path, inp, params.margin, params.threshold, temp_wav)
            try:
                rc_temp, stopped_temp = _run_streaming(temp_cmd, on_log=on_log, should_stop=should_stop)
                
                if stopped_temp:
                    result.stopped = True
                    on_log(tr("log_stopped"), "warn")
                elif rc_temp == 0:
                    if temp_wav.exists():
                        temp_success = True
                    else:
                        on_log(tr("log_wav_missing"), "error")
                else:
                    on_log(tr("log_error", rc_temp), "error")
            except Exception as e:
                on_log(tr("log_unexpected", traceback.format_exc()), "error")
                
            if should_stop() and not result.stopped:
                result.stopped = True
                on_log(tr("log_stopped"), "warn")

            # 2b. Transcribe Temp WAV
            if temp_success and not result.stopped:
                on_log(tr("log_srt_analyze", params.model_size), "info")
                try:
                    device, compute_type = resolve_device(params.use_gpu)

                    def _decode(dev, ctype):
                        # transcribe を呼び、ジェネレータをリスト化して“この場で”デコードを完走させる。
                        # → CUDA 実行時エラーをこの try 内で確実に捕捉できる。
                        if transcribe is not None:
                            seg_iter, inf = transcribe(temp_wav, params.model_size)
                        else:
                            from faster_whisper import WhisperModel
                            model = WhisperModel(params.model_size, device=dev, compute_type=ctype)
                            seg_iter, inf = model.transcribe(str(temp_wav), beam_size=5, language=None)
                        return list(seg_iter), inf   # ← list() でデコード完走（例外はここで出る）

                    try:
                        if device == "cuda":
                            segments, info = _decode("cuda", compute_type)
                            on_log(tr("log_device", "cuda"), "muted")
                        else:
                            segments, info = _decode("cpu", compute_type)
                            on_log(tr("log_device", "cpu"), "muted")
                    except Exception:
                        if device == "cuda":
                            on_log(tr("log_gpu_fallback"), "warn")
                            device, compute_type = "cpu", "int8"   # ← device/compute_type を同時に CPU へ
                            segments, info = _decode("cpu", compute_type)
                            on_log(tr("log_device", "cpu"), "muted")
                        else:
                            raise   # CPU でも失敗なら外側 except へ（log_unexpected）

                    on_log(tr("log_lang_detected", info.language, info.language_probability), "muted")

                    # SRT 書き込み（segments は確定済みリスト）
                    with open(output_srt, "w", encoding="utf-8") as srt_file:
                        for i, segment in enumerate(segments, start=1):
                            if should_stop():
                                result.stopped = True
                                break
                            start = format_timestamp(segment.start)
                            end = format_timestamp(segment.end)
                            text = segment.text.strip()
                            srt_file.write(f"{i}\n{start} --> {end}\n{text}\n\n")
                            on_log(f"  [{start} -> {end}] {text}", "muted")

                    if should_stop() or result.stopped:
                        result.stopped = True
                        on_log(tr("log_stopped"), "warn")
                    else:
                        on_log(tr("log_srt_done"), "success")
                        on_log(f"   {output_srt.name}", "success")
                        result.srt_path = output_srt
                except Exception:
                    on_log(tr("log_unexpected", traceback.format_exc()), "error")
            
            # 2c. Cleanup Temp WAV
            try:
                if temp_wav.exists():
                    temp_wav.unlink()
            except Exception as e:
                on_log(tr("log_cleanup_failed", str(e)), "warn")
                
    except Exception as e:
        # Catch any unexpected top-level worker thread crashes
        on_log(tr("log_unexpected", traceback.format_exc()), "error")
        
    return result
