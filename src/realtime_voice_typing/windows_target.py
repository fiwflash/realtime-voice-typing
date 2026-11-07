"""Track the last focused external window so text can be typed into it."""

import ctypes
import os


class WindowsApi:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.own_pid = os.getpid()

    def get_foreground_window(self) -> int:
        return int(self.user32.GetForegroundWindow())

    def get_window_pid(self, hwnd: int) -> int:
        pid = ctypes.c_ulong()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def is_window(self, hwnd: int) -> bool:
        return bool(hwnd and self.user32.IsWindow(hwnd))

    def set_foreground_window(self, hwnd: int) -> None:
        if hwnd:
            self.user32.SetForegroundWindow(hwnd)


class TargetTracker:
    """Remembers the last foreground window that is not this app."""

    def __init__(self, api=None):
        self.api = api or WindowsApi()
        self.last_external_hwnd = None
        self._previous_hwnd = None

    def observe_foreground(self) -> int | None:
        """Record the foreground window if it belongs to another process."""
        hwnd = self.api.get_foreground_window()
        if not hwnd or not self.api.is_window(hwnd):
            return self.last_external_hwnd
        if self.api.get_window_pid(hwnd) != self.api.own_pid:
            self.last_external_hwnd = hwnd
        return self.last_external_hwnd

    def resolve_last_focus(self) -> int | None:
        if self.last_external_hwnd and self.api.is_window(self.last_external_hwnd):
            return self.last_external_hwnd
        return None

    def resolve_target(self, mode: str) -> int | None:
        """Resolve the insertion target for a destination mode."""
        if mode == "last_focus":
            return self.resolve_last_focus()
        # follow_cursor: the current foreground if it's another process, else
        # fall back to the last external window (covers the app/icon having focus).
        current = self.api.get_foreground_window()
        if current and self.api.is_window(current) and self.api.get_window_pid(current) != self.api.own_pid:
            return current
        return self.resolve_last_focus()

    def focus_for_insert(self, hwnd: int) -> bool:
        if not hwnd or not self.api.is_window(hwnd):
            return False
        self._previous_hwnd = self.api.get_foreground_window()
        self.api.set_foreground_window(hwnd)
        return True

    def restore_previous_focus(self) -> None:
        if self._previous_hwnd and self.api.is_window(self._previous_hwnd):
            self.api.set_foreground_window(self._previous_hwnd)
        self._previous_hwnd = None
