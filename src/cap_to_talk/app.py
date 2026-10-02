"""Push-to-talk recording application."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import suppress
from typing import Any

import numpy as np
import sounddevice as sd

from cap_to_talk.config import Settings
from cap_to_talk.desktop import DesktopBackend, create_desktop_backend
from cap_to_talk.glossary import load_terms
from cap_to_talk.services import DictationServices
from cap_to_talk.status import send_status

LOGGER = logging.getLogger(__name__)


class VoiceDictationApp:
    def __init__(
        self, settings: Settings, *, desktop: DesktopBackend | None = None
    ) -> None:
        self.settings = settings
        self.desktop = (
            desktop if desktop is not None else create_desktop_backend(settings)
        )
        self.recording = False
        self.transcribing = False
        self.frames: list[np.ndarray[Any, Any]] = []
        self.stream: sd.InputStream | None = None
        self.current_raw_mode = False
        self.current_target_window: str | None = None
        self.lock = threading.Lock()
        self._closed = threading.Event()

        assert settings.hotwords_file is not None
        assert settings.master_hotwords_file is not None
        hotwords = load_terms(
            settings.hotwords_file,
            max_terms=128,
            max_chars=4_000,
        )
        master_terms = load_terms(settings.master_hotwords_file) or list(hotwords)
        self.services = DictationServices(settings, hotwords, master_terms)
        LOGGER.info(
            "Loaded %d recognition hotwords and %d glossary terms",
            len(hotwords),
            len(master_terms),
        )

    def _audio_callback(
        self,
        indata: np.ndarray[Any, Any],
        _frame_count: int,
        _time_info: Any,
        status: Any,
    ) -> None:
        if status:
            LOGGER.warning("Audio status: %s", status)
        if self.recording:
            self.frames.append(indata.copy())

    def start_recording(self, *, raw_mode: bool = False) -> None:
        with self.lock:
            if self._closed.is_set() or self.recording or self.transcribing:
                return

            self.frames = []
            self.recording = True
            self.current_raw_mode = raw_mode
            try:
                self.current_target_window = self.desktop.capture_target()
            except Exception:
                self.recording = False
                LOGGER.exception("Unable to capture the dictation target")
                self.desktop.notify("⚠ Cannot identify the target window", 3_000)
                return

            try:
                self.stream = sd.InputStream(
                    samplerate=self.settings.rate,
                    device=self.settings.audio_device,
                    channels=self.settings.channels,
                    dtype="float32",
                    callback=self._audio_callback,
                )
                self.stream.start()
            except Exception:
                self.recording = False
                with suppress(Exception):
                    self._close_stream()
                self.desktop.release_target(self.current_target_window)
                self.current_target_window = None
                LOGGER.exception("Unable to start microphone input")
                self.desktop.notify("⚠ Microphone error", 3_000)
                return

        if raw_mode:
            LOGGER.info("Recording in raw mode")
            self.desktop.notify("🎙 Recording — RAW", 60_000)
            send_status(self.settings, "🎙 Recording — RAW")
        else:
            LOGGER.info("Recording")
            self.desktop.notify("🎙 Recording", 60_000)
            send_status(self.settings, "🎙 Recording")

    def stop_recording(self) -> None:
        time.sleep(self.settings.post_roll_seconds)

        with self.lock:
            if not self.recording:
                return
            self.recording = False
            self._close_stream()

            captured = list(self.frames)
            raw_mode = self.current_raw_mode
            target_window = self.current_target_window

        if not captured:
            self.desktop.release_target(target_window)
            self.desktop.notify("No audio captured")
            send_status(self.settings, "⚠ No audio captured")
            return

        audio = np.concatenate(captured, axis=0)
        if len(audio) < self.settings.rate * 0.2:
            self.desktop.release_target(target_window)
            self.desktop.notify("Recording too short")
            send_status(self.settings, "⚠ Recording too short")
            return

        with self.lock:
            self.transcribing = True

        progress = (
            "Processing dictation"
            if self.settings.pipeline_mode == "single" and not raw_mode
            else "Transcribing"
        )
        LOGGER.info("%s", progress)
        self.desktop.notify(f"⏳ {progress}…", 60_000)
        send_status(self.settings, f"⏳ {progress}")
        threading.Thread(
            target=self._process_audio,
            args=(audio, raw_mode, target_window),
            daemon=True,
        ).start()

    def _process_audio(
        self,
        audio: np.ndarray[Any, Any],
        raw_mode: bool,
        target_window: str | None,
    ) -> None:
        try:
            if self.settings.pipeline_mode == "single":
                final_text = self.services.dictate(audio, raw_mode=raw_mode)
            else:
                raw_text = self.services.transcribe(audio)
                if self.settings.debug_transcripts:
                    LOGGER.debug("Raw transcript: %s", raw_text)

                final_text = raw_text
                if (
                    raw_text
                    and not self._closed.is_set()
                    and not raw_mode
                    and self.settings.rewrite_config.provider != "none"
                ):
                    self.desktop.notify("✨ Cleaning up…", 60_000)
                    send_status(self.settings, "✨ Cleaning up")
                    try:
                        final_text = self.services.rewrite(raw_text)
                    except Exception:
                        LOGGER.exception("Rewrite failed; using the raw transcript")
                        self.desktop.notify("⚠ Rewrite failed — using raw text", 2_000)

            if self._closed.is_set():
                return
            if not final_text:
                self.desktop.notify("No speech recognized")
                send_status(self.settings, "⚠ No speech")
                return

            if self.settings.debug_transcripts:
                LOGGER.debug("Final transcript: %s", final_text)

            send_status(self.settings, "⌨ Inserting…")
            self.desktop.insert_text(
                final_text,
                target_window,
                delay_ms=self.settings.typing_delay_ms,
            )
            self.desktop.notify("✓ Dictated", 800)
            send_status(self.settings, "✓ Done")
        except Exception:
            LOGGER.exception("Dictation failed")
            self.desktop.notify("⚠ Dictation failed", 3_000)
            send_status(self.settings, "⚠ Dictation failed")
        finally:
            self.desktop.release_target(target_window)
            with self.lock:
                self.transcribing = False

    def _close_stream(self) -> None:
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

    def request_stop(self) -> None:
        self._closed.set()
        self.desktop.stop()

    def close(self) -> None:
        self._closed.set()
        with self.lock:
            self.recording = False
            try:
                self._close_stream()
            finally:
                self.desktop.release_target(self.current_target_window)
                self.current_target_window = None

    def _on_ready(self) -> None:
        LOGGER.info("Cap To Talk ready")
        self.desktop.notify("Cap To Talk ready", 1_200)

    def run(self) -> None:
        try:
            self.desktop.run_hotkey_loop(
                on_press=lambda raw_mode: self.start_recording(raw_mode=raw_mode),
                on_release=self.stop_recording,
                on_ready=self._on_ready,
            )
        finally:
            self.close()
