from pathlib import Path
from typing import Any

import numpy as np

from caps_talk.config import Settings
from caps_talk.services import LocalServices


class FakeResponse:
    def __init__(self, payload: dict[str, Any] | None = None, text: str = ""):
        self.payload = payload
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
        self.upload_path: Path | None = None

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if "files" in kwargs:
            self.upload_path = Path(kwargs["files"]["file"][1].name)
            assert self.upload_path.exists()
        return self.response


def test_transcribe_deletes_temporary_audio():
    session = FakeSession(FakeResponse({"text": "hello"}))
    services = LocalServices(
        Settings(),
        ["OpenASR"],
        [],
        session=session,  # type: ignore[arg-type]
    )
    audio = np.zeros((4_000, 1), dtype=np.float32)

    assert services.transcribe(audio) == "hello"
    assert session.upload_path is not None
    assert not session.upload_path.exists()
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
