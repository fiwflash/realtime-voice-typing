"""Entry point for the packaged (PyInstaller) build."""

import os
import sys

# A windowed PyInstaller app has no console: sys.stdout/stderr are None. Some
# libraries (tqdm inside huggingface_hub) write progress bars to stderr, so give
# them a harmless sink instead of crashing.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

if os.environ.get("RVT_SMOKE_TEST"):
    from realtime_voice_typing.smoke import run_smoke

    run_smoke(os.environ["RVT_SMOKE_TEST"])
else:
    from realtime_voice_typing.gui import run_gui

    run_gui()
