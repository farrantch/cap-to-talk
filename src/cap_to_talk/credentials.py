"""Credentials stored only in the operating system's native credential store."""

from __future__ import annotations

import sys
from typing import Any
from urllib.parse import urlsplit

from cap_to_talk.config import ProviderSettings

SERVICE = "cap-to-talk"


class CredentialError(RuntimeError):
    pass


def credential_account(config: ProviderSettings) -> str:
    """Bind each stored key to its endpoint origin and configured key name."""
    url = urlsplit(config.url)
    port = url.port or (443 if url.scheme == "https" else 80)
    return f"{config.api_key_env}@{url.scheme}://{url.hostname}:{port}"


def _backend() -> Any:
    try:
        if sys.platform == "darwin":
            from keyring.backends.macOS import Keyring
        elif sys.platform == "win32":
            from keyring.backends.Windows import WinVaultKeyring as Keyring
        elif sys.platform == "linux":
            from keyring.backends.SecretService import Keyring
        else:
            raise CredentialError("No system credential store is supported on this OS.")
        return Keyring()
    except (ImportError, RuntimeError) as error:
        raise CredentialError(
            "System credential storage is unavailable. Install the desktop extra "
            "and unlock your credential store, or use an environment variable."
        ) from error


def read_key(config: ProviderSettings) -> str:
    try:
        return _backend().get_password(SERVICE, credential_account(config)) or ""
    except Exception:
        raise CredentialError(
            "Cannot read the saved API key. Unlock your system credential store "
            "or choose an environment variable."
        ) from None


def save_key(config: ProviderSettings, secret: str) -> None:
    if not secret.strip():
        raise CredentialError("Enter a nonempty API key.")
    try:
        _backend().set_password(SERVICE, credential_account(config), secret.strip())
    except Exception:
        raise CredentialError(
            "Cannot save the API key. Unlock your system credential store "
            "or choose an environment variable. The key was not saved to a file."
        ) from None


def delete_key(config: ProviderSettings) -> None:
    try:
        backend = _backend()
        account = credential_account(config)
        if backend.get_password(SERVICE, account) is not None:
            backend.delete_password(SERVICE, account)
    except Exception:
        raise CredentialError(
            "Cannot remove the saved key from the credential store."
        ) from None
