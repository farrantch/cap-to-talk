"""X11 window targeting and text insertion."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

from cap_to_talk.text import normalize_for_typing

LOGGER = logging.getLogger(__name__)
REQUIRED_COMMANDS = ("xdotool", "xprintidle", "notify-send")


def missing_commands() -> list[str]:
    return [command for command in REQUIRED_COMMANDS if shutil.which(command) is None]


def get_active_window_id() -> str | None:
    try:
        return subprocess.check_output(
            ["xdotool", "getactivewindow"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def window_exists(window_id: str | None) -> bool:
    if not window_id:
        return False
    result = subprocess.run(
        ["xdotool", "getwindowname", window_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def get_idle_ms() -> int | None:
    try:
        return int(
            subprocess.check_output(
                ["xprintidle"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def wait_for_user_pause(min_idle_ms: int = 1_000) -> None:
    announced = False
    while True:
        idle = get_idle_ms()
        if idle is None:
            time.sleep(1.0)
            return
        if idle >= min_idle_ms:
            return
        if not announced:
            LOGGER.info("Waiting for keyboard and mouse input to pause")
            announced = True
        time.sleep(0.1)


def _type(text: str, delay_ms: int) -> None:
    subprocess.run(
        [
            "xdotool",
            "type",
            "--clearmodifiers",
            "--delay",
            str(delay_ms),
            "--file",
            "-",
        ],
        check=True,
        input=text,
        text=True,
    )


def type_text(
    text: str,
    target_window: str | None,
    *,
    delay_ms: int = 0,
) -> None:
    text = normalize_for_typing(text)
    if not target_window:
        _type(text, delay_ms)
        return
    if not window_exists(target_window):
        raise RuntimeError("The original dictation target window no longer exists.")

    current_window = get_active_window_id()
    if current_window != target_window:
        wait_for_user_pause()
        current_window = get_active_window_id()

    try:
        if current_window != target_window:
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", target_window],
                check=True,
            )
            time.sleep(0.08)
        _type(text, delay_ms)
    finally:
        if (
            current_window
            and current_window != target_window
            and window_exists(current_window)
        ):
            time.sleep(0.05)
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", current_window],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
