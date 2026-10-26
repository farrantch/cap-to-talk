from pathlib import Path

import pytest

from cap_to_talk.config import load_settings


def test_loads_toml_and_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_root = tmp_path / "config"
    config_dir = config_root / "cap-to-talk"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        """
[audio]
rate = 22050

[services]
rewrite_model = "small-model"

[privacy]
debug_transcripts = true
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root))
    monkeypatch.setenv("CAP_TO_TALK_REWRITE_MODEL", "environment-model")

    settings = load_settings()

    assert settings.rate == 22_050
    assert settings.rewrite_model == "environment-model"
    assert settings.debug_transcripts is True
    assert settings.hotwords_file == config_dir / "hotwords.txt"


def test_supports_legacy_environment_names_with_new_names_taking_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("CAPS_TALK_REWRITE_MODEL", "legacy-model")

    assert load_settings(config_path).rewrite_model == "legacy-model"

    monkeypatch.setenv("CAP_TO_TALK_REWRITE_MODEL", "cap-model")

    assert load_settings(config_path).rewrite_model == "cap-model"


def test_explicit_config_uses_its_directory_for_glossaries(tmp_path: Path):
    path = tmp_path / "profile" / "config.toml"
    path.parent.mkdir()
    path.write_text("", encoding="utf-8")

    assert load_settings(path).hotwords_file == path.parent / "hotwords.txt"


def test_rejects_invalid_values(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("[ui]\nstatus_port = 70000\n", encoding="utf-8")

    with pytest.raises(ValueError, match="status_port"):
        load_settings(path)


def test_provider_defaults_preserve_existing_local_configuration(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[services]\nasr_model = "my-asr"\nrewrite_model = "my-cleanup"\n')
    settings = load_settings(path)
    assert settings.transcription_config.provider == "openasr"
    assert settings.transcription_config.model == "my-asr"
    assert settings.rewrite_config.provider == "ollama"
    assert settings.rewrite_config.model == "my-cleanup"
    assert settings.transcription_config.api_key_env == ""
    assert settings.rewrite_config.api_key_env == ""


def test_new_provider_sections_override_legacy_configuration(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("""
[services]
asr_model = "old-asr"
rewrite_model = "old-cleanup"

[transcription]
provider = "openai"
model = "selected-speech-model"

[rewrite]
provider = "anthropic"
model = "selected-text-model"
max_output_tokens = 2048
""")
    settings = load_settings(path)
    assert (
        settings.transcription_config.url
        == "https://api.openai.com/v1/audio/transcriptions"
    )
    assert settings.transcription_config.model == "selected-speech-model"
    assert settings.transcription_config.api_key_env == "OPENAI_API_KEY"
    assert settings.rewrite_config.url == "https://api.anthropic.com/v1/messages"
    assert settings.rewrite_config.api_key_env == "ANTHROPIC_API_KEY"
    assert settings.rewrite_config.model == "selected-text-model"
    assert settings.rewrite_config.max_output_tokens == 2048


def test_provider_environment_overrides_config_without_storing_keys(
    tmp_path, monkeypatch
):
    path = tmp_path / "config.toml"
    path.write_text('[transcription]\nprovider = "openai"\nmodel = "file-model"\n')
    monkeypatch.setenv("CAP_TO_TALK_TRANSCRIPTION_MODEL", "environment-model")
    monkeypatch.setenv("CAP_TO_TALK_TRANSCRIPTION_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("CAP_TO_TALK_TRANSCRIPTION_SEND_HOTWORDS", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-token")
    settings = load_settings(path)
    assert settings.transcription_config.model == "environment-model"
    assert settings.transcription_config.timeout_seconds == 45
    assert settings.transcription_config.send_hotwords is False
    assert "secret-test-token" not in repr(settings)


def test_cloud_provider_does_not_inherit_local_model(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[transcription]\nprovider = "openai"\n')
    with pytest.raises(ValueError, match="transcription.model"):
        load_settings(path)


def test_custom_url_does_not_inherit_official_health_endpoint(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("""
[transcription]
provider = "openai"
url = "https://gateway.example/audio/transcriptions"
model = "selected-model"
""")
    assert load_settings(path).transcription_config.health_url == ""


def test_custom_compatible_provider_does_not_inherit_openai_credentials(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("""
[transcription]
provider = "openai-compatible"
url = "http://127.0.0.1:9000/v1/audio/transcriptions"
model = "local-model"

[rewrite]
provider = "none"
""")
    settings = load_settings(path)
    assert settings.transcription_config.api_key_env == ""
    assert settings.rewrite_config.provider == "none"


@pytest.mark.parametrize(
    ("document", "error"),
    [
        ('[transcription]\nprovider = "anthropic"', "transcription.provider"),
        ('[rewrite]\nprovider = "openasr"', "rewrite.provider"),
        ("[rewrite]\nprovider = 4", "rewrite.provider"),
        ('[rewrite]\nurl = "ftp://host/api"', "rewrite.url"),
        ('[rewrite]\nurl = "https://token@host/api"', "rewrite.url"),
        ('[rewrite]\nurl = "https://host:bad/api"', "rewrite.url"),
        ("[rewrite]\nurl = 4", "rewrite.url"),
        ("[rewrite]\ntimeout_seconds = 0", "rewrite.timeout_seconds"),
        ("[rewrite]\ntimeout_seconds = nan", "rewrite.timeout_seconds"),
        ("[rewrite]\ntimeout_seconds = true", "rewrite.timeout_seconds"),
        ("[rewrite]\nmax_output_tokens = -1", "rewrite.max_output_tokens"),
        ("[rewrite]\nmax_output_tokens = true", "rewrite.max_output_tokens"),
        ('[transcription]\nsend_hotwords = "false"', "transcription.send_hotwords"),
        ('[rewrite]\napi_key_env = "not an env name"', "rewrite.api_key_env"),
        ('[rewrite]\napi_key = "do-not-print-this"', "Unknown rewrite setting"),
        ('rewrite = "ollama"', "rewrite must be a TOML table"),
    ],
)
def test_invalid_provider_configuration_has_actionable_errors(
    tmp_path, document, error
):
    path = tmp_path / "config.toml"
    path.write_text(document)
    with pytest.raises(ValueError, match=error) as raised:
        load_settings(path)
    assert "do-not-print-this" not in str(raised.value)


def test_authenticated_health_check_cannot_send_credentials_to_another_origin(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("""
[transcription]
provider = "openai"
model = "speech-model"
health_url = "https://different.example/health"
""")
    with pytest.raises(ValueError, match="same origin"):
        load_settings(path)


def test_single_mode_uses_audio_chat_and_ignores_inactive_models(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("""
[pipeline]
mode = "single"

[dictation]
provider = "openai"
model = "selected-audio-model"

[transcription]
provider = "openai"

[rewrite]
provider = "anthropic"
""")
    settings = load_settings(path)
    assert settings.pipeline_mode == "single"
    assert settings.dictation_config.model == "selected-audio-model"
    assert settings.dictation_config.url == "https://api.openai.com/v1/chat/completions"
    assert settings.dictation_config.api_key_env == "OPENAI_API_KEY"
    assert settings.transcription_config.model == ""
    assert settings.rewrite_config.model == ""


def test_pipeline_and_dictation_environment_overrides(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[pipeline]\nmode = "two-stage"\n')
    monkeypatch.setenv("CAP_TO_TALK_PIPELINE_MODE", "single")
    monkeypatch.setenv("CAP_TO_TALK_DICTATION_PROVIDER", "openai-compatible")
    monkeypatch.setenv(
        "CAP_TO_TALK_DICTATION_URL", "http://127.0.0.1:9000/v1/chat/completions"
    )
    monkeypatch.setenv("CAP_TO_TALK_DICTATION_MODEL", "local-audio-model")
    monkeypatch.setenv("CAP_TO_TALK_DICTATION_SEND_HOTWORDS", "false")
    monkeypatch.setenv("CAP_TO_TALK_DICTATION_MAX_OUTPUT_TOKENS", "2048")
    settings = load_settings(path)
    assert settings.pipeline_mode == "single"
    assert settings.dictation_config.model == "local-audio-model"
    assert settings.dictation_config.api_key_env == ""
    assert settings.dictation_config.health_url == ""
    assert settings.dictation_config.send_hotwords is False
    assert settings.dictation_config.max_output_tokens == 2048


@pytest.mark.parametrize(
    ("document", "error"),
    [
        ('[pipeline]\nmode = "unknown"', "pipeline.mode"),
        ('[pipeline]\nmode = "single"', "dictation.model"),
        (
            '[pipeline]\nmode = "single"\n[dictation]\nprovider = "ollama"',
            "dictation.provider",
        ),
        (
            '[pipeline]\nmode = "single"\n[dictation]\n'
            'provider = "openai-compatible"\nmodel = "audio-model"',
            "dictation.url",
        ),
        (
            '[pipeline]\nmode = "single"\n[dictation]\nmodel = "audio-model"\n'
            'health_url = "https://different.example/health"',
            "same origin",
        ),
    ],
)
def test_invalid_single_mode_configuration(tmp_path, document, error):
    path = tmp_path / "config.toml"
    path.write_text(document)
    with pytest.raises(ValueError, match=error):
        load_settings(path)


def test_example_configuration_stays_local_with_no_dictation_model():
    path = Path(__file__).resolve().parents[1] / "config/config.example.toml"
    settings = load_settings(path)
    assert settings.pipeline_mode == "two-stage"
    assert settings.transcription_config.provider == "openasr"
    assert settings.rewrite_config.provider == "ollama"
    assert settings.dictation_config.model == ""


@pytest.mark.parametrize("hotkey", ["auto", "caps_lock", "f1", "f8", "f12"])
def test_named_hotkey_configuration(tmp_path, hotkey):
    path = tmp_path / "config.toml"
    path.write_text(f'[input]\nhotkey = "{hotkey}"\n')
    assert load_settings(path).hotkey == hotkey


@pytest.mark.parametrize("value", ['"f13"', '"shift"', '""', "123"])
def test_invalid_named_hotkeys_are_rejected(tmp_path, value):
    path = tmp_path / "config.toml"
    path.write_text(f"[input]\nhotkey = {value}\n")
    with pytest.raises(ValueError, match="input.hotkey"):
        load_settings(path)


def test_hotkey_environment_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CAP_TO_TALK_HOTKEY", "f10")
    assert load_settings(tmp_path / "config.toml").hotkey == "f10"


@pytest.mark.parametrize("platform_name", ["darwin", "win32", "linux"])
def test_native_config_locations(tmp_path, monkeypatch, platform_name):
    from types import SimpleNamespace

    from cap_to_talk import config

    monkeypatch.setattr(config, "sys", SimpleNamespace(platform=platform_name))
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    expected = {
        "darwin": tmp_path / "Library/Application Support/cap-to-talk",
        "win32": tmp_path / "Roaming/cap-to-talk",
        "linux": tmp_path / ".config/cap-to-talk",
    }
    assert config.default_config_dir() == expected[platform_name]


@pytest.mark.parametrize("appdata", [None, ""])
def test_windows_config_dir_falls_back_to_home(monkeypatch, tmp_path, appdata):
    from types import SimpleNamespace

    from cap_to_talk import config

    monkeypatch.setattr(config, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    if appdata is None:
        monkeypatch.delenv("APPDATA", raising=False)
    else:
        monkeypatch.setenv("APPDATA", appdata)
    assert config.default_config_dir() == tmp_path / "AppData/Roaming/cap-to-talk"
