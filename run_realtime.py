import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from realtime_voice_typing.gui import run_gui


if __name__ == "__main__":
    run_gui()
