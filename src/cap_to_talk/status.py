"""Status-overlay client helpers and the legacy notification entry point."""

from __future__ import annotations

import socket
from contextlib import suppress

from cap_to_talk.config import Settings
from cap_to_talk.desktop import DesktopUnavailableError, create_desktop_backend


def send_status(settings: Settings, message: str) -> None:
    try:
        with socket.create_connection(
            (settings.status_host, settings.status_port),
            timeout=0.15,
        ) as connection:
            connection.sendall(message.encode("utf-8"))
    except OSError:
        pass


def notify(settings: Settings, message: str, timeout: int = 1_500) -> None:
    """Compatibility helper for callers of the original notification function."""
    with suppress(DesktopUnavailableError):
        create_desktop_backend(settings).notify(message, timeout)
