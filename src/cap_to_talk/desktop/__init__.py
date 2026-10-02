"""Select a desktop implementation without importing another platform's APIs."""

from __future__ import annotations

import sys

from cap_to_talk.config import Settings
from cap_to_talk.desktop.base import (
    DesktopBackend,
    DesktopCheck,
    DesktopUnavailableError,
)

__all__ = [
    "DesktopBackend",
    "DesktopCheck",
    "DesktopUnavailableError",
    "create_desktop_backend",
]


def create_desktop_backend(settings: Settings) -> DesktopBackend:
    if sys.platform == "linux":
        from cap_to_talk.desktop.linux_x11 import LinuxX11Desktop

        return LinuxX11Desktop(settings)

    if sys.platform == "win32":
        from cap_to_talk.desktop.windows import WindowsDesktop

        return WindowsDesktop(settings)
    if sys.platform == "darwin":
        from cap_to_talk.desktop.macos import MacOSDesktop

        return MacOSDesktop(settings)
    platform_name = sys.platform
    raise DesktopUnavailableError(
        f"Desktop dictation is not available on {platform_name} yet. "
        "Desktop adapters are available for Linux/X11, Windows, and macOS."
    )
