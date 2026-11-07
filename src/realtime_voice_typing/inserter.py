"""Type Unicode text into the focused window, independent of keyboard layout."""

import ctypes
from ctypes import wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002

PUL = ctypes.POINTER(ctypes.c_ulong)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUTUNION),
    ]


def codepoints(text: str) -> list:
    """UTF-16 code units to inject. Non-BMP chars are dropped (SendInput limit)."""
    return [ord(ch) for ch in text if ord(ch) <= 0xFFFF]


class TextInserter:
    def __init__(self, method: str = "unicode"):
        self.method = method
        self.user32 = ctypes.windll.user32

    def type_text(self, text: str) -> None:
        if not text:
            return
        if self.method == "clipboard":
            self._paste(text)
        else:
            self._unicode(text)

    def _unicode(self, text: str) -> None:
        units = codepoints(text)
        if not units:
            return
        events = (_INPUT * 2)()
        for unit in units:
            events[0].type = INPUT_KEYBOARD
            events[0].u.ki.wVk = 0
            events[0].u.ki.wScan = unit
            events[0].u.ki.dwFlags = KEYEVENTF_UNICODE
            events[0].u.ki.time = 0
            events[0].u.ki.dwExtraInfo = None

            events[1].type = INPUT_KEYBOARD
            events[1].u.ki.wVk = 0
            events[1].u.ki.wScan = unit
            events[1].u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            events[1].u.ki.time = 0
            events[1].u.ki.dwExtraInfo = None

            self.user32.SendInput(2, events, ctypes.sizeof(_INPUT))

    def _paste(self, text: str) -> None:
        import time

        import pyperclip

        previous = pyperclip.paste()
        try:
            pyperclip.copy(text)
            import keyboard

            keyboard.press_and_release("ctrl+v")
            time.sleep(0.05)
        finally:
            pyperclip.copy(previous)
