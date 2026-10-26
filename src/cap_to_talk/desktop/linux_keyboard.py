"""Prepare and restore Caps Lock for the graphical launcher on X11."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager

from cap_to_talk.config import Settings
from cap_to_talk.desktop.base import DesktopUnavailableError


@contextmanager
def prepared_keyboard(settings: Settings) -> Iterator[None]:
    if settings.hotkey not in ("auto", "caps_lock"):
        yield
        return
    display = os.environ.get("DISPLAY", "")
    snapshot = None
    try:
        snapshot = subprocess.run(
            ["xkbcomp", "-xkb", display, "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        if not snapshot.strip():
            raise DesktopUnavailableError("Could not save the current keyboard layout.")
        for command in (
            ["setxkbmap", "-option", "caps:none"],
            ["xmodmap", "-e", "clear Lock"],
            ["xmodmap", "-e", f"keycode {settings.ptt_keycode} = NoSymbol"],
        ):
            subprocess.run(command, check=True, capture_output=True)
        yield
    except (OSError, subprocess.CalledProcessError):
        raise DesktopUnavailableError(
            "Could not prepare the dictation key. "
            "Install xkbcomp, setxkbmap, and xmodmap, "
            "or select a function key."
        ) from None
    finally:
        if snapshot:
            try:
                subprocess.run(
                    ["xkbcomp", "-", display],
                    input=snapshot,
                    text=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            except (OSError, subprocess.CalledProcessError):
                raise DesktopUnavailableError(
                    "Could not restore the keyboard layout. "
                    "Reapply your layout in desktop settings."
                ) from None
