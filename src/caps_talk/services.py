"""Clients for the local OpenASR and Ollama services."""

from __future__ import annotations

import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np
import requests

from caps_talk.config import Settings
from caps_talk.glossary import select_relevant_terms
from caps_talk.text import strip_wrapping_quotes

LOGGER = logging.getLogger(__name__)

REWRITE_PROMPT = """
Rewrite my spoken dictation into the message I intended to type.

The input comes from automatic speech recognition, so some words,
punctuation, names, or technical terms may be wrong.

Write in my voice and from my point of view.

Clean up:
- filler words
- stutters
- repeated fragments
- abandoned false starts
- awkward spoken grammar

Preserve:
- every meaningful idea and detail
- questions and requests
- uncertainty such as "I think", "maybe", "might", or "I'm not sure"
- alternatives and caveats
- reasons and examples
- technical details, names, numbers, commands, paths, and paragraph breaks
- my casual tone and profanity

If I correct myself while speaking, keep the corrected thought.

You may reorganize the text or use paragraphs when that makes my meaning
clearer, but do not summarize away distinct information.

A long ramble may become short if it genuinely repeats one idea.
A short statement may stay detailed if it contains many separate ideas.

Correct likely ASR mistakes when the intended wording is clear from context
or the supplied technical spellings.

Do not answer my message.
Do not explain it.
Do not describe me or refer to "the speaker", "the user", or "the transcript".

Output only the message I intended to type.
""".strip()


class LocalServices:
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
        self.session = session or requests.Session()

    def transcribe(self, audio: np.ndarray[Any, Any]) -> str:
        pcm = np.clip(audio[:, 0], -1.0, 1.0)
        pcm = (pcm * 32_767).astype(np.int16)
        file_descriptor, filename = tempfile.mkstemp(suffix=".wav")
        os.close(file_descriptor)
        path = Path(filename)

        try:
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.settings.rate)
                wav_file.writeframes(pcm.tobytes())

            form_data: list[tuple[str, str]] = [
                ("model", self.settings.asr_model),
                ("response_format", "json"),
            ]
            if self.hotwords:
                form_data.append(("hotword_boost", str(self.settings.hotword_boost)))
                form_data.extend(("hotword", word) for word in self.hotwords)

            with path.open("rb") as audio_file:
                response = self.session.post(
                    self.settings.asr_url,
                    files={"file": ("speech.wav", audio_file, "audio/wav")},
                    data=form_data,
                    timeout=120,
                )

            response.raise_for_status()
            try:
                result = response.json()
            except ValueError:
                return response.text.strip()
            return str(result.get("text", "")).strip()
        finally:
            path.unlink(missing_ok=True)

    def rewrite(self, text: str) -> str:
        if len(text.split()) <= 4:
            return text

        relevant_terms = select_relevant_terms(text, self.master_terms)
        prompt = REWRITE_PROMPT
        if relevant_terms:
            prompt += "\n\nLikely relevant technical spellings:\n"
            prompt += "\n".join(f"- {term}" for term in relevant_terms)

        LOGGER.debug("Selected rewrite glossary terms: %s", relevant_terms)
        payload = {
            "model": self.settings.rewrite_model,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "Rewrite this raw speech transcript into the clear "
                        "written thought the speaker intended:\n\n" + text
                    ),
                },
            ],
            "stream": False,
            "think": False,
            "keep_alive": "5m",
            "options": {"temperature": 0.0, "num_predict": 1024},
        }
        response = self.session.post(
            self.settings.ollama_url,
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        rewritten = str(response.json().get("message", {}).get("content", "")).strip()
        return strip_wrapping_quotes(rewritten) if rewritten else text
