import os
from dataclasses import replace

import pytest

from cap_to_talk.config import ProviderSettings, load_settings
from cap_to_talk.settings_store import settings_document, write_settings


def test_save_preserves_comments_and_advanced_options(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "# Keep my comment\n[output]\ntyping_delay_ms = 7\n"
        "[glossary]\nhotword_boost = 2.5\n"
    )
    old = path.read_bytes()
    settings = replace(load_settings(path), hotkey="f9", audio_device="USB Mic, WASAPI")
    document = settings_document(path, settings)
    write_settings(path, document, expected=old)
    assert "# Keep my comment" in path.read_text()
    loaded = load_settings(path)
    assert loaded.hotkey == "f9"
    assert loaded.audio_device == "USB Mic, WASAPI"
    assert loaded.typing_delay_ms == 7
    assert loaded.hotword_boost == 2.5
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_invalid_settings_leave_existing_file_untouched(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[input]\nhotkey='f8'\n")
    old = path.read_bytes()
    settings = replace(
        load_settings(path),
        pipeline_mode="single",
        dictation=ProviderSettings(
            provider="openai", url="https://api.example/v1/chat", model=""
        ),
    )
    with pytest.raises(ValueError, match="model is required"):
        settings_document(path, settings)
    assert path.read_bytes() == old


def test_external_edits_are_not_overwritten(tmp_path):
    path = tmp_path / "config.toml"
    settings = load_settings(path)
    document = settings_document(path, settings)
    path.write_text("# Edited elsewhere")
    with pytest.raises(ValueError, match="changed outside"):
        write_settings(path, document, expected=None)
    assert path.read_text() == "# Edited elsewhere"


def test_default_microphone_removes_old_device_selection(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[audio]\ndevice=4\n")
    settings = replace(load_settings(path), audio_device=None)
    write_settings(path, settings_document(path, settings), expected=path.read_bytes())
    assert load_settings(path).audio_device is None
