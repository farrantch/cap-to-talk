"""Shared lifecycle and window targeting for native desktop adapters."""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from cap_to_talk.config import Settings
from cap_to_talk.desktop.base import DesktopCheck, DesktopUnavailableError
from cap_to_talk.status import send_status
from cap_to_talk.text import normalize_for_typing

LOGGER = logging.getLogger(__name__)


class NativeDesktop:
    platform_name = ""
    default_hotkey = "f8"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._api: Any = None
        self._targets: dict[str, Any] = {}
        self._target_lock = threading.Lock()
        self._stopped = threading.Event()

    @property
    def hotkey(self) -> str:
        return (
            self.default_hotkey
            if self.settings.hotkey == "auto"
            else self.settings.hotkey
        )

    def _load_api(self) -> Any:
        raise NotImplementedError

    @property
    def api(self) -> Any:
        if self._api is None:
            try:
                self._api = self._load_api()
            except (ImportError, OSError, AttributeError) as error:
                raise DesktopUnavailableError(
                    f"{self.platform_name} desktop libraries are unavailable. "
                    "Reinstall Cap To Talk on this operating system."
                ) from error
        return self._api

    def check(self) -> list[DesktopCheck]:
        return self.api.check(self.hotkey)

    def capture_target(self) -> str:
        target = self.api.foreground_target()
        if target is None:
            raise DesktopUnavailableError(
                "Could not identify the dictation target window."
            )
        token = uuid.uuid4().hex
        with self._target_lock:
            self._targets[token] = target
        return token

    def release_target(self, target: str | None) -> None:
        with self._target_lock:
            self._targets.pop(target, None)

    def _wait_for_pause(self, target: Any) -> None:
        deadline = time.monotonic() + 15
        while not self._stopped.is_set():
            current = self.api.foreground_target()
            switching = current is None or not self.api.same_target(current, target)
            if not self.api.modifiers_pressed() and (
                not switching or self.api.idle_ms() >= 1000
            ):
                return
            if time.monotonic() >= deadline:
                raise DesktopUnavailableError(
                    "Text insertion timed out waiting for input to pause."
                )
            self._stopped.wait(0.05)
        raise DesktopUnavailableError(
            "Dictation stopped before text could be inserted."
        )

    def insert_text(self, text: str, target: str | None, *, delay_ms: int = 0) -> None:
        with self._target_lock:
            destination = self._targets.get(target)
        if destination is None or not self.api.window_exists(destination):
            raise DesktopUnavailableError(
                "The original dictation target window no longer exists."
            )
        self._wait_for_pause(destination)
        previous = self.api.foreground_target()
        changed = previous is None or not self.api.same_target(previous, destination)
        try:
            if changed:
                self.api.activate(destination)
            # Verify focus for each character, including after a configurable delay.
            for char in normalize_for_typing(text):
                current = self.api.foreground_target()
                if self._stopped.is_set():
                    raise DesktopUnavailableError(
                        "Dictation stopped during text insertion."
                    )
                if (
                    current is None
                    or not self.api.same_target(current, destination)
                    or not self.api.window_exists(destination)
                    or self.api.modifiers_pressed()
                ):
                    raise DesktopUnavailableError(
                        "Window focus or modifiers changed during text insertion."
                    )
                self.api.type_character(char)
                if delay_ms:
                    self._stopped.wait(delay_ms / 1000)
        finally:
            current = self.api.foreground_target()
            # Do not undo a window switch the user made while insertion was running.
            if (
                changed
                and previous is not None
                and current is not None
                and self.api.same_target(current, destination)
                and self.api.window_exists(previous)
            ):
                try:
                    self.api.activate(previous)
                except DesktopUnavailableError:
                    LOGGER.warning("Could not restore the previous window focus")

    def notify(self, message: str, timeout: int = 1500) -> None:
        LOGGER.info("%s", message)
        send_status(self.settings, message)

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
            f"{item.name}: {item.detail}"
            for item in self.check()
            if item.required and not item.ok
        ]
        if failures:
            raise DesktopUnavailableError("; ".join(failures))
        events: queue.Queue[tuple[str, Any]] = queue.Queue()

        def listen() -> None:
            try:
                self.api.listen(
                    self.hotkey,
                    lambda pressed, raw: events.put(
                        ("press" if pressed else "release", raw)
                    ),
                    lambda: events.put(("ready", None)),
                    self._stopped,
                )
            except Exception as error:
                events.put(("error", error))
            finally:
                events.put(("stopped", None))

        listener = threading.Thread(
            target=listen, name="dictation-shortcut", daemon=True
        )
        listener.start()
        deadline = time.monotonic() + 5
        ready = False
        pressed = False
        try:
            while True:
                try:
                    kind, value = events.get(timeout=0.1)
                except queue.Empty:
                    if not ready and time.monotonic() >= deadline:
                        raise DesktopUnavailableError(
                            "The dictation shortcut did not start."
                        ) from None
                    continue
                if kind == "ready" and not ready:
                    ready = True
                    on_ready()
                elif kind == "press" and ready and not pressed:
                    pressed = True
                    on_press(bool(value))
                elif kind == "release" and ready and pressed:
                    pressed = False
                    on_release()
                elif kind == "error":
                    if isinstance(value, DesktopUnavailableError):
                        raise value
                    raise DesktopUnavailableError(
                        "The native shortcut listener failed."
                    ) from value
                elif kind == "stopped":
                    if self._stopped.is_set():
                        return
                    raise DesktopUnavailableError(
                        "The native shortcut listener stopped."
                    )
        finally:
            self._stopped.set()
            listener.join(timeout=2)
            with self._target_lock:
                self._targets.clear()
