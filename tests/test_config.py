from pathlib import Path

import pytest

from caps_talk.config import load_settings


def test_loads_toml_and_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_root = tmp_path / "config"
    config_dir = config_root / "caps-talk"
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
    monkeypatch.setenv("CAPS_TALK_REWRITE_MODEL", "environment-model")

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
    monkeypatch.setenv("CAP_TO_TALK_REWRITE_MODEL", "legacy-model")

    assert load_settings(config_path).rewrite_model == "legacy-model"

    monkeypatch.setenv("CAPS_TALK_REWRITE_MODEL", "caps-model")

    assert load_settings(config_path).rewrite_model == "caps-model"


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
