"""Model catalogue, download, and removal for the installed app.

Large model files are never shipped inside the installer. The app downloads
them on demand from Hugging Face into ``%LOCALAPPDATA%\\RealtimeVoiceTyping``
so the installer stays small and users only pay for the model they need.
"""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .paths import models_dir


@dataclass(frozen=True)
class ModelEntry:
    key: str
    label: str
    repo_id: str
    size_gb: float
    languages: str
    note: str

    @property
    def folder(self) -> Path:
        return models_dir() / self.key

    @property
    def model_file(self) -> Path:
        return self.folder / "model.bin"

    @property
    def size_label(self) -> str:
        if self.size_gb >= 1:
            return f"~{self.size_gb:.1f} GB"
        return f"~{self.size_gb * 1000:.0f} MB"


# Display order matches the old dropdown (most useful first).
MODEL_CATALOG: list[ModelEntry] = [
    ModelEntry(
        key="turbo",
        label="Turbo — Thai+EN (fast)",
        repo_id="mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        size_gb=1.6,
        languages="ไทย + อังกฤษ",
        note="คุ้มสุดสำหรับใช้งานทั่วไป เร็วและแม่นระดับดี",
    ),
    ModelEntry(
        key="large-v3",
        label="Large v3 — Thai+EN (accurate)",
        repo_id="Systran/faster-whisper-large-v3",
        size_gb=3.0,
        languages="ไทย + อังกฤษ",
        note="แม่นยำสูงทั้งไทยและอังกฤษ แต่กิน VRAM/RAM มากขึ้น",
    ),
    ModelEntry(
        key="th-pathumma",
        label="Pathumma — Thai+EN (accurate)",
        repo_id="PogusTheWhisper/Faster-Pathumma-whisper-th-large-v3-ct2",
        size_gb=3.0,
        languages="ไทย + อังกฤษ",
        note="แม่นไทย+อังกฤษที่สุดในชุดนี้ เหมาะกับเครื่องมีการ์ดจอแยก",
    ),
    ModelEntry(
        key="th-distill",
        label="Thai Distill — Thai (fast)",
        repo_id="Vinxscribe/biodatlab-whisper-th-large-v3-faster",
        size_gb=3.0,
        languages="ไทยล้วน",
        note="แม่นภาษาไทยสูง แต่ไม่เหมาะกับประโยคปนภาษาอังกฤษ",
    ),
    ModelEntry(
        key="medium",
        label="Medium — balanced",
        repo_id="Systran/faster-whisper-medium",
        size_gb=1.5,
        languages="ไทย + อังกฤษ",
        note="สมดุลระหว่างความเร็วและความแม่นยำ",
    ),
    ModelEntry(
        key="small",
        label="Small — light",
        repo_id="Systran/faster-whisper-small",
        size_gb=0.5,
        languages="ไทย + อังกฤษ",
        note="เบาสุด เหมาะกับโน้ตบุ๊กหรือเครื่องไม่มีการ์ดจอแยก",
    ),
]

MODEL_BY_KEY: dict[str, ModelEntry] = {entry.key: entry for entry in MODEL_CATALOG}

MODEL_LABELS: dict[str, str] = {entry.label: entry.key for entry in MODEL_CATALOG}
MODEL_LABEL_BY_KEY: dict[str, str] = {entry.key: entry.label for entry in MODEL_CATALOG}

# Files a CTranslate2 Whisper model needs. Keeping the list tight avoids
# pulling README images and other repository extras.
_ALLOWED_PATTERNS = [
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.json",
    "vocabulary.txt",
    "preprocessor_config.json",
    "added_tokens.json",
    "merges.txt",
    "normalizer.json",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "generation_config.json",
]


def get_entry(value: str) -> ModelEntry | None:
    if not value:
        return None
    entry = MODEL_BY_KEY.get(str(value))
    if entry is not None:
        return entry
    name = Path(str(value)).name
    return MODEL_BY_KEY.get(name)


def is_installed(value: str | ModelEntry) -> bool:
    entry = value if isinstance(value, ModelEntry) else get_entry(value)
    if entry is None:
        # A user-supplied local path is usable when it has a model.bin.
        path = Path(str(value))
        return (path / "model.bin").is_file()
    return entry.model_file.is_file()


def resolve_model(value: str) -> str:
    """Return the local model folder when downloaded, else the original value."""
    entry = get_entry(value)
    if entry is not None and entry.model_file.is_file():
        return str(entry.folder)
    if entry is None:
        path = Path(str(value))
        if (path / "model.bin").is_file():
            return str(path)
    return str(value)


def installed_entries() -> list[ModelEntry]:
    return [entry for entry in MODEL_CATALOG if entry.model_file.is_file()]


def folder_size_mb(path: Path) -> float:
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        pass
    return round(total / (1024 * 1024), 1)


def _download_to_tmp(entry: ModelEntry) -> Path:
    """Download into a .part folder so a failed download is never "installed"."""
    tmp = models_dir() / f".{entry.key}.part"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp


def download_entry(
    entry: ModelEntry,
    on_progress: Callable[[float, str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> Path:
    """Download a model and return its final folder.

    ``on_progress`` receives ``(percent, message)``. Percent is an estimate
    based on the published model size because Hugging Face does not expose a
    single aggregate progress callback.
    """
    from huggingface_hub import snapshot_download

    target = entry.folder
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    tmp = _download_to_tmp(entry)
    expected = max(1, int(entry.size_gb * 1024 * 1024 * 1024))

    result: list[Path | None] = [None]
    error: list[BaseException | None] = [None]

    def worker():
        try:
            snapshot_download(
                repo_id=entry.repo_id,
                local_dir=str(tmp),
                allow_patterns=_ALLOWED_PATTERNS,
                max_workers=4,
            )
        except BaseException as exc:  # noqa: BLE001 - reported to the UI
            error[0] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while thread.is_alive():
        if stop_event is not None and stop_event.is_set():
            # The worker cannot be cancelled mid-file; tell the UI we stopped.
            on_progress and on_progress(0.0, "ยกเลิกแล้ว (ไฟล์ที่โหลดมาจะถูกลบ)")
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError("cancelled")
        downloaded = _folder_bytes(tmp)
        percent = min(99.0, downloaded * 100.0 / expected)
        on_progress and on_progress(
            percent,
            f"กำลังดาวน์โหลด {entry.label}: {downloaded / (1024 ** 3):.2f} / "
            f"{entry.size_gb:.1f} GB",
        )
        time.sleep(0.4)

    thread.join()
    if error[0] is not None:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"ดาวน์โหลดไม่สำเร็จ: {error[0]}")

    if not (tmp / "model.bin").is_file():
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("ดาวน์โหลดไม่สำเร็จ: ไม่พบไฟล์ model.bin")

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    tmp.replace(target)
    on_progress and on_progress(100.0, f"ติดตั้ง {entry.label} เรียบร้อย")
    return target


def _folder_bytes(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        pass
    return total


def delete_entry(entry: ModelEntry) -> None:
    shutil.rmtree(entry.folder, ignore_errors=True)
