"""編集後の音を、書き出す前に聞くための再生ロジック。画面（tkinter）には依存しない。

流れ:
  元の音声 + カット区間（v1 chunks） → EditedAudio（カット後の音。字幕用の音声と同じ組み立て方）
  EditedAudio → Player（再生・一時停止・速度・カット点へジャンプ）

用語:
  編集後の時刻 = カットと倍速を反映した、書き出し後のタイムラインの秒数（速度 1 倍で数える）。
  元の時刻     = 取り込んだ動画の秒数。カットマップの横軸はこちら。
"""
from __future__ import annotations

import bisect
import threading
from dataclasses import dataclass
from fractions import Fraction

from audiocut import render_cut_audio
from autoeditor import CUT_SPEED

PLAY_SR = 24000                       # 聞いて確かめるための音質。16 kHz（VAD 用）より自然で、長尺でもメモリを食わない
RATES = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
PREV_CUT_GRACE = 0.6                  # カット点の直後（この秒数以内）で「前へ」を押したら、その1つ前へ戻る


class PlayerError(Exception):
    """再生を始められなかった。利用者に見せてよい原因が入っている。"""


def sounddevice_available() -> bool:
    try:
        import sounddevice  # noqa: F401
        return True
    except Exception:       # PortAudio が読み込めない環境も含む
        return False


# ── 編集後の音 ────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Segment:
    edited_start: float
    edited_end: float
    source_start: float
    source_end: float
    speed: float


class EditedAudio:
    """カット後の音声（mono float32）と、編集後の時刻 ⇔ 元の時刻の対応、カット点。"""

    def __init__(self, samples, sr: int, segments: list[Segment]):
        self.samples = samples
        self.sr = sr
        self.segments = segments
        self._edited_starts = [s.edited_start for s in segments]
        self._source_starts = [s.source_start for s in segments]
        self.cut_points = [
            cur.edited_start for prev, cur in zip(segments, segments[1:], strict=False)
            if not (prev.source_end == cur.source_start and prev.speed == cur.speed)    # 実際に切った/速度が変わる所だけ
        ]

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sr

    @classmethod
    def build(cls, source, chunks, tb: float, sr: int = PLAY_SR) -> EditedAudio:
        """source（sr, mono）に chunks=[(開始フレーム, 終了フレーム, 速度)] を適用する。"""
        segments, acc = [], 0.0
        for start, end, speed in chunks:
            if speed >= CUT_SPEED:
                continue
            sp = speed if speed and speed > 0 else 1.0
            frames = (end - start) / sp
            segments.append(Segment(acc / tb, (acc + frames) / tb, start / tb, end / tb, sp))
            acc += frames
        return cls(render_cut_audio(source, chunks, tb, sr), sr, segments)

    def edited_to_source(self, t: float) -> float:
        if not self.segments:
            return 0.0
        i = max(0, bisect.bisect_right(self._edited_starts, t) - 1)
        s = self.segments[i]
        return min(s.source_end, s.source_start + max(0.0, t - s.edited_start) * s.speed)

    def source_to_edited(self, t: float) -> float:
        """元の時刻 → 編集後の時刻。切られた所を指していたら、次に残る所の頭へ送る。"""
        for s in self.segments:
            if t < s.source_start:
                return s.edited_start
            if t < s.source_end:
                return s.edited_start + (t - s.source_start) / s.speed
        return self.duration


def stretch(samples, sr: int, rate: float):
    """音程を変えずに rate 倍速にする（FFmpeg の atempo。PyAV 同梱）。失敗したら、音程が変わる単純な方法で代える。"""
    import numpy as np
    if abs(rate - 1.0) < 1e-6 or len(samples) == 0:
        return samples
    try:
        import av
        graph = av.filter.Graph()
        src = graph.add_abuffer(format="flt", sample_rate=sr, layout="mono", time_base=Fraction(1, sr))
        tempo = graph.add("atempo", f"{rate}")
        sink = graph.add("abuffersink")
        src.link_to(tempo)
        tempo.link_to(sink)
        graph.configure()
        out: list = []

        def drain():
            while True:
                try:
                    out.append(sink.pull().to_ndarray().reshape(-1))
                except (av.error.BlockingIOError, av.error.EOFError):
                    return

        for i in range(0, len(samples), sr):
            frame = av.AudioFrame.from_ndarray(samples[i:i + sr].reshape(1, -1).astype(np.float32),
                                               format="flt", layout="mono")
            frame.sample_rate, frame.pts = sr, i
            src.push(frame)
            drain()
        src.push(None)
        drain()
        if out:
            return np.concatenate(out).astype(np.float32)
    except Exception:
        pass
    n = max(1, int(round(len(samples) / rate)))
    return np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples).astype(np.float32)


# ── 再生 ──────────────────────────────────────────────────────────────────────────────
def _default_stream_factory(sr, callback, finished):
    import sounddevice as sd

    def wrapped(outdata, frames, _time, _status):
        if callback(outdata, frames) is False:
            raise sd.CallbackStop

    try:
        return sd.OutputStream(samplerate=sr, channels=1, dtype="float32", callback=wrapped,
                               finished_callback=finished)
    except Exception as exc:
        raise PlayerError(str(exc)) from exc


class Player:
    """EditedAudio を鳴らす。位置は、実際にデバイスへ渡したサンプル数で数える。"""

    def __init__(self, stream_factory=None):
        self._factory = stream_factory or _default_stream_factory
        self.audio: EditedAudio | None = None
        self.rate = 1.0
        self._buf = None                  # 現在の速度に変換した音
        self._pos = 0                     # _buf 上の位置（サンプル）
        self._cache: dict = {}            # 速度 -> 変換済みの音（同じ速度へ戻すとき再計算しない）
        self._lock = threading.Lock()
        self._stream = None
        self.playing = False

    # ── 読み込み ──
    @property
    def loaded(self) -> bool:
        return self.audio is not None

    def load(self, audio: EditedAudio, rate: float = 1.0):
        self.close()
        self.audio, self.rate = audio, rate
        self._cache = {1.0: audio.samples}
        self._buf = self._buffer_for(rate)
        self._pos = 0

    def unload(self):
        self.close()
        self.audio, self._buf, self._cache, self._pos = None, None, {}, 0

    def _buffer_for(self, rate: float):
        if rate not in self._cache:
            if len(self._cache) > 3:                       # 1.0 以外は直近だけ残す
                for k in [k for k in self._cache if k != 1.0][:1]:
                    del self._cache[k]
            self._cache[rate] = stretch(self.audio.samples, self.audio.sr, rate)
        return self._cache[rate]

    # ── 位置 ──
    @property
    def position(self) -> float:
        """編集後の時刻（速度 1 倍で数えた秒）。"""
        if not self.loaded:
            return 0.0
        return min(self._pos / self.audio.sr * self.rate, self.audio.duration)

    @property
    def source_position(self) -> float:
        return self.audio.edited_to_source(self.position) if self.loaded else 0.0

    @property
    def at_end(self) -> bool:
        return self.loaded and self._buf is not None and self._pos >= len(self._buf)

    def seek(self, edited_sec: float):
        if not self.loaded:
            return
        with self._lock:
            n = len(self._buf)
            self._pos = min(n, max(0, int(round(edited_sec / self.rate * self.audio.sr))))

    def seek_source(self, source_sec: float):
        if self.loaded:
            self.seek(self.audio.source_to_edited(source_sec))

    def next_cut(self) -> float | None:
        """次のカット点へ。無ければ末尾（再生は止まる）。移動先の編集後の時刻を返す。"""
        if not self.loaded:
            return None
        pos = self.position
        later = [t for t in self.audio.cut_points if t > pos + 0.05]
        target = later[0] if later else self.audio.duration
        self.seek(target)
        return target

    def prev_cut(self) -> float | None:
        """前のカット点へ。カット点の直後なら、その1つ前へ。無ければ先頭。"""
        if not self.loaded:
            return None
        pos = self.position
        earlier = [t for t in self.audio.cut_points if t < pos - PREV_CUT_GRACE]
        target = earlier[-1] if earlier else 0.0
        self.seek(target)
        return target

    # ── 速度 ──
    def set_rate(self, rate: float):
        """再生中でも切り替えられる。位置は、切り替えた瞬間の編集後の時刻に合わせ直す。"""
        if not self.loaded or rate == self.rate:
            self.rate = rate
            return
        buf = self._buffer_for(rate)               # 重い処理は、ロックの外で（この間も再生は進む）
        with self._lock:
            edited = self._pos / self.audio.sr * self.rate
            self.rate, self._buf = rate, buf
            self._pos = min(len(buf), int(round(edited / rate * self.audio.sr)))

    # ── 再生・停止 ──
    def play(self):
        if not self.loaded or self.playing:
            return
        self._drop_stream()                # 末尾で止まったまま残っているストリームがあれば閉じる
        with self._lock:
            if self._pos >= len(self._buf):
                self._pos = 0
        self._stream = self._factory(self.audio.sr, self._callback, self._finished)
        self.playing = True
        try:
            self._stream.start()
        except Exception as exc:
            self.playing = False
            self._drop_stream()
            raise PlayerError(str(exc)) from exc

    def pause(self):
        self.playing = False
        self._drop_stream()

    def toggle(self):
        self.pause() if self.playing else self.play()

    def close(self):
        self.pause()

    def _drop_stream(self):
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def _callback(self, outdata, frames):
        with self._lock:
            buf, a = self._buf, self._pos
            b = min(a + frames, len(buf))
            n = b - a
            outdata[:n, 0] = buf[a:b]
            outdata[n:, 0] = 0
            self._pos = b
            if b >= len(buf):
                self.playing = False
                return False          # 末尾まで来た: ストリームを止める
        return True

    def _finished(self):
        # 音声スレッドから呼ばれる。ここでストリームは閉じず、画面側の定期確認（playing が False）に任せる。
        self.playing = False
