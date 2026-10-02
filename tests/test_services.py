import base64
import io
import wave
from typing import Any

import numpy as np
import pytest

from cap_to_talk.config import ProviderSettings, Settings
from cap_to_talk.providers import ProviderError
from cap_to_talk.services import LocalServices


class FakeResponse:
    def __init__(self, payload: dict[str, Any] | None = None, text: str = ""):
        self.payload = payload
        self.status_code = 200
        self.headers = {}
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        if self.payload is None:
            raise ValueError
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.upload: io.BytesIO | None = None

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if "files" in kwargs:
            self.upload = kwargs["files"]["file"][1]
            assert isinstance(self.upload, io.BytesIO)
            assert self.upload.read(4) == b"RIFF"
            self.upload.seek(0)
        return self.response


def test_transcribe_uploads_memory_audio_and_closes_it():
    session = FakeSession(FakeResponse({"text": "hello"}))
    services = LocalServices(
        Settings(),
        ["OpenASR"],
        [],
        session=session,  # type: ignore[arg-type]
    )
    audio = np.zeros((4_000, 1), dtype=np.float32)

    assert services.transcribe(audio) == "hello"
    assert session.upload is not None
    assert session.upload.closed
    assert ("hotword", "OpenASR") in session.calls[0]["data"]


def test_rewrite_uses_relevant_terms_and_strips_quotes():
    session = FakeSession(FakeResponse({"message": {"content": '"Use OpenASR."'}}))
    services = LocalServices(
        Settings(),
        [],
        ["OpenASR", "PostgreSQL"],
        session=session,  # type: ignore[arg-type]
    )

    assert services.rewrite("please use open asr for this sentence") == "Use OpenASR."
    system_prompt = session.calls[0]["json"]["messages"][0]["content"]
    assert "OpenASR" in system_prompt
    assert "PostgreSQL" not in system_prompt


def test_short_transcript_skips_rewrite_service():
    session = FakeSession(FakeResponse())
    services = LocalServices(Settings(), [], [], session=session)  # type: ignore[arg-type]

    assert services.rewrite("short raw text") == "short raw text"
    assert session.calls == []


def test_disabled_cleanup_preserves_even_long_transcripts_without_requests():
    session = FakeSession(FakeResponse())
    services = LocalServices(
        Settings(rewrite=ProviderSettings(provider="none")), [], [], session=session
    )
    text = "This is a long raw transcript that should be kept exactly."
    assert services.rewrite(text) == text
    assert session.calls == []


def test_transcription_failure_closes_memory_audio():
    response = FakeResponse({"error": "provider failure"})
    response.status_code = 500
    session = FakeSession(response)
    services = LocalServices(Settings(), [], [], session=session)
    with pytest.raises(ProviderError, match="HTTP 500"):
        services.transcribe(np.zeros((4000, 1), dtype=np.float32))
    assert session.upload is not None
    assert session.upload.closed


@pytest.mark.parametrize("raw_mode", [False, True])
@pytest.mark.parametrize("send_hotwords", [False, True])
def test_single_model_encodes_wav_and_uses_only_selected_provider(
    tmp_path, monkeypatch, raw_mode, send_hotwords
):
    from cap_to_talk import services as services_module

    def unexpected(*args, **kwargs):
        raise AssertionError("Inactive providers must not be created")

    monkeypatch.setattr(services_module, "create_transcriber", unexpected)
    monkeypatch.setattr(services_module, "create_rewriter", unexpected)
    settings = Settings(
        pipeline_mode="single",
        dictation=ProviderSettings(
            provider="openai-compatible",
            url="http://127.0.0.1:9000/v1/chat/completions",
            model="audio-model",
            send_hotwords=send_hotwords,
        ),
    )
    # Keep meaningful quotes when the audio model returns them.
    result = '"Keep this quoted message."'
    session = FakeSession(
        FakeResponse(
            {"choices": [{"message": {"content": result}, "finish_reason": "stop"}]}
        )
    )
    services = LocalServices(
        settings, ["OpenASR"], ["PrivateMasterTerm"], session=session
    )
    audio = np.array([[-2], [-0.5], [0], [0.5], [2]], dtype=np.float32)

    assert services.dictate(audio, raw_mode=raw_mode) == result
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == settings.dictation_config.url
    assert call["headers"] == {}
    messages = call["json"]["messages"]
    prompt = messages[0]["content"]
    assert ("Transcribe the recording verbatim" in prompt) is raw_mode
    assert ("Clean up:" in prompt) is not raw_mode
    assert ("OpenASR" in prompt) is send_hotwords
    assert "PrivateMasterTerm" not in prompt

    encoded = messages[1]["content"][1]["input_audio"]["data"]
    with wave.open(io.BytesIO(base64.b64decode(encoded)), "rb") as recording:
        assert recording.getnchannels() == 1
        assert recording.getsampwidth() == 2
        assert recording.getframerate() == settings.rate
        samples = np.frombuffer(recording.readframes(5), dtype="<i2")
        np.testing.assert_array_equal(samples, [-32767, -16383, 0, 16383, 32767])
    assert list(tmp_path.iterdir()) == []


def test_single_model_failure_does_not_write_audio_or_retry(tmp_path):
    response = FakeResponse({"error": "request failed"})
    response.status_code = 500
    session = FakeSession(response)
    services = LocalServices(
        Settings(
            pipeline_mode="single",
            dictation=ProviderSettings(
                provider="openai-compatible",
                url="https://audio.example/v1/chat/completions",
                model="audio-model",
            ),
        ),
        [],
        [],
        session=session,
    )
    with pytest.raises(ProviderError, match="HTTP 500"):
        services.dictate(np.zeros((4000, 1), dtype=np.float32))
    assert len(session.calls) == 1
    assert list(tmp_path.iterdir()) == []
