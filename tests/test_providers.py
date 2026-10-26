import base64
import io
import json
from unittest.mock import Mock

import pytest
import requests

from cap_to_talk.config import ProviderSettings
from cap_to_talk.providers import (
    ProviderError,
    check_provider,
    create_audio_dictation,
    create_rewriter,
    create_transcriber,
)


def session_with(payload, *, status=200):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload).encode()
    response.headers["Content-Type"] = "application/json"
    session = Mock(spec=requests.Session)
    session.headers = {}
    session.request.return_value = response
    return session


def config(provider, **kwargs):
    return ProviderSettings(
        provider=provider,
        url="https://provider.example/v1/endpoint",
        model="selected-model",
        **kwargs,
    )


@pytest.mark.parametrize("provider", ["openai", "openai-compatible"])
def test_transcription_uses_selected_model_auth_and_compatible_hints(
    monkeypatch, provider
):
    monkeypatch.setenv("TEST_TRANSCRIPTION_KEY", "test-transcription-token")
    session = session_with({"text": "  Use PostgreSQL.  "})
    adapter = create_transcriber(
        config(provider, api_key_env="TEST_TRANSCRIPTION_KEY", timeout_seconds=45),
        session,
    )
    audio = io.BytesIO(b"audio")
    assert adapter.transcribe(audio, ["PostgreSQL"], 3) == "Use PostgreSQL."

    args, kwargs = session.request.call_args
    assert args == ("POST", "https://provider.example/v1/endpoint")
    assert kwargs["headers"] == {"Authorization": "Bearer test-transcription-token"}
    assert dict(kwargs["data"]) == {
        "model": "selected-model",
        "response_format": "json",
        "prompt": "PostgreSQL",
    }
    assert kwargs["files"]["file"] == ("speech.wav", audio, "audio/wav")
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 45


def test_openasr_preserves_repeated_hotword_fields_without_cloud_auth():
    session = session_with({"text": "hello"})
    adapter = create_transcriber(config("openasr"), session)
    adapter.transcribe(io.BytesIO(), ["One", "Two"], 2.5)
    kwargs = session.request.call_args.kwargs
    assert kwargs["data"][-3:] == [
        ("hotword_boost", "2.5"),
        ("hotword", "One"),
        ("hotword", "Two"),
    ]
    assert kwargs["headers"] == {}


@pytest.mark.parametrize("provider", ["openasr", "openai", "openai-compatible"])
def test_vocabulary_hints_can_be_disabled(provider):
    session = session_with({"text": ""})
    adapter = create_transcriber(config(provider, send_hotwords=False), session)
    assert adapter.transcribe(io.BytesIO(), ["Private glossary"], 3) == ""
    assert dict(session.request.call_args.kwargs["data"]) == {
        "model": "selected-model",
        "response_format": "json",
    }


@pytest.mark.parametrize(
    ("provider", "token_parameter"),
    [("openai", "max_completion_tokens"), ("openai-compatible", "max_tokens")],
)
def test_chat_cleanup_uses_standard_messages_and_selected_model(
    provider, token_parameter
):
    session = session_with(
        {"choices": [{"message": {"content": "Clean text."}, "finish_reason": "stop"}]}
    )
    adapter = create_rewriter(config(provider, max_output_tokens=2048), session)
    assert adapter.rewrite("Instructions", "Original text") == "Clean text."
    assert session.request.call_args.kwargs["json"] == {
        "model": "selected-model",
        "messages": [
            {"role": "system", "content": "Instructions"},
            {"role": "user", "content": "Original text"},
        ],
        "stream": False,
        token_parameter: 2048,
    }


def test_anthropic_uses_its_own_auth_and_message_format(monkeypatch):
    monkeypatch.setenv("TEST_CLEANUP_KEY", "test-anthropic-token")
    session = session_with(
        {
            "stop_reason": "end_turn",
            "content": [
                {"type": "thinking", "thinking": "Do not insert this"},
                {"type": "text", "text": "Clean "},
                {"type": "text", "text": "text."},
            ],
        }
    )
    adapter = create_rewriter(
        config("anthropic", api_key_env="TEST_CLEANUP_KEY", max_output_tokens=2048),
        session,
    )
    assert adapter.rewrite("Instructions", "Original text") == "Clean text."
    kwargs = session.request.call_args.kwargs
    assert kwargs["headers"] == {
        "x-api-key": "test-anthropic-token",
        "anthropic-version": "2023-06-01",
    }
    assert kwargs["json"] == {
        "model": "selected-model",
        "system": "Instructions",
        "messages": [{"role": "user", "content": "Original text"}],
        "max_tokens": 2048,
        "stream": False,
    }


def test_ollama_keeps_local_options_and_has_no_cloud_headers():
    session = session_with({"message": {"content": "Clean text."}})
    adapter = create_rewriter(config("ollama"), session)
    assert adapter.rewrite("Instructions", "Raw text") == "Clean text."
    kwargs = session.request.call_args.kwargs
    assert kwargs["headers"] == {}
    assert kwargs["json"]["options"] == {"temperature": 0.0, "num_predict": 1024}
    assert kwargs["json"]["think"] is False
    assert kwargs["json"]["keep_alive"] == "5m"


def test_api_keys_do_not_leak_between_providers_sharing_a_session(monkeypatch):
    monkeypatch.setenv("TEST_CLEANUP_KEY", "cloud-token")
    session = session_with({"message": {"content": "Clean text."}})
    cloud = create_rewriter(
        config("anthropic", api_key_env="TEST_CLEANUP_KEY"), session
    )
    # An invalid payload still exercises authentication on the cloud request.
    with pytest.raises(ProviderError):
        cloud.rewrite("Instructions", "Raw text")
    create_rewriter(config("ollama"), session).rewrite("Instructions", "Raw text")
    assert (
        session.request.call_args_list[0].kwargs["headers"]["x-api-key"]
        == "cloud-token"
    )
    assert session.request.call_args_list[1].kwargs["headers"] == {}
    assert session.headers == {}


def test_missing_api_key_fails_without_network_request(monkeypatch):
    monkeypatch.delenv("TEST_TRANSCRIPTION_KEY", raising=False)
    session = session_with({"text": "hello"})
    adapter = create_transcriber(
        config("openai", api_key_env="TEST_TRANSCRIPTION_KEY"), session
    )
    with pytest.raises(ProviderError, match="TEST_TRANSCRIPTION_KEY"):
        adapter.transcribe(io.BytesIO(), [], 3)
    session.request.assert_not_called()


@pytest.mark.parametrize("status", [302, 307, 401, 403, 404, 429, 500])
def test_http_errors_do_not_expose_response_body_or_retry_another_provider(status):
    session = session_with({"error": "secret text and token"}, status=status)
    adapter = create_transcriber(config("openai-compatible"), session)
    with pytest.raises(ProviderError, match=f"HTTP {status}") as error:
        adapter.transcribe(io.BytesIO(), [], 3)
    assert "secret" not in str(error.value)
    assert session.request.call_count == 1


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (requests.Timeout("secret in URL"), "timed out"),
        (requests.ConnectionError("secret in URL"), "Could not connect"),
    ],
)
def test_transport_errors_are_redacted(failure, message):
    session = session_with({})
    session.request.side_effect = failure
    adapter = create_rewriter(config("ollama"), session)
    with pytest.raises(ProviderError, match=message) as error:
        adapter.rewrite("Instructions", "Text")
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("payload", [None, [], {}, {"text": None}, {"text": 123}])
def test_invalid_transcription_response_is_not_inserted_as_text(payload):
    session = session_with(payload)
    adapter = create_transcriber(config("openai-compatible"), session)
    with pytest.raises(ProviderError):
        adapter.transcribe(io.BytesIO(), [], 3)


@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        ("openai", {"choices": []}),
        ("openai", {"choices": [{"message": {"content": None}}]}),
        (
            "openai",
            {
                "choices": [
                    {"message": {"content": "Partial"}, "finish_reason": "length"}
                ]
            },
        ),
        (
            "openai",
            {"choices": [{"message": {"content": "Refusal", "refusal": "refused"}}]},
        ),
        ("anthropic", {"content": [{"type": "thinking", "thinking": "Hidden"}]}),
        (
            "anthropic",
            {
                "content": [{"type": "text", "text": "Partial"}],
                "stop_reason": "max_tokens",
            },
        ),
        ("ollama", {"message": {"content": "Partial"}, "done_reason": "length"}),
    ],
)
def test_incomplete_cleanup_is_rejected_so_app_can_keep_raw_text(provider, payload):
    session = session_with(payload)
    adapter = create_rewriter(config(provider), session)
    with pytest.raises(ProviderError):
        adapter.rewrite("Instructions", "Original transcript")


def test_health_check_uses_auth_without_transmitting_audio_or_text(monkeypatch):
    monkeypatch.setenv("TEST_CLEANUP_KEY", "test-token")
    session = session_with({"data": []})
    ok, detail = check_provider(
        config(
            "anthropic",
            api_key_env="TEST_CLEANUP_KEY",
            health_url="https://provider.example/v1/models",
        ),
        session,
    )
    assert ok
    assert "model availability not tested" in detail
    args, kwargs = session.request.call_args
    assert args == ("GET", "https://provider.example/v1/models")
    assert kwargs["headers"]["x-api-key"] == "test-token"
    assert "json" not in kwargs and "files" not in kwargs
    assert kwargs["allow_redirects"] is False


def test_health_check_without_endpoint_reports_it_did_not_test_connectivity():
    session = session_with({})
    ok, detail = check_provider(config("openai-compatible"), session)
    assert ok
    assert "connectivity not tested" in detail
    session.request.assert_not_called()


def test_disabled_cleanup_needs_no_endpoint_credentials_or_requests():
    session = session_with({})
    disabled = ProviderSettings(provider="none", api_key_env="UNSET_KEY")
    assert check_provider(disabled, session) == (True, "disabled")
    assert create_rewriter(disabled, session).rewrite("Instructions", "Text") == ""
    session.request.assert_not_called()


def test_startup_retries_temporary_connection_failure(monkeypatch):
    from cap_to_talk import providers

    session = session_with({})
    response = session.request.return_value
    session.request.side_effect = [requests.ConnectionError(), response]
    sleep = Mock()
    monkeypatch.setattr(providers.time, "sleep", sleep)

    ok, _ = check_provider(
        config("openasr", health_url="https://provider.example/health"),
        session,
        wait_seconds=30,
    )
    assert ok
    assert session.request.call_count == 2
    sleep.assert_called_once()


def test_startup_does_not_retry_rejected_credentials():
    session = session_with({"error": "unauthorized"}, status=401)
    ok, detail = check_provider(
        config("openai", health_url="https://provider.example/v1/models"),
        session,
        wait_seconds=30,
    )
    assert not ok
    assert "HTTP 401" in detail
    assert session.request.call_count == 1


def test_startup_stops_retrying_when_wait_window_expires(monkeypatch):
    from cap_to_talk import providers

    session = session_with({})
    session.request.side_effect = requests.ConnectionError()
    monkeypatch.setattr(providers.time, "monotonic", Mock(side_effect=[0, 31]))
    sleep = Mock()
    monkeypatch.setattr(providers.time, "sleep", sleep)
    ok, _ = check_provider(
        config("openasr", health_url="https://provider.example/health"),
        session,
        wait_seconds=30,
    )
    assert not ok
    assert session.request.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize(
    ("provider", "token_parameter"),
    [("openai", "max_completion_tokens"), ("openai-compatible", "max_tokens")],
)
def test_audio_dictation_sends_audio_and_instructions_in_one_text_output_request(
    provider, token_parameter, monkeypatch
):
    monkeypatch.setenv("TEST_DICTATION_KEY", "audio-test-token")
    session = session_with(
        {
            "choices": [
                {
                    "message": {"content": "  Finished message.  "},
                    "finish_reason": "stop",
                }
            ]
        }
    )
    adapter = create_audio_dictation(
        config(provider, api_key_env="TEST_DICTATION_KEY", max_output_tokens=2048),
        session,
    )
    audio_bytes = b"recorded WAV data"
    assert (
        adapter.dictate(io.BytesIO(audio_bytes), "Dictation instructions")
        == "Finished message."
    )
    session.request.assert_called_once()
    args, kwargs = session.request.call_args
    assert args == ("POST", "https://provider.example/v1/endpoint")
    assert kwargs["headers"] == {"Authorization": "Bearer audio-test-token"}
    assert kwargs["allow_redirects"] is False
    payload = kwargs["json"]
    assert payload["model"] == "selected-model"
    assert payload[token_parameter] == 2048
    assert payload["stream"] is False
    assert payload["messages"][0] == {
        "role": "system",
        "content": "Dictation instructions",
    }
    audio_part = payload["messages"][1]["content"][1]
    assert audio_part["type"] == "input_audio"
    assert audio_part["input_audio"]["format"] == "wav"
    assert base64.b64decode(audio_part["input_audio"]["data"]) == audio_bytes
    if provider == "openai":
        assert payload["modalities"] == ["text"]
    else:
        assert "modalities" not in payload
    assert "audio" not in payload  # No generated speech is requested.


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": []},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": "Partial"}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "Refusal", "refusal": "refused"}}]},
        {
            "choices": [
                {"message": {"content": "Filtered"}, "finish_reason": "content_filter"}
            ]
        },
    ],
)
def test_audio_dictation_rejects_incomplete_or_refused_text(payload):
    session = session_with(payload)
    adapter = create_audio_dictation(config("openai-compatible"), session)
    with pytest.raises(ProviderError, match="dictation"):
        adapter.dictate(io.BytesIO(b"audio"), "Instructions")
    session.request.assert_called_once()


def test_audio_dictation_requires_key_before_any_request(monkeypatch):
    monkeypatch.delenv("TEST_DICTATION_KEY", raising=False)
    session = session_with({})
    adapter = create_audio_dictation(
        config("openai", api_key_env="TEST_DICTATION_KEY"), session
    )
    with pytest.raises(ProviderError, match="TEST_DICTATION_KEY"):
        adapter.dictate(io.BytesIO(b"audio"), "Instructions")
    session.request.assert_not_called()
