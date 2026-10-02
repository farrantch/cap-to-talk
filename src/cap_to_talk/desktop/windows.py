"""Windows keyboard hooks, window targeting, and Unicode input."""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cap_to_talk.desktop.base import DesktopCheck, DesktopUnavailableError
from cap_to_talk.desktop.native import NativeDesktop

DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
WORD = ctypes.c_uint16
HANDLE = ctypes.c_void_p
UINT_PTR = ctypes.c_size_t
LONG_PTR = ctypes.c_ssize_t
EVENT_TAG = 0x43415454


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", UINT_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", UINT_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", DWORD), ("data", INPUTUNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", DWORD),
        ("scanCode", DWORD),
        ("flags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", UINT_PTR),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", HANDLE),
        ("message", DWORD),
        ("wParam", UINT_PTR),
        ("lParam", LONG_PTR),
        ("time", DWORD),
        ("pt", POINT),
        ("lPrivate", DWORD),
    ]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", DWORD), ("dwTime", DWORD)]


@dataclass(frozen=True)
class WindowsTarget:
    hwnd: int
    pid: int


def virtual_key(hotkey: str) -> int:
    if hotkey == "caps_lock":
        return 0x14
    return 0x70 + int(hotkey[1:]) - 1


def keyboard_inputs(char: str) -> list[INPUT]:
    if char in ("\n", "\t"):
        key = 0x0D if char == "\n" else 0x09
        return [
            INPUT(type=1, ki=KEYBDINPUT(wVk=key, dwFlags=flags, dwExtraInfo=EVENT_TAG))
            for flags in (0, 2)
        ]
    encoded = char.encode("utf-16-le")
    return [
        INPUT(
            type=1,
            ki=KEYBDINPUT(
                wScan=int.from_bytes(encoded[offset : offset + 2], "little"),
                dwFlags=flags,
                dwExtraInfo=EVENT_TAG,
            ),
        )
        for offset in range(0, len(encoded), 2)
        for flags in (4, 6)
    ]


class WindowsAPI:
    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.hook_type = ctypes.WINFUNCTYPE(LONG_PTR, ctypes.c_int, UINT_PTR, HANDLE)
        signatures = {
            "GetForegroundWindow": ([], HANDLE),
            "GetWindowThreadProcessId": ([HANDLE, ctypes.POINTER(DWORD)], DWORD),
            "IsWindow": ([HANDLE], ctypes.c_int),
            "IsIconic": ([HANDLE], ctypes.c_int),
            "ShowWindow": ([HANDLE, ctypes.c_int], ctypes.c_int),
            "SetForegroundWindow": ([HANDLE], ctypes.c_int),
            "GetAsyncKeyState": ([ctypes.c_int], ctypes.c_int16),
            "GetLastInputInfo": ([ctypes.POINTER(LASTINPUTINFO)], ctypes.c_int),
            "SendInput": ([DWORD, ctypes.POINTER(INPUT), ctypes.c_int], DWORD),
            "SetWindowsHookExW": (
                [ctypes.c_int, self.hook_type, HANDLE, DWORD],
                HANDLE,
            ),
            "UnhookWindowsHookEx": ([HANDLE], ctypes.c_int),
            "CallNextHookEx": ([HANDLE, ctypes.c_int, UINT_PTR, HANDLE], LONG_PTR),
            "PeekMessageW": (
                [ctypes.POINTER(MSG), HANDLE, DWORD, DWORD, DWORD],
                ctypes.c_int,
            ),
            "TranslateMessage": ([ctypes.POINTER(MSG)], ctypes.c_int),
            "DispatchMessageW": ([ctypes.POINTER(MSG)], LONG_PTR),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user32, name)
            function.argtypes = args
            function.restype = result
        self.kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        self.kernel32.GetModuleHandleW.restype = HANDLE
        self.kernel32.GetTickCount64.argtypes = []
        self.kernel32.GetTickCount64.restype = ctypes.c_uint64

    def check(self, hotkey: str) -> list[DesktopCheck]:
        return [
            DesktopCheck(
                "Windows desktop",
                bool(self.user32.GetForegroundWindow()),
                "an interactive desktop session is required",
            ),
            DesktopCheck("dictation shortcut", True, hotkey),
        ]

    def foreground_target(self) -> WindowsTarget | None:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return WindowsTarget(int(hwnd), pid.value) if pid.value else None

    def same_target(self, first: WindowsTarget, second: WindowsTarget) -> bool:
        return first == second

    def window_exists(self, target: WindowsTarget) -> bool:
        if not self.user32.IsWindow(target.hwnd):
            return False
        pid = DWORD()
        self.user32.GetWindowThreadProcessId(target.hwnd, ctypes.byref(pid))
        return pid.value == target.pid

    def activate(self, target: WindowsTarget) -> None:
        if not self.window_exists(target):
            raise DesktopUnavailableError("The original target window has closed.")
        if self.user32.IsIconic(target.hwnd):
            self.user32.ShowWindow(target.hwnd, 9)
        self.user32.SetForegroundWindow(target.hwnd)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if self.foreground_target() == target:
                return
            time.sleep(0.01)
        raise DesktopUnavailableError(
            "Windows did not allow the target window to receive focus. "
            "Switch to that window and dictate again."
        )

    def modifiers_pressed(self) -> bool:
        return any(
            self.user32.GetAsyncKeyState(key) & 0x8000
            for key in (0x10, 0x11, 0x12, 0x5B, 0x5C)
        )

    def idle_ms(self) -> int:
        info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        return (self.kernel32.GetTickCount64() - info.dwTime) & 0xFFFFFFFF

    def type_character(self, char: str) -> None:
        events = keyboard_inputs(char)
        inputs = (INPUT * len(events))(*events)
        sent = self.user32.SendInput(len(events), inputs, ctypes.sizeof(INPUT))
        if sent != len(events):
            raise DesktopUnavailableError(
                "Windows blocked text insertion or accepted only part of it. "
                "The target may be running with higher privileges."
            )

    def listen(
        self,
        hotkey: str,
        emit: Callable[[bool, bool], None],
        ready: Callable[[], None],
        stopped: threading.Event,
    ) -> None:
        key = virtual_key(hotkey)
        failures: list[Exception] = []

        @self.hook_type
        def callback(code: int, message: int, pointer: Any) -> int:
            try:
                if code >= 0:
                    event = ctypes.cast(
                        pointer, ctypes.POINTER(KBDLLHOOKSTRUCT)
                    ).contents
                    if (
                        not event.flags & 0x10
                        and event.vkCode == key
                        and message in (0x100, 0x104, 0x101, 0x105)
                    ):
                        emit(
                            message in (0x100, 0x104),
                            bool(self.user32.GetAsyncKeyState(0x10) & 0x8000),
                        )
                        return 1
            except Exception as error:
                failures.append(error)
                stopped.set()
            return self.user32.CallNextHookEx(None, code, message, pointer)

        hook = self.user32.SetWindowsHookExW(
            13, callback, self.kernel32.GetModuleHandleW(None), 0
        )
        if not hook:
            raise DesktopUnavailableError(
                "Windows could not register the dictation shortcut."
            )
        try:
            ready()
            message = MSG()
            while not stopped.is_set():
                while self.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                    if message.message == 0x12:
                        return
                    self.user32.TranslateMessage(ctypes.byref(message))
                    self.user32.DispatchMessageW(ctypes.byref(message))
                stopped.wait(0.01)
            if failures:
                raise failures[0]
        finally:
            self.user32.UnhookWindowsHookEx(hook)


class WindowsDesktop(NativeDesktop):
    platform_name = "Windows"
    default_hotkey = "caps_lock"

    def _load_api(self) -> WindowsAPI:
        return WindowsAPI()
