"""Tiny JSON state store for window mode, model choice and icon position."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .paths import state_file


def load_state() -> dict:
    try:
        raw = state_file().read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    path: Path = state_file()
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # State is a convenience, never a reason to crash the app.
        pass
