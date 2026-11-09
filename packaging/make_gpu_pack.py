"""Build the optional CUDA runtime pack from pip-installed NVIDIA wheels.

Usage (from the repository root):

    python packaging/make_gpu_pack.py

Output: release/cuda-runtime-win64.zip plus a small JSON manifest. Upload the
zip as a GitHub Release asset and keep cuda_pack.CUDA_PACK_SHA256 in sync.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
RELEASE_DIR = PROJECT_DIR / "release"
ZIP_NAME = "cuda-runtime-win64.zip"

REQUIRED_DLLS = (
    "cublas64_12.dll",
    "cublasLt64_12.dll",
    "cudnn64_9.dll",
    "cudnn_ops64_9.dll",
    "cudnn_cnn64_9.dll",
    "cudnn_adv64_9.dll",
    "cudnn_engines_precompiled64_9.dll",
    "cudnn_engines_runtime_compiled64_9.dll",
    "cudart64_12.dll",
)


def nvidia_package_dir() -> Path:
    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("ไม่พบแพ็กเกจ nvidia ใน Python นี้")
    return Path(spec.submodule_search_locations[0])


def collect_dlls() -> dict[str, Path]:
    root = nvidia_package_dir()
    found: dict[str, Path] = {}
    for dll in sorted(root.glob("*/bin/*.dll")):
        # Keep the first occurrence; names are unique across the CUDA wheels.
        found.setdefault(dll.name.lower(), dll)
    return found


def main() -> int:
    dlls = collect_dlls()
    missing = [name for name in REQUIRED_DLLS if name.lower() not in dlls]
    if missing:
        print("DLL ไม่ครบ: " + ", ".join(missing), file=sys.stderr)
        print(
            "ติดตั้งก่อน: pip install nvidia-cublas-cu12 nvidia-cudnn-cu12 "
            "nvidia-cuda-nvrtc-cu12 nvidia-cuda-runtime-cu12",
            file=sys.stderr,
        )
        return 1

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = RELEASE_DIR / ZIP_NAME
    total = sum(path.stat().st_size for path in dlls.values())

    print(f"กำลังสร้าง {zip_path.name} จาก {len(dlls)} ไฟล์ ({total / (1024 ** 3):.2f} GB)")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in sorted(dlls.items()):
            archive.write(path, arcname=path.name)

    digest = hashlib.sha256()
    with open(zip_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    digest_hex = digest.hexdigest()
    size = zip_path.stat().st_size
    manifest = {
        "file": ZIP_NAME,
        "sha256": digest_hex,
        "size_bytes": size,
        "uncompressed_bytes": total,
        "files": [path.name for path in sorted(dlls.values(), key=lambda p: p.name.lower())],
    }
    (RELEASE_DIR / "cuda-runtime-win64.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"เสร็จแล้ว: {zip_path} ({size / (1024 ** 3):.2f} GB)")
    print(f"SHA-256: {digest_hex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
