"""Configuration loading for Cap To Talk."""

from __future__ import annotations

import math
import os
import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    provider: str
    url: str = ""
    model: str = ""
    health_url: str = ""
    api_key_env: str = ""
    api_key_source: str = "environment"
    timeout_seconds: float = 120
    send_hotwords: bool = True
    max_output_tokens: int = 1_024


TRANSCRIPTION_PROVIDERS = ("openasr", "openai", "openai-compatible")
REWRITE_PROVIDERS = ("ollama", "openai", "openai-compatible", "anthropic", "none")
DICTATION_PROVIDERS = ("openai", "openai-compatible")


def default_config_dir() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME")
    if root:
        return Path(root).expanduser() / "cap-to-talk"
    if sys.platform == "win32":
        return (
            Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
            / "cap-to-talk"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "cap-to-talk"
    return Path.home() / ".config" / "cap-to-talk"


@dataclass(frozen=True, slots=True)
class Settings:
    rate: int = 16_000
    channels: int = 1
    audio_device: str | int | None = None
    ptt_keycode: int = 66
    hotkey: str = "auto"
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
    pipeline_mode: str = "two-stage"
    transcription: ProviderSettings | None = None
    rewrite: ProviderSettings | None = None
    dictation: ProviderSettings | None = None

    @property
    def transcription_config(self) -> ProviderSettings:
        return self.transcription or ProviderSettings(
            provider="openasr",
            url=self.asr_url,
            health_url=self.asr_health_url,
            model=self.asr_model,
        )

    @property
    def rewrite_config(self) -> ProviderSettings:
        return self.rewrite or ProviderSettings(
            provider="ollama",
            url=self.ollama_url,
            health_url=self.ollama_health_url,
            model=self.rewrite_model,
        )

    @property
    def dictation_config(self) -> ProviderSettings:
        return self.dictation or _provider_defaults("openai", "dictation")

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
    ("pipeline", "mode"): "pipeline_mode",
    ("audio", "rate"): "rate",
    ("audio", "device"): "audio_device",
    ("audio", "post_roll_seconds"): "post_roll_seconds",
    ("input", "ptt_keycode"): "ptt_keycode",
    ("input", "hotkey"): "hotkey",
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
    "PIPELINE_MODE": ("pipeline_mode", str),
    "RATE": ("rate", int),
    "AUDIO_DEVICE": ("audio_device", str),
    "PTT_KEYCODE": ("ptt_keycode", int),
    "HOTKEY": ("hotkey", str),
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


def _as_bool(value: str) -> bool:
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise ValueError("boolean environment settings must be true or false")


_PROVIDER_FIELDS: dict[str, Callable[[str], Any]] = {
    "provider": str,
    "url": str,
    "model": str,
    "health_url": str,
    "api_key_env": str,
    "api_key_source": str,
    "timeout_seconds": float,
    "send_hotwords": _as_bool,
    "max_output_tokens": int,
}


def _provider_defaults(provider: str, section: str) -> ProviderSettings:
    if provider == "openai":
        endpoint = (
            "audio/transcriptions" if section == "transcription" else "chat/completions"
        )
        return ProviderSettings(
            provider=provider,
            url=f"https://api.openai.com/v1/{endpoint}",
            health_url="https://api.openai.com/v1/models",
            api_key_env="OPENAI_API_KEY",
        )
    if provider == "anthropic":
        return ProviderSettings(
            provider=provider,
            url="https://api.anthropic.com/v1/messages",
            health_url="https://api.anthropic.com/v1/models",
            api_key_env="ANTHROPIC_API_KEY",
        )
    return ProviderSettings(provider=provider)


def _load_provider(
    document: dict[str, Any], section: str, fallback: ProviderSettings
) -> ProviderSettings:
    section_data = document.get(section, {})
    if not isinstance(section_data, dict):
        raise ValueError(f"{section} must be a TOML table")
    unknown = section_data.keys() - _PROVIDER_FIELDS.keys()
    if unknown:
        raise ValueError(f"Unknown {section} setting: {', '.join(sorted(unknown))}")
    values = dict(section_data)
    for name, converter in _PROVIDER_FIELDS.items():
        env_name = f"CAP_TO_TALK_{section.upper()}_{name.upper()}"
        if env_name in os.environ:
            values[name] = converter(os.environ[env_name])

    provider = values.get("provider", fallback.provider)
    allowed = {
        "transcription": TRANSCRIPTION_PROVIDERS,
        "rewrite": REWRITE_PROVIDERS,
        "dictation": DICTATION_PROVIDERS,
    }[section]
    if provider not in allowed:
        raise ValueError(f"{section}.provider must be one of: {', '.join(allowed)}")
    defaults = (
        fallback
        if provider == fallback.provider
        else _provider_defaults(provider, section)
    )
    # A custom endpoint must not inherit a health URL on a different server.
    if "url" in values and values["url"] != defaults.url:
        values.setdefault("health_url", "")
    return replace(defaults, **values)


def _validate_url(url: str, setting: str) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
        valid = (
            parsed.scheme in ("http", "https")
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
            and not any(char.isspace() for char in url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            f"{setting} must be an HTTP(S) URL without embedded credentials"
        )
    return (
        parsed.scheme,
        parsed.hostname or "",
        port or (443 if parsed.scheme == "https" else 80),
    )


def _validate_provider(config: ProviderSettings, section: str) -> None:
    for name in ("provider", "url", "model", "health_url", "api_key_env"):
        if not isinstance(getattr(config, name), str):
            raise ValueError(f"{section}.{name} must be a string")
    if config.api_key_source not in ("environment", "keyring"):
        raise ValueError(f"{section}.api_key_source must be environment or keyring")
    if config.api_key_source == "keyring" and not config.api_key_env:
        raise ValueError(f"{section}.api_key_env must name the stored credential")
    if config.provider == "none":
        return
    if not config.model.strip():
        raise ValueError(f"{section}.model is required for the selected provider")
    origin = _validate_url(config.url, f"{section}.url")
    if config.health_url:
        health_origin = _validate_url(config.health_url, f"{section}.health_url")
        if config.api_key_env and origin != health_origin:
            raise ValueError(f"{section}.health_url must use the same origin as url")
    if config.api_key_env and not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*", config.api_key_env
    ):
        raise ValueError(f"{section}.api_key_env must name an environment variable")
    if config.provider in ("openai", "anthropic") and not config.api_key_env:
        raise ValueError(f"{section}.api_key_env is required for the selected provider")
    if (
        isinstance(config.timeout_seconds, bool)
        or not isinstance(config.timeout_seconds, (int, float))
        or not math.isfinite(config.timeout_seconds)
        or config.timeout_seconds <= 0
    ):
        raise ValueError(f"{section}.timeout_seconds must be a positive finite number")
    if not isinstance(config.send_hotwords, bool):
        raise ValueError(f"{section}.send_hotwords must be a boolean")
    if type(config.max_output_tokens) is not int or config.max_output_tokens <= 0:
        raise ValueError(f"{section}.max_output_tokens must be a positive integer")


def validate_settings(settings: Settings) -> None:
    if settings.audio_device is not None and (
        type(settings.audio_device) not in (str, int)
        or isinstance(settings.audio_device, str)
        and not settings.audio_device.strip()
        or isinstance(settings.audio_device, int)
        and settings.audio_device < 0
    ):
        raise ValueError("audio.device must be a device name or a nonnegative index")
    if settings.rate <= 0:
        raise ValueError("audio.rate must be positive")
    if settings.post_roll_seconds < 0:
        raise ValueError("audio.post_roll_seconds cannot be negative")
    if type(settings.ptt_keycode) is not int or not 1 <= settings.ptt_keycode <= 255:
        raise ValueError("input.ptt_keycode must be between 1 and 255")
    if settings.hotkey not in ("auto", "caps_lock", *(f"f{i}" for i in range(1, 13))):
        raise ValueError("input.hotkey must be auto, caps_lock, or f1 through f12")
    if not 1 <= settings.status_port <= 65_535:
        raise ValueError("ui.status_port must be between 1 and 65535")
    if settings.typing_delay_ms < 0:
        raise ValueError("output.typing_delay_ms cannot be negative")
    if settings.pipeline_mode not in ("two-stage", "single"):
        raise ValueError("pipeline.mode must be two-stage or single")
    if settings.pipeline_mode == "single":
        _validate_provider(settings.dictation_config, "dictation")
    else:
        _validate_provider(settings.transcription_config, "transcription")
        _validate_provider(settings.rewrite_config, "rewrite")


def load_settings(config_path: Path | None = None) -> Settings:
    path = (
        config_path.expanduser()
        if config_path
        else default_config_dir() / "config.toml"
    )
    config_dir = path.parent
    values: dict[str, Any] = {}
    document: dict[str, Any] = {}

    if path.exists():
        with path.open("rb") as handle:
            document = tomllib.load(handle)

        for (section, key), field_name in _TOML_FIELDS.items():
            section_data = document.get(section, {})
            if not isinstance(section_data, dict):
                raise ValueError(f"{section} must be a TOML table")
            if key in section_data:
                values[field_name] = section_data[key]

    for environment_name, (field_name, converter) in _ENV_FIELDS.items():
        if environment_name in os.environ:
            values[field_name] = converter(os.environ[environment_name])

    for path_field in ("hotwords_file", "master_hotwords_file"):
        if path_field in values:
            values[path_field] = _as_path(values[path_field])

    settings = Settings(**values).with_runtime_paths(config_dir)
    settings = replace(
        settings,
        transcription=_load_provider(
            document, "transcription", settings.transcription_config
        ),
        rewrite=_load_provider(document, "rewrite", settings.rewrite_config),
        dictation=_load_provider(document, "dictation", settings.dictation_config),
    )
    validate_settings(settings)
    assert settings.hotwords_file is not None
    assert settings.master_hotwords_file is not None
    return settings
