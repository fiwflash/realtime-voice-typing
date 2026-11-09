# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the onedir Windows build.

One directory (not one-file) keeps launch time fast: a one-file build would
unpack several hundred MB on every start. Inno Setup wraps this folder into a
single normal installer.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

PACKAGING_DIR = Path(SPECPATH)
PROJECT_DIR = PACKAGING_DIR.parent
ASSETS = PROJECT_DIR / "assets"

datas = [(str(ASSETS), "assets")]
datas += collect_data_files("faster_whisper")
datas += collect_data_files("sounddevice")
datas += collect_data_files("onnxruntime")
datas += collect_data_files("huggingface_hub", include_py_files=False)

binaries = []
binaries += collect_dynamic_libs("ctranslate2")
binaries += collect_dynamic_libs("av")
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("tokenizers")

hiddenimports = [
    "faster_whisper",
    "faster_whisper.audio",
    "faster_whisper.feature_extractor",
    "faster_whisper.tokenizer",
    "faster_whisper.transcribe",
    "faster_whisper.utils",
    "faster_whisper.vad",
    "ctranslate2",
    "tokenizers",
    "huggingface_hub",
    "onnxruntime",
    "av",
    "sounddevice",
    "pyperclip",
    "PIL.Image",
    "PIL.ImageTk",
    "numpy",
    "tkinter",
    "tkinter.ttk",
]

# Keep the app small and avoid shipping a second CUDA stack. The optional GPU
# runtime pack is installed separately at runtime.
excludes = [
    "torch",
    "torchaudio",
    "torchvision",
    "transformers",
    "tensorflow",
    "scipy",
    "pandas",
    "matplotlib",
    "IPython",
    "notebook",
    "jupyter",
    "pytest",
    "setuptools",
    "pip",
    "wheel",
    "nvidia",
    "triton",
    "pyarrow",
    "aiohttp",
    "aiohappyeyeballs",
    "cryptography",
    "starlette",
    "fsspec",
    "safetensors",
    "rich",
    "markdown_it",
    "itsdangerous",
    "onnxruntime.tools",
    "onnxruntime.transformers",
]

a = Analysis(
    [str(PROJECT_DIR / "app_entry.py")],
    pathex=[str(PROJECT_DIR / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RealtimeVoiceTyping",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ASSETS / "VoiceTyping.ico"),
    version=str(PACKAGING_DIR / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RealtimeVoiceTyping",
)
