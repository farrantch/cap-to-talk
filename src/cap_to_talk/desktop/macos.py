"""macOS event taps, Accessibility window targeting, and Unicode input."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cap_to_talk.desktop.base import DesktopCheck, DesktopUnavailableError
from cap_to_talk.desktop.native import NativeDesktop

EVENT_TAG = 0x43415454
KEY_CODES = {
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
}


@dataclass(frozen=True)
class MacOSTarget:
    pid: int
    app: Any
    window: Any


class MacOSAPI:
    def __init__(self) -> None:
        import AppKit
        import ApplicationServices
        import AVFoundation
        import CoreFoundation
        import objc
        import Quartz

        self.appkit = AppKit
        self.ax = ApplicationServices
        self.av = AVFoundation
        self.cf = CoreFoundation
        self.quartz = Quartz
        self.objc = objc

    def check(self, hotkey: str) -> list[DesktopCheck]:
        mic = self.av.AVCaptureDevice.authorizationStatusForMediaType_(
            self.av.AVMediaTypeAudio
        )
        trusted = bool(self.ax.AXIsProcessTrusted())
        monitoring = bool(self.quartz.CGPreflightListenEventAccess())
        return [
            DesktopCheck(
                "Accessibility",
                trusted,
                "granted"
                if trusted
                else (
                    "enable the terminal or app in System Settings > "
                    "Privacy & Security > Accessibility"
                ),
            ),
            DesktopCheck(
                "Input Monitoring",
                monitoring,
                "granted"
                if monitoring
                else (
                    "enable the terminal or app in System Settings > "
                    "Privacy & Security > Input Monitoring"
                ),
            ),
            DesktopCheck(
                "Microphone permission",
                mic in (0, 3),
                "requested on first recording"
                if mic == 0
                else (
                    "granted"
                    if mic == 3
                    else (
                        "enable microphone access in System Settings > "
                        "Privacy & Security > Microphone"
                    )
                ),
            ),
            DesktopCheck(
                "dictation shortcut",
                hotkey in KEY_CODES,
                hotkey
                if hotkey in KEY_CODES
                else (
                    "macOS hold-to-talk requires f1 through f12; "
                    "Caps Lock does not report a reliable release"
                ),
            ),
        ]

    def _attribute(self, element: Any, attribute: str) -> Any:
        status, value = self.ax.AXUIElementCopyAttributeValue(element, attribute, None)
        return value if status == 0 else None

    def foreground_target(self) -> MacOSTarget | None:
        with self.objc.autorelease_pool():
            app = self.appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
            if app is None:
                return None
            pid = int(app.processIdentifier())
            element = self.ax.AXUIElementCreateApplication(pid)
            self.ax.AXUIElementSetMessagingTimeout(element, 1.0)
            window = self._attribute(element, self.ax.kAXFocusedWindowAttribute)
            return MacOSTarget(pid, app, window) if window is not None else None

    def same_target(self, first: MacOSTarget, second: MacOSTarget) -> bool:
        return first.pid == second.pid and bool(
            self.cf.CFEqual(first.window, second.window)
        )

    def window_exists(self, target: MacOSTarget) -> bool:
        with self.objc.autorelease_pool():
            return not target.app.isTerminated() and (
                self._attribute(target.window, self.ax.kAXRoleAttribute) is not None
            )

    def activate(self, target: MacOSTarget) -> None:
        with self.objc.autorelease_pool():
            if not self.window_exists(target):
                raise DesktopUnavailableError("The original target window has closed.")
            target.app.activateWithOptions_(
                self.appkit.NSApplicationActivateIgnoringOtherApps
            )
            self.ax.AXUIElementPerformAction(target.window, self.ax.kAXRaiseAction)
            self.ax.AXUIElementSetAttributeValue(
                target.window, self.ax.kAXMainAttribute, True
            )
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                current = self.foreground_target()
                if current is not None and self.same_target(current, target):
                    return
                time.sleep(0.01)
        raise DesktopUnavailableError(
            "macOS could not focus the original window. Switch to it and dictate again."
        )

    def modifiers_pressed(self) -> bool:
        q = self.quartz
        flags = q.CGEventSourceFlagsState(q.kCGEventSourceStateCombinedSessionState)
        return bool(
            flags
            & (
                q.kCGEventFlagMaskShift
                | q.kCGEventFlagMaskControl
                | q.kCGEventFlagMaskAlternate
                | q.kCGEventFlagMaskCommand
            )
        )

    def idle_ms(self) -> int:
        q = self.quartz
        return int(
            q.CGEventSourceSecondsSinceLastEventType(
                q.kCGEventSourceStateCombinedSessionState, q.kCGAnyInputEventType
            )
            * 1000
        )

    def type_character(self, char: str) -> None:
        q = self.quartz
        with self.objc.autorelease_pool():
            if not self.ax.AXIsProcessTrusted():
                raise DesktopUnavailableError("Accessibility permission was revoked.")
            code = {"\n": 0x24, "\t": 0x30}.get(char, 0)
            for pressed in (True, False):
                event = q.CGEventCreateKeyboardEvent(None, code, pressed)
                if event is None:
                    raise DesktopUnavailableError(
                        "macOS could not create a keyboard event."
                    )
                q.CGEventSetFlags(event, 0)
                q.CGEventSetIntegerValueField(
                    event, q.kCGEventSourceUserData, EVENT_TAG
                )
                if char not in ("\n", "\t"):
                    q.CGEventKeyboardSetUnicodeString(
                        event, len(char.encode("utf-16-le")) // 2, char
                    )
                q.CGEventPost(q.kCGHIDEventTap, event)

    def listen(
        self,
        hotkey: str,
        emit: Callable[[bool, bool], None],
        ready: Callable[[], None],
        stopped: threading.Event,
    ) -> None:
        q = self.quartz
        key = KEY_CODES[hotkey]
        failures: list[Exception] = []

        def callback(proxy: Any, event_type: int, event: Any, refcon: Any) -> Any:
            try:
                if event_type in (
                    q.kCGEventTapDisabledByTimeout,
                    q.kCGEventTapDisabledByUserInput,
                ):
                    raise DesktopUnavailableError(
                        "macOS disabled the dictation shortcut listener."
                    )
                if (
                    event_type in (q.kCGEventKeyDown, q.kCGEventKeyUp)
                    and q.CGEventGetIntegerValueField(event, q.kCGKeyboardEventKeycode)
                    == key
                    and q.CGEventGetIntegerValueField(event, q.kCGEventSourceUserData)
                    != EVENT_TAG
                ):
                    emit(
                        event_type == q.kCGEventKeyDown,
                        bool(q.CGEventGetFlags(event) & q.kCGEventFlagMaskShift),
                    )
                    return None
            except Exception as error:
                failures.append(error)
                stopped.set()
            return event

        with self.objc.autorelease_pool():
            tap = q.CGEventTapCreate(
                q.kCGSessionEventTap,
                q.kCGHeadInsertEventTap,
                q.kCGEventTapOptionDefault,
                (1 << q.kCGEventKeyDown) | (1 << q.kCGEventKeyUp),
                callback,
                None,
            )
            if tap is None:
                raise DesktopUnavailableError(
                    "macOS could not register the shortcut. "
                    "Check Accessibility and Input Monitoring permissions."
                )
            source = None
            loop = None
            try:
                loop = q.CFRunLoopGetCurrent()
                source = q.CFMachPortCreateRunLoopSource(None, tap, 0)
                if source is None:
                    raise DesktopUnavailableError(
                        "macOS could not create the shortcut event loop."
                    )
                q.CFRunLoopAddSource(loop, source, q.kCFRunLoopDefaultMode)
                q.CGEventTapEnable(tap, True)
                ready()
                while not stopped.is_set():
                    q.CFRunLoopRunInMode(q.kCFRunLoopDefaultMode, 0.1, False)
                if failures:
                    raise failures[0]
            finally:
                try:
                    q.CGEventTapEnable(tap, False)
                finally:
                    try:
                        if source is not None:
                            q.CFRunLoopRemoveSource(
                                loop, source, q.kCFRunLoopDefaultMode
                            )
                    finally:
                        q.CFMachPortInvalidate(tap)


class MacOSDesktop(NativeDesktop):
    platform_name = "macOS"
    default_hotkey = "f8"

    def _load_api(self) -> MacOSAPI:
        return MacOSAPI()
