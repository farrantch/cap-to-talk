"""HTTP adapters for transcription, cleanup, and audio dictation providers."""

from __future__ import annotations

import base64
import os
import time
from typing import Any, BinaryIO, Protocol

import requests

from cap_to_talk.config import ProviderSettings


class ProviderError(RuntimeError):
    """An actionable provider failure that contains no credentials or transcript."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class Transcriber(Protocol):
    def transcribe(
        self, audio_file: BinaryIO, hotwords: list[str], hotword_boost: float
    ) -> str: ...


class Rewriter(Protocol):
    def rewrite(self, system_prompt: str, user_prompt: str) -> str: ...


class AudioDictation(Protocol):
    def dictate(self, audio_file: BinaryIO, system_prompt: str) -> str: ...


class HTTPProvider:
    def __init__(
        self, config: ProviderSettings, session: requests.Session | None = None
    ) -> None:
        self.config = config
        self.session = session or requests.Session()

    def headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.config.provider == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
        if self.config.api_key_env:
            if self.config.api_key_source == "keyring":
                from cap_to_talk.credentials import CredentialError, read_key

                try:
                    key = read_key(self.config).strip()
                except CredentialError as error:
                    raise ProviderError(str(error)) from None
            else:
                key = os.environ.get(self.config.api_key_env, "").strip()
            if not key:
                if self.config.api_key_source == "keyring":
                    raise ProviderError(
                        "No saved API key for this endpoint. Add it in Settings."
                    )
                raise ProviderError(
                    f"Set the {self.config.api_key_env} environment variable "
                    f"for {self.config.provider}."
                )
            if self.config.provider == "anthropic":
                headers["x-api-key"] = key
            else:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def request(
        self, method: str, *, health_check: bool = False, **kwargs: Any
    ) -> requests.Response:
        headers = self.headers()
        try:
            response = self.session.request(
                method,
                self.config.health_url if health_check else self.config.url,
                headers=headers,
                timeout=(
                    min(3, self.config.timeout_seconds)
                    if health_check
                    else self.config.timeout_seconds
                ),
                # Do not forward audio, transcripts, or API keys to a redirect target.
                allow_redirects=False,
                **kwargs,
            )
        except requests.Timeout:
            raise ProviderError(
                f"{self.config.provider} request timed out.", retryable=True
            ) from None
        except requests.RequestException:
            raise ProviderError(
                f"Could not connect to {self.config.provider}; "
                "check its URL and connection.",
                retryable=True,
            ) from None
        if not 200 <= response.status_code < 300:
            raise ProviderError(
                f"{self.config.provider} returned HTTP {response.status_code}; "
                "check the endpoint, model, API key, and provider limits.",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        return response

    def json_response(self, response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            raise ProviderError(
                f"{self.config.provider} returned invalid JSON."
            ) from None
        if not isinstance(data, dict):
            raise ProviderError(
                f"{self.config.provider} returned an unexpected response."
            )
        return data


class OpenAITranscriber(HTTPProvider):
    def form_data(
        self, hotwords: list[str], hotword_boost: float
    ) -> list[tuple[str, str]]:
        data = [("model", self.config.model), ("response_format", "json")]
        if hotwords and self.config.send_hotwords:
            data.append(("prompt", ", ".join(hotwords)))
        return data

    def transcribe(
        self, audio_file: BinaryIO, hotwords: list[str], hotword_boost: float
    ) -> str:
        response = self.request(
            "POST",
            files={"file": ("speech.wav", audio_file, "audio/wav")},
            data=self.form_data(hotwords, hotword_boost),
        )
        if (
            self.config.provider == "openasr"
            and response.headers.get("Content-Type", "").split(";")[0] == "text/plain"
        ):
            return response.text.strip()
        text = self.json_response(response).get("text")
        if not isinstance(text, str):
            raise ProviderError(
                f"{self.config.provider} returned no transcription text."
            )
        return text.strip()


class OpenASRTranscriber(OpenAITranscriber):
    def form_data(
        self, hotwords: list[str], hotword_boost: float
    ) -> list[tuple[str, str]]:
        data = [("model", self.config.model), ("response_format", "json")]
        if hotwords and self.config.send_hotwords:
            data.append(("hotword_boost", str(hotword_boost)))
            data.extend(("hotword", word) for word in hotwords)
        return data


class OllamaRewriter(HTTPProvider):
    def rewrite(self, system_prompt: str, user_prompt: str) -> str:
        response = self.request(
            "POST",
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "think": False,
                "keep_alive": "5m",
                "options": {
                    "temperature": 0.0,
                    "num_predict": self.config.max_output_tokens,
                },
            },
        )
        data = self.json_response(response)
        if data.get("done_reason") == "length":
            raise ProviderError("ollama cleanup exceeded the output token limit.")
        message = data.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise ProviderError("ollama returned no cleanup text.")
        return text.strip()


class OpenAIChatProvider(HTTPProvider):
    def complete(
        self, messages: list[dict[str, Any]], *, task: str, **options: Any
    ) -> str:
        token_parameter = (
            "max_completion_tokens"
            if self.config.provider == "openai"
            else "max_tokens"
        )
        response = self.request(
            "POST",
            json={
                "model": self.config.model,
                "messages": messages,
                "stream": False,
                token_parameter: self.config.max_output_tokens,
                **options,
            },
        )
        data = self.json_response(response)
        choices = data.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise ProviderError(f"{self.config.provider} returned no {task} choices.")
        choice = choices[0]
        if choice.get("finish_reason") not in (None, "stop"):
            raise ProviderError(f"{self.config.provider} did not finish the {task}.")
        message = choice.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or message.get("refusal"):
            raise ProviderError(f"{self.config.provider} returned no {task} text.")
        return text.strip()


class OpenAIRewriter(OpenAIChatProvider):
    def rewrite(self, system_prompt: str, user_prompt: str) -> str:
        return self.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            task="cleanup",
        )


class OpenAIAudioDictation(OpenAIChatProvider):
    def dictate(self, audio_file: BinaryIO, system_prompt: str) -> str:
        encoded_audio = base64.b64encode(audio_file.read()).decode("ascii")
        # Text is the default output. Only send the explicit modalities option
        # to OpenAI, since compatible servers do not all accept this parameter.
        options = {"modalities": ["text"]} if self.config.provider == "openai" else {}
        return self.complete(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Produce the requested dictation from this recording."
                            ),
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {"data": encoded_audio, "format": "wav"},
                        },
                    ],
                },
            ],
            task="dictation",
            **options,
        )


class AnthropicRewriter(HTTPProvider):
    def rewrite(self, system_prompt: str, user_prompt: str) -> str:
        response = self.request(
            "POST",
            json={
                "model": self.config.model,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
                "max_tokens": self.config.max_output_tokens,
                "stream": False,
            },
        )
        data = self.json_response(response)
        if data.get("stop_reason") not in (None, "end_turn", "stop_sequence"):
            raise ProviderError("anthropic did not finish the cleanup.")
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise ProviderError("anthropic returned no cleanup text.")
        parts = [
            block["text"]
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        if not parts:
            raise ProviderError("anthropic returned no cleanup text.")
        return "".join(parts).strip()


class NoRewrite:
    def rewrite(self, system_prompt: str, user_prompt: str) -> str:
        return ""


def create_transcriber(
    config: ProviderSettings, session: requests.Session | None = None
) -> Transcriber:
    adapters = {
        "openasr": OpenASRTranscriber,
        "openai": OpenAITranscriber,
        "openai-compatible": OpenAITranscriber,
    }
    if config.provider not in adapters:
        raise ValueError("Unsupported transcription provider")
    return adapters[config.provider](config, session)


def create_rewriter(
    config: ProviderSettings, session: requests.Session | None = None
) -> Rewriter:
    if config.provider == "none":
        return NoRewrite()
    adapters = {
        "ollama": OllamaRewriter,
        "openai": OpenAIRewriter,
        "openai-compatible": OpenAIRewriter,
        "anthropic": AnthropicRewriter,
    }
    if config.provider not in adapters:
        raise ValueError("Unsupported cleanup provider")
    return adapters[config.provider](config, session)


def create_audio_dictation(
    config: ProviderSettings, session: requests.Session | None = None
) -> AudioDictation:
    if config.provider not in ("openai", "openai-compatible"):
        raise ValueError("Unsupported audio dictation provider")
    return OpenAIAudioDictation(config, session)


def check_provider(
    config: ProviderSettings,
    session: requests.Session | None = None,
    *,
    wait_seconds: int = 0,
) -> tuple[bool, str]:
    if config.provider == "none":
        return True, "disabled"
    client = HTTPProvider(config, session)
    try:
        client.headers()
        if not config.health_url:
            return True, "configured; connectivity not tested (no health_url)"
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                response = client.request("GET", health_check=True)
                return (
                    True,
                    f"HTTP {response.status_code}; model availability not tested",
                )
            except ProviderError as error:
                remaining = deadline - time.monotonic()
                if not error.retryable or remaining <= 0:
                    raise
                time.sleep(min(1, remaining))
    except ProviderError as error:
        return False, str(error)
    finally:
        if session is None:
            client.session.close()
