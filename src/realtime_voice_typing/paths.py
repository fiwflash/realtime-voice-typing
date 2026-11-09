"""Locations used by both source runs and installed (frozen) builds.

In source mode everything lives inside the repository so the existing
``models/`` and ``assets/`` folders keep working. In a frozen build the
program files are read-only, so models, the optional CUDA runtime pack and
user settings go to ``%LOCALAPPDATA%\\RealtimeVoiceTyping``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "RealtimeVoiceTyping"
APP_DISPLAY_NAME = "Real-time Voice Typing"
APP_VERSION = "1.0.0"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory that contains the bundled read-only assets."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    return bundle_dir() / "assets"


def data_dir() -> Path:
    """Writable per-user directory."""
    override = os.environ.get("RVT_DATA_DIR")
    if override:
        root = Path(override).expanduser()
    elif is_frozen():
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        root = base / APP_NAME
    else:
        root = Path(__file__).resolve().parents[2]
    root.mkdir(parents=True, exist_ok=True)
    return root


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cuda_dir() -> Path:
    return data_dir() / "cuda"


def state_file() -> Path:
    return data_dir() / "state.json"


def log_file() -> Path:
    return data_dir() / "voice_typing.log"


def downloads_dir() -> Path:
    path = data_dir() / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path
