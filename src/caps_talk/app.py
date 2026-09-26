"""Push-to-talk recording application."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np
import sounddevice as sd
from Xlib import X, display

from caps_talk.config import Settings
from caps_talk.glossary import load_terms
from caps_talk.services import LocalServices
from caps_talk.status import notify, send_status
from caps_talk.x11 import get_active_window_id, type_text

LOGGER = logging.getLogger(__name__)


class VoiceDictationApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.recording = False
        self.transcribing = False
        self.frames: list[np.ndarray[Any, Any]] = []
        self.stream: sd.InputStream | None = None
        self.current_raw_mode = False
        self.current_target_window: str | None = None
        self.lock = threading.Lock()

        assert settings.hotwords_file is not None
        assert settings.master_hotwords_file is not None
        hotwords = load_terms(
            settings.hotwords_file,
            max_terms=128,
            max_chars=4_000,
        )
        master_terms = load_terms(settings.master_hotwords_file) or list(hotwords)
        self.services = LocalServices(settings, hotwords, master_terms)
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
            if self.recording or self.transcribing:
                return

            self.frames = []
            self.recording = True
            self.current_raw_mode = raw_mode
            self.current_target_window = get_active_window_id()

            try:
                self.stream = sd.InputStream(
                    samplerate=self.settings.rate,
                    channels=self.settings.channels,
                    dtype="float32",
                    callback=self._audio_callback,
                )
                self.stream.start()
            except Exception:
                self.recording = False
                self.stream = None
                LOGGER.exception("Unable to start microphone input")
                notify(self.settings, "⚠ Microphone error", 3_000)
                return

        if raw_mode:
            LOGGER.info("Recording in raw mode")
            notify(self.settings, "🎙 Recording — RAW", 60_000)
            send_status(self.settings, "🎙 Recording — RAW")
        else:
            LOGGER.info("Recording")
            notify(self.settings, "🎙 Recording", 60_000)
            send_status(self.settings, "🎙 Recording")

    def stop_recording(self) -> None:
        time.sleep(self.settings.post_roll_seconds)

        with self.lock:
            if not self.recording:
                return
            self.recording = False
            try:
                if self.stream is not None:
                    self.stream.stop()
                    self.stream.close()
            finally:
                self.stream = None

            captured = list(self.frames)
            raw_mode = self.current_raw_mode
            target_window = self.current_target_window

        if not captured:
            notify(self.settings, "No audio captured")
            send_status(self.settings, "⚠ No audio captured")
            return

        audio = np.concatenate(captured, axis=0)
        if len(audio) < self.settings.rate * 0.2:
            notify(self.settings, "Recording too short")
            send_status(self.settings, "⚠ Recording too short")
            return

        with self.lock:
            self.transcribing = True

        LOGGER.info("Transcribing")
        notify(self.settings, "⏳ Transcribing…", 60_000)
        send_status(self.settings, "⏳ Transcribing")
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
            raw_text = self.services.transcribe(audio)
            if not raw_text:
                notify(self.settings, "No speech recognized")
                send_status(self.settings, "⚠ No speech")
                return

            if self.settings.debug_transcripts:
                LOGGER.debug("Raw transcript: %s", raw_text)

            final_text = raw_text
            if not raw_mode:
                notify(self.settings, "✨ Cleaning up…", 60_000)
                send_status(self.settings, "✨ Cleaning up")
                try:
                    final_text = self.services.rewrite(raw_text)
                except Exception:
                    LOGGER.exception("Rewrite failed; using the raw transcript")
                    notify(self.settings, "⚠ Rewrite failed — using raw text", 2_000)

            if self.settings.debug_transcripts:
                LOGGER.debug("Final transcript: %s", final_text)

            send_status(self.settings, "⌨ Inserting…")
            type_text(
                final_text,
                target_window,
                delay_ms=self.settings.typing_delay_ms,
            )
            notify(self.settings, "✓ Dictated", 800)
            send_status(self.settings, "✓ Done")
        except Exception:
            LOGGER.exception("Dictation failed")
            notify(self.settings, "⚠ Dictation failed", 3_000)
            send_status(self.settings, "⚠ Dictation failed")
        finally:
            with self.lock:
                self.transcribing = False

    def close(self) -> None:
        with self.lock:
            self.recording = False
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
                self.stream = None

    def run(self) -> None:
        x_display = display.Display()
        root = x_display.screen().root
        root.grab_key(
            self.settings.ptt_keycode,
            X.AnyModifier,
            False,
            X.GrabModeAsync,
            X.GrabModeAsync,
        )
        x_display.sync()
        LOGGER.info("Caps Talk ready")
        notify(self.settings, "Caps Talk ready", 1_200)

        try:
            while True:
                event = x_display.next_event()
                if (
                    event.type == X.KeyPress
                    and event.detail == self.settings.ptt_keycode
                ):
                    self.start_recording(raw_mode=bool(event.state & X.ShiftMask))
                elif (
                    event.type == X.KeyRelease
                    and event.detail == self.settings.ptt_keycode
                ):
                    self.stop_recording()
        finally:
            self.close()
            root.ungrab_key(self.settings.ptt_keycode, X.AnyModifier)
            x_display.sync()
            x_display.close()
