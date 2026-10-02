"""Linux/X11 hotkeys, notifications, diagnostics, and window targeting."""

from __future__ import annotations

import importlib.util
import os
import select
import subprocess
import threading
from collections.abc import Callable
from contextlib import suppress

from cap_to_talk import x11
from cap_to_talk.config import Settings
from cap_to_talk.desktop.base import DesktopCheck, DesktopUnavailableError


class LinuxX11Desktop:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._stopped = threading.Event()

    def check(self) -> list[DesktopCheck]:
        session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
        missing = x11.missing_commands()
        has_xlib = importlib.util.find_spec("Xlib") is not None
        return [
            DesktopCheck("X11 session", session_type == "x11", session_type),
            DesktopCheck(
                "DISPLAY",
                bool(os.environ.get("DISPLAY")),
                os.environ.get("DISPLAY", "unset"),
            ),
            DesktopCheck(
                "desktop commands",
                not missing,
                "available" if not missing else "missing: " + ", ".join(missing),
            ),
            DesktopCheck(
                "X11 library",
                has_xlib,
                "available"
                if has_xlib
                else "missing python-xlib; reinstall Cap To Talk",
            ),
        ]

    def capture_target(self) -> str | None:
        return x11.get_active_window_id()

    def release_target(self, target: str | None) -> None:
        pass

    def insert_text(self, text: str, target: str | None, *, delay_ms: int = 0) -> None:
        x11.type_text(text, target, delay_ms=delay_ms)

    def notify(self, message: str, timeout: int = 1_500) -> None:
        with suppress(OSError):
            subprocess.Popen(
                [
                    "notify-send",
                    "-r",
                    self.settings.notify_id,
                    "-t",
                    str(timeout),
                    "Cap To Talk",
                    message,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def stop(self) -> None:
        self._stopped.set()

    def run_hotkey_loop(
        self,
        *,
        on_press: Callable[[bool], None],
        on_release: Callable[[], None],
        on_ready: Callable[[], None],
    ) -> None:
        failures = [
            f"{check.name}: {check.detail}"
            for check in self.check()
            if check.required and not check.ok
        ]
        if failures:
            raise DesktopUnavailableError("; ".join(failures))

        # Only the selected adapter loads the native keyboard dependency.
        from Xlib import XK, X, display, error

        try:
            x_display = display.Display()
        except (error.DisplayError, OSError):
            raise DesktopUnavailableError(
                "Could not connect to the X11 display. "
                "Run Cap To Talk from your desktop session."
            ) from None

        root = None
        keycode = self.settings.ptt_keycode
        repeat_mode = None
        grab_attempted = False
        grab_failed = False

        def handle_grab_error(_error: object, _request: object) -> bool:
            nonlocal grab_failed
            grab_failed = True
            return True

        try:
            root = x_display.screen().root
            if self.settings.hotkey not in ("auto", "caps_lock"):
                keycode = x_display.keysym_to_keycode(
                    XK.string_to_keysym(self.settings.hotkey.upper())
                )
                if not keycode:
                    raise DesktopUnavailableError(
                        "The selected shortcut has no X11 keycode."
                    )
            grab_attempted = True
            root.grab_key(
                keycode,
                X.AnyModifier,
                False,
                X.GrabModeAsync,
                X.GrabModeAsync,
                onerror=handle_grab_error,
            )
            x_display.sync()
            if grab_failed:
                raise DesktopUnavailableError(
                    "Could not register the dictation shortcut. Another application "
                    "may already be using it; choose another input.hotkey."
                )
            repeats = x_display.get_keyboard_control().auto_repeats
            repeat_mode = (
                X.AutoRepeatModeOn
                if repeats[keycode // 8] & (1 << (keycode % 8))
                else X.AutoRepeatModeOff
            )
            x_display.change_keyboard_control(
                key=keycode, auto_repeat_mode=X.AutoRepeatModeOff
            )
            x_display.sync()
            on_ready()
            pressed = False
            while not self._stopped.is_set():
                if not x_display.pending_events():
                    select.select([x_display.fileno()], [], [], 0.1)
                    continue
                event = x_display.next_event()
                if getattr(event, "detail", None) != keycode:
                    continue
                if event.type == X.KeyPress and not pressed:
                    pressed = True
                    on_press(bool(event.state & X.ShiftMask))
                elif event.type == X.KeyRelease and pressed:
                    pressed = False
                    on_release()
        except error.ConnectionClosedError:
            raise DesktopUnavailableError(
                "The X11 display connection closed."
            ) from None
        finally:
            try:
                try:
                    if root is not None and grab_attempted:
                        with suppress(error.ConnectionClosedError, OSError):
                            root.ungrab_key(keycode, X.AnyModifier)
                            x_display.sync()
                finally:
                    if repeat_mode is not None:
                        with suppress(error.ConnectionClosedError, OSError):
                            x_display.change_keyboard_control(
                                key=keycode, auto_repeat_mode=repeat_mode
                            )
                            x_display.sync()
            finally:
                with suppress(error.ConnectionClosedError, OSError):
                    x_display.close()
