"""Real-time voice typing package."""

import os

# huggingface_hub's cache relies on symlinks, which fail on Windows unless
# Developer Mode is enabled or Python runs as administrator. Without them, model
# downloads via snapshot_download can crash with "'NoneType' object has no
# attribute 'write'". Force the no-symlink cache mode and disable the xet shared
# blob store (also symlink-based) so files are copied directly instead.
#
# These variables are read at huggingface_hub import time, so they must be set
# here — the first module imported — before any huggingface_hub import anywhere
# in the app (faster_whisper / model_manager / etc.).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SHARED_BLOBS", "1")
