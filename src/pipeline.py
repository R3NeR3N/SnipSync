import re
import shutil
import subprocess
import sys
import traceback
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

import safexml
from audiocut import render_cut_audio, write_wav
from autoeditor import (
    AUDIO_EXTS,
    AUDIO_ONLY_TIMEBASE,
    AUDIO_RENDER_EXTS,
    EXPORT_MEDIA,
    build_cut_cmd,
    build_cut_cmd_from_chunks,
    build_extract_wav_cmd,
    build_extract_wav_cmd_from_chunks,
    build_v1_export_cmd,
    exceeds_unlicensed_render_limit,
    is_audio_only,
    probe_duration,
    probe_fps,
    probe_resolution,
)
from diarize import diarize, sherpa_available
from markers import (
    add_markers,
    cut_point_markers,
    resolve_marks,
    speaker_turn_markers,
    write_marker_edl,
)
from models import (
    DownloadCancelled,
    DownloadFailed,
    get_spec,
    lang_hint,
    needs_download,
    prepare_model,
)
from subtitles import (
    add_cuda_dll_dirs,
    build_cut_aligned_cues,
    chunks_to_boundaries,
    cues_from_segments,
    format_srt,
    format_timestamp,
    normalize_turns,
    refine_cue_times,
    resolve_device,
    tag_words,
)
from transcript import write_transcripts
from vad import SAMPLE_RATE, decode_mix, detect_speech, read_v1_chunks, speech_to_chunks, write_v1

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


def _rewrite_fcpxml_track_paths(timeline_path: Path, old_dir: Path, new_dir: Path) -> bool:
    """relocate 後、fcpxml 内の {stem}_tracks 参照パスを移動先へ書き換える。書き換えたら True。

    auto-editor は、参照を file:// の URL で書く（実測: スペースは %20、日本語などは %XX）。
    以前は、生のパス文字列で置換していたため、ファイル名に**スペースや日本語を含むと一致せず、
    何も書き換えないまま成功したことになり**、DaVinci Resolve で「3 クリップのうち 3 クリップが
    見つかりません」になった（OBS の録画は、名前にスペースを含むことが多い）。
    URL 形式（%エンコード）を先に試し、生の形式・バックスラッシュ形式も保険で試す。
    置換後の形式は、一致した形式に合わせる（URL なら、移動先も %エンコードして書く）。
    """
    from urllib.parse import quote
    try:
        text = timeline_path.read_text(encoding="utf-8")
    except Exception:
        return False
    old_fwd = str(old_dir).replace("\\", "/")
    new_fwd = str(new_dir).replace("\\", "/")
    candidates = (
        (quote(old_fwd, safe="/:"), quote(new_fwd, safe="/:")),      # file:///G:/…/2026-06-20%2011-04-28_tracks
        (old_fwd, new_fwd),                                          # 生の形式
        (str(old_dir), str(new_dir)),                                # バックスラッシュ形式
    )
    for old, new in candidates:
        if old in text:
            timeline_path.write_text(text.replace(old, new), encoding="utf-8")
            return True
    return False


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
        tree = safexml.parse(timeline_path)
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
    track_lists: dict[str, list] = {video_id: []}
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
    export_key: str          # "resolve" | "premiere" | "final-cut-pro" | "media"(カット済みメディアを書き出す)
    do_srt: bool
    model_size: str          # models.MODELS のキー（tiny/base/small/medium/turbo/large-v3/kotoba-ja/distil-en）
    use_gpu: bool = False
    snap_srt: bool = True
    cut_mode: str = "threshold"      # "threshold"(音量) | "vad"(音声区間検出)
    silent_speed: float | None = None  # 無音を切らずにこの倍速にする（None=カット）
    hotwords: str = ""               # 用語辞書（カンマ/改行区切り）。Whisper の hotwords に渡す
    diarize: bool = False            # 話者分離
    num_speakers: int = -1           # -1=自動
    speaker_labels: bool = True      # 字幕に「話者1：」を前置する
    markers: bool = False            # タイムラインにカット点/話者交代のマーカーを追加
    line_chars: int = 0              # 字幕1行の全角文字数（0=整形しない）
    txt: bool = False                # 文字起こしを .txt でも書き出す
    md: bool = False                 # 文字起こしを .md でも書き出す
    refine_timing: bool = True       # 字幕の時刻を、実際に声がある区間（VAD）に合わせて補正する
    hold_subtitles: bool = False     # 字幕（.srt/.txt/.md）をここでは書かず、確認・編集してから呼び出し側が保存する
    out_stem: str | None = None      # 出力ファイル名の幹（バッチで同名を避ける用）
    ui_lang: str = "ja"


class Stopped(Exception):
    """利用者の「停止」で、処理を途中でやめた（文字起こしの最中など）。"""


@dataclass
class PipelineResult:
    ok: bool                 # メインカット成功（完了ダイアログ可否の判定に使用）
    stopped: bool            # 停止要求で中断したか
    timeline_path: Path | None
    srt_path: Path | None
    cues: list = field(default_factory=list)          # 最終的な字幕（プレビュー/書き出し用）
    extra_paths: list = field(default_factory=list)   # 追加で書いた .txt / .md
    pending_paths: dict = field(default_factory=dict)  # hold_subtitles のとき: まだ書いていない宛先（形式 -> パス）
    markers_added: int = 0
    marker_edl_path: Path | None = None     # DaVinci Resolve 用: マーカーを書いた EDL（.fcpxml のマーカーは Resolve が読まない）
    marker_cuts: list = field(default_factory=list)   # 同: カット点のマーカー（話者交代を足して、EDL を書き直すため）
    speaker_markers_pending: bool = False   # hold_subtitles のとき: 話者交代のマーカーは、確認・編集後の字幕で入れる


def _output_ext(export_key: str, inp: Path) -> str:
    if export_key == EXPORT_MEDIA:
        suffix = inp.suffix.lower()
        if suffix in AUDIO_EXTS:
            # 同梱の auto-editor が書き出せない形式（mp3 / m4a / aac / wma）は WAV にする
            return suffix if suffix in AUDIO_RENDER_EXTS else ".wav"
        if suffix in (".mp4", ".mov", ".mkv", ".webm", ".m4v"):
            return suffix
        return ".mp4"        # avi/wmv/flv は互換性の高い mp4 へ
    return {
        "resolve": ".fcpxml",
        "premiere": ".xml",
        "final-cut-pro": ".fcpxml",
    }.get(export_key, ".xml")


def _hotwords(text: str) -> str | None:
    words = [w.strip() for w in text.replace("\n", ",").replace("、", ",").split(",")]
    words = [w for w in words if w]
    return ", ".join(words) if words else None


def run_folder_name(model_key, when, *, with_model: bool = True) -> str:
    """処理 1 回ぶんの出力フォルダー名。「日時_モデル名」（例: 2026-10-04_190357_large-v3）。

    日時を先頭に置くので、フォルダーの一覧が、処理した順に並ぶ。字幕を作らない（モデルを使わない）ときは、日時だけ。
    """
    stamp = when.strftime("%Y-%m-%d_%H%M%S")
    safe = re.sub(r'[\\/:*?"<>|\s]+', "-", str(model_key or "")).strip("-.")
    return f"{stamp}_{safe}" if (with_model and safe) else stamp


def _prepare_vad_cuts(inp, out_dir, name, params, *, on_log, tr, audio_only):
    """VAD でカット区間を決め、v1 JSON を書く。戻り値 (json_path, fps)。失敗/発話なしは (None, None)。"""
    fps = AUDIO_ONLY_TIMEBASE if audio_only else probe_fps(inp)
    if not fps:
        on_log(tr("log_vad_no_fps"), "warn")
        return None, None
    on_log(tr("log_vad_start"), "info")
    samples = decode_mix(inp)
    duration = probe_duration(inp) or len(samples) / SAMPLE_RATE
    ranges = detect_speech(samples)
    chunks = speech_to_chunks(ranges, duration, fps, margin=params.margin,
                              silent_speed=params.silent_speed)
    if not chunks:
        on_log(tr("log_vad_none"), "warn")
        return None, None
    path = write_v1(out_dir / f"{name}_cuts_vad.json", inp, chunks)
    on_log(tr("log_vad_done", len(ranges)), "muted")
    return path, fps


def run_pipeline(
    ae_path,                 # auto-editor 実行パス
    inp: Path,               # 入力動画/音声（解決済み絶対パス）
    out_dir: Path,           # 出力先（解決済み絶対パス）
    params: PipelineParams,
    *,
    on_log,                  # (msg: str, level: str="") -> None
    should_stop,             # () -> bool
    tr,                      # (key: str, *args) -> str
    transcribe=None,         # DI用フック（既定 None→内部で faster_whisper を使用）
    model_cache=None,        # dict を渡すと WhisperModel を使い回す（バッチ処理用）
    on_progress=None,        # (kind, done, total) -> None。kind は "model"（取得。バイト）/ "load"（読み込み中）/
                             # "transcribe"（文字起こし。秒）。終わりは done=None
) -> PipelineResult:
    result = PipelineResult(ok=False, stopped=False, timeline_path=None, srt_path=None)

    name = params.out_stem or inp.stem
    ext = _output_ext(params.export_key, inp)
    audio_only = is_audio_only(inp)
    is_media = params.export_key == EXPORT_MEDIA

    output_ae = out_dir / f"{name}_snipsynced{ext}"
    output_srt = out_dir / f"{name}.srt"

    # auto-editor は多トラック音声入力を分解し、入力ファイルの隣に {stem}_tracks
    # フォルダ（_1.wav/_2.wav...）を残す。--temp-dir では移動できず抑制フラグも無い
    # （実測で確認）ため、本実行で出現した場合のみ後始末する。既存フォルダは触らない
    # よう、開始前に存在有無を記録しておく。
    tracks_dir = inp.parent / f"{inp.stem}_tracks"
    tracks_pre_existed = tracks_dir.exists()
    is_fcpxml = ext == ".fcpxml"
    # fcpxml の参照アセットを入力隣に温存する必要があるとき True（finally で消さない）。
    tracks_keep_in_place = False

    vad_json = None          # VAD 方式のとき、全 auto-editor 呼び出しで共有するカット区間
    cut_tb = None
    v1_json = output_ae.parent / f"{name}_cuts_v1.json"
    chunks_cache: list | None = None
    chunks_tb = None

    def get_chunks():
        """(chunks, tb)。VAD 方式は自前の区間、音量方式は auto-editor の v1 export。取れなければ ([], None)。

        chunks はタイムラインの元になる区間そのもの。カット境界・字幕用音声・マーカーはすべてここから作る。
        """
        nonlocal chunks_cache, chunks_tb
        if chunks_cache is not None:
            return chunks_cache, chunks_tb
        chunks_cache = []
        try:
            if vad_json is not None:
                chunks_cache, chunks_tb = read_v1_chunks(vad_json), cut_tb
            else:
                fps = AUDIO_ONLY_TIMEBASE if audio_only else probe_fps(inp)
                if fps:
                    v1_cmd = build_v1_export_cmd(
                        ae_path, inp, params.margin, params.threshold, v1_json, fps,
                        silent_speed=params.silent_speed,
                    )
                    rc_v1, stopped_v1 = _run_streaming(
                        v1_cmd, on_log=on_log, should_stop=should_stop,
                    )
                    if not stopped_v1 and rc_v1 == 0 and v1_json.exists():
                        chunks_cache, chunks_tb = read_v1_chunks(v1_json), fps
        except Exception:
            on_log(tr("log_unexpected", traceback.format_exc()), "error")
        finally:
            try:
                if v1_json.exists():
                    v1_json.unlink()
            except Exception:
                pass
        return chunks_cache, chunks_tb

    def get_boundaries() -> list:
        """タイムライン上のカット境界(秒)。"""
        chunks, tb = get_chunks()
        return chunks_to_boundaries(chunks, tb)

    def render_audio(sr: int):
        """カット後の音声を自前で組み立てる。作れなければ None。"""
        chunks, tb = get_chunks()
        if not chunks or not tb:
            return None
        audio = render_cut_audio(decode_mix(inp, sr), chunks, tb, sr)
        return audio if len(audio) else None

    try:
        # 1. Auto-Editor Processing
        if should_stop():
            result.stopped = True
            on_log(tr("log_stopped"), "warn")
            return result

        # 0. VAD 方式: 発話区間からカット区間を作る（失敗時は音量方式へ戻す）
        if params.cut_mode == "vad":
            try:
                vad_json, cut_tb = _prepare_vad_cuts(
                    inp, out_dir, name, params, on_log=on_log, tr=tr, audio_only=audio_only)
            except Exception:
                vad_json, cut_tb = None, None
                on_log(tr("log_unexpected", traceback.format_exc()), "error")

        # メディア書き出しだけ: ライセンスキー無しの auto-editor は大きい解像度のレンダリングを縮小する。
        if is_media and not audio_only:
            res = probe_resolution(inp)
            if exceeds_unlicensed_render_limit(res):
                on_log(tr("log_media_downscale", res[0], res[1]), "warn")

        try:
            if vad_json is not None:
                cmd = build_cut_cmd_from_chunks(ae_path, vad_json, params.export_key, output_ae, tb=cut_tb)
            else:
                cmd = build_cut_cmd(ae_path, inp, params.margin, params.threshold,
                                    params.export_key, output_ae, silent_speed=params.silent_speed)
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
            if is_media and not result.ok:
                output_ae.unlink(missing_ok=True)       # 書きかけの動画・音声（再生できない）を残さない
        except FileNotFoundError as e:
            on_log(tr("log_ae_missing", e), "error")
        except Exception:
            on_log(tr("log_unexpected", traceback.format_exc()), "error")

        # 1b. 多トラック音声の _tracks 後処理（B 案）。
        # fcpxml(resolve / final-cut-pro) は _tracks/*.wav を必須アセットとして
        # 参照するため、掃除すると DaVinci 等で当該トラックが「メディア未検出」に
        # なる（実測）。出力先へ移動し fcpxml 内の参照パスを書き換える。
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
                    if _rewrite_fcpxml_track_paths(result.timeline_path, tracks_dir, dest):
                        on_log(tr("log_tracks_relocated", dest.name), "muted")
                    else:
                        # 参照を書き換えられなかった。移動してしまうと、タイムラインが音声を見失うので、元に戻す。
                        shutil.move(str(dest), str(tracks_dir))
                        tracks_keep_in_place = True
                        on_log(tr("log_tracks_rewrite_failed"), "warn")
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
        turns = None             # 話者分離の結果（タイムライン基準）
        if result.ok and params.do_srt and not result.stopped:
            temp_wav = output_ae.parent / f"{name}_temp_audio.wav"
            temp_success = False
            srt_words = []
            srt_natural_segs = []
            seg_tuples = []
            detected_lang = lang_hint(params.model_size)

            # 2a. 字幕用のカット済み音声（16kHz mono）を作る。
            #     まず chunks から自前で組み立てる（モノラルでも壊れず、auto-editor の追加実行も不要）。
            #     組み立てられないときだけ、従来どおり auto-editor で WAV を書き出す。
            on_log(tr("log_srt_temp_start"), "info")
            cut_samples = None
            try:
                built = render_audio(SAMPLE_RATE)
                if built is not None:
                    write_wav(temp_wav, built, SAMPLE_RATE)
                    cut_samples = built
                    temp_success = True
            except Exception:
                temp_success = False
            if not temp_success and not should_stop():
                if vad_json is not None:
                    temp_cmd = build_extract_wav_cmd_from_chunks(ae_path, vad_json, temp_wav, tb=cut_tb)
                else:
                    temp_cmd = build_extract_wav_cmd(ae_path, inp, params.margin, params.threshold,
                                                     temp_wav, silent_speed=params.silent_speed)
                try:
                    rc_temp, stopped_temp = _run_streaming(temp_cmd, on_log=on_log,
                                                           should_stop=should_stop)

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
                    want_words = params.snap_srt or params.diarize or params.line_chars > 0
                    spec = get_spec(params.model_size)

                    # モデルの取得は、デコードの試行（GPU 失敗時の CPU やり直し）より前に1回だけ行う。
                    # 取得の停止や失敗が「GPU の失敗」と取り違えられ、同じ取得をやり直さないようにするため。
                    model_path = params.model_size
                    if transcribe is None and not (model_cache and any(k[0] == params.model_size for k in model_cache)):
                        if needs_download(params.model_size):
                            on_log(tr("log_model_download", spec.source), "info")
                        model_path = prepare_model(
                            params.model_size, should_stop=should_stop,
                            on_progress=(lambda d, t: on_progress("model", d, t)) if on_progress else None)

                    def _get_model(dev, ctype):
                        key = (params.model_size, dev, ctype)
                        if model_cache is not None and key in model_cache:
                            return model_cache[key]
                        from faster_whisper import WhisperModel
                        if dev == "cuda":
                            add_cuda_dll_dirs()   # venv内CUDA DLLをロード可能に（Win）
                        if on_progress:
                            on_progress("load", 0, 0)       # 大きなモデルの読み込みは数十秒かかる。止まって見えないように知らせる
                        try:
                            model = WhisperModel(model_path, device=dev, compute_type=ctype)
                        finally:
                            if on_progress:
                                on_progress("load", None, None)
                        if should_stop():                   # 読み込み中に停止が押されていたら、ここで止める
                            raise Stopped()
                        if model_cache is not None:
                            model_cache[key] = model
                        return model

                    def _decode(dev, ctype):
                        # transcribe を呼び、ジェネレータをリスト化して“この場で”デコードを完走させる。
                        # → CUDA 実行時エラーをこの try 内で確実に捕捉できる。
                        if transcribe is not None:
                            seg_iter, inf = transcribe(temp_wav, params.model_size)
                        else:
                            model = _get_model(dev, ctype)
                            kwargs = dict(beam_size=5, language=None, word_timestamps=want_words)
                            kwargs.update(spec.transcribe_kwargs)
                            hot = _hotwords(params.hotwords)
                            if hot:
                                kwargs["hotwords"] = hot
                            seg_iter, inf = model.transcribe(str(temp_wav), **kwargs)
                        # セグメントを1つずつ取り出し、そのつど停止を確かめて、進み具合を知らせる。
                        # （まとめて list() すると、長い音声では終わるまで「停止」が効かない）
                        # 取り出しきる＝デコード完走なので、CUDA の実行時エラーもこの try 内で捕捉できる。
                        total = float(getattr(inf, "duration", 0) or 0)
                        got = []
                        try:
                            for seg in seg_iter:
                                if should_stop():
                                    raise Stopped()
                                got.append(seg)
                                if on_progress:
                                    on_progress("transcribe", float(seg.end), total)
                        finally:
                            if on_progress:
                                on_progress("transcribe", None, None)
                        return got, inf

                    try:
                        if device == "cuda":
                            segments, info = _decode("cuda", compute_type)
                            on_log(tr("log_device", "cuda"), "muted")
                        else:
                            segments, info = _decode("cpu", compute_type)
                            on_log(tr("log_device", "cpu"), "muted")
                    except Stopped:
                        raise
                    except Exception as gpu_exc:
                        if device == "cuda":
                            on_log(tr("log_gpu_fallback", str(gpu_exc).splitlines()[0][:160] if str(gpu_exc) else
                                      type(gpu_exc).__name__), "warn")
                            device, compute_type = "cpu", "int8"   # ← device/compute_type を同時に CPU へ
                            segments, info = _decode("cpu", compute_type)
                            on_log(tr("log_device", "cpu"), "muted")
                        else:
                            raise   # CPU でも失敗なら外側 except へ（log_unexpected）

                    on_log(tr("log_lang_detected", info.language, info.language_probability), "muted")
                    detected_lang = getattr(info, "language", None) or detected_lang

                    srt_natural_segs = [(s.start, s.end) for s in segments]
                    srt_words = []
                    for s in segments:
                        for w in (getattr(s, "words", None) or []):
                            srt_words.append((w.start, w.end, w.word))
                    seg_tuples = [
                        (s.start, s.end, s.text,
                         [(w.start, w.end, w.word) for w in (getattr(s, "words", None) or [])] or None)
                        for s in segments
                    ]

                    # SRT 書き込み（segments は確定済みリスト）。保留中はファイルを作らず、ログだけ出す。
                    hold = params.hold_subtitles
                    with (nullcontext() if hold else open(output_srt, "w", encoding="utf-8")) as srt_file:
                        for i, segment in enumerate(segments, start=1):
                            if should_stop():
                                result.stopped = True
                                break
                            start = format_timestamp(segment.start)
                            end = format_timestamp(segment.end)
                            text = segment.text.strip()
                            if srt_file:
                                srt_file.write(f"{i}\n{start} --> {end}\n{text}\n\n")
                            on_log(f"  [{start} -> {end}] {text}", "muted")

                    if should_stop() or result.stopped:
                        result.stopped = True
                        on_log(tr("log_stopped"), "warn")
                    else:
                        if hold:
                            on_log(tr("log_srt_held"), "success")
                        else:
                            on_log(tr("log_srt_done"), "success")
                            on_log(f"   {output_srt.name}", "success")
                        result.srt_path = output_srt
                except (DownloadCancelled, Stopped):
                    result.stopped = True
                    on_log(tr("log_stopped"), "warn")
                except DownloadFailed as exc:
                    on_log(tr("log_model_failed", tr("log_model_stalled") if str(exc) == "stalled" else str(exc)),
                           "error")
                except Exception:
                    on_log(tr("log_unexpected", traceback.format_exc()), "error")

            # 2b'. 話者分離（カット済み WAV＝タイムライン基準の音声に対して実行）
            if params.diarize and temp_success and result.srt_path and not result.stopped:
                try:
                    if not sherpa_available():
                        on_log(tr("log_diar_unavailable"), "warn")
                    else:
                        on_log(tr("log_speaker_start"), "info")
                        turns_raw = diarize(decode_mix(temp_wav), num_speakers=params.num_speakers,
                                            on_log=on_log)
                        turns = normalize_turns(turns_raw)
                        on_log(tr("log_speaker_done", len({t[2] for t in turns})), "muted")
                except Exception:
                    turns = None
                    on_log(tr("log_speaker_fail", traceback.format_exc()), "warn")

            # 2c'. 字幕の時刻の補正に使う、実際に声がある区間（Silero VAD）。失敗しても、補正を省くだけ。
            speech_ranges, cut_total = None, None
            if params.refine_timing and result.srt_path and not result.stopped:
                try:
                    samples = cut_samples if cut_samples is not None else decode_mix(temp_wav)
                    speech_ranges = detect_speech(samples, SAMPLE_RATE)
                    cut_total = len(samples) / SAMPLE_RATE
                except Exception:
                    speech_ranges = None

            # 2c. Cleanup Temp WAV
            try:
                if temp_wav.exists():
                    temp_wav.unlink()
            except Exception as e:
                on_log(tr("log_cleanup_failed", str(e)), "warn")

            # 2d. 字幕の最終整形（カット境界で分割・話者付与・文節改行）。いずれも不要なら
            #     上で書いた自然セグメントの SRT をそのまま使う。
            if result.srt_path and not result.stopped:
                try:
                    cues = None
                    aligned = False
                    if params.snap_srt and srt_words:
                        boundaries = get_boundaries()
                        if boundaries:
                            words = tag_words(srt_words, turns) if turns else srt_words
                            cues = build_cut_aligned_cues(
                                words, srt_natural_segs, boundaries,
                                max_chars=params.line_chars, lang=detected_lang) or None
                            if cues:
                                aligned = True
                                on_log(tr("log_srt_cut_aligned"), "muted")
                    if cues is None:
                        cues = cues_from_segments(seg_tuples, turns, max_chars=params.line_chars,
                                                  lang=detected_lang)
                    refined = False
                    if cues and speech_ranges:
                        try:
                            cut_points = get_boundaries()
                        except Exception:
                            cut_points = []
                        better = refine_cue_times(cues, speech_ranges, cut_points, cut_total)
                        refined = better != cues
                        cues = better
                        if refined:
                            on_log(tr("log_srt_refined"), "muted")
                    result.cues = cues
                    if cues and not params.hold_subtitles and (aligned or turns or refined or params.line_chars > 0):
                        srt = format_srt(cues, max_chars=params.line_chars, lang=detected_lang,
                                         speaker_labels=bool(turns) and params.speaker_labels,
                                         ui_lang=params.ui_lang)
                        if srt.strip():
                            result.srt_path.write_text(srt, encoding="utf-8")
                except Exception:
                    on_log(tr("log_unexpected", traceback.format_exc()), "error")

        # 3. 文字起こしの書き出し（.txt / .md）
        if result.cues and params.hold_subtitles and not result.stopped:
            # 保留: 書かない。確認後に保存する宛先だけ返す（呼び出し側が編集結果を書く）。
            result.pending_paths = {"srt": output_srt}
            if params.txt:
                result.pending_paths["txt"] = out_dir / f"{name}.txt"
            if params.md:
                result.pending_paths["md"] = out_dir / f"{name}.md"
        elif result.cues and (params.txt or params.md) and not result.stopped:
            try:
                paths = write_transcripts(
                    result.cues, out_dir / name, title=name, want_txt=params.txt, want_md=params.md,
                    speakers=bool(turns) and params.speaker_labels, ui_lang=params.ui_lang)
                result.extra_paths = paths
                for p in paths:
                    on_log(tr("log_transcript_written", p.name), "success")
            except Exception:
                on_log(tr("log_unexpected", traceback.format_exc()), "error")

        # 4. タイムラインへのマーカー（カット点／話者交代）。タイムライン形式のときだけ。
        if (params.markers and result.ok and not result.stopped and result.timeline_path
                and result.timeline_path.suffix in (".fcpxml", ".xml")
                and result.timeline_path.exists()):
            try:
                marks = cut_point_markers(get_boundaries(), tr("marker_cut"))
                speaker_marks = []
                if result.pending_paths:
                    # 字幕は確認・編集のあとに保存される。話者交代のマーカーは、編集後の字幕から入れる
                    # （いま入れると、確認画面で話者を直しても、マーカーが古いままになる）。
                    result.speaker_markers_pending = True
                elif turns and result.cues:
                    speaker_marks = speaker_turn_markers(result.cues, params.ui_lang)
                if params.export_key == "resolve":
                    # Resolve は .fcpxml のマーカーを読み込まない。EDL に書き、読み込み方をログに出す。
                    result.marker_cuts = marks
                    edl = out_dir / f"{name}_markers.edl"
                    # 件数が 0 でも、置き場は決めておく。カット点が無く、話者交代を字幕の保存後に足すだけのときも、
                    # EDL に書く（決めないと、足す側が .fcpxml へ書いてしまい、Resolve が読まず、失われる）。
                    result.marker_edl_path = edl
                    result.markers_added = write_marker_edl(edl, result.timeline_path,
                                                            resolve_marks(marks, speaker_marks), title=name)
                    if result.markers_added:
                        on_log(tr("log_markers_edl", result.markers_added, edl.name), "success")
                else:
                    marks += speaker_marks
                    marks.sort(key=lambda m: m[0])
                    result.markers_added = add_markers(result.timeline_path, marks)
                    on_log(tr("log_markers_added", result.markers_added), "muted")
            except Exception:
                on_log(tr("log_unexpected", traceback.format_exc()), "error")

    except Exception:
        # Catch any unexpected top-level worker thread crashes
        on_log(tr("log_unexpected", traceback.format_exc()), "error")
    finally:
        # VAD 方式で作った一時 JSON を消す。
        try:
            if vad_json is not None and Path(vad_json).exists():
                Path(vad_json).unlink()
        except Exception:
            pass
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
