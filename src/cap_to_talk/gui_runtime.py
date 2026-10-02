"""Background work for the desktop window. Qt widgets stay on the GUI thread."""

from __future__ import annotations

import sys
import threading
from contextlib import nullcontext
from typing import Any

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, Signal

from cap_to_talk.app import VoiceDictationApp
from cap_to_talk.config import Settings
from cap_to_talk.desktop import create_desktop_backend
from cap_to_talk.providers import check_provider


def active_providers(settings: Settings) -> list[tuple[str, Any, bool]]:
    if settings.pipeline_mode == "single":
        return [("Dictation", settings.dictation_config, True)]
    return [
        ("Transcription", settings.transcription_config, True),
        ("Cleanup", settings.rewrite_config, False),
    ]


def check_setup(settings: Settings) -> str:
    lines = []
    for item in create_desktop_backend(settings).check():
        label = "PASS" if item.ok else "FAIL" if item.required else "WARN"
        lines.append(f"[{label}] {item.name}: {item.detail}")
    try:
        device = sd.query_devices(settings.audio_device, kind="input")
        lines.append(f"[PASS] Microphone: {device['name']}")
    except Exception:
        lines.append(
            "[FAIL] Microphone: check the selected device and microphone permission."
        )
    for name, config, required in active_providers(settings):
        ok, detail = check_provider(config)
        label = "PASS" if ok else "FAIL" if required else "WARN"
        lines.append(f"[{label}] {name}: {detail}")
    return "\n".join(lines)


def test_microphone(settings: Settings) -> str:
    audio = sd.rec(
        int(settings.rate * 3),
        samplerate=settings.rate,
        channels=1,
        dtype="float32",
        device=settings.audio_device,
        blocking=True,
    )
    peak = float(np.max(np.abs(audio)))
    if peak < 0.005:
        return (
            "Recording finished, but the input was very quiet. "
            "Check the microphone and try again."
        )
    return (
        f"Microphone recorded successfully (peak {min(100, round(peak * 100))}%). "
        "No audio was saved or sent."
    )


class StatusDesktop:
    def __init__(self, backend: Any, status: Any, stopped: threading.Event) -> None:
        self.backend = backend
        self.status = status
        self.stopped = stopped

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)

    def notify(self, message: str, timeout: int = 1500) -> None:
        if not self.stopped.is_set():
            self.status.emit(message)


class DictationController(QObject):
    status = Signal(str)
    finished = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.thread: threading.Thread | None = None
        self.application: VoiceDictationApp | None = None
        self.stopped = threading.Event()

    def start(self, settings: Settings) -> None:
        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("Dictation is already running.")
        self.stopped.clear()
        self.thread = threading.Thread(target=self._run, args=(settings,), daemon=True)
        self.thread.start()

    def _run(self, settings: Settings) -> None:
        error_message = ""
        try:
            self.status.emit("Checking providers…")
            for name, config, required in active_providers(settings):
                if self.stopped.is_set():
                    return
                ok, detail = check_provider(config)
                if not ok and required:
                    raise RuntimeError(f"{name}: {detail}")
            if self.stopped.is_set():
                return
            backend = create_desktop_backend(settings)
            self.application = VoiceDictationApp(
                settings, desktop=StatusDesktop(backend, self.status, self.stopped)
            )
            if self.stopped.is_set():
                self.application.request_stop()
                return
            context = nullcontext()
            if sys.platform == "linux":
                from cap_to_talk.desktop.linux_keyboard import prepared_keyboard

                failures = [
                    item.detail
                    for item in backend.check()
                    if item.required and not item.ok
                ]
                if failures:
                    raise RuntimeError("; ".join(failures))
                context = prepared_keyboard(settings)
            with context:
                self.application.run()
        except Exception as error:
            if not self.stopped.is_set():
                error_message = str(error)
        finally:
            try:
                if self.application is not None:
                    self.application.close()
            except Exception as error:
                error_message = error_message or str(error)
            finally:
                self.application = None
                self.finished.emit(error_message)

    def stop(self) -> None:
        self.stopped.set()
        if self.application is not None:
            self.application.request_stop()
