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
import tkinter as tk
from tkinter import ttk

import numpy as np

from .app import RealtimeVoiceApp
from .settings import (
    DESTINATION_CHOICES,
    MODEL_CHOICES,
    MODEL_SPECS,
    Settings,
    get_model_spec,
)
from .speech import cuda_available


ICON_SIZE = 72
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"

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
        self.root.geometry("580x590")
        self.root.minsize(500, 460)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self.root.iconbitmap(str(ASSETS_DIR / "VoiceTyping.ico"))
        except tk.TclError:
            pass

        self._mode = "full"
        self._press = None
        self._win_pos = (0, 0)
        self._dragged = False
        self._icon_active_state = None
        self._icon_pos = None
        self._spec_win = None
        self._machine_profile = _detect_machine_profile()

        self.status_var = tk.StringVar(value="Ready")
        self._model_map = {label: value for label, value in MODEL_CHOICES}
        default_label = next(label for label, value in MODEL_CHOICES if value == "turbo")
        self.model_var = tk.StringVar(value=default_label)
        self.model_var.trace_add("write", self._on_model_selection_change)
        self.model_hint_var = tk.StringVar(value="")

        self._dest_map = {label: value for label, value in DESTINATION_CHOICES}
        dest_default = next(label for label, value in DESTINATION_CHOICES if value == "follow_cursor")
        self.destination_var = tk.StringVar(value=dest_default)
        self.destination_var.trace_add("write", self._on_destination_change)

        self.app = None
        self._build_app()
        self._build_full()
        self._create_icon()
        self._register_hotkey()
        self._poll_target()
        self.root.bind_all("<Button-3>", self._on_right_click)

    # -- app ----------------------------------------------------------------

    def _build_app(self):
        self.app = RealtimeVoiceApp(
            settings=Settings(
                model_size=self._model_map[self.model_var.get()],
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
        ttk.Label(frame, textvariable=self.status_var, wraplength=520).pack(anchor="w", pady=(6, 4))

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
        ttk.Button(settings, text="สเปคแต่ละโมเดล", command=self._show_model_specs).grid(
            row=0, column=3, padx=(6, 0)
        )

        self.model_hint_label = tk.Label(
            settings,
            textvariable=self.model_hint_var,
            justify="left",
            anchor="w",
            wraplength=510,
            font=("Segoe UI", 9),
        )
        self.model_hint_label.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(5, 2))
        self._update_model_hint()

        ttk.Label(settings, text="Destination").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            settings,
            textvariable=self.destination_var,
            values=[label for label, _ in DESTINATION_CHOICES],
            state="readonly",
        ).grid(row=2, column=1, columnspan=3, sticky="ew", pady=(6, 0))
        settings.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Transcript").pack(anchor="w")
        self.transcript = tk.Text(frame, height=10, wrap="word", state="disabled")
        self.transcript.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Press F8, click Start, or use the floating icon. Right-click anywhere → Icon mode.",
            foreground="#555",
            wraplength=520,
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

    def _switch_to_full(self):
        self._mode = "full"
        self.icon_win.withdraw()
        self.root.deiconify()

    # -- controls ------------------------------------------------------------

    def toggle(self):
        if self.app.is_listening:
            self.app.stop()
            self.toggle_button.configure(text="Start Listening")
        else:
            self.app.start()
            self.toggle_button.configure(text="Stop Listening")
        self._draw_icon()

    def clear(self):
        self.app.clear_transcript()

    def _apply_settings(self):
        was_listening = self.app.is_listening
        last_hwnd = self.app.target_tracker.last_external_hwnd if self.app else None
        if was_listening:
            self.app.stop()
        self._build_app()
        if last_hwnd:
            self.app.target_tracker.last_external_hwnd = last_hwnd
        if was_listening:
            self.app.start()
        self._draw_icon()

    def _register_hotkey(self):
        try:
            import keyboard

            keyboard.add_hotkey(self.app.settings.hotkey, self._hotkey_toggle)
            self.set_status("Ready. Hotkey: F8")
        except Exception as exc:
            self.set_status(f"Hotkey unavailable: {exc}")

    def _hotkey_toggle(self):
        self.root.after(0, self.toggle)

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

    def _on_model_selection_change(self, *args):
        if hasattr(self, "model_hint_label"):
            self._update_model_hint()

    def _update_model_hint(self):
        model_value = self._model_map.get(self.model_var.get(), "turbo")
        text, color = evaluate_model_fit(model_value, self._machine_profile)
        self.model_hint_var.set(text)
        if hasattr(self, "model_hint_label"):
            self.model_hint_label.configure(fg=color)

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

        mp = self._machine_profile
        hw_parts = [f"CPU {mp.get('cpu_cores', '?')} threads"]
        if mp.get("ram_gb"):
            hw_parts.append(f"RAM {mp['ram_gb']} GB")
        if mp.get("cuda_ready"):
            gpu = mp.get("gpu_name") or "NVIDIA GPU"
            vram = f" ({mp['vram_gb']} GB)" if mp.get("vram_gb") else ""
            hw_parts.append(f"GPU: {gpu}{vram} [CUDA พร้อม]")
        else:
            hw_parts.append("GPU: ไม่พบ CUDA (ทำงานโหมด CPU)")

        ttk.Label(
            body,
            text="เครื่องที่ตรวจพบ: " + " | ".join(hw_parts),
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 8))

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
        if self.app is not None and self.app.is_listening:
            self.app.stop()
        try:
            self.icon_win.destroy()
        except Exception:
            pass
        self.root.destroy()


def run_gui():
    root = tk.Tk()
    RealtimeVoiceGui(root)
    root.mainloop()
