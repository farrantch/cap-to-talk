from dataclasses import replace
from unittest.mock import Mock

import pytest

from cap_to_talk import credentials
from cap_to_talk.config import ProviderSettings
from cap_to_talk.providers import HTTPProvider, ProviderError


@pytest.fixture
def profile():
    return ProviderSettings(
        provider="openai",
        model="test-model",
        url="https://api.example/v1/audio",
        api_key_env="TEST_KEY",
        api_key_source="keyring",
    )


@pytest.fixture
def vault(monkeypatch):
    items = {}
    backend = Mock()
    backend.get_password.side_effect = lambda service, account: items.get(
        (service, account)
    )
    backend.set_password.side_effect = lambda service, account, secret: (
        items.__setitem__((service, account), secret)
    )
    backend.delete_password.side_effect = lambda service, account: items.pop(
        (service, account), None
    )
    monkeypatch.setattr(credentials, "_backend", lambda: backend)
    return backend, items


def test_saved_key_is_bound_to_endpoint_origin(profile, vault, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "environment-secret")
    credentials.save_key(profile, "stored-secret")
    assert HTTPProvider(profile).headers()["Authorization"] == "Bearer stored-secret"
    assert (
        credentials.read_key(replace(profile, url="https://api.example/v1/chat"))
        == "stored-secret"
    )
    assert (
        credentials.read_key(replace(profile, url="https://other.example/v1/audio"))
        == ""
    )
    assert (
        credentials.read_key(replace(profile, url="http://api.example/v1/audio")) == ""
    )
    assert (
        credentials.read_key(replace(profile, url="https://api.example:8443/v1/audio"))
        == ""
    )


def test_environment_mode_never_opens_credential_store(profile, monkeypatch):
    backend = Mock(side_effect=AssertionError("store should not be accessed"))
    monkeypatch.setattr(credentials, "_backend", backend)
    monkeypatch.setenv("TEST_KEY", "environment-secret")
    assert HTTPProvider(replace(profile, api_key_source="environment")).headers() == {
        "Authorization": "Bearer environment-secret"
    }
    backend.assert_not_called()


def test_missing_saved_key_does_not_fall_back_to_environment(
    profile, vault, monkeypatch
):
    monkeypatch.setenv("TEST_KEY", "wrong-account")
    with pytest.raises(ProviderError, match="No saved API key"):
        HTTPProvider(profile).headers()


def test_store_failure_does_not_leak_secret_or_use_a_file(profile, vault):
    backend, _ = vault
    backend.set_password.side_effect = RuntimeError("secret-from-backend")
    with pytest.raises(credentials.CredentialError) as result:
        credentials.save_key(profile, "new-secret")
    assert "secret-from-backend" not in str(result.value)
    assert "new-secret" not in str(result.value)
    assert result.value.__suppress_context__


def test_delete_saved_key(profile, vault):
    credentials.save_key(profile, "stored-secret")
    credentials.delete_key(profile)
    assert credentials.read_key(profile) == ""
    credentials.delete_key(profile)
