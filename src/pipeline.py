import traceback
from dataclasses import dataclass
from pathlib import Path
import subprocess

from autoeditor import build_cut_cmd, build_extract_wav_cmd
from subtitles import format_timestamp


@dataclass
class PipelineParams:
    margin: float
    threshold: float
    export_key: str          # "resolve" | "premiere" | "final-cut-pro"
    do_srt: bool
    model_size: str          # "tiny" | "base" | "small" | "medium"


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
            res = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            
            # Log stdout
            if res.stdout:
                for line in res.stdout.splitlines():
                    line = line.rstrip()
                    if not line:
                        continue
                    if any(k in line.lower() for k in ("error", "failed", "exception")):
                        on_log(line, "error")
                    elif any(k in line.lower() for k in ("warning", "warn")):
                        on_log(line, "warn")
                    else:
                        on_log(line)
            
            rc = res.returncode
            if should_stop():
                result.stopped = True
                on_log(tr("log_stopped"), "warn")
            elif rc == 0:
                on_log(tr("log_done_ae"), "success")
                on_log(f"   {output_ae.name}", "success")
                result.ok = True
                result.timeline_path = output_ae
            else:
                on_log(tr("log_error", rc, res.stderr), "error")
        except FileNotFoundError as e:
            on_log(tr("log_ae_missing", e), "error")
        except Exception as e:
            on_log(tr("log_unexpected", traceback.format_exc()), "error")

        if should_stop() and not result.stopped:
            result.stopped = True
            on_log(tr("log_stopped"), "warn")

        # 2. Faster-Whisper Processing via Temp WAV
        if result.ok and params.do_srt and not result.stopped:
            temp_wav = output_ae.parent / f"{inp.stem}_temp_audio.wav"
            temp_success = False
            
            # 2a. Generate Temp WAV
            on_log(tr("log_srt_temp_start"), "info")
            temp_cmd = build_extract_wav_cmd(ae_path, inp, params.margin, params.threshold, temp_wav)
            try:
                res_temp = subprocess.run(
                    temp_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
                )
                
                if should_stop():
                    result.stopped = True
                    on_log(tr("log_stopped"), "warn")
                elif res_temp.returncode == 0:
                    if temp_wav.exists():
                        temp_success = True
                    else:
                        on_log(tr("log_wav_missing"), "error")
                else:
                    on_log(tr("log_error", res_temp.returncode, res_temp.stderr), "error")
            except Exception as e:
                on_log(tr("log_unexpected", traceback.format_exc()), "error")
                
            if should_stop() and not result.stopped:
                result.stopped = True
                on_log(tr("log_stopped"), "warn")

            # 2b. Transcribe Temp WAV
            if temp_success and not result.stopped:
                on_log(tr("log_srt_analyze", params.model_size), "info")
                try:
                    if transcribe is not None:
                        segments, info = transcribe(temp_wav, params.model_size)
                    else:
                        from faster_whisper import WhisperModel
                        model = WhisperModel(params.model_size, device="cpu", compute_type="int8")
                        segments, info = model.transcribe(str(temp_wav), beam_size=5, language=None)
                    
                    on_log(f"  音声検出: {info.language} (確率: {info.language_probability:.2f})", "muted")
                    
                    # Generate SRT
                    with open(output_srt, "w", encoding="utf-8") as srt_file:
                        for i, segment in enumerate(segments, start=1):
                            if should_stop():
                                result.stopped = True
                                break
                            start = format_timestamp(segment.start)
                            end = format_timestamp(segment.end)
                            text = segment.text.strip()
                            srt_file.write(f"{i}\n{start} --> {end}\n{text}\n\n")
                            # Log partial progress
                            on_log(f"  [{start} -> {end}] {text}", "muted")
                    
                    if should_stop() or result.stopped:
                        result.stopped = True
                        on_log(tr("log_stopped"), "warn")
                    else:
                        on_log(tr("log_srt_done"), "success")
                        on_log(f"   {output_srt.name}", "success")
                        result.srt_path = output_srt
                except Exception as e:
                    on_log(tr("log_unexpected", traceback.format_exc()), "error")
            
            # 2c. Cleanup Temp WAV
            try:
                if temp_wav.exists():
                    temp_wav.unlink()
            except Exception as e:
                on_log(f"Temp file cleanup failed: {e}", "warn")
                
    except Exception as e:
        # Catch any unexpected top-level worker thread crashes
        on_log(tr("log_unexpected", traceback.format_exc()), "error")
        
    return result
