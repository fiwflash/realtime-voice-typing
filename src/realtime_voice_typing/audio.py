"""Continuous microphone capture using sounddevice."""

import queue

import numpy as np


class AudioCapture:
    """Captures mono float32 audio from the default input device into a queue."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._stream = None
        self._queue: queue.Queue = queue.Queue()

    def _callback(self, indata, frames, time_info, status):
        # indata is (frames, channels); keep only the first channel as contiguous mono.
        self._queue.put(np.ascontiguousarray(indata[:, 0], dtype="float32"))

    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def read(self, timeout: float | None = None) -> np.ndarray | None:
        """Return the next audio block, or None if nothing arrived within the timeout."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
