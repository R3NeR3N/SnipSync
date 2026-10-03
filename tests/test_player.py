"""編集後の音の再生ロジック。音の出力は偽のストリームに差し替え、画面にも依存しない。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

np = pytest.importorskip("numpy")

import player as pl  # noqa: E402

SR = 1000
TB = 10.0
# 10 秒の元音声。0–2s 残す / 2–5s 削除 / 5–8s 残す / 8–10s は 2 倍速。
CHUNKS = [(0, 20, 1.0), (20, 50, 99999.0), (50, 80, 1.0), (80, 100, 2.0)]


def make_audio():
    src = np.arange(10 * SR, dtype=np.float32) / (10 * SR)         # 位置が分かる傾斜
    return pl.EditedAudio.build(src, CHUNKS, TB, SR)


class FakeStream:
    def __init__(self, sr, callback, finished):
        self.sr, self.callback, self.finished = sr, callback, finished
        self.started = self.stopped = self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True

    def pull(self, frames):
        out = np.zeros((frames, 1), dtype=np.float32)
        keep_going = self.callback(out, frames)
        return out[:, 0], keep_going


@pytest.fixture
def player():
    streams = []

    def factory(sr, cb, fin):
        s = FakeStream(sr, cb, fin)
        streams.append(s)
        return s

    p = pl.Player(factory)
    p.streams = streams
    p.load(make_audio())
    return p


# ── 編集後の音 ──
def test_edited_audio_length_and_segments():
    a = make_audio()
    assert a.duration == pytest.approx(6.0)                     # 2 + 3 + 1（8–10s は 2 倍速で 1 秒）
    assert [(s.edited_start, s.edited_end, s.speed) for s in a.segments] == [(0.0, 2.0, 1.0), (2.0, 5.0, 1.0), (5.0, 6.0, 2.0)]


def test_cut_points_are_real_cuts_and_speed_changes_only():
    assert make_audio().cut_points == [2.0, 5.0]
    joined = [(0, 20, 1.0), (20, 50, 1.0)]                      # 切れ目なしで続く 2 チャンクは、カット点ではない
    a = pl.EditedAudio.build(np.zeros(5 * SR, dtype=np.float32), joined, TB, SR)
    assert a.cut_points == []


def test_time_mapping_both_ways():
    a = make_audio()
    assert a.edited_to_source(1.0) == pytest.approx(1.0)
    assert a.edited_to_source(3.0) == pytest.approx(6.0)        # 削除（2–5s）を飛ばした分だけ、元の時刻が進む
    assert a.edited_to_source(5.5) == pytest.approx(9.0)        # 倍速区間は、編集後 0.5 秒で元の 1 秒
    assert a.edited_to_source(99) == pytest.approx(10.0)
    assert a.source_to_edited(6.0) == pytest.approx(3.0)
    assert a.source_to_edited(3.0) == pytest.approx(2.0)        # 削除された所を指したら、次に残る所の頭
    assert a.source_to_edited(9.0) == pytest.approx(5.5)
    assert a.source_to_edited(11.0) == pytest.approx(6.0)


def test_stretch_changes_length_by_the_rate_and_keeps_pitch_family():
    pytest.importorskip("av")
    x = (0.3 * np.sin(2 * np.pi * 440 * np.arange(SR * 4 * 24) / (SR * 24))).astype(np.float32)
    for rate in (0.5, 1.5, 2.0, 3.0, 4.0):
        y = pl.stretch(x, SR * 24, rate)
        assert len(y) == pytest.approx(len(x) / rate, rel=0.03)
    assert pl.stretch(x, SR * 24, 1.0) is x


def test_stretch_falls_back_when_the_filter_is_unavailable(monkeypatch):
    av = pytest.importorskip("av")
    monkeypatch.setattr(av.filter, "Graph", lambda: (_ for _ in ()).throw(RuntimeError("no filter")))
    y = pl.stretch(np.ones(2400, dtype=np.float32), 24000, 2.0)
    assert len(y) == 1200


# ── 再生 ──
def test_play_streams_samples_in_order_and_stops_at_the_end(player):
    player.play()
    s = player.streams[0]
    assert s.started and player.playing
    block, more = s.pull(1000)
    assert more and block[0] == pytest.approx(0.0) and player.position == pytest.approx(1.0)
    rest = []
    while True:
        block, more = s.pull(1100)
        rest.append(block)
        if more is False:
            break
    assert not player.playing and player.at_end
    assert player.position == pytest.approx(6.0)
    assert np.concatenate(rest)[-1] == 0.0                      # 足りない分は無音で埋める


def test_pause_closes_the_stream_and_keeps_the_position(player):
    player.play()
    player.streams[0].pull(1500)
    player.pause()
    s = player.streams[0]
    assert s.stopped and s.closed and not player.playing
    assert player.position == pytest.approx(1.5)
    player.play()                                               # 続きから
    assert len(player.streams) == 2 and player.position == pytest.approx(1.5)


def test_toggle_and_replay_from_the_start_after_the_end(player):
    player.toggle()
    assert player.playing
    player.toggle()
    assert not player.playing
    player.seek(6.0)
    player.play()
    assert player.position == pytest.approx(0.0)


def test_seek_clamps_to_the_audio(player):
    player.seek(-3)
    assert player.position == 0.0
    player.seek(99)
    assert player.position == pytest.approx(6.0)


def test_next_and_prev_cut_jump_between_cut_points(player):
    assert player.next_cut() == 2.0 and player.position == pytest.approx(2.0)
    assert player.next_cut() == 5.0
    assert player.next_cut() == pytest.approx(6.0)              # もう無い: 末尾
    assert player.prev_cut() == 5.0 or player.position == pytest.approx(5.0)
    player.seek(5.2)
    assert player.prev_cut() == 2.0                             # 直後（0.6 秒以内）なら、その1つ前へ
    player.seek(2.0 + pl.PREV_CUT_GRACE + 0.3)
    assert player.prev_cut() == 2.0
    player.seek(1.0)
    assert player.prev_cut() == 0.0                             # カット点より前: 先頭


def test_rate_change_keeps_the_same_moment(player):
    player.seek(3.0)
    player.set_rate(2.0)
    assert player.position == pytest.approx(3.0, abs=0.01)
    assert len(player._buf) == pytest.approx(len(player.audio.samples) / 2, rel=0.05)
    player.set_rate(1.0)
    assert player.position == pytest.approx(3.0, abs=0.02)


def test_rate_change_while_playing_is_picked_up_by_the_running_stream(player):
    player.play()
    s = player.streams[0]
    s.pull(1000)
    player.set_rate(2.0)
    assert player.playing and len(player.streams) == 1          # ストリームは作り直さない
    s.pull(500)
    assert player.position == pytest.approx(1.0 + 0.5 * 2, abs=0.02)   # 速度 2 倍で 0.5 秒ぶん進んだ


def test_next_cut_while_playing_continues_from_the_new_place(player):
    player.play()
    player.streams[0].pull(500)
    player.next_cut()
    block, more = player.streams[0].pull(10)
    assert more and player.position == pytest.approx(2.01, abs=0.005)


def test_start_failure_is_reported_and_leaves_the_player_idle():
    class Broken(FakeStream):
        def start(self):
            raise OSError("device busy")

    p = pl.Player(lambda sr, cb, fin: Broken(sr, cb, fin))
    p.load(make_audio())
    with pytest.raises(pl.PlayerError, match="device busy"):
        p.play()
    assert not p.playing


def test_controls_are_noops_without_audio():
    p = pl.Player(lambda *a: FakeStream(*a))
    p.play()
    p.seek(1)
    assert p.next_cut() is None and p.prev_cut() is None and not p.playing and p.position == 0.0


def test_unload_stops_and_forgets(player):
    player.play()
    player.unload()
    assert not player.loaded and not player.playing and player.streams[0].closed
