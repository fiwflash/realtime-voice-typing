"""Speech-to-text using faster-whisper with automatic language detection."""

import os
import tempfile
from pathlib import Path

import numpy as np

_DLL_HANDLES: list = []
_DLL_DIRS_ADDED = False


def _nvidia_bin_dirs() -> list:
    import importlib.util

    try:
        spec = importlib.util.find_spec("nvidia")
    except Exception:
        return []
    if spec is None or not spec.submodule_search_locations:
        return []
    root = Path(spec.submodule_search_locations[0])
    return [str(d) for d in root.glob("*/bin") if d.is_dir()]


def _add_nvidia_dll_dirs() -> None:
    """Make CUDA DLLs installed via pip (nvidia-*-cu12 wheels) discoverable.

    ctranslate2 loads cublas/cudnn DLLs lazily, but pip installs them under
    ``site-packages/nvidia/*/bin`` which is not on the DLL search path. We add
    those directories to both the process PATH and the DLL search directories
    so GPU execution works without the user editing PATH by hand.
    """
    global _DLL_DIRS_ADDED
    if os.name != "nt" or _DLL_DIRS_ADDED:
        return
    _DLL_DIRS_ADDED = True

    dirs = _nvidia_bin_dirs()
    if not dirs:
        return

    existing = os.environ.get("PATH", "")
    for d in dirs:
        if d not in existing:
            existing = d + os.pathsep + existing
    os.environ["PATH"] = existing

    for d in dirs:
        try:
            _DLL_HANDLES.append(os.add_dll_directory(d))
        except OSError:
            pass


# Run once at import so the DLLs are on the search path before ctranslate2
# ever tries to load them.
_add_nvidia_dll_dirs()


def cuda_available() -> bool:
    try:
        import ctranslate2

        ctranslate2.get_supported_compute_types("cuda")
        return True
    except Exception:
        return False


class SpeechEngine:
    """Lazy-loading faster-whisper model with CPU/GPU auto-detection.

    `language=None` lets Whisper detect the spoken language from the audio
    itself, which is more accurate than trusting the OS language setting.
    """

    def __init__(
        self,
        model_size: str = "turbo",
        device: str = "auto",
        compute_type: str = "auto",
        language: str | None = None,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None
        self._resolved_device = None
        self._resolved_compute_type = None

    def _resolve(self) -> None:
        if self._resolved_device is not None:
            return

        _add_nvidia_dll_dirs()

        if self.device == "auto":
            self._resolved_device = "cuda" if cuda_available() else "cpu"
        else:
            self._resolved_device = self.device

        if self.compute_type == "auto":
            self._resolved_compute_type = (
                "float16" if self._resolved_device == "cuda" else "int8"
            )
        else:
            self._resolved_compute_type = self.compute_type

    @property
    def model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._resolve()
            self._model = WhisperModel(
                self.model_size,
                device=self._resolved_device,
                compute_type=self._resolved_compute_type,
            )
        return self._model

    def info(self) -> str:
        self._resolve()
        name = Path(self.model_size).name if Path(self.model_size).exists() else self.model_size
        return f"model={name}, device={self._resolved_device}, compute={self._resolved_compute_type}"

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> tuple[str, str]:
        """Return (text, language_code) for a mono float32 utterance."""
        import soundfile as sf

        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            sf.write(path, audio.astype("float32"), sample_rate)
            segments, info = self.model.transcribe(
                path,
                language=self.language,
                vad_filter=False,
                beam_size=5,
                condition_on_previous_text=False,
            )
            text = "".join(segment.text for segment in segments).strip()
            return text, info.language
        finally:
            os.unlink(path)
