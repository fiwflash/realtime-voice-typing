"""Global toggle hotkey built on Win32 ``RegisterHotKey``.

The previous implementation used the ``keyboard`` package, which installs a
low-level keyboard hook and can observe every keystroke on the system. That is
both heavier than necessary and, in practice, tripped Windows Defender's ML
classifier on the packaged executable. ``RegisterHotKey`` lets Windows deliver
exactly one key combination to this process and nothing else.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
}

_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "pause": 0x13,
    "scrolllock": 0x91,
    "capslock": 0x14,
    "`": 0xC0,
}
_KEYS.update({f"f{n}": 0x6F + n for n in range(1, 25)})


class MSG(ctypes.Structure):
    _fields_ = [
        ("hWnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def parse_hotkey(spec: str) -> tuple[int, int]:
    """Turn ``"f8"`` or ``"ctrl+alt+space"`` into ``(modifiers, virtual-key)``."""
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    if not parts:
        raise ValueError("hotkey is empty")

    key = parts[-1]
    modifiers = 0
    for part in parts[:-1]:
        if part not in _MODIFIERS:
            raise ValueError(f"unsupported modifier: {part}")
        modifiers |= _MODIFIERS[part]

    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        vk = _KEYS.get(key)
    if vk is None:
        raise ValueError(f"unsupported key: {key}")
    return modifiers, vk


class GlobalHotkey:
    """Registers one system-wide hotkey and records presses until consumed.

    Tkinter must only be touched from its own thread, so the Win32 message loop
    runs on a helper thread and just raises a flag; the GUI polls
    :meth:`consume` from its existing ``after`` loop.
    """

    def __init__(self, spec: str, hotkey_id: int = 1):
        self.spec = spec
        self.modifiers, self.vk = parse_hotkey(spec)
        self.hotkey_id = hotkey_id
        self.error: OSError | None = None
        self._pressed = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None

    def start(self, timeout: float = 2.0) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        if self.error is not None:
            raise self.error

    def consume(self) -> bool:
        """Return True once per key press."""
        if not self._pressed.is_set():
            return False
        self._pressed.clear()
        return True

    def stop(self) -> None:
        thread, thread_id = self._thread, self._thread_id
        self._thread = None
        if thread is None:
            return
        if thread_id is not None:
            try:
                ctypes.windll.user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except OSError:
                pass
        thread.join(timeout=2.0)

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        self._thread_id = int(kernel32.GetCurrentThreadId())
        if not user32.RegisterHotKey(None, self.hotkey_id, self.modifiers, self.vk):
            self.error = ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            return

        self._ready.set()
        message = MSG()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                if message.message == WM_HOTKEY:
                    self._pressed.set()
        finally:
            user32.UnregisterHotKey(None, self.hotkey_id)
            self._thread_id = None
