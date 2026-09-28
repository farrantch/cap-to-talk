"""Configuration loading for Cap To Talk."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


def default_config_dir() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME")
    if root:
        return Path(root).expanduser() / "cap-to-talk"
    return Path.home() / ".config" / "cap-to-talk"


@dataclass(frozen=True, slots=True)
class Settings:
    rate: int = 16_000
    channels: int = 1
    ptt_keycode: int = 66
    post_roll_seconds: float = 0.25
    asr_url: str = "http://127.0.0.1:8080/v1/audio/transcriptions"
    asr_health_url: str = "http://127.0.0.1:8080/health"
    asr_model: str = "qwen3-asr-0.6b"
    ollama_url: str = "http://127.0.0.1:11434/api/chat"
    ollama_health_url: str = "http://127.0.0.1:11434/api/tags"
    rewrite_model: str = "qwen3:4b-instruct"
    hotword_boost: float = 3.0
    typing_delay_ms: int = 0
    status_host: str = "127.0.0.1"
    status_port: int = 47_653
    notify_id: str = "9042"
    debug_transcripts: bool = False
    config_dir: Path = Path()
    hotwords_file: Path | None = None
    master_hotwords_file: Path | None = None

    def with_runtime_paths(self, config_dir: Path) -> Settings:
        return replace(
            self,
            config_dir=config_dir,
            hotwords_file=self.hotwords_file or config_dir / "hotwords.txt",
            master_hotwords_file=(
                self.master_hotwords_file or config_dir / "master-hotwords.txt"
            ),
        )


_TOML_FIELDS: dict[tuple[str, str], str] = {
    ("audio", "rate"): "rate",
    ("audio", "post_roll_seconds"): "post_roll_seconds",
    ("input", "ptt_keycode"): "ptt_keycode",
    ("services", "asr_url"): "asr_url",
    ("services", "asr_health_url"): "asr_health_url",
    ("services", "asr_model"): "asr_model",
    ("services", "ollama_url"): "ollama_url",
    ("services", "ollama_health_url"): "ollama_health_url",
    ("services", "rewrite_model"): "rewrite_model",
    ("glossary", "hotword_boost"): "hotword_boost",
    ("glossary", "hotwords_file"): "hotwords_file",
    ("glossary", "master_hotwords_file"): "master_hotwords_file",
    ("output", "typing_delay_ms"): "typing_delay_ms",
    ("privacy", "debug_transcripts"): "debug_transcripts",
    ("ui", "status_port"): "status_port",
}

_ENV_FIELD_SPECS: dict[str, tuple[str, type]] = {
    "RATE": ("rate", int),
    "PTT_KEYCODE": ("ptt_keycode", int),
    "POST_ROLL_SECONDS": ("post_roll_seconds", float),
    "ASR_URL": ("asr_url", str),
    "ASR_HEALTH_URL": ("asr_health_url", str),
    "ASR_MODEL": ("asr_model", str),
    "OLLAMA_URL": ("ollama_url", str),
    "OLLAMA_HEALTH_URL": ("ollama_health_url", str),
    "REWRITE_MODEL": ("rewrite_model", str),
    "HOTWORD_BOOST": ("hotword_boost", float),
    "TYPING_DELAY_MS": ("typing_delay_ms", int),
    "STATUS_PORT": ("status_port", int),
}

# Read legacy variables first so the new CAP_TO_TALK_* names win when both exist.
_ENV_FIELDS: dict[str, tuple[str, type]] = {
    **{f"CAPS_TALK_{suffix}": spec for suffix, spec in _ENV_FIELD_SPECS.items()},
    **{f"CAP_TO_TALK_{suffix}": spec for suffix, spec in _ENV_FIELD_SPECS.items()},
}


def _as_path(value: Any) -> Path:
    return Path(str(value)).expanduser()


def _validate(settings: Settings) -> None:
    if settings.rate <= 0:
        raise ValueError("audio.rate must be positive")
    if settings.post_roll_seconds < 0:
        raise ValueError("audio.post_roll_seconds cannot be negative")
    if settings.ptt_keycode <= 0:
        raise ValueError("input.ptt_keycode must be positive")
    if not 1 <= settings.status_port <= 65_535:
        raise ValueError("ui.status_port must be between 1 and 65535")
    if settings.typing_delay_ms < 0:
        raise ValueError("output.typing_delay_ms cannot be negative")


def load_settings(config_path: Path | None = None) -> Settings:
    path = (
        config_path.expanduser()
        if config_path
        else default_config_dir() / "config.toml"
    )
    config_dir = path.parent
    values: dict[str, Any] = {}

    if path.exists():
        with path.open("rb") as handle:
            document = tomllib.load(handle)

        for (section, key), field_name in _TOML_FIELDS.items():
            section_data = document.get(section, {})
            if key in section_data:
                values[field_name] = section_data[key]

    for environment_name, (field_name, converter) in _ENV_FIELDS.items():
        if environment_name in os.environ:
            values[field_name] = converter(os.environ[environment_name])

    for path_field in ("hotwords_file", "master_hotwords_file"):
        if path_field in values:
            values[path_field] = _as_path(values[path_field])

    settings = Settings(**values).with_runtime_paths(config_dir)
    _validate(settings)
    assert settings.hotwords_file is not None
    assert settings.master_hotwords_file is not None
    return settings
