"""Speech-to-text using faster-whisper with automatic language detection."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .paths import cuda_dir

_DLL_HANDLES: list = []
_DLL_DIRS_ADDED = False


def _app_cuda_dirs() -> list[str]:
    """The optional CUDA runtime pack installed by the app itself."""
    root = cuda_dir()
    if not root.is_dir():
        return []
    dirs = [str(root)]
    bin_dir = root / "bin"
    if bin_dir.is_dir():
        dirs.append(str(bin_dir))
    return dirs


def _nvidia_bin_dirs() -> list[str]:
    """CUDA DLLs installed through pip (used by source/development runs)."""
    import importlib.util

    dirs = _app_cuda_dirs()
    try:
        spec = importlib.util.find_spec("nvidia")
    except Exception:
        return dirs
    if spec is None or not spec.submodule_search_locations:
        return dirs
    root = Path(spec.submodule_search_locations[0])
    dirs.extend(str(d) for d in root.glob("*/bin") if d.is_dir())
    return dirs


def _add_dll_dirs(dirs: list[str]) -> None:
    existing = os.environ.get("PATH", "")
    for d in dirs:
        if d not in existing.split(os.pathsep):
            existing = d + os.pathsep + existing
    os.environ["PATH"] = existing

    for d in dirs:
        try:
            _DLL_HANDLES.append(os.add_dll_directory(d))
        except (OSError, AttributeError):
            pass


def _add_nvidia_dll_dirs() -> None:
    """Make CUDA DLLs discoverable before ctranslate2 loads them.

    ctranslate2 loads cuBLAS/cuDNN lazily, but they are not on the DLL search
    path by default. This covers both the app's own CUDA pack and pip-installed
    ``nvidia-*-cu12`` wheels used during development.
    """
    global _DLL_DIRS_ADDED
    if os.name != "nt" or _DLL_DIRS_ADDED:
        return
    _DLL_DIRS_ADDED = True
    dirs = _nvidia_bin_dirs()
    if dirs:
        _add_dll_dirs(dirs)


def refresh_dll_paths() -> None:
    """Re-scan CUDA DLL folders after the user installs the GPU pack."""
    global _DLL_DIRS_ADDED
    _DLL_DIRS_ADDED = False
    _add_nvidia_dll_dirs()


# Run once at import so the DLLs are on the search path before ctranslate2
# ever tries to load them.
_add_nvidia_dll_dirs()


_CUDA_RUNTIME_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")


def _has_cuda_runtime() -> bool:
    """Check that cuBLAS/cuDNN really exist where this process can load them.

    ``get_supported_compute_types("cuda")`` can succeed from the driver alone,
    so it is not enough to decide whether a model can actually run on GPU.
    """
    for directory in _nvidia_bin_dirs():
        try:
            if all((Path(directory) / name).is_file() for name in _CUDA_RUNTIME_DLLS):
                return True
        except OSError:
            continue
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        try:
            if all((Path(directory) / name).is_file() for name in _CUDA_RUNTIME_DLLS):
                return True
        except OSError:
            continue
    return False


def cuda_available() -> bool:
    if not _has_cuda_runtime():
        return False
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            return False
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
        segments, info = self.model.transcribe(
            np.ascontiguousarray(audio, dtype=np.float32),
            language=self.language,
            vad_filter=False,
            beam_size=5,
            condition_on_previous_text=False,
        )
        text = "".join(segment.text for segment in segments).strip()
        return text, info.language
