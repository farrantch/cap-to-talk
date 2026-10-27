import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cap_to_talk.config import load_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILES = (
    "install.sh",
    "pyproject.toml",
    "scripts/start.sh",
    "config/config.example.toml",
    "config/hotwords.example.txt",
    "config/master-hotwords.example.txt",
)
FAKE_COMMANDS = (
    "curl",
    "flock",
    "notify-send",
    "setxkbmap",
    "xdotool",
    "xkbcomp",
    "xmodmap",
    "xprintidle",
    "xset",
    "systemctl",
    "openasr",
    "ollama",
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() == 0,
    reason="Linux installer must run as a normal user",
)


class Installer:
    def __init__(self, tmp_path: Path) -> None:
        self.project = tmp_path / "project"
        for relative_path in PROJECT_FILES:
            destination = self.project / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / relative_path, destination)
        self.calls = tmp_path / "calls"
        self.calls.touch()
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        for command in FAKE_COMMANDS:
            self.fake(
                fake_bin / command,
                'printf "%s %s\\n" "${0##*/}" "$*" >> "$TEST_CALLS"\n',
            )
        # A new environment gets a cap-to-talk command that records saved keys.
        self.fake(
            fake_bin / "python3",
            'if [[ "${1:-}" == -m && "${2:-}" == venv ]]; then\n'
            '    mkdir -p "$3/bin"\n    cp "$0" "$3/bin/python"\n'
            '    cp "$TEST_SAVER" "$3/bin/cap-to-talk"\nfi\n',
        )
        saver = tmp_path / "saver"
        self.fake(
            saver,
            'printf "cap-to-talk %s key=%s\\n" "$*" "$(cat)" >> "$TEST_CALLS"\n',
        )
        # A clone copies the prepared project, as GitHub would serve it.
        self.fake(
            fake_bin / "git",
            'printf "git %s\\n" "$*" >> "$TEST_CALLS"\n'
            '[[ "$1" == clone ]] && mkdir -p "$3" && cp -R "$TEST_SOURCE"/. "$3"\n',
        )
        self.home = tmp_path / "home"
        self.config = self.home / ".config"
        self.data = self.home / ".local/share"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "XDG_SESSION_TYPE": "x11",
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_HOME": str(self.data),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "XDG_RUNTIME_DIR": str(tmp_path),
            "TEST_CALLS": str(self.calls),
            "TEST_SOURCE": str(self.project),
            "TEST_SAVER": str(saver),
        }
        self.env.pop("DISPLAY", None)
        for name in ("CAP_TO_TALK_CONFIRMED", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            self.env.pop(name, None)

    @staticmethod
    def fake(path: Path, body: str) -> None:
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)

    def run(
        self, *args: str, script: Path | None = None
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", script or self.project / "install.sh", "--yes", *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def install(self, *args: str) -> None:
        result = self.run("--no-start", "--skip-system-packages", *args)
        assert result.returncode == 0, result.stderr

    @property
    def autostart(self) -> Path:
        return self.config / "autostart/cap-to-talk.desktop"

    @property
    def menu(self) -> Path:
        return self.data / "applications/cap-to-talk.desktop"

    def recorded(self) -> list[str]:
        return self.calls.read_text().splitlines()

    @property
    def config_file(self) -> Path:
        return self.config / "cap-to-talk/config.toml"

    def settings(self):
        return load_settings(self.config_file)


@pytest.fixture
def installer(tmp_path: Path) -> Installer:
    return Installer(tmp_path)


def test_installs_from_checkout_without_local_services(installer):
    installer.install("--setup", "later")

    assert installer.recorded() == []
    assert (installer.project / ".venv/bin/python").exists()
    for name in ("config.toml", "hotwords.txt", "master-hotwords.txt"):
        assert (installer.config / "cap-to-talk" / name).is_file()
    link = installer.home / ".local/bin/cap-to-talk"
    assert os.readlink(link) == str(installer.project / ".venv/bin/cap-to-talk")
    assert f"Exec={installer.project}/scripts/start.sh" in installer.menu.read_text()
    assert not installer.autostart.exists()
    assert not (installer.config / "systemd").exists()


def test_default_setup_installs_standard_local_models(installer):
    installer.install()

    calls = installer.recorded()
    assert "openasr pull qwen3-asr-0.6b:q8" in calls
    assert "ollama pull qwen3:4b-instruct" in calls
    assert "systemctl --user daemon-reload" in calls
    service = installer.config / "systemd/user/cap-to-talk-openasr.service"
    openasr = Path(installer.env["PATH"].split(":")[0]) / "openasr"
    assert (
        f"ExecStart={openasr} serve --model qwen3-asr-0.6b --addr 127.0.0.1:8080"
        in service.read_text()
    )
    settings = installer.settings()
    assert settings.transcription_config.model == "qwen3-asr-0.6b"
    assert settings.rewrite_config.provider == "ollama"
    assert settings.rewrite_config.model == "qwen3:4b-instruct"


def test_best_size_downloads_and_configures_the_larger_models(installer):
    installer.install("--setup", "local", "--size", "best")

    calls = installer.recorded()
    assert "openasr pull qwen3-asr-1.7b:q8" in calls
    assert "ollama pull qwen3:8b" in calls
    service = installer.config / "systemd/user/cap-to-talk-openasr.service"
    assert "--model qwen3-asr-1.7b " in service.read_text()
    settings = installer.settings()
    assert settings.transcription_config.model == "qwen3-asr-1.7b"
    assert settings.rewrite_config.model == "qwen3:8b"


def test_claude_setup_saves_the_key_and_skips_ollama(installer):
    installer.env["ANTHROPIC_API_KEY"] = "sk-ant-test"
    installer.install("--setup", "claude")

    calls = installer.recorded()
    assert "openasr pull qwen3-asr-0.6b:q8" in calls
    assert not any(call.startswith("ollama") for call in calls)
    assert (
        f"cap-to-talk --config {installer.config_file} --save-key rewrite "
        "key=sk-ant-test" in calls
    )
    rewrite = installer.settings().rewrite_config
    assert (rewrite.provider, rewrite.model) == ("anthropic", "claude-opus-5-5")
    assert rewrite.api_key_source == "keyring"


def test_openai_setup_without_a_key_explains_how_to_add_it(installer):
    result = installer.run("--no-start", "--skip-system-packages", "--setup", "openai")

    assert result.returncode == 0, result.stderr
    assert installer.recorded() == []
    assert "cap-to-talk --save-key dictation" in result.stdout
    settings = installer.settings()
    assert settings.pipeline_mode == "single"
    dictation = settings.dictation_config
    assert (dictation.provider, dictation.model) == ("openai", "gpt-audio-1.5")
    assert dictation.api_key_source == "keyring"


def test_rerun_keeps_existing_providers_and_switching_resets_keys(installer):
    installer.env["ANTHROPIC_API_KEY"] = "sk-ant-test"
    installer.install("--setup", "claude")
    installer.calls.write_text("")
    installer.install()

    assert installer.settings().rewrite_config.provider == "anthropic"
    assert not any(call.startswith("ollama") for call in installer.recorded())

    installer.install("--setup", "local", "--size", "light")
    rewrite = installer.settings().rewrite_config
    assert (rewrite.provider, rewrite.model) == ("ollama", "qwen3:1.7b")
    assert rewrite.api_key_source == "environment"
    assert "ollama pull qwen3:1.7b" in installer.recorded()


def test_later_setup_leaves_the_example_settings_unchanged(installer):
    installer.install("--setup", "later")

    assert installer.recorded() == []
    example = PROJECT_ROOT / "config/config.example.toml"
    assert installer.config_file.read_text() == example.read_text()


def test_unknown_setup_is_rejected(installer):
    result = installer.run("--setup", "cloud")
    assert result.returncode == 1
    assert "--setup must be local, claude, openai, or later" in result.stderr


def test_rerun_keeps_settings_and_manages_only_its_autostart(installer):
    installer.install("--setup", "later", "--autostart")
    contents = installer.autostart.read_text()
    config_file = installer.config / "cap-to-talk/config.toml"
    config_file.write_text("# personalized\n")
    installer.install("--setup", "later", "--autostart")

    assert installer.autostart.read_text() == contents
    assert "X-GNOME-Autostart-enabled=true" in contents
    assert config_file.read_text() == "# personalized\n"

    installer.install("--setup", "later")
    assert not installer.autostart.exists()

    installer.autostart.write_text("[Desktop Entry]\nExec=/another/cap-to-talk\n")
    installer.install("--setup", "later")
    assert (
        installer.autostart.read_text()
        == "[Desktop Entry]\nExec=/another/cap-to-talk\n"
    )


def test_download_clones_a_copy_and_installs_from_it(installer, tmp_path):
    download = tmp_path / "download/install.sh"
    download.parent.mkdir()
    shutil.copy2(PROJECT_ROOT / "install.sh", download)

    result = installer.run(
        "--no-start",
        "--skip-system-packages",
        "--setup",
        "later",
        script=download,
    )

    assert result.returncode == 0, result.stderr
    managed = installer.data / "cap-to-talk"
    assert (
        f"git clone https://github.com/farrantch/cap-to-talk.git {managed}"
        in installer.recorded()
    )
    assert (managed / ".venv/bin/python").exists()
    assert f"Exec={managed}/scripts/start.sh" in installer.menu.read_text()
    assert result.stdout.count("Cap To Talk will:") == 1


def test_uninstall_keeps_settings_unless_purged(installer):
    installer.install("--setup", "later", "--autostart")
    config_dir = installer.config / "cap-to-talk"

    result = installer.run("--uninstall")
    assert result.returncode == 0, result.stderr
    assert not (installer.project / ".venv").exists()
    assert not (installer.home / ".local/bin/cap-to-talk").is_symlink()
    assert not installer.menu.exists()
    assert not installer.autostart.exists()
    assert (config_dir / "config.toml").is_file()

    result = installer.run("--uninstall", "--purge")
    assert result.returncode == 0, result.stderr
    assert not config_dir.exists()


def test_purge_requires_uninstall(installer):
    result = installer.run("--purge")
    assert result.returncode == 1
    assert "--purge requires --uninstall" in result.stderr
