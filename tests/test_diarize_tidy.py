"""話者ラベルの後処理（声の特徴が近い小さなラベルを、大きなラベルへ寄せる）。モデルは使わず、ベクトルを直接渡す。"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from snipsync.core import diarize as dz  # noqa: E402
from snipsync.core import pipeline  # noqa: E402


def unit(*v):
    a = np.asarray(v, dtype=np.float32)
    return a / np.linalg.norm(a)


# A（大）と B（大）の会話に、A の声に近い小ラベル 5、B の声に近い小ラベル 6、誰にも近くない小ラベル 7
TURNS = [(0, 40, 0), (40, 80, 1), (80, 83, 5), (83, 120, 0), (120, 124, 6), (124, 160, 1), (160, 163, 7)]
VECTORS = {0: unit(1, 0, 0), 1: unit(0, 1, 0), 5: unit(0.9, 0.1, 0), 6: unit(0.1, 0.9, 0), 7: unit(0, 0, 1)}


def test_small_labels_move_to_the_closest_big_label_when_the_voice_is_close_enough():
    out = dz.merge_similar_small_labels(TURNS, VECTORS)
    assert [k for _s, _e, k in out] == [0, 1, 0, 0, 1, 1, 7]          # 5 は A へ、6 は B へ。7 は、誰にも近くないのでそのまま
    assert [(s, e) for s, e, _k in out] == [(s, e) for s, e, _k in TURNS]


def test_a_stricter_similarity_leaves_more_labels_alone():
    out = dz.merge_similar_small_labels(TURNS, VECTORS, min_similarity=0.999)
    assert out == TURNS


def test_big_labels_are_never_merged_and_labels_without_a_voice_vector_stay():
    vectors = dict(VECTORS)
    del vectors[5]                                                    # 5 は、使える区間が無く、声の特徴が取れなかった
    out = dz.merge_similar_small_labels(TURNS, vectors)
    assert [k for _s, _e, k in out] == [0, 1, 5, 0, 1, 1, 7]
    assert dz.merge_similar_small_labels([(0, 5, 0), (5, 9, 1)], {0: unit(1, 0), 1: unit(1, 0)}) == [(0, 5, 0), (5, 9, 1)]


def test_nothing_happens_when_there_is_no_big_label():
    small = [(0, 5, 0), (5, 9, 1)]
    assert dz.merge_similar_small_labels(small, {0: unit(1, 0), 1: unit(1, 0.1)}) == small


def test_label_embeddings_skips_short_turns_and_normalises(monkeypatch):
    class FakeStream:
        def __init__(self):
            self.n = 0

        def accept_waveform(self, rate, wav):
            self.n = len(wav)

        def input_finished(self):
            pass

    class FakeExtractor:
        def __init__(self, config):
            pass

        def create_stream(self):
            return FakeStream()

        def is_ready(self, stream):
            return True

        def compute(self, stream):
            return [3.0, 4.0]                                          # 長さ 5 -> 0.6, 0.8 に揃う

    sherpa_onnx = pytest.importorskip("sherpa_onnx")           # CI の最小構成には無い
    monkeypatch.setattr(sherpa_onnx, "SpeakerEmbeddingExtractor", FakeExtractor)
    monkeypatch.setattr(dz, "ensure_models", lambda on_log=None: (Path("seg"), Path("emb")))
    samples = np.zeros(16000 * 30, dtype=np.float32)
    vecs = dz.label_embeddings(samples, [(0.0, 0.5, 0), (1.0, 5.0, 1)])
    assert set(vecs) == {1}                                             # 0.5 秒の区間しかないラベルは、入らない
    assert np.allclose(vecs[1], [0.6, 0.8], atol=1e-5)


def test_the_pipeline_helper_logs_the_count_and_falls_back_on_failure(monkeypatch):
    logs = []
    tr = lambda key, *a: f"{key}:{','.join(str(x) for x in a)}"          # noqa: E731
    monkeypatch.setattr(pipeline, "label_embeddings", lambda samples, turns, on_log=None: VECTORS)
    out = pipeline._tidy_labels(None, TURNS, lambda m, t="": logs.append(m), tr)
    assert len({k for _s, _e, k in out}) == 3 and logs == ["log_speaker_tidy:2"]

    def boom(*a, **k):
        raise RuntimeError("model missing")

    monkeypatch.setattr(pipeline, "label_embeddings", boom)
    logs.clear()
    assert pipeline._tidy_labels(None, TURNS, lambda m, t="": logs.append(m), tr) == TURNS      # 寄せる前の結果で続ける
    assert logs and logs[0].startswith("log_speaker_tidy_fail:")


def test_auto_threshold_is_the_default_and_a_given_number_of_speakers_skips_tidying():
    import inspect
    assert inspect.signature(dz.diarize).parameters["cluster_threshold"].default == dz.AUTO_THRESHOLD
    assert pipeline.PipelineParams.__dataclass_fields__["tidy_speakers"].default is True


@pytest.mark.parametrize("num", ["2", "8", "12", "20"])
def test_people_menu_offers_up_to_twenty(num):
    from snipsync.ui.app import SPEAKER_COUNTS
    assert num in SPEAKER_COUNTS and SPEAKER_COUNTS[0] == "auto" and SPEAKER_COUNTS[-1] == "20"
    assert "21" not in SPEAKER_COUNTS and "1" not in SPEAKER_COUNTS
