import shutil
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from autoeditor import build_cut_cmd, build_extract_wav_cmd
from subtitles import add_cuda_dll_dirs, format_timestamp, resolve_device

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


def _rewrite_fcpxml_track_paths(timeline_path: Path, old_dir: Path, new_dir: Path) -> None:
    """relocate 後、fcpxml 内の {stem}_tracks 参照パスを移動先へ書き換える。
    auto-editor は forward-slash の絶対パスで file:// 参照を書く（実測）ため、
    まず forward-slash 形で置換し、不一致なら backslash 形を保険で試す。
    """
    try:
        text = timeline_path.read_text(encoding="utf-8")
    except Exception:
        return
    old_fwd = str(old_dir).replace("\\", "/")
    new_fwd = str(new_dir).replace("\\", "/")
    new_text = text.replace(old_fwd, new_fwd)
    if new_text == text:
        new_text = text.replace(str(old_dir), str(new_dir))
    if new_text != text:
        timeline_path.write_text(new_text, encoding="utf-8")


def _reorder_fcpxml_tracks(timeline_path: Path, stem: str) -> bool:
    """多トラック fcpxml の spine を元のストリーム順へ並べ替える（トラックごとのブロック列挙の維持）。

    auto-editor は「各トラックの全カットセグメントを時系列順に並べたブロック」を
    spine 直下にフラットに順番に列挙する（例: [映像_seg1..N] -> [WAV1_seg1..N]...）。
    Resolve 等の NLE は、この物理的な出現順（ブロック順）をトラック割当の基準とする。
    本関数では、元の「トラックごとに全セグメントを並べる」フラットな構造を完全に維持したまま、
    ブロックの出現順序のみを元のストリーム順（映像A1 -> WAV_1..N）に整列する。
    これにより、Resolve 側での解釈エラー（映像消失、トラック過剰分裂、一部トラックの消失）を
    完全に回避し、4つのトラックが正しい順序通り（A1..A4）に展開されるようにする。

    戻り値: 並べ替えた=True / 対象外（単トラック等）=False。
    """
    try:
        tree = ET.parse(timeline_path)
    except Exception:
        return False
    root = tree.getroot()

    video_id = None
    wavs: dict[int, str] = {}          # stream index -> asset id
    for asset in root.findall(".//resources/asset"):
        aid = asset.get("id")
        name = asset.get("name", "")
        if asset.get("hasVideo") == "1" and video_id is None:
            video_id = aid
        elif name.startswith(stem + "_"):
            suffix = name[len(stem) + 1:]
            if suffix.isdigit():
                wavs[int(suffix)] = aid

    # 単トラック（wav 無し）や構造不明なら何もしない
    if video_id is None or not wavs:
        return False

    spine = root.find(".//sequence/spine")
    if spine is None:
        return False
    clips = spine.findall("asset-clip")
    if not clips:
        return False

    # トラックごとの要素リストを初期化
    track_lists: dict[str, list[ET.Element]] = {video_id: []}
    for ref_id in wavs.values():
        track_lists[ref_id] = []

    # spine の全子要素を走査し、トラックごとに分類（元の要素オブジェクトをそのまま維持）
    for child in list(spine):
        if child.tag != "asset-clip":
            # gap などの非 asset-clip 要素は、映像トラック（プライマリ）のリストに追加
            track_lists[video_id].append(child)
        else:
            ref = child.get("ref")
            if ref == video_id:
                track_lists[video_id].append(child)
            elif ref in track_lists:
                track_lists[ref].append(child)

    # 堅牢性チェック：各トラックのクリップ数が一致しているか（gap は除く）
    # 通常、映像と各 WAV は同じカット数を持つため、リストの長さが一致するはず
    # 一致しない場合、安全のため False を返す
    expected_len = len([c for c in track_lists[video_id] if c.tag == "asset-clip"])
    for ref_id, lst in track_lists.items():
        clip_count = len([c for c in lst if c.tag == "asset-clip"])
        if clip_count != expected_len:
            return False

    # spine をクリアして、正しいトラック of 順番で要素を再配置 (Resolveの逆順展開を考慮して逆順に並べる)
    spine.clear()
    
    # 1. 各 WAV トラックのブロック（WAV_N...WAV1 の降順）
    for stream_idx in sorted(wavs, reverse=True):
        ref_id = wavs[stream_idx]
        for child in track_lists[ref_id]:
            spine.append(child)

    # 2. 映像トラックのブロックを最後に追加
    for child in track_lists[video_id]:
        spine.append(child)

    tree.write(timeline_path, encoding="utf-8", xml_declaration=True)
    return True




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

    # auto-editor は多トラック音声入力を分解し、入力ファイルの隣に {stem}_tracks
    # フォルダ（_1.wav/_2.wav...）を残す。--temp-dir では移動できず抑制フラグも無い
    # （実測で確認）ため、本実行で出現した場合のみ後始末する。既存フォルダは触らない
    # よう、開始前に存在有無を記録しておく。
    tracks_dir = inp.parent / f"{inp.stem}_tracks"
    tracks_pre_existed = tracks_dir.exists()
    is_fcpxml = ext == ".fcpxml"
    # fcpxml の参照アセットを入力隣に温存する必要があるとき True（finally で消さない）。
    tracks_keep_in_place = False

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
        except Exception:
            on_log(tr("log_unexpected", traceback.format_exc()), "error")

        # 1b. 多トラック音声の _tracks 後処理（B 案）。
        # fcpxml(resolve / final-cut-pro) は _tracks/*.wav を必須アセットとして
        # 参照するため、掃除すると DaVinci 等で当該トラックが「メディア未検出」に
        # なる（実測・PITFALLS 参照）。出力先へ移動し fcpxml 内の参照パスを書き換える。
        # premiere(.xml) は元動画を直接参照するため _tracks は不要 → finally で掃除。
        # 字幕用 WAV 抽出(2a)が _tracks を再生成し得るので、その前にここで移動する。
        if (result.ok and is_fcpxml and result.timeline_path
                and tracks_dir.is_dir() and not tracks_pre_existed):
            if tracks_dir.parent == out_dir:
                # 既に .fcpxml と同じ場所にある → 参照アセットとしてそのまま残す
                tracks_keep_in_place = True
            else:
                dest = out_dir / tracks_dir.name
                try:
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    shutil.move(str(tracks_dir), str(dest))
                    _rewrite_fcpxml_track_paths(result.timeline_path, tracks_dir, dest)
                    on_log(tr("log_tracks_relocated", dest.name), "muted")
                except Exception:
                    # 移動失敗時は参照を壊さぬよう元の場所に温存（タイムライン保護優先）
                    tracks_keep_in_place = True
                    on_log(tr("log_unexpected", traceback.format_exc()), "error")

        # 1c. fcpxml のトラック順を元のストリーム順へ正規化（多トラック時のみ）。
        if result.ok and is_fcpxml and result.timeline_path and result.timeline_path.exists():
            try:
                if _reorder_fcpxml_tracks(result.timeline_path, inp.stem):
                    on_log(tr("log_tracks_reordered"), "muted")
            except Exception:
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
            except Exception:
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
                            if dev == "cuda":
                                add_cuda_dll_dirs()   # venv内CUDA DLLをロード可能に（Win）
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

    except Exception:
        # Catch any unexpected top-level worker thread crashes
        on_log(tr("log_unexpected", traceback.format_exc()), "error")
    finally:
        # 入力の隣に残る {stem}_tracks を掃除（本実行で出現した分のみ）。
        # fcpxml で出力先へ移動済み(relocate)なら、ここに残るのは字幕用 WAV 抽出が
        # 再生成したクラッタ → 削除してよい。fcpxml で温存判定(tracks_keep_in_place)の
        # ときだけは参照アセットなので消さない。premiere(.xml) は常に掃除対象。
        # 停止/失敗時も必ず後始末されるよう finally に置く。
        try:
            if (tracks_dir.is_dir() and not tracks_pre_existed
                    and not tracks_keep_in_place):
                shutil.rmtree(tracks_dir, ignore_errors=True)
                on_log(tr("log_tracks_cleaned", tracks_dir.name), "muted")
        except Exception:
            pass

    return result
