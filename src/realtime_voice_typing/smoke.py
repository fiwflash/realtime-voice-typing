"""Headless-ish self test used to validate frozen builds.

Run the packaged executable with ``RVT_SMOKE_TEST=<path>``; it initialises the
GUI, writes a JSON report, and exits. This is how the installer is verified on
a machine without Python installed.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def run_smoke(output_path: str | Path) -> None:
    from .paths import assets_dir, data_dir, is_frozen, models_dir

    result: dict = {
        "frozen": is_frozen(),
        "executable": sys.executable,
        "assets_dir": str(assets_dir()),
        "data_dir": str(data_dir()),
        "models_dir": str(models_dir()),
    }

    try:
        result["assets"] = sorted(p.name for p in assets_dir().iterdir())
    except OSError as exc:
        result["assets_error"] = str(exc)

    try:
        import tkinter as tk

        from .gui import RealtimeVoiceGui

        root = tk.Tk()
        gui = RealtimeVoiceGui(root)
        root.update()
        result["gui_ok"] = True
        result["icon_renderer"] = type(gui._icon_renderer).__name__
        result["model_choice"] = gui.model_var.get()
        result["device_choice"] = gui.device_var.get()
        gui._on_close()
    except Exception:
        result["gui_ok"] = False
        result["gui_error"] = traceback.format_exc()

    try:
        import ctranslate2
        import faster_whisper

        result["faster_whisper"] = faster_whisper.__version__
        result["ctranslate2"] = ctranslate2.__version__
    except Exception:
        result["import_error"] = traceback.format_exc()

    try:
        from .speech import cuda_available

        result["cuda_available"] = cuda_available()
    except Exception:
        result["cuda_error"] = traceback.format_exc()

    model_key = os.environ.get("RVT_SMOKE_MODEL")
    if model_key:
        try:
            import numpy as np

            from . import model_manager
            from .speech import SpeechEngine

            resolved = model_manager.resolve_model(model_key)
            device = os.environ.get("RVT_SMOKE_DEVICE", "cpu")
            engine = SpeechEngine(model_size=resolved, device=device)
            result["model_info"] = engine.info()
            text, language = engine.transcribe(np.zeros(16000, dtype="float32"), 16000)
            result["model_text"] = text
            result["model_language"] = language
            result["model_loaded"] = True
        except Exception:
            result["model_loaded"] = False
            result["model_error"] = traceback.format_exc()

    try:
        from . import cuda_pack

        result["cuda_pack_installed"] = cuda_pack.is_installed()
    except Exception:
        pass

    try:
        from huggingface_hub import snapshot_download

        files = snapshot_download(
            "Systran/faster-whisper-small",
            allow_patterns=["config.json", "model.bin"],
            dry_run=True,
        )
        result["hf_dry_run_files"] = len(files)
    except Exception:
        result["hf_error"] = traceback.format_exc()

    Path(output_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
