"""Tkinter GUI for the real-time voice typing app.

Two modes:
- Full window: transcript, settings, mic level bar.
- Floating round icon: draggable, click to start/stop, right-click for a menu.
"""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

from . import cuda_pack, model_manager
from .app import RealtimeVoiceApp
from .hotkey import GlobalHotkey
from .model_manager import MODEL_LABEL_BY_KEY
from .paths import assets_dir, is_frozen
from .settings import (
    DESTINATION_CHOICES,
    DEVICE_CHOICES,
    MODEL_CHOICES,
    MODEL_SPECS,
    Settings,
    get_model_spec,
)
from .speech import cuda_available, refresh_dll_paths
from .store import load_state, save_state


ICON_SIZE = 72
ASSETS_DIR = assets_dir()

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
BI_RGB = 0
DIB_RGB_COLORS = 0


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


class _LayeredAlphaIconRenderer:
    """Renders RGBA PNG assets onto a borderless Toplevel with Win32 per-pixel alpha."""

    def __init__(self, idle_path: Path, listening_path: Path, base_size: int = ICON_SIZE):
        self.idle_path = idle_path
        self.listening_path = listening_path
        self.base_size = base_size
        self._cache: dict[tuple[bool, int], np.ndarray] = {}
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32

    def hwnd_for(self, widget: tk.Misc) -> int:
        wid = int(widget.winfo_id())
        parent = int(self.user32.GetParent(wid))
        return parent or wid

    def pixel_size_for(self, widget: tk.Misc) -> int:
        try:
            dpi = float(widget.winfo_fpixels("1i"))
            scale = max(1.0, dpi / 96.0)
        except Exception:
            scale = 1.0
        return max(48, int(round(self.base_size * scale)))

    def _premultiplied_bgra(self, active: bool, size: int) -> np.ndarray:
        key = (bool(active), int(size))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        from PIL import Image

        path = self.listening_path if active else self.idle_path
        im = Image.open(path).convert("RGBA")
        if im.size != (size, size):
            im = im.resize((size, size), Image.Resampling.LANCZOS)
        rgba = np.asarray(im, dtype=np.uint8)
        alpha = rgba[:, :, 3].astype(np.uint16)

        bgra = np.empty_like(rgba)
        bgra[:, :, 0] = (rgba[:, :, 2].astype(np.uint16) * alpha + 127) // 255
        bgra[:, :, 1] = (rgba[:, :, 1].astype(np.uint16) * alpha + 127) // 255
        bgra[:, :, 2] = (rgba[:, :, 0].astype(np.uint16) * alpha + 127) // 255
        bgra[:, :, 3] = rgba[:, :, 3]
        bgra = np.ascontiguousarray(bgra, dtype=np.uint8)
        self._cache[key] = bgra
        return bgra

    def render(self, window: tk.Toplevel, active: bool, x: int, y: int) -> bool:
        window.update_idletasks()
        hwnd = self.hwnd_for(window)
        if not hwnd:
            return False

        size = self.pixel_size_for(window)
        bgra = self._premultiplied_bgra(active, size)

        style = int(self.user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
        if not (style & WS_EX_LAYERED):
            self.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)

        hdc_screen = self.user32.GetDC(0)
        hdc_mem = self.gdi32.CreateCompatibleDC(hdc_screen)
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = size
        bmi.bmiHeader.biHeight = -size  # top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        bits = ctypes.c_void_p()
        hbmp = self.gdi32.CreateDIBSection(
            hdc_screen,
            ctypes.byref(bmi),
            DIB_RGB_COLORS,
            ctypes.byref(bits),
            None,
            0,
        )
        if not hbmp:
            self.gdi32.DeleteDC(hdc_mem)
            self.user32.ReleaseDC(0, hdc_screen)
            return False

        old = self.gdi32.SelectObject(hdc_mem, hbmp)
        try:
            ctypes.memmove(bits, bgra.ctypes.data, bgra.nbytes)
            pt_dst = _POINT(int(x), int(y))
            sz = _SIZE(int(size), int(size))
            pt_src = _POINT(0, 0)
            blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            ok = bool(
                self.user32.UpdateLayeredWindow(
                    hwnd,
                    hdc_screen,
                    ctypes.byref(pt_dst),
                    ctypes.byref(sz),
                    hdc_mem,
                    ctypes.byref(pt_src),
                    0,
                    ctypes.byref(blend),
                    ULW_ALPHA,
                )
            )
            return ok
        finally:
            self.gdi32.SelectObject(hdc_mem, old)
            self.gdi32.DeleteObject(hbmp)
            self.gdi32.DeleteDC(hdc_mem)
            self.user32.ReleaseDC(0, hdc_screen)


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _detect_machine_profile() -> dict:
    ram_gb = None
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            ram_gb = round(stat.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        ram_gb = None

    gpu_name = None
    vram_gb = None
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            text=True,
            timeout=2.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()
        if out:
            first = out.splitlines()[0]
            parts = [p.strip() for p in first.split(",")]
            if len(parts) >= 2:
                gpu_name = parts[0]
                vram_gb = round(float(parts[1]) / 1024.0, 1)
    except Exception:
        pass

    return {
        "cpu_cores": os.cpu_count() or 4,
        "ram_gb": ram_gb,
        "cuda_ready": cuda_available(),
        "gpu_name": gpu_name,
        "vram_gb": vram_gb,
    }


def evaluate_model_fit(model_value: str, machine: dict) -> tuple[str, str]:
    """Return (summary_text, status_color) for the selected model."""
    spec = get_model_spec(model_value)
    if spec is None:
        return ("ไม่พบข้อมูลสเปคของโมเดลนี้", "#555555")

    cuda_ok = bool(machine.get("cuda_ready"))
    vram_gb = machine.get("vram_gb")
    gpu_name = machine.get("gpu_name") or "NVIDIA GPU"
    base = (
        f"ใช้ทรัพยากร: VRAM {spec.vram_gb} (GPU) / RAM {spec.ram_gb} (CPU) | "
        f"แนะนำ: {spec.recommended_spec}"
    )

    if cuda_ok:
        if vram_gb is not None and vram_gb < spec.min_vram_gb:
            advice = (
                f"คำเตือน: {gpu_name} ({vram_gb} GB) มี VRAM น้อยกว่าที่แนะนำ "
                f"({spec.min_vram_gb:.0f} GB+) อาจตึงเมื่อเปิดคู่โปรแกรมอื่น แนะนำ Turbo หรือ Small"
            )
            return (f"{base}\n{advice}", "#b45309")
        gpu_desc = f"{gpu_name} ({vram_gb} GB)" if vram_gb is not None else gpu_name
        advice = f"เครื่องนี้พร้อม ({gpu_desc}) — {spec.note}"
        return (f"{base}\n{advice}", "#15803d")

    if not spec.cpu_realtime_ok:
        advice = (
            "คำเตือน: ตอนนี้ทำงานโหมด CPU ล้วน โมเดลนี้ใหญ่เกินไปและอาจพิมพ์ดีเลย์มาก "
            "แนะนำเปลี่ยนเป็น Small หรือ Turbo"
        )
        return (f"{base}\n{advice}", "#b45309")

    advice = f"โหมด CPU ล้วน: ใช้งานได้ ({spec.note})"
    return (f"{base}\n{advice}", "#1d4ed8")


class RealtimeVoiceGui:
    def __init__(self, root):
        self.root = root
        self.root.title("Real-time Voice Typing")
        self.root.geometry("720x700")
        self.root.minsize(640, 560)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self.root.iconbitmap(str(ASSETS_DIR / "VoiceTyping.ico"))
        except tk.TclError:
            pass

        self._state = load_state()
        self._mode = "full"
        self._press = None
        self._win_pos = (0, 0)
        self._dragged = False
        self._icon_active_state = None
        self._icon_pos = None
        self._spec_win = None
        self._spec_check_button = None
        self._manager_win = None
        self._manager_tree = None
        self._manager_status_var = None
        self._manager_progress = None
        self._manager_busy = False
        self._hotkey = None
        self._hotkey_poll = None
        # Hardware probing is intentionally on-demand. Importing ctranslate2 and
        # initialising CUDA can take ~8 seconds on the first call, which used to
        # delay every app launch. The user triggers it with a button instead.
        self._machine_profile = None
        self._machine_check_running = False
        self._machine_summary_var = tk.StringVar(
            value="เครื่องที่ตรวจพบ: ยังไม่ได้ตรวจสอบ — กดปุ่ม “ตรวจสเปคเครื่อง”"
        )

        self.status_var = tk.StringVar(value="Ready")
        self._model_map = {label: value for label, value in MODEL_CHOICES}
        self.model_var = tk.StringVar(value=self._initial_model_label())
        self.model_var.trace_add("write", self._on_model_selection_change)
        self.model_hint_var = tk.StringVar(value="")

        self._dest_map = {label: value for label, value in DESTINATION_CHOICES}
        saved_dest = self._state.get("destination", "follow_cursor")
        dest_default = next(
            (label for label, value in DESTINATION_CHOICES if value == saved_dest),
            DESTINATION_CHOICES[0][0],
        )
        self.destination_var = tk.StringVar(value=dest_default)
        self.destination_var.trace_add("write", self._on_destination_change)

        self._device_map = {label: value for label, value in DEVICE_CHOICES}
        saved_device = self._state.get("device", "auto")
        self.device_var = tk.StringVar(
            value=next(
                (label for label, value in DEVICE_CHOICES if value == saved_device),
                DEVICE_CHOICES[0][0],
            )
        )

        self.app = None
        self._build_app()
        self._build_full()
        self._create_icon()
        self._restore_mode()
        self._register_hotkey()
        self._poll_target()
        self.root.bind_all("<Button-3>", self._on_right_click)

        if (
            is_frozen()
            and not os.environ.get("RVT_SMOKE_TEST")
            and not model_manager.installed_entries()
        ):
            self.root.after(500, self._first_run_setup)

    # -- persisted state -----------------------------------------------------

    def _initial_model_label(self) -> str:
        saved = self._state.get("model")
        entry = model_manager.get_entry(str(saved)) if saved else None
        if entry is not None and (not is_frozen() or model_manager.is_installed(entry)):
            label = MODEL_LABEL_BY_KEY.get(entry.key)
            if label:
                return label
        installed = model_manager.installed_entries()
        if installed:
            preferred = next((e for e in installed if e.key == "turbo"), installed[0])
            label = MODEL_LABEL_BY_KEY.get(preferred.key)
            if label:
                return label
        return MODEL_LABEL_BY_KEY["turbo"]

    def _save_state(self) -> None:
        if self.app is None:
            return
        try:
            self._state.update(
                {
                    "model": self._model_map[self.model_var.get()],
                    "destination": self._dest_map[self.destination_var.get()],
                    "device": self._device_map[self.device_var.get()],
                    "mode": self._mode,
                }
            )
            if self._icon_pos is not None:
                self._state["icon_pos"] = [int(self._icon_pos[0]), int(self._icon_pos[1])]
            save_state(self._state)
        except (KeyError, tk.TclError):
            pass

    def _restore_mode(self) -> None:
        pos = self._state.get("icon_pos")
        if isinstance(pos, list) and len(pos) == 2:
            try:
                self._icon_pos = (int(pos[0]), int(pos[1]))
                size = self._icon_renderer.pixel_size_for(self.icon_win)
                self.icon_win.geometry(f"{size}x{size}+{self._icon_pos[0]}+{self._icon_pos[1]}")
            except (TypeError, ValueError, tk.TclError):
                pass
        if self._state.get("mode") == "icon":
            self._switch_to_icon()

    def _first_run_setup(self) -> None:
        if model_manager.installed_entries():
            return
        self.set_status("ยังไม่มีโมเดลในเครื่อง — เลือกและดาวน์โหลดโมเดลก่อนเริ่มใช้งาน")
        self._open_model_manager(select="turbo")

    # -- app ----------------------------------------------------------------

    def _build_app(self):
        model_key = self._model_map[self.model_var.get()]
        self.app = RealtimeVoiceApp(
            settings=Settings(
                model_size=model_manager.resolve_model(model_key),
                device=self._device_map[self.device_var.get()],
                destination_mode=self._dest_map[self.destination_var.get()],
            ),
            on_status=self.set_status,
            on_transcript=self.set_transcript,
            on_level=self.set_level,
        )

    # -- full window ---------------------------------------------------------

    def _build_full(self):
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Real-time Voice Typing", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Thai + English (auto-detect)", foreground="#555").pack(anchor="w")
        ttk.Label(frame, textvariable=self.status_var, wraplength=600).pack(anchor="w", pady=(6, 4))

        level_frame = ttk.Frame(frame)
        level_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(level_frame, text="Mic").pack(side="left")
        self.level_bar = ttk.Progressbar(level_frame, maximum=100)
        self.level_bar.pack(side="left", fill="x", expand=True, padx=(6, 0))

        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        self.toggle_button = ttk.Button(controls, text="Start Listening", command=self.toggle)
        self.toggle_button.pack(side="left", fill="x", expand=True)
        ttk.Button(controls, text="Icon mode", command=self._switch_to_icon).pack(side="left", padx=(8, 0))

        settings = ttk.LabelFrame(frame, text="Settings", padding=8)
        settings.pack(fill="x", pady=10)
        ttk.Label(settings, text="Model").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            settings,
            textvariable=self.model_var,
            values=[label for label, _ in MODEL_CHOICES],
            state="readonly",
        ).grid(row=0, column=1, sticky="ew")
        ttk.Button(settings, text="Apply", command=self._apply_settings).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(settings, text="จัดการโมเดล", command=self._open_model_manager).grid(
            row=0, column=3, padx=(6, 0)
        )

        self.model_hint_label = tk.Label(
            settings,
            textvariable=self.model_hint_var,
            justify="left",
            anchor="w",
            wraplength=640,
            font=("Segoe UI", 9),
        )
        self.model_hint_label.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(5, 2))
        self._update_model_hint()

        ttk.Label(settings, text="ประมวลผล").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            settings,
            textvariable=self.device_var,
            values=[label for label, _ in DEVICE_CHOICES],
            state="readonly",
        ).grid(row=2, column=1, columnspan=3, sticky="ew", pady=(6, 0))

        ttk.Label(settings, text="Destination").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            settings,
            textvariable=self.destination_var,
            values=[label for label, _ in DESTINATION_CHOICES],
            state="readonly",
        ).grid(row=3, column=1, columnspan=3, sticky="ew", pady=(6, 0))
        settings.columnconfigure(1, weight=1)

        self.check_button = ttk.Button(
            settings, text="ตรวจสเปคเครื่อง", command=self._start_machine_check
        )
        self.check_button.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(settings, text="สเปคแต่ละโมเดล", command=self._show_model_specs).grid(
            row=4, column=2, columnspan=2, sticky="e", pady=(8, 0)
        )

        ttk.Label(frame, text="Transcript").pack(anchor="w")
        self.transcript = tk.Text(frame, height=10, wrap="word", state="disabled")
        self.transcript.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Press F8, click Start, or use the floating icon. Right-click anywhere → Icon mode.",
            foreground="#555",
            wraplength=640,
        ).pack(anchor="w", pady=(8, 0))

    # -- icon window ---------------------------------------------------------

    def _create_icon(self):
        self.icon_win = tk.Toplevel(self.root)
        self.icon_win.overrideredirect(True)
        self.icon_win.attributes("-topmost", True)
        self._icon_renderer = _LayeredAlphaIconRenderer(
            idle_path=ASSETS_DIR / "voice_icon_idle.png",
            listening_path=ASSETS_DIR / "voice_icon_listening.png",
            base_size=ICON_SIZE,
        )
        size = self._icon_renderer.pixel_size_for(self.icon_win)
        screen_w = self.root.winfo_screenwidth()
        self._icon_pos = (screen_w - size - 40, 60)
        self.icon_win.geometry(f"{size}x{size}+{self._icon_pos[0]}+{self._icon_pos[1]}")
        self.icon_win.withdraw()  # start hidden (full mode is default)

        self.icon_canvas = tk.Canvas(
            self.icon_win, width=size, height=size,
            bg="#000000", highlightthickness=0,
        )
        self.icon_canvas.pack(fill="both", expand=True)
        self.icon_canvas.bind("<ButtonPress-1>", self._icon_press)
        self.icon_canvas.bind("<B1-Motion>", self._icon_motion)
        self.icon_canvas.bind("<ButtonRelease-1>", self._icon_release)

        self._full_menu = tk.Menu(self.root, tearoff=0)
        self._full_menu.add_command(label="Icon mode", command=self._switch_to_icon)
        self._full_menu.add_separator()
        self._full_menu.add_command(label="Exit", command=self._on_close)

        self._icon_menu = tk.Menu(self.icon_win, tearoff=0)
        self._icon_menu.add_command(label="Full mode", command=self._switch_to_full)
        self._icon_menu.add_separator()
        self._icon_menu.add_command(label="Exit", command=self._on_close)
        self._draw_icon()

    def _draw_icon(self) -> None:
        active = bool(self.app and self.app.is_listening and self.app.is_mic_ready)
        self._icon_active_state = active
        if self._icon_pos is None:
            self._icon_pos = (self.icon_win.winfo_x(), self.icon_win.winfo_y())
        x, y = self._icon_pos
        self._icon_renderer.render(self.icon_win, active, x, y)

    def _icon_press(self, event):
        self._press = (event.x_root, event.y_root)
        self._win_pos = self._icon_pos or (self.icon_win.winfo_x(), self.icon_win.winfo_y())
        self._dragged = False

    def _icon_motion(self, event):
        if self._press is None:
            return
        dx = event.x_root - self._press[0]
        dy = event.y_root - self._press[1]
        if abs(dx) > 3 or abs(dy) > 3:
            self._dragged = True
        if self._dragged:
            x = self._win_pos[0] + dx
            y = self._win_pos[1] + dy
            self._icon_pos = (x, y)
            size = self._icon_renderer.pixel_size_for(self.icon_win)
            self.icon_win.geometry(f"{size}x{size}+{x}+{y}")
            self._draw_icon()

    def _icon_release(self, event):
        if not self._dragged:
            self.toggle()
        else:
            self._save_state()
        self._press = None

    def _on_right_click(self, event):
        if self._mode == "icon":
            self._icon_menu.tk_popup(event.x_root, event.y_root)
        else:
            self._full_menu.tk_popup(event.x_root, event.y_root)

    def _switch_to_icon(self):
        self._mode = "icon"
        self.root.withdraw()
        self.icon_win.deiconify()
        self._draw_icon()
        self._save_state()

    def _switch_to_full(self):
        self._mode = "full"
        self.icon_win.withdraw()
        self.root.deiconify()
        self._save_state()

    # -- controls ------------------------------------------------------------

    def toggle(self):
        if self.app.is_listening:
            self.app.stop()
            self.toggle_button.configure(text="Start Listening")
        else:
            if not self._ensure_model_ready():
                return
            self.app.start()
            self.toggle_button.configure(text="Stop Listening")
        self._draw_icon()

    def clear(self):
        self.app.clear_transcript()

    def _apply_settings(self):
        if not self._ensure_model_ready():
            return
        was_listening = self.app.is_listening
        last_hwnd = self.app.target_tracker.last_external_hwnd if self.app else None
        if was_listening:
            self.app.stop()
        self._build_app()
        if last_hwnd:
            self.app.target_tracker.last_external_hwnd = last_hwnd
        if was_listening:
            self.app.start()
        self._update_model_hint()
        self._save_state()
        self._draw_icon()

    # -- model / runtime manager -------------------------------------------

    def _selected_model_key(self) -> str:
        return self._model_map.get(self.model_var.get(), "turbo")

    def _ensure_model_ready(self) -> bool:
        key = self._selected_model_key()
        if model_manager.is_installed(key):
            return True
        if not is_frozen():
            # Development runs may use faster-whisper's own Hugging Face cache.
            return True
        answer = messagebox.askyesno(
            "ยังไม่ได้ติดตั้งโมเดล",
            "โมเดลที่เลือกยังไม่ได้ดาวน์โหลด\n\n"
            "ต้องการเปิดหน้าจัดการโมเดลเพื่อดาวน์โหลดตอนนี้หรือไม่?",
            parent=self.root,
        )
        if answer:
            self._open_model_manager(select=key)
        return False

    def _open_model_manager(self, select: str | None = None):
        win = self._manager_win
        if win is not None and win.winfo_exists():
            win.deiconify()
            win.lift()
            win.focus_force()
            self._select_manager_row(select or self._selected_model_key())
            return

        win = tk.Toplevel(self.root)
        win.title("จัดการโมเดลและ CUDA Runtime")
        win.geometry("820x600")
        win.minsize(720, 540)
        win.attributes("-topmost", True)
        win.transient(self.root)
        try:
            win.iconbitmap(str(ASSETS_DIR / "VoiceTyping.ico"))
        except tk.TclError:
            pass
        self._manager_win = win

        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text="ดาวน์โหลดเฉพาะโมเดลที่ต้องการ ไฟล์จะเก็บไว้ในเครื่องและใช้ซ้ำได้",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            body,
            text=(
                "แนะนำ: Small สำหรับเครื่องทั่วไป, Turbo สำหรับเครื่องมีการ์ดจอ NVIDIA, "
                "Pathumma/Large v3 เมื่อต้องการความแม่นยำสูงสุด"
            ),
            foreground="#555",
            wraplength=770,
            justify="left",
        ).pack(anchor="w", pady=(2, 8))

        columns = ("model", "size", "lang", "status")
        tree = ttk.Treeview(body, columns=columns, show="headings", height=8)
        headings = {
            "model": ("โมเดล", 280),
            "size": ("ขนาด", 90),
            "lang": ("ภาษา", 110),
            "status": ("สถานะ", 190),
        }
        for col, (title, width) in headings.items():
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="w")
        tree.pack(fill="both", expand=True)
        tree.tag_configure("installed", foreground="#15803d")
        self._manager_tree = tree
        self._refresh_manager_table(select or self._selected_model_key())

        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(8, 4))
        self._manager_download_btn = ttk.Button(
            actions, text="ดาวน์โหลดโมเดลที่เลือก", command=self._manager_download
        )
        self._manager_download_btn.pack(side="left")
        self._manager_delete_btn = ttk.Button(
            actions, text="ลบโมเดลที่เลือก", command=self._manager_delete
        )
        self._manager_delete_btn.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="ปิด", command=win.destroy).pack(side="right")

        gpu_box = ttk.LabelFrame(body, text="CUDA Runtime สำหรับ GPU (ไม่บังคับ)", padding=8)
        gpu_box.pack(fill="x", pady=(8, 4))
        self._manager_gpu_var = tk.StringVar(value="")
        ttk.Label(
            gpu_box,
            textvariable=self._manager_gpu_var,
            wraplength=600,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        self._manager_gpu_btn = ttk.Button(
            gpu_box, text="ติดตั้ง", command=self._manager_gpu_toggle
        )
        self._manager_gpu_btn.pack(side="right", padx=(8, 0))
        self._refresh_gpu_row()

        self._manager_status_var = tk.StringVar(value="พร้อมใช้งาน")
        self._manager_progress = ttk.Progressbar(body, maximum=100)
        self._manager_progress.pack(fill="x", pady=(8, 2))
        ttk.Label(
            body,
            textvariable=self._manager_status_var,
            foreground="#555",
            wraplength=770,
            justify="left",
        ).pack(anchor="w")

        ttk.Label(
            body,
            text=(
                "หมายเหตุ: โมเดลถูกเก็บไว้ที่ "
                f"{model_manager.models_dir()} และจะไม่ถูกลบเมื่อถอนการติดตั้งโปรแกรม"
            ),
            foreground="#777",
            wraplength=770,
            justify="left",
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(6, 0))

    def _select_manager_row(self, key: str | None) -> None:
        tree = self._manager_tree
        if tree is None or not tree.winfo_exists() or not key:
            return
        if tree.exists(key):
            tree.selection_set(key)
            tree.focus(key)
            tree.see(key)

    def _manager_selected_entry(self) -> model_manager.ModelEntry | None:
        tree = self._manager_tree
        if tree is None or not tree.winfo_exists():
            return None
        selection = tree.selection()
        if not selection:
            return None
        return model_manager.MODEL_BY_KEY.get(selection[0])

    def _refresh_manager_table(self, select: str | None = None) -> None:
        tree = self._manager_tree
        if tree is None or not tree.winfo_exists():
            return
        current = select or (tree.selection()[0] if tree.selection() else None)
        for item in tree.get_children():
            tree.delete(item)
        for entry in model_manager.MODEL_CATALOG:
            installed = model_manager.is_installed(entry)
            status = (
                f"ติดตั้งแล้ว ({model_manager.folder_size_mb(entry.folder):,.0f} MB)"
                if installed
                else "ยังไม่ติดตั้ง"
            )
            tree.insert(
                "",
                "end",
                iid=entry.key,
                values=(entry.label, entry.size_label, entry.languages, status),
                tags=("installed",) if installed else (),
            )
        if current and tree.exists(current):
            self._select_manager_row(current)

    def _refresh_gpu_row(self) -> None:
        if self._manager_gpu_var is None:
            return
        if cuda_pack.is_installed():
            self._manager_gpu_var.set(
                "สถานะ: ติดตั้งแล้ว "
                f"({cuda_pack.installed_size_mb():,.0f} MB) — ใช้ GPU กับ CTranslate2 ได้"
            )
            label = "ถอนการติดตั้ง"
        else:
            self._manager_gpu_var.set(
                "สถานะ: ยังไม่ได้ติดตั้ง — ดาวน์โหลดประมาณ 1.2 GB "
                "(แตกไฟล์ราว 1.95 GB) สำหรับเครื่อง NVIDIA"
            )
            label = "ติดตั้ง"
        try:
            if self._manager_gpu_btn is not None and self._manager_gpu_btn.winfo_exists():
                self._manager_gpu_btn.configure(text=label)
        except tk.TclError:
            pass

    def _manager_set_busy(self, busy: bool) -> None:
        self._manager_busy = busy
        state = "disabled" if busy else "normal"
        for widget in (
            getattr(self, "_manager_download_btn", None),
            getattr(self, "_manager_delete_btn", None),
            getattr(self, "_manager_gpu_btn", None),
        ):
            if widget is not None:
                try:
                    widget.configure(state=state)
                except tk.TclError:
                    pass

    def _manager_post(self, func, *args) -> None:
        try:
            self.root.after(0, func, *args)
        except tk.TclError:
            pass

    def _manager_progress_update(self, percent: float, message: str) -> None:
        self._manager_post(self._manager_progress_apply, percent, message)

    def _manager_progress_apply(self, percent: float, message: str) -> None:
        if self._manager_progress is not None and self._manager_progress.winfo_exists():
            self._manager_progress.configure(value=percent)
        if self._manager_status_var is not None:
            self._manager_status_var.set(message)

    def _manager_download(self) -> None:
        entry = self._manager_selected_entry()
        if entry is None:
            messagebox.showinfo("เลือกโมเดล", "กรุณาเลือกโมเดลจากรายการก่อน", parent=self.root)
            return
        if self._manager_busy:
            return
        if model_manager.is_installed(entry):
            messagebox.showinfo(
                "ติดตั้งแล้ว", f"{entry.label} ติดตั้งอยู่ในเครื่องแล้ว", parent=self.root
            )
            return
        if not messagebox.askyesno(
            "ยืนยันดาวน์โหลด",
            f"ดาวน์โหลด {entry.label}\nขนาดประมาณ {entry.size_label}\n\n"
            "ต้องใช้อินเทอร์เน็ตและพื้นที่ว่างในเครื่องตามขนาดไฟล์",
            parent=self.root,
        ):
            return

        self._manager_set_busy(True)
        self._manager_progress_apply(0.0, f"กำลังเตรียมดาวน์โหลด {entry.label}...")

        def worker():
            try:
                model_manager.download_entry(
                    entry, on_progress=self._manager_progress_update
                )
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self._manager_post(self._manager_finished, entry.key, False, str(exc))
            else:
                self._manager_post(self._manager_finished, entry.key, True, "")

        threading.Thread(target=worker, daemon=True).start()

    def _manager_finished(self, key: str, ok: bool, message: str) -> None:
        self._manager_set_busy(False)
        entry = model_manager.MODEL_BY_KEY.get(key)
        if ok:
            self._manager_progress_apply(
                100.0, f"ติดตั้ง {entry.label if entry else key} เรียบร้อย"
            )
            self._refresh_manager_table(select=key)
            self._refresh_gpu_row()
            if is_frozen():
                current = self._selected_model_key()
                if not model_manager.is_installed(current):
                    label = MODEL_LABEL_BY_KEY.get(key)
                    if label:
                        self.model_var.set(label)
                        self._build_app()
                        self.set_status(f"เลือกโมเดล {label} ให้แล้ว — กด Start Listening ได้เลย")
                        self._save_state()
            self._update_model_hint()
            if self._machine_profile is not None:
                self._update_machine_summary()
        else:
            self._manager_progress_apply(0.0, "ดาวน์โหลดไม่สำเร็จ")
            messagebox.showerror("ดาวน์โหลดไม่สำเร็จ", message, parent=self.root)

    def _manager_delete(self) -> None:
        entry = self._manager_selected_entry()
        if entry is None or self._manager_busy:
            return
        if not model_manager.is_installed(entry):
            messagebox.showinfo("ยังไม่ได้ติดตั้ง", "โมเดลนี้ยังไม่ได้ติดตั้ง", parent=self.root)
            return
        if not messagebox.askyesno(
            "ยืนยันลบโมเดล",
            f"ลบ {entry.label} ออกจากเครื่องหรือไม่?\n"
            "หากต้องการใช้อีกครั้งต้องดาวน์โหลดใหม่",
            parent=self.root,
        ):
            return
        model_manager.delete_entry(entry)
        self._refresh_manager_table(select=entry.key)
        self._manager_progress_apply(0.0, f"ลบ {entry.label} แล้ว")
        self._update_model_hint()
        if is_frozen() and self._selected_model_key() == entry.key:
            self.set_status("โมเดลที่เลือกถูกลบแล้ว — เลือกโมเดลอื่นหรือดาวน์โหลดใหม่")

    def _manager_gpu_toggle(self) -> None:
        if self._manager_busy:
            return
        if cuda_pack.is_installed():
            if not messagebox.askyesno(
                "ถอนการติดตั้ง CUDA Runtime",
                "ลบ CUDA Runtime ที่แอปติดตั้งไว้หรือไม่?\n"
                "แอปจะกลับไปทำงานบน CPU จนกว่าจะติดตั้งใหม่",
                parent=self.root,
            ):
                return
            cuda_pack.remove_pack()
            refresh_dll_paths()
            self._refresh_gpu_row()
            self._manager_progress_apply(0.0, "ถอนการติดตั้ง CUDA Runtime แล้ว")
            self._update_machine_summary()
            return

        if not messagebox.askyesno(
            "ติดตั้ง CUDA Runtime",
            "ดาวน์โหลด CUDA Runtime สำหรับ GPU NVIDIA หรือไม่?\n\n"
            "ขนาดดาวน์โหลดประมาณ 1.2 GB และใช้พื้นที่หลังแตกไฟล์ราว 1.95 GB\n"
            "ต้องใช้เครื่องที่มีการ์ดจอ NVIDIA และไดรเวอร์ล่าสุด",
            parent=self.root,
        ):
            return

        self._manager_set_busy(True)
        self._manager_progress_apply(0.0, "กำลังเริ่มดาวน์โหลด CUDA Runtime...")

        def worker():
            try:
                zip_path = cuda_pack.download_pack(on_progress=self._manager_progress_update)
                cuda_pack.install_from_file(
                    zip_path, on_progress=self._manager_progress_update
                )
                try:
                    zip_path.unlink()
                except OSError:
                    pass
                refresh_dll_paths()
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self._manager_post(self._manager_gpu_finished, False, str(exc))
            else:
                self._manager_post(self._manager_gpu_finished, True, "")

        threading.Thread(target=worker, daemon=True).start()

    def _manager_gpu_finished(self, ok: bool, message: str) -> None:
        self._manager_set_busy(False)
        if ok:
            self._manager_progress_apply(
                100.0,
                "ติดตั้ง CUDA Runtime เรียบร้อย — กด “ตรวจสเปคเครื่อง” เพื่อยืนยัน "
                "(ถ้ายังไม่เห็น GPU ให้ปิด-เปิดแอปใหม่)",
            )
            self._refresh_gpu_row()
            self._update_machine_summary()
        else:
            self._manager_progress_apply(0.0, "ติดตั้ง CUDA Runtime ไม่สำเร็จ")
            messagebox.showerror("ติดตั้ง CUDA Runtime ไม่สำเร็จ", message, parent=self.root)

    def _register_hotkey(self):
        spec = self.app.settings.hotkey
        try:
            self._hotkey = GlobalHotkey(spec)
            self._hotkey.start()
        except Exception as exc:  # noqa: BLE001 - shown in the status bar
            self._hotkey = None
            self.set_status(f"Hotkey unavailable: {exc}")
            return
        self._poll_hotkey()
        self.set_status(f"Ready. Hotkey: {spec.upper()}")

    def _poll_hotkey(self):
        hotkey = self._hotkey
        if hotkey is None:
            return
        if hotkey.consume():
            self.toggle()
        self._hotkey_poll = self.root.after(120, self._poll_hotkey)

    def _stop_hotkey(self):
        if self._hotkey_poll is not None:
            try:
                self.root.after_cancel(self._hotkey_poll)
            except tk.TclError:
                pass
            self._hotkey_poll = None
        if self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None

    def set_status(self, message):
        def update():
            self.status_var.set(message)
            if hasattr(self, "toggle_button"):
                text = "Stop Listening" if self.app.is_listening else "Start Listening"
                self.toggle_button.configure(text=text)
            self._draw_icon()

        self.root.after(0, update)

    def set_transcript(self, text):
        def update():
            self.transcript.configure(state="normal")
            self.transcript.delete("1.0", "end")
            self.transcript.insert("1.0", text)
            self.transcript.configure(state="disabled")
            self.transcript.see("end")

        self.root.after(0, update)

    def set_level(self, rms):
        value = min(100.0, rms * 1000.0)
        self.root.after(0, lambda: self.level_bar.configure(value=value))

    def _on_destination_change(self, *args):
        if self.app is not None:
            self.app.destination_mode = self._dest_map[self.destination_var.get()]
        self._save_state()

    def _on_model_selection_change(self, *args):
        if hasattr(self, "model_hint_label"):
            self._update_model_hint()
        self._save_state()

    def _update_model_hint(self):
        if self._machine_check_running:
            self.model_hint_var.set(
                "กำลังตรวจสอบสเปคเครื่อง... (ครั้งแรกอาจใช้เวลาราว 10 วินาที)"
            )
            if hasattr(self, "model_hint_label"):
                self.model_hint_label.configure(fg="#555555")
            return

        model_value = self._model_map.get(self.model_var.get(), "turbo")
        spec = get_model_spec(model_value)
        entry = model_manager.get_entry(model_value)
        installed_note = ""
        if entry is not None and not model_manager.is_installed(entry):
            installed_note = (
                f"\nสถานะ: ยังไม่ได้ดาวน์โหลด ({entry.size_label}) — "
                "กด “จัดการโมเดล” เพื่อติดตั้ง"
            )

        if self._machine_profile is None:
            if spec is None:
                text, color = "ไม่พบข้อมูลสเปคของโมเดลนี้", "#555555"
            else:
                text = (
                    f"ใช้ทรัพยากร: VRAM {spec.vram_gb} (GPU) / RAM {spec.ram_gb} (CPU) | "
                    f"แนะนำ: {spec.recommended_spec}\n"
                    "กดปุ่ม “ตรวจสเปคเครื่อง” เพื่อเช็กว่าเครื่องนี้พร้อมแค่ไหน"
                )
                color = "#555555"
        else:
            text, color = evaluate_model_fit(model_value, self._machine_profile)

        self.model_hint_var.set(text + installed_note)
        if hasattr(self, "model_hint_label"):
            self.model_hint_label.configure(fg=color)

    # -- on-demand hardware check -------------------------------------------

    def _machine_summary_text(self) -> str:
        mp = self._machine_profile
        if not mp:
            return "เครื่องที่ตรวจพบ: ยังไม่ได้ตรวจสอบ — กดปุ่ม “ตรวจสเปคเครื่อง”"
        hw_parts = [f"CPU {mp.get('cpu_cores', '?')} threads"]
        if mp.get("ram_gb"):
            hw_parts.append(f"RAM {mp['ram_gb']} GB")
        if mp.get("cuda_ready"):
            gpu = mp.get("gpu_name") or "NVIDIA GPU"
            vram = f" ({mp['vram_gb']} GB)" if mp.get("vram_gb") else ""
            hw_parts.append(f"GPU: {gpu}{vram} [CUDA พร้อม]")
        else:
            hw_parts.append(
                "GPU: ไม่พบ CUDA (ทำงานโหมด CPU — ติดตั้ง CUDA Runtime ใน “จัดการโมเดล” เพื่อใช้ GPU)"
            )
        return "เครื่องที่ตรวจพบ: " + " | ".join(hw_parts)

    def _update_machine_summary(self) -> None:
        self._machine_summary_var.set(self._machine_summary_text())

    def _set_machine_check_controls(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        if hasattr(self, "check_button"):
            self.check_button.configure(
                state=state,
                text="กำลังตรวจสอบ..." if running else "ตรวจสเปคเครื่อง",
            )
        button = getattr(self, "_spec_check_button", None)
        if button is not None:
            try:
                if button.winfo_exists():
                    button.configure(
                        state=state,
                        text="กำลังตรวจสอบ..." if running else "ตรวจสเปคเครื่องใหม่",
                    )
            except tk.TclError:
                pass

    def _start_machine_check(self) -> None:
        """Probe CPU/RAM/GPU only when the user asks (never at startup)."""
        if self._machine_check_running:
            return
        self._machine_check_running = True
        self._set_machine_check_controls(True)
        self._update_model_hint()

        def worker():
            try:
                profile = _detect_machine_profile()
            except Exception:
                profile = None
            try:
                self.root.after(0, self._apply_machine_profile, profile)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _apply_machine_profile(self, profile: dict | None) -> None:
        self._machine_profile = profile
        self._machine_check_running = False
        self._set_machine_check_controls(False)
        self._update_machine_summary()
        self._update_model_hint()

    def _show_model_specs(self):
        if self._spec_win is not None and self._spec_win.winfo_exists():
            self._spec_win.deiconify()
            self._spec_win.lift()
            self._spec_win.focus_force()
            return

        win = tk.Toplevel(self.root)
        win.title("สเปคที่แนะนำของแต่ละโมเดล")
        win.geometry("880x380")
        win.minsize(760, 320)
        win.attributes("-topmost", True)
        try:
            win.iconbitmap(str(ASSETS_DIR / "VoiceTyping.ico"))
        except tk.TclError:
            pass
        self._spec_win = win

        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)

        header = ttk.Frame(body)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(
            header,
            textvariable=self._machine_summary_var,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", fill="x", expand=True)
        self._spec_check_button = ttk.Button(
            header, text="ตรวจสเปคเครื่องใหม่", command=self._start_machine_check
        )
        self._spec_check_button.pack(side="right", padx=(8, 0))
        if self._machine_check_running:
            self._spec_check_button.configure(state="disabled", text="กำลังตรวจสอบ...")

        columns = ("model", "lang", "vram", "ram", "min_spec", "rec_spec", "note")
        tree = ttk.Treeview(body, columns=columns, show="headings", height=7)
        headings = {
            "model": ("โมเดล", 150),
            "lang": ("ภาษา", 85),
            "vram": ("VRAM (GPU)", 90),
            "ram": ("RAM (CPU)", 90),
            "min_spec": ("สเปคขั้นต่ำ", 180),
            "rec_spec": ("สเปคแนะนำ", 180),
            "note": ("หมายเหตุ", 220),
        }
        for col, (title, width) in headings.items():
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="w")

        for spec in MODEL_SPECS:
            tree.insert(
                "",
                "end",
                values=(
                    spec.label,
                    spec.languages,
                    spec.vram_gb,
                    spec.ram_gb,
                    spec.min_spec,
                    spec.recommended_spec,
                    spec.note,
                ),
            )
        tree.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text="คำแนะนำ: ถ้าต้องเปิดคู่เกมหรือโปรแกรมกิน GPU หนัก แนะนำ Turbo หรือ Small เพื่อลดการใช้ VRAM",
            foreground="#555",
        ).pack(anchor="w", pady=(8, 0))

        # Opening this dialog is an explicit user action, so it is fine to run
        # the hardware check now (in the background) when it has not run yet.
        if self._machine_profile is None and not self._machine_check_running:
            self._start_machine_check()

    def _poll_target(self):
        if self.app is not None and self.app.target_tracker is not None:
            try:
                self.app.target_tracker.observe_foreground()
            except Exception:
                pass
            active = self.app.is_listening and self.app.is_mic_ready
            if active != self._icon_active_state:
                self._draw_icon()
        self.root.after(500, self._poll_target)

    def _on_close(self):
        self._save_state()
        if self.app is not None and self.app.is_listening:
            self.app.stop()
        self._stop_hotkey()
        try:
            self.icon_win.destroy()
        except Exception:
            pass
        self.root.destroy()


def run_gui():
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "FiwFlash.RealtimeVoiceTyping"
            )
        except Exception:
            pass
    root = tk.Tk()
    RealtimeVoiceGui(root)
    root.mainloop()
