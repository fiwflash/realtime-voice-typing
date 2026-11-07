"""Configuration for the real-time voice typing app."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # Model & hardware
    model_size: str = "turbo"        # "turbo", "large-v3", "medium", "small"
    device: str = "auto"             # "auto", "cuda", "cpu"
    compute_type: str = "auto"       # "auto", "float16", "int8", "int8_float16"
    language: str | None = None      # None = auto-detect (recommended); or "th" / "en"

    # Audio capture
    sample_rate: int = 16000

    # Voice activity detection (utterance segmentation)
    silence_seconds: float = 0.7        # pause longer than this ends an utterance
    min_speech_seconds: float = 0.4     # ignore noise bursts shorter than this
    pre_roll_seconds: float = 0.25      # audio kept before speech is detected
    max_utterance_seconds: float = 20.0  # force-cut very long speech

    # Insertion
    insert_method: str = "unicode"      # "unicode" (SendInput) or "clipboard"
    destination_mode: str = "follow_cursor"  # "follow_cursor" or "last_focus"

    # Global hotkey to toggle listening
    hotkey: str = "f8"


# Directory holding locally converted (CTranslate2) models.
MODELS_DIR = Path(__file__).resolve().parents[2] / "models"

def _local_model_choice(folder: str, label: str) -> tuple[str, str] | None:
    """Offer a converted local model only when its folder actually exists."""
    path = MODELS_DIR / folder
    return (label, str(path)) if path.is_dir() else None


# Model choices for the GUI: (display label, value).
# Values are either a faster-whisper size name or a path to a converted model.
MODEL_CHOICES = [
    ("Turbo — Thai+EN (fast)", "turbo"),
    ("Large v3 — Thai+EN (accurate)", "large-v3"),
    ("Medium — balanced", "medium"),
    ("Small — light", "small"),
]

for _choice in (
    _local_model_choice("th-distill", "Thai Distill — Thai (fast)"),
    _local_model_choice("th-pathumma", "Pathumma — Thai+EN (accurate)"),
):
    if _choice is not None:
        MODEL_CHOICES.append(_choice)

# Text destination choices for the GUI: (display label, value).
DESTINATION_CHOICES = [
    ("Follow Cursor (current focus)", "follow_cursor"),
    ("Last focused window", "last_focus"),
]


@dataclass(frozen=True)
class ModelSpecInfo:
    key: str
    label: str
    languages: str
    disk_gb: str
    vram_gb: str
    ram_gb: str
    min_spec: str
    recommended_spec: str
    note: str
    min_vram_gb: float
    cpu_realtime_ok: bool


MODEL_SPECS: list[ModelSpecInfo] = [
    ModelSpecInfo(
        key="small",
        label="Small — light",
        languages="ไทย + อังกฤษ",
        disk_gb="~0.5 GB",
        vram_gb="~0.8–1.2 GB",
        ram_gb="~1.0–1.5 GB",
        min_spec="CPU 4 คอร์, RAM 8 GB (ไม่ต้องมี GPU แยก)",
        recommended_spec="CPU 6 คอร์ หรือ GPU 4 GB VRAM",
        note="เบาสุด เหมาะกับโน้ตบุ๊กหรือเครื่องไม่มีการ์ดจอแยก",
        min_vram_gb=2.0,
        cpu_realtime_ok=True,
    ),
    ModelSpecInfo(
        key="medium",
        label="Medium — balanced",
        languages="ไทย + อังกฤษ",
        disk_gb="~1.5 GB",
        vram_gb="~1.8–2.5 GB",
        ram_gb="~2.0–3.0 GB",
        min_spec="CPU 6 คอร์ หรือ GPU 4 GB VRAM, RAM 8–16 GB",
        recommended_spec="GPU 6 GB VRAM (เช่น RTX 2060/3050), RAM 16 GB",
        note="สมดุลระหว่างความเร็วและความแม่นยำ",
        min_vram_gb=4.0,
        cpu_realtime_ok=True,
    ),
    ModelSpecInfo(
        key="turbo",
        label="Turbo — Thai+EN (fast)",
        languages="ไทย + อังกฤษ",
        disk_gb="~1.6 GB",
        vram_gb="~1.8–2.4 GB",
        ram_gb="~2.0–3.0 GB",
        min_spec="GPU 4 GB VRAM หรือ CPU 6–8 คอร์, RAM 16 GB",
        recommended_spec="GPU 6–8 GB VRAM (RTX 3050/3060/4060), RAM 16 GB",
        note="คุ้มสุดสำหรับใช้งานทั่วไป เปิดคู่โปรแกรมอื่นลื่น",
        min_vram_gb=4.0,
        cpu_realtime_ok=True,
    ),
    ModelSpecInfo(
        key=str(MODELS_DIR / "th-distill"),
        label="Thai Distill — Thai (fast)",
        languages="ไทยล้วน",
        disk_gb="~1.55 GB",
        vram_gb="~1.8–2.4 GB",
        ram_gb="~2.0–3.0 GB",
        min_spec="GPU 4 GB VRAM หรือ CPU 6–8 คอร์, RAM 16 GB",
        recommended_spec="GPU 6–8 GB VRAM, RAM 16 GB",
        note="แม่นภาษาไทยสูงและเบา แต่ไม่เหมาะกับประโยคปนภาษาอังกฤษ",
        min_vram_gb=4.0,
        cpu_realtime_ok=True,
    ),
    ModelSpecInfo(
        key="large-v3",
        label="Large v3 — Thai+EN (accurate)",
        languages="ไทย + อังกฤษ",
        disk_gb="~3.0 GB",
        vram_gb="~3.3–4.2 GB",
        ram_gb="~3.5–5.0 GB",
        min_spec="GPU 6 GB VRAM, RAM 16 GB (ไม่แนะนำบน CPU ล้วน)",
        recommended_spec="GPU 8 GB VRAM+ (RTX 3060/4060), RAM 16 GB",
        note="แม่นยำสูงทั้งไทยและอังกฤษ แต่กิน VRAM มากขึ้น",
        min_vram_gb=6.0,
        cpu_realtime_ok=False,
    ),
    ModelSpecInfo(
        key=str(MODELS_DIR / "th-pathumma"),
        label="Pathumma — Thai+EN (accurate)",
        languages="ไทย + อังกฤษ",
        disk_gb="~2.95 GB",
        vram_gb="~3.3–4.2 GB",
        ram_gb="~3.5–5.0 GB",
        min_spec="GPU 6 GB VRAM, RAM 16 GB (ไม่แนะนำบน CPU ล้วน)",
        recommended_spec="GPU 8 GB VRAM+ (RTX 3060/4060), RAM 16–32 GB",
        note="แม่นไทย+อังกฤษที่สุดในชุดนี้ เหมาะกับเครื่องมีการ์ดจอแยก",
        min_vram_gb=6.0,
        cpu_realtime_ok=False,
    ),
]


def get_model_spec(model_value: str) -> ModelSpecInfo | None:
    norm = str(model_value)
    for spec in MODEL_SPECS:
        if spec.key == norm or Path(spec.key).name == Path(norm).name:
            return spec
    return None
