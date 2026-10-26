"""Command-line entry point for Cap To Talk."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

import sounddevice as sd

from cap_to_talk import __version__
from cap_to_talk.config import Settings, load_settings
from cap_to_talk.desktop import DesktopUnavailableError, create_desktop_backend
from cap_to_talk.providers import check_provider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cap-to-talk",
        description="Push-to-talk dictation with configurable AI providers.",
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
    parser.add_argument(
        "--services-only",
        action="store_true",
        help="check the configured AI providers without checking desktop or audio",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=0,
        help="retry temporary connection failures for the required AI provider",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _check(
    settings: Settings,
    *,
    as_json: bool,
    services_only: bool = False,
    wait_seconds: int = 0,
) -> int:
    results: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, *, required: bool = True) -> None:
        results.append({"name": name, "ok": ok, "detail": detail, "required": required})

    if not services_only:
        try:
            desktop = create_desktop_backend(settings)
            for check in desktop.check():
                add(check.name, check.ok, check.detail, required=check.required)
        except DesktopUnavailableError as error:
            add("desktop", False, str(error))

        try:
            microphone = sd.query_devices(device=settings.audio_device, kind="input")
            add("microphone", True, str(microphone.get("name", "default input")))
        except Exception as error:
            add("microphone", False, str(error))

    providers = (
        [("dictation", settings.dictation_config, True)]
        if settings.pipeline_mode == "single"
        else [
            ("transcription", settings.transcription_config, True),
            ("cleanup", settings.rewrite_config, False),
        ]
    )
    for name, config, required in providers:
        ok, detail = check_provider(
            config, wait_seconds=wait_seconds if required else 0
        )
        if not ok and not required:
            detail += " Raw transcripts will be used."
        add(f"{name} ({config.provider})", ok, detail, required=required)

    ready = all(item["ok"] for item in results if item["required"])
    if as_json:
        print(json.dumps({"ok": ready, "checks": results}))
    else:
        for result in results:
            marker = (
                "PASS" if result["ok"] else "FAIL" if result["required"] else "WARN"
            )
            print(f"[{marker}] {result['name']}: {result['detail']}")

    return 0 if ready else 1


def _raise_keyboard_interrupt(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.wait_seconds < 0:
        parser.error("--wait-seconds cannot be negative")
    try:
        settings = load_settings(arguments.config)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    if arguments.command == "check":
        return _check(
            settings,
            as_json=arguments.json,
            services_only=arguments.services_only,
            wait_seconds=arguments.wait_seconds,
        )

    level = (
        logging.DEBUG if arguments.debug or settings.debug_transcripts else logging.INFO
    )
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
    if arguments.debug:
        settings = replace(settings, debug_transcripts=True)

    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    from cap_to_talk.app import VoiceDictationApp

    try:
        desktop = create_desktop_backend(settings)
        VoiceDictationApp(settings, desktop=desktop).run()
    except DesktopUnavailableError as error:
        print(f"Desktop error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Cap To Talk stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
