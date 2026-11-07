"""Energy-based voice activity detection that segments speech into utterances."""

import numpy as np


class UtteranceDetector:
    """Splits a continuous mono float32 stream into utterance arrays.

    Uses a simple RMS threshold with an adaptive noise floor. This is accurate
    enough for clean dictation; swap for a neural VAD (e.g. Silero) if you need
    robustness in noisy environments.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_seconds: float = 0.7,
        min_speech_seconds: float = 0.4,
        pre_roll_seconds: float = 0.25,
        max_utterance_seconds: float = 20.0,
        frame_ms: int = 30,
    ):
        self.sample_rate = sample_rate
        self.frame_len = max(1, int(sample_rate * frame_ms / 1000))
        self.silence_frames = max(1, int(silence_seconds * 1000 / frame_ms))
        self.min_speech_frames = max(1, int(min_speech_seconds * 1000 / frame_ms))
        self.pre_roll_frames = max(0, int(pre_roll_seconds * 1000 / frame_ms))
        self.max_utterance_frames = max(1, int(max_utterance_seconds * 1000 / frame_ms))

        self._noise_floor = 0.0
        self._tail: list = []
        self._buffer: list = []
        self._in_speech = False
        self._silence_run = 0
        self._speech_frames = 0
        self._total_frames = 0
        self._pending = np.zeros(0, dtype="float32")

    @staticmethod
    def _rms(frame: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(frame))) + 1e-10)

    def _threshold(self) -> float:
        return max(self._noise_floor * 3.0, 0.004)

    def add(self, block: np.ndarray) -> list:
        """Feed an audio block; return any completed utterances as a list.

        Audio blocks from the sound device may be smaller than one VAD frame
        (e.g. 416 samples vs a 480-sample frame), so partial frames are buffered
        and carried over to the next block.
        """
        data = block
        if self._pending.size:
            data = np.concatenate([self._pending, block])

        results = []
        n_frames = len(data) // self.frame_len
        usable = n_frames * self.frame_len
        if usable:
            for frame in data[:usable].reshape(n_frames, self.frame_len):
                if self._process_frame(frame):
                    audio = self._emit()
                    if audio is not None:
                        results.append(audio)
        self._pending = data[usable:].copy()
        return results

    def _process_frame(self, frame: np.ndarray) -> bool:
        """Advance the state machine one frame; True if an utterance just ended."""
        rms = self._rms(frame)
        speech = rms > self._threshold()

        if self.pre_roll_frames:
            self._tail.append(frame)
            if len(self._tail) > self.pre_roll_frames:
                self._tail.pop(0)

        if not self._in_speech:
            if speech:
                self._in_speech = True
                self._speech_frames = 1
                self._total_frames = 1
                self._silence_run = 0
                self._buffer = list(self._tail)
            else:
                self._noise_floor = 0.9 * self._noise_floor + 0.1 * rms
            return False

        self._buffer.append(frame)
        self._total_frames += 1
        if speech:
            self._speech_frames += 1
            self._silence_run = 0
        else:
            self._silence_run += 1

        return self._silence_run >= self.silence_frames or self._total_frames >= self.max_utterance_frames

    def _emit(self) -> np.ndarray | None:
        audio = None
        if self._speech_frames >= self.min_speech_frames:
            audio = np.concatenate(self._buffer)
        self._reset_speech()
        return audio

    def flush(self) -> list:
        """Emit any in-progress utterance (used when stopping)."""
        if not self._in_speech:
            return []
        audio = self._emit()
        return [audio] if audio is not None else []

    def _reset_speech(self) -> None:
        self._in_speech = False
        self._buffer = []
        self._tail = []
        self._speech_frames = 0
        self._total_frames = 0
        self._silence_run = 0
