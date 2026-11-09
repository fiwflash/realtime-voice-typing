"""Optional CUDA runtime pack for NVIDIA GPUs.

The base installer is CPU-capable so it works on every Windows machine. Users
with an NVIDIA card can install a separate CUDA runtime pack (cuBLAS, cuDNN,
NVRTC and cudart) from inside the app. It is stored under
``%LOCALAPPDATA%\\RealtimeVoiceTyping\\cuda`` and loaded dynamically, so it
never conflicts with a system CUDA installation.
"""

from __future__ import annotations

import hashlib
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .paths import cuda_dir, downloads_dir

# Published as a GitHub Release asset. Keep in sync with packaging/make_gpu_pack.ps1.
CUDA_PACK_VERSION = "12.4"
CUDA_PACK_FILENAME = "cuda-runtime-win64.zip"
CUDA_PACK_URL = (
    "https://github.com/fiwflash/realtime-voice-typing/releases/download/"
    f"v1.0.0/{CUDA_PACK_FILENAME}"
)
# Filled in when the pack is built; empty means "size check only".
CUDA_PACK_SHA256 = "116a6b88debf5ff3757028da9b6d8c1eedb5409f9ac74cc04ff4f31ff62168ca"

_REQUIRED_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")
_HEADERS = {"User-Agent": "RealtimeVoiceTyping/1.0"}


def is_installed() -> bool:
    root = cuda_dir()
    return all((root / name).is_file() for name in _REQUIRED_DLLS)


def installed_size_mb() -> float:
    root = cuda_dir()
    if not root.is_dir():
        return 0.0
    total = 0
    for item in root.glob("*.dll"):
        try:
            total += item.stat().st_size
        except OSError:
            pass
    return round(total / (1024 * 1024), 1)


def status_text() -> str:
    if is_installed():
        return f"ติดตั้งแล้ว ({installed_size_mb():,.0f} MB)"
    return "ยังไม่ได้ติดตั้ง"


def remove_pack() -> None:
    shutil.rmtree(cuda_dir(), ignore_errors=True)


def download_pack(
    on_progress: Callable[[float, str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> Path:
    target = downloads_dir() / CUDA_PACK_FILENAME
    part = target.with_suffix(".part")

    request = urllib.request.Request(CUDA_PACK_URL, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with open(part, "wb") as handle:
            while True:
                if stop_event is not None and stop_event.is_set():
                    handle.close()
                    part.unlink(missing_ok=True)
                    raise RuntimeError("cancelled")
                chunk = response.read(1024 * 512)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if total:
                    percent = min(99.0, done * 100.0 / total)
                    message = (
                        f"กำลังดาวน์โหลด CUDA Runtime: "
                        f"{done / (1024 ** 3):.2f} / {total / (1024 ** 3):.2f} GB"
                    )
                else:
                    percent = 50.0
                    message = f"กำลังดาวน์โหลด CUDA Runtime: {done / (1024 ** 3):.2f} GB"
                on_progress and on_progress(percent, message)

    part.replace(target)
    return target


def install_from_zip(
    zip_path: Path,
    on_progress: Callable[[float, str], None] | None = None,
) -> None:
    """Extract every DLL from the pack into the flat cuda folder."""
    root = cuda_dir()
    root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        members = [m for m in archive.infolist() if m.filename.lower().endswith(".dll")]
        if not members:
            raise RuntimeError("ไฟล์แพ็ก CUDA ไม่มี DLL อยู่ข้างใน")
        for index, member in enumerate(members, start=1):
            name = Path(member.filename).name
            if not name:
                continue
            destination = root / name
            tmp = root / f".{name}.part"
            with archive.open(member) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            tmp.replace(destination)
            if on_progress is not None:
                on_progress(
                    index * 100.0 / len(members),
                    f"กำลังแตกไฟล์ {name} ({index}/{len(members)})",
                )

    if not is_installed():
        raise RuntimeError("ติดตั้ง CUDA Runtime ไม่ครบ: ไม่พบ cublas/cuDNN")
    on_progress and on_progress(100.0, "ติดตั้ง CUDA Runtime เรียบร้อย")


def install_from_file(
    zip_path: Path,
    on_progress: Callable[[float, str], None] | None = None,
) -> None:
    if CUDA_PACK_SHA256:
        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        if digest.lower() != CUDA_PACK_SHA256.lower():
            raise RuntimeError("ไฟล์แพ็ก CUDA ไม่ถูกต้อง (SHA-256 ไม่ตรง)")
    install_from_zip(zip_path, on_progress=on_progress)
