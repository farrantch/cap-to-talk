import os
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def prepare_installer(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    project_dir = tmp_path / "project"
    for relative_path in (
        "scripts/install-user.sh",
        "autostart/caps-talk.desktop.in",
        "config/config.example.toml",
        "config/hotwords.example.txt",
        "config/master-hotwords.example.txt",
    ):
        source = PROJECT_ROOT / relative_path
        destination = project_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
    mkdir -p "$3/bin"
    cp "$0" "$3/bin/python"
fi
"""
    )
    fake_python.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        PATH=f"{fake_bin}:/usr/bin:/bin",
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_STATE_HOME=str(home / ".local/state"),
    )
    return project_dir, env


def run_installer(project_dir: Path, env: dict[str, str], *args: str) -> None:
    subprocess.run(
        [project_dir / "scripts/install-user.sh", *args],
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )


def test_on_demand_install_is_default_and_idempotent(tmp_path: Path) -> None:
    project_dir, env = prepare_installer(tmp_path)
    autostart_file = Path(env["XDG_CONFIG_HOME"]) / "autostart/caps-talk.desktop"
    config_file = Path(env["XDG_CONFIG_HOME"]) / "caps-talk/config.toml"

    run_installer(project_dir, env)
    config_file.write_text("# personalized\n")
    run_installer(project_dir, env)

    assert not autostart_file.exists()
    assert config_file.read_text() == "# personalized\n"


def test_autostart_install_is_idempotent(tmp_path: Path) -> None:
    project_dir, env = prepare_installer(tmp_path)
    autostart_file = Path(env["XDG_CONFIG_HOME"]) / "autostart/caps-talk.desktop"

    run_installer(project_dir, env, "--autostart")
    expected_contents = autostart_file.read_text()
    run_installer(project_dir, env, "--autostart")

    assert autostart_file.read_text() == expected_contents
    assert f"Exec={project_dir}/scripts/start.sh" in expected_contents


def test_default_install_disables_managed_autostart(tmp_path: Path) -> None:
    project_dir, env = prepare_installer(tmp_path)
    autostart_file = Path(env["XDG_CONFIG_HOME"]) / "autostart/caps-talk.desktop"

    run_installer(project_dir, env, "--autostart")
    run_installer(project_dir, env)

    assert not autostart_file.exists()


def test_default_install_preserves_unmanaged_autostart(tmp_path: Path) -> None:
    project_dir, env = prepare_installer(tmp_path)
    autostart_file = Path(env["XDG_CONFIG_HOME"]) / "autostart/caps-talk.desktop"
    autostart_file.parent.mkdir(parents=True)
    autostart_file.write_text("[Desktop Entry]\nExec=/another/caps-talk\n")

    run_installer(project_dir, env)

    assert autostart_file.read_text() == ("[Desktop Entry]\nExec=/another/caps-talk\n")
