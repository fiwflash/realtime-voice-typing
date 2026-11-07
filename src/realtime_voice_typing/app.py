"""Main controller: continuous capture -> VAD segmentation -> transcription -> insertion."""

import queue
import threading
import time

import numpy as np

from .audio import AudioCapture
from .inserter import TextInserter
from .settings import Settings
from .speech import SpeechEngine
from .vad import UtteranceDetector
from .windows_target import TargetTracker


def _clean(text: str) -> str:
    return " ".join(text.split())


class RealtimeVoiceApp:
    def __init__(
        self,
        settings: Settings | None = None,
        on_status=None,
        on_transcript=None,
        on_level=None,
    ):
        self.settings = settings or Settings()
        self.on_status = on_status
        self.on_transcript = on_transcript
        self.on_level = on_level

        self.speech = SpeechEngine(
            model_size=self.settings.model_size,
            device=self.settings.device,
            compute_type=self.settings.compute_type,
            language=self.settings.language,
        )
        self.inserter = TextInserter(method=self.settings.insert_method)
        self.target_tracker = TargetTracker()
        # Mutable copy so the GUI can switch destination without rebuilding the app.
        self.destination_mode = self.settings.destination_mode

        self._listening = False
        self._mic_ready = False
        self._stop_event = threading.Event()
        self._thread = None
        self._transcript: list = []
        self._level_ema = 0.0

    @property
    def is_listening(self) -> bool:
        return self._listening

    @property
    def is_mic_ready(self) -> bool:
        return self._mic_ready

    def toggle(self) -> None:
        if self._listening:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self._listening:
            return
        self._listening = True
        self._mic_ready = False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._listening = False
        self._stop_event.set()

    def clear_transcript(self) -> None:
        self._transcript = []
        self._emit_transcript()

    # -- internals ---------------------------------------------------------

    def _run(self) -> None:
        capture = AudioCapture(self.settings.sample_rate)
        detector = UtteranceDetector(
            sample_rate=self.settings.sample_rate,
            silence_seconds=self.settings.silence_seconds,
            min_speech_seconds=self.settings.min_speech_seconds,
            pre_roll_seconds=self.settings.pre_roll_seconds,
            max_utterance_seconds=self.settings.max_utterance_seconds,
        )
        utterances: queue.Queue = queue.Queue()
        transcriber = threading.Thread(
            target=self._transcribe_loop, args=(utterances,), daemon=True
        )
        transcriber.start()

        try:
            self._status("Loading model... (first run downloads)")
            self.speech.model  # force load up front so the first utterance is not delayed
            capture.start()
            self._mic_ready = True
            self._status(f"Listening ({self.speech.info()})")
            while not self._stop_event.is_set():
                block = capture.read(timeout=0.2)
                if block is None:
                    continue
                rms = float(np.sqrt(np.mean(np.square(block))) + 1e-10)
                self._level_ema = 0.8 * self._level_ema + 0.2 * rms
                self._level(self._level_ema)
                for utterance in detector.add(block):
                    utterances.put(utterance)
        except Exception as exc:
            self._mic_ready = False
            self._listening = False
            self._status(f"Microphone error: {exc}")
        finally:
            capture.stop()
            self._mic_ready = False
            self._listening = False
            for utterance in detector.flush():
                utterances.put(utterance)
            utterances.put(None)  # sentinel to stop the transcriber
            transcriber.join(timeout=60)
            if self._stop_event.is_set():
                self._status("Stopped.")

    def _transcribe_loop(self, utterances: queue.Queue) -> None:
        while True:
            item = utterances.get()
            if item is None:
                break
            try:
                text, lang = self.speech.transcribe(item, self.settings.sample_rate)
            except Exception as exc:
                self._status(f"Transcribe error: {exc}")
                continue
            text = _clean(text)
            if not text:
                continue
            self._transcript.append(text)
            self._emit_transcript()
            self._status(f"[{lang.upper()}] {text}")
            try:
                target = self.target_tracker.resolve_target(self.destination_mode)
                if target:
                    self.target_tracker.focus_for_insert(target)
                    time.sleep(0.15)
                self.inserter.type_text(text + " ")
            except Exception as exc:
                self._status(f"Insert error: {exc}")

    def _status(self, message: str) -> None:
        if self.on_status:
            self.on_status(message)

    def _level(self, rms: float) -> None:
        if self.on_level:
            self.on_level(rms)

    def _emit_transcript(self) -> None:
        if self.on_transcript:
            self.on_transcript("\n".join(self._transcript))
