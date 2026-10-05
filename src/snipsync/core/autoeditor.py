"""auto-editor command builders.

Pure functions -> unit-testable without spawning processes. The main cut and
the subtitle WAV extraction MUST share margin/threshold or subtitle timecodes
drift from the timeline.

Flag names follow auto-editor 31.x (``--when-inactive``). 29.x spelled it ``--when-silent``
and could only take one ``--cut-out`` range. The pinned version lives in ``aebin.AE_VERSION``;
re-check every flag against that version's ``--help`` when bumping it.
"""
from fractions import Fraction
from pathlib import Path

# 音声のみ入力として扱う拡張子（タイムライン/レンダリングとも auto-editor が処理できる）
AUDIO_EXTS = frozenset({".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".wma"})
VIDEO_EXTS = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".m4v"})
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS
# 同梱の auto-editor が書き出せる音声形式（実測 31.7.2）。mp3 / m4a / aac は同梱エンコーダーが無く失敗する。
AUDIO_RENDER_EXTS = frozenset({".wav", ".flac", ".ogg", ".opus"})
# ライセンスキー無しで、レンダリングが縮小されずに済む上限（31.4.0 以降の公式仕様）。超えると自動で縮小される。
UNLICENSED_RENDER_MAX = (3200, 1800)

# export_key がこの値のとき、タイムラインではなくカット済みメディアを直接書き出す
EXPORT_MEDIA = "media"
# 音声のみ入力に使う仮のタイムベース（映像が無く fps が定義できないため）
AUDIO_ONLY_TIMEBASE = 30
# v1 JSON の chunk で「カット」を表す速度値（auto-editor 仕様）
CUT_SPEED = 99999.0


def is_audio_only(path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTS


def format_timebase(tb) -> str:
    """-tb 用の文字列。29.97 を 30 に丸めず 30000/1001 のまま渡す。

    NTSC 系 (23.976 / 29.97 / 59.94) を整数へ丸めると、auto-editor が量子化する
    フレーム格子が NLE のタイムラインとずれ、字幕のカット境界が累積でずれる。
    """
    frac = Fraction(tb).limit_denominator(1001)
    if frac.denominator == 1:
        return str(frac.numerator)
    return f"{frac.numerator}/{frac.denominator}"


def _edit_args(margin, threshold, silent_speed=None):
    args = ["--margin", f"{margin:.3f}s", "--edit", f"audio:threshold={threshold:.1f}%"]
    if silent_speed:
        args += ["--when-inactive", f"speed:{silent_speed:g}"]
    return args


# 全コマンド共通の末尾。--progress none は進捗バー（ANSI 制御文字）がログ欄を汚すのを防ぐ。
def _tail(output):
    return ["--progress", "none", "--output", str(output), "--no-open"]


# カット済みの動画を書き出すとき、映像のプロファイルを明示する。
# auto-editor 31.7.2 は、指定しないと、B フレームのある H.264（OBS などの録画に多い）で
# 「Could not write packet: Invalid argument (pts/dts …)」で失敗することがある（実測: 24 通りの設定のうち、
# 指定なしは 8 通り中 5 通りで失敗、high / main を指定した 16 通りはすべて成功）。
VIDEO_PROFILE_EXTS = (".mp4", ".mov", ".mkv", ".m4v")      # H.264 で書き出す入れ物。webm（VP9）などには付けない


def _media_video_args(output) -> list[str]:
    return ["-vprofile", "high"] if Path(str(output)).suffix.lower() in VIDEO_PROFILE_EXTS else []


def build_cut_cmd(ae_path, inp, margin, threshold, export_key, output, *, silent_speed=None):
    """auto-editor command: silence cut -> NLE timeline (.fcpxml/.xml) or rendered media.

    silent_speed: 無音区間をカットせずこの倍速にする（None=カット）。
    export_key == EXPORT_MEDIA: ``--export`` を付けず、カット済みメディアを書き出す。
    """
    cmd = [str(ae_path), str(inp), *_edit_args(margin, threshold, silent_speed)]
    if export_key != EXPORT_MEDIA:
        cmd += ["--export", export_key]
    else:
        cmd += _media_video_args(output)
    return cmd + _tail(output)


def build_extract_wav_cmd(ae_path, inp, margin, threshold, output, *, silent_speed=None):
    """auto-editor command: extract cut audio only -> temp WAV for ASR."""
    return [
        str(ae_path), str(inp),
        *_edit_args(margin, threshold, silent_speed),
        "-vn", "-sn", "-dn",
        "--mix-audio-streams",
        *_tail(output),
    ]


def build_v1_export_cmd(ae_path, inp, margin, threshold, out_json, tb, *, silent_speed=None):
    """auto-editor command: export cut decisions as v1 JSON (chunks).

    NLE 形式に依存しないカット境界の正準ソース。-tb で frame グリッドを
    source fps に固定し、step1 のデフォルト timebase と一致させる（P-2 と同じ
    margin/threshold）。tb は有理数（30000/1001 等）を保つ。
    """
    return [
        str(ae_path), str(inp),
        *_edit_args(margin, threshold, silent_speed),
        "--export", "v1",
        "-tb", format_timebase(tb),
        "--progress", "none", "--output", str(Path(out_json).resolve()), "--no-open",
    ]


# ── 自前のカット区間（VAD 等）を v1 JSON 経由で auto-editor に渡す ──────────────────
# auto-editor は v1 JSON を入力として受け取れる。直接実行と同じ出力になることを実測済み
# （29.3.1 / 31.7.2 とも。Premiere / Resolve / Final Cut Pro の XML が1バイトも違わない）。
# --cut は1回に1区間しか取れないため、多数の区間はこの経路で渡す。

def build_cut_cmd_from_chunks(ae_path, chunks_json, export_key, output, tb=None):
    cmd = [str(ae_path), str(chunks_json)]
    if tb:
        cmd += ["-tb", format_timebase(tb)]
    if export_key != EXPORT_MEDIA:
        cmd += ["--export", export_key]
    else:
        cmd += _media_video_args(output)
    return cmd + _tail(output)


def build_extract_wav_cmd_from_chunks(ae_path, chunks_json, output, tb=None):
    cmd = [str(ae_path), str(chunks_json)]
    if tb:
        cmd += ["-tb", format_timebase(tb)]
    return cmd + ["-vn", "-sn", "-dn", "--mix-audio-streams", *_tail(output)]


def _probe_fps_ffprobe(path):
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(Path(path).resolve())],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        out = (result.stdout or "").strip()
        if not out:
            return None
        if "/" in out:
            num, den = out.split("/")
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        return float(out)
    except Exception:
        return None


def _probe_fps_av(path):
    """PyAV（faster-whisper の依存に同梱）で fps を読む。ffprobe が無い PC 向けの代替。"""
    try:
        import av
        with av.open(str(Path(path).resolve())) as container:
            stream = container.streams.video[0]
            rate = stream.average_rate or stream.guessed_rate
            return float(rate) if rate else None
    except Exception:
        return None


def probe_fps(path):
    """動画の fps(float) を返す。失敗時 None。

    ffprobe（r_frame_rate）を先に試し、PATH に無い等で取れなければ PyAV で読む。
    v1 export の frame->秒 変換 timebase に使う（CFR 前提）。
    """
    fps = _probe_fps_ffprobe(path)
    if fps:
        return fps
    return _probe_fps_av(path)


def probe_duration(path):
    """メディア全体の長さ(秒)を PyAV で読む。失敗時 None。"""
    try:
        import av
        with av.open(str(Path(path).resolve())) as container:
            if container.duration:
                return container.duration / 1_000_000
    except Exception:
        pass
    return None


def probe_resolution(path):
    """動画の (幅, 高さ)。映像が無い/読めない場合は None。"""
    try:
        import av
        with av.open(str(Path(path).resolve())) as container:
            vs = container.streams.video[0]
            return vs.width, vs.height
    except Exception:
        return None


def exceeds_unlicensed_render_limit(resolution) -> bool:
    """ライセンスキー無しの auto-editor が縮小するほどの解像度か。"""
    if not resolution:
        return False
    w, h = resolution
    return w > UNLICENSED_RENDER_MAX[0] or h > UNLICENSED_RENDER_MAX[1]
