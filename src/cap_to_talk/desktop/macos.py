"""macOS event taps, Accessibility window targeting, and Unicode input."""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any

from cap_to_talk.desktop.base import DesktopCheck, DesktopUnavailableError
from cap_to_talk.desktop.native import NativeDesktop

EVENT_TAG = 0x43415454
HIDUTIL = "/usr/bin/hidutil"
CAPS_LOCK_USAGE = 0x700000039
F18_USAGE = 0x70000006D
CAPS_LOCK_REMAP = (CAPS_LOCK_USAGE, F18_USAGE)
KEY_CODES = {
    # Caps Lock only reports toggles, so it is remapped to F18 while listening.
    "caps_lock": 79,
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


def _key_mappings() -> list[tuple[int, int]]:
    output = subprocess.run(
        [HIDUTIL, "property", "--get", "UserKeyMapping"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout
    mappings = []
    for block in re.findall(r"\{([^}]*)\}", output):
        source = re.search(r"HIDKeyboardModifierMappingSrc\s*=\s*(\d+)", block)
        destination = re.search(r"HIDKeyboardModifierMappingDst\s*=\s*(\d+)", block)
        if source and destination:
            mappings.append((int(source.group(1)), int(destination.group(1))))
    return mappings


def _set_key_mappings(mappings: list[tuple[int, int]]) -> None:
    value = [
        {"HIDKeyboardModifierMappingSrc": source, "HIDKeyboardModifierMappingDst": dest}
        for source, dest in mappings
    ]
    subprocess.run(
        [HIDUTIL, "property", "--set", json.dumps({"UserKeyMapping": value})],
        check=True,
        capture_output=True,
        timeout=5,
    )


@contextmanager
def caps_lock_as_f18() -> Iterator[None]:
    try:
        # Drop a remap left by a crash so it is not restored as the user's own.
        saved = [item for item in _key_mappings() if item != CAPS_LOCK_REMAP]
        _set_key_mappings(
            [item for item in saved if item[0] != CAPS_LOCK_USAGE] + [CAPS_LOCK_REMAP]
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DesktopUnavailableError(
            "Could not prepare Caps Lock. Choose a function key in Settings."
        ) from error
    try:
        yield
    finally:
        _set_key_mappings(saved)


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

    def request_permissions(self) -> None:
        """Show the prompts that add this app to the privacy settings lists."""
        if not self.ax.AXIsProcessTrusted():
            self.ax.AXIsProcessTrustedWithOptions(
                {self.ax.kAXTrustedCheckOptionPrompt: True}
            )
        if not self.quartz.CGPreflightListenEventAccess():
            self.quartz.CGRequestListenEventAccess()

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
                    "enable Cap To Talk (or your terminal) in System Settings > "
                    "Privacy & Security > Accessibility"
                ),
            ),
            DesktopCheck(
                "Input Monitoring",
                monitoring,
                "granted"
                if monitoring
                else (
                    "enable Cap To Talk (or your terminal) in System Settings > "
                    "Privacy & Security > Input Monitoring, then reopen it"
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
                else "macOS hold-to-talk requires caps_lock or f1 through f12",
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
        remap = nullcontext()
        if hotkey == "caps_lock":
            flags = q.CGEventSourceFlagsState(q.kCGEventSourceStateHIDSystemState)
            # Once remapped, Caps Lock could not be switched off until dictation stops.
            if flags & q.kCGEventFlagMaskAlphaShift:
                raise DesktopUnavailableError(
                    "Turn off Caps Lock, then start dictation again."
                )
            remap = caps_lock_as_f18()

        def callback(proxy: Any, event_type: int, event: Any, refcon: Any) -> Any:
            try:
                if event_type in (
                    q.kCGEventTapDisabledByTimeout,
                    q.kCGEventTapDisabledByUserInput,
                ):
                    # macOS disables a tap that responds slowly; resume listening.
                    q.CGEventTapEnable(tap, True)
                    return event
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
                with remap:
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
    default_hotkey = "caps_lock"

    def _load_api(self) -> MacOSAPI:
        return MacOSAPI()

    def run_hotkey_loop(
        self,
        *,
        on_press: Callable[[bool], None],
        on_release: Callable[[], None],
        on_ready: Callable[[], None],
    ) -> None:
        self.api.request_permissions()
        super().run_hotkey_loop(
            on_press=on_press, on_release=on_release, on_ready=on_ready
        )
