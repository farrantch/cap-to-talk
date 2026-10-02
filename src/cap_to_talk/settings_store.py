"""Save settings atomically while retaining comments and extra options."""

from __future__ import annotations

import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from cap_to_talk.config import Settings, validate_settings


def settings_document(path: Path, settings: Settings) -> str:
    import tomlkit

    validate_settings(settings)
    document = (
        tomlkit.parse(path.read_text(encoding="utf-8"))
        if path.exists()
        else tomlkit.document()
    )
    updates = {
        "pipeline": {"mode": settings.pipeline_mode},
        "input": {"hotkey": settings.hotkey},
        "audio": {"device": settings.audio_device},
        "transcription": asdict(settings.transcription_config),
        "rewrite": asdict(settings.rewrite_config),
        "dictation": asdict(settings.dictation_config),
    }
    for section, values in updates.items():
        if section not in document:
            document[section] = tomlkit.table()
        for key, value in values.items():
            if value is None:
                document[section].pop(key, None)
            else:
                document[section][key] = value
    return tomlkit.dumps(document)


def write_settings(path: Path, document: str, *, expected: bytes | None) -> None:
    """Refuse to overwrite edits made since the window loaded the configuration."""
    current = path.read_bytes() if path.exists() else None
    if current != expected:
        raise ValueError(
            "Settings changed outside this window. Reopen Settings before saving."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(
        prefix=".config-", suffix=".toml", dir=path.parent
    )
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
