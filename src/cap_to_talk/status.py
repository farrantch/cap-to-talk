"""Desktop notification and status-overlay client helpers."""

from __future__ import annotations

import socket
import subprocess
from contextlib import suppress

from cap_to_talk.config import Settings


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
    with suppress(OSError):
        subprocess.Popen(
            [
                "notify-send",
                "-r",
                settings.notify_id,
                "-t",
                str(timeout),
                "Cap to Talk",
                message,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
