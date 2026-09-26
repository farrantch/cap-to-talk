"""Command-line entry point for Caps Talk."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

import requests
import sounddevice as sd

from caps_talk import __version__
from caps_talk.config import Settings, load_settings
from caps_talk.x11 import missing_commands


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caps-talk",
        description="Local Caps Lock push-to-talk dictation for Linux/X11.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "check"),
        default="run",
        help="run dictation (default) or check the local setup",
    )
    parser.add_argument("--config", type=Path, help="path to config.toml")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable debug logs, including transcript contents",
    )
    parser.add_argument("--json", action="store_true", help="JSON output for check")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _endpoint_check(url: str) -> tuple[bool, str]:
    try:
        response = requests.get(url, timeout=3)
        response.raise_for_status()
        return True, f"HTTP {response.status_code}"
    except requests.RequestException as error:
        return False, str(error)


def _check(settings: Settings, *, as_json: bool) -> int:
    results: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": ok, "detail": detail})

    session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
    add("X11 session", session_type == "x11", session_type)
    add("DISPLAY", bool(os.environ.get("DISPLAY")), os.environ.get("DISPLAY", "unset"))

    missing = missing_commands()
    add(
        "desktop commands",
        not missing,
        "available" if not missing else "missing: " + ", ".join(missing),
    )

    try:
        microphone = sd.query_devices(kind="input")
        add("microphone", True, str(microphone.get("name", "default input")))
    except Exception as error:
        add("microphone", False, str(error))

    for name, url in (
        ("OpenASR", settings.asr_health_url),
        ("Ollama", settings.ollama_health_url),
    ):
        ok, detail = _endpoint_check(url)
        add(name, ok, detail)

    if as_json:
        print(
            json.dumps({"ok": all(item["ok"] for item in results), "checks": results})
        )
    else:
        for result in results:
            marker = "PASS" if result["ok"] else "FAIL"
            print(f"[{marker}] {result['name']}: {result['detail']}")

    return 0 if all(item["ok"] for item in results) else 1


def _raise_keyboard_interrupt(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        settings = load_settings(arguments.config)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    if arguments.command == "check":
        return _check(settings, as_json=arguments.json)

    level = (
        logging.DEBUG if arguments.debug or settings.debug_transcripts else logging.INFO
    )
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
    if arguments.debug:
        settings = replace(settings, debug_transcripts=True)

    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    from caps_talk.app import VoiceDictationApp

    try:
        VoiceDictationApp(settings).run()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Caps Talk stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
