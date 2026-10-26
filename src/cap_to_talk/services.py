"""Provider-independent dictation pipelines."""

from __future__ import annotations

import io
import logging
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, BinaryIO

import numpy as np
import requests

from cap_to_talk.config import Settings
from cap_to_talk.glossary import select_relevant_terms
from cap_to_talk.prompts import AUDIO_DICTATION_PROMPT, RAW_AUDIO_PROMPT, REWRITE_PROMPT
from cap_to_talk.providers import (
    AudioDictation,
    Rewriter,
    Transcriber,
    create_audio_dictation,
    create_rewriter,
    create_transcriber,
)
from cap_to_talk.text import strip_wrapping_quotes

LOGGER = logging.getLogger(__name__)


class DictationServices:
    def __init__(
        self,
        settings: Settings,
        hotwords: list[str],
        master_terms: list[str],
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.hotwords = hotwords
        self.master_terms = master_terms
        self.transcriber: Transcriber | None = None
        self.rewriter: Rewriter | None = None
        self.audio_dictation: AudioDictation | None = None
        if settings.pipeline_mode == "single":
            self.audio_dictation = create_audio_dictation(
                settings.dictation_config, session
            )
        else:
            self.transcriber = create_transcriber(
                settings.transcription_config, session
            )
            self.rewriter = create_rewriter(settings.rewrite_config, session)

    @contextmanager
    def _audio_file(self, audio: np.ndarray[Any, Any]) -> Iterator[BinaryIO]:
        pcm = np.clip(audio[:, 0], -1.0, 1.0)
        pcm = (pcm * 32_767).astype("<i2")
        # Keep audio in memory so quitting during a request cannot leave a WAV on disk.
        with io.BytesIO() as audio_file:
            with wave.open(audio_file, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.settings.rate)
                wav_file.writeframes(pcm.tobytes())
            audio_file.seek(0)
            yield audio_file

    def transcribe(self, audio: np.ndarray[Any, Any]) -> str:
        if self.transcriber is None:
            raise RuntimeError("Transcription is only available in two-stage mode")
        with self._audio_file(audio) as audio_file:
            return self.transcriber.transcribe(
                audio_file, self.hotwords, self.settings.hotword_boost
            )

    def dictate(self, audio: np.ndarray[Any, Any], *, raw_mode: bool = False) -> str:
        if self.audio_dictation is None:
            raise RuntimeError("Audio dictation is only available in single mode")
        prompt = RAW_AUDIO_PROMPT if raw_mode else AUDIO_DICTATION_PROMPT
        if self.hotwords and self.settings.dictation_config.send_hotwords:
            prompt += (
                "\n\nReference spellings; use only when heard in the recording:\n"
                + "\n".join(f"- {word}" for word in self.hotwords)
            )
        with self._audio_file(audio) as audio_file:
            return self.audio_dictation.dictate(audio_file, prompt)

    def rewrite(self, text: str) -> str:
        if self.rewriter is None:
            raise RuntimeError("Cleanup is only available in two-stage mode")
        if self.settings.rewrite_config.provider == "none" or len(text.split()) <= 4:
            return text

        relevant_terms = select_relevant_terms(text, self.master_terms)
        prompt = REWRITE_PROMPT
        if relevant_terms:
            prompt += "\n\nLikely relevant technical spellings:\n"
            prompt += "\n".join(f"- {term}" for term in relevant_terms)

        LOGGER.debug("Selected rewrite glossary terms: %s", relevant_terms)
        user_prompt = (
            "Rewrite this raw speech transcript into the clear "
            "written thought the speaker intended:\n\n" + text
        )
        rewritten = self.rewriter.rewrite(prompt, user_prompt)
        return strip_wrapping_quotes(rewritten) if rewritten else text


# Preserve imports used by existing integrations.
LocalServices = DictationServices
