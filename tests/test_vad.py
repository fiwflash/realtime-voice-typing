import numpy as np

from realtime_voice_typing.vad import UtteranceDetector


def make_tone(seconds, sr, freq=440.0, amp=0.2):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    return (amp * np.sin(2 * np.pi * freq * t)).astype("float32")


def make_silence(seconds, sr):
    return np.zeros(int(sr * seconds), dtype="float32")


def test_no_utterance_from_silence():
    det = UtteranceDetector(sample_rate=16000)
    assert det.add(make_silence(1.0, 16000)) == []


def test_emits_utterance_after_speech_then_silence():
    det = UtteranceDetector(sample_rate=16000, silence_seconds=0.5)
    det.add(make_silence(0.5, 16000))
    det.add(make_tone(0.8, 16000))
    out = det.add(make_silence(1.0, 16000))
    assert len(out) == 1
    assert len(out[0]) > 0


def test_ignores_short_noise_blip():
    det = UtteranceDetector(sample_rate=16000, min_speech_seconds=0.4, silence_seconds=0.5)
    det.add(make_silence(0.5, 16000))
    det.add(make_tone(0.05, 16000))
    assert det.add(make_silence(1.0, 16000)) == []


def test_flush_returns_in_progress_utterance():
    det = UtteranceDetector(sample_rate=16000)
    det.add(make_silence(0.5, 16000))
    det.add(make_tone(0.8, 16000))
    assert len(det.flush()) == 1


def test_small_blocks_are_buffered():
    # Sound device often delivers blocks smaller than one VAD frame (e.g. 416
    # samples vs a 480-sample frame). Partial frames must be buffered, not dropped.
    det = UtteranceDetector(sample_rate=16000, silence_seconds=0.5)
    det.add(make_silence(0.5, 16000))
    tone = make_tone(0.8, 16000)
    for i in range(0, len(tone), 100):
        det.add(tone[i : i + 100])
    out = det.add(make_silence(1.0, 16000))
    assert len(out) == 1
    assert len(out[0]) > 0
