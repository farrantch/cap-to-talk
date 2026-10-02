import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
    path.chmod(0o755)


def prepare_launcher(tmp_path):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "scripts/start.sh", project / "scripts/start.sh")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    for command in ("setxkbmap", "xmodmap", "xkbcomp", "xset"):
        executable(
            fake_bin / command,
            'printf "%s %s\\n" "${0##*/}" "$*" >> "$TEST_CALLS"\n',
        )
    executable(
        fake_bin / "curl",
        'echo "Unexpected hard-coded health check" >&2\nexit 99\n',
    )
    executable(
        project / ".venv/bin/cap-to-talk",
        'printf "app %s\\n" "$*" >> "$TEST_CALLS"\n'
        'if [[ "${1:-}" == check ]]; then exit "$TEST_CHECK_EXIT"; fi\n',
    )
    executable(project / ".venv/bin/python", "echo 66\n")
    executable(project / ".venv/bin/cap-to-talk-status", "exec sleep 60\n")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "XDG_SESSION_TYPE": "x11",
        "DISPLAY": ":99",
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "TEST_CALLS": str(calls),
        "TEST_CHECK_EXIT": "0",
    }
    return project, env, calls


@pytest.mark.skipif(os.name != "posix", reason="Linux launcher")
def test_launcher_uses_selected_provider_checks_and_restores_keyboard(tmp_path):
    project, env, calls = prepare_launcher(tmp_path)
    result = subprocess.run(
        ["bash", project / "scripts/start.sh"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    recorded = calls.read_text()
    assert "app check --services-only --wait-seconds 30" in recorded
    assert "app run" in recorded
    assert recorded.count("xkbcomp ") == 2
    assert not list(Path(env["XDG_RUNTIME_DIR"]).glob("*.pid"))


@pytest.mark.skipif(os.name != "posix", reason="Linux launcher")
def test_launcher_does_not_remap_keyboard_when_transcription_check_fails(tmp_path):
    project, env, calls = prepare_launcher(tmp_path)
    env["TEST_CHECK_EXIT"] = "1"
    result = subprocess.run(
        ["bash", project / "scripts/start.sh"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert calls.read_text() == "app check --services-only --wait-seconds 30\n"
    assert not list(Path(env["XDG_RUNTIME_DIR"]).glob("*.pid"))


@pytest.mark.skipif(os.name != "posix", reason="Linux launcher")
def test_function_shortcut_does_not_remap_caps_lock(tmp_path):
    project, env, calls = prepare_launcher(tmp_path)
    executable(project / ".venv/bin/python", "echo '66 f8'\n")
    result = subprocess.run(
        ["bash", project / "scripts/start.sh"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    recorded = calls.read_text()
    assert "setxkbmap" not in recorded
    assert "xmodmap" not in recorded
    assert "xset" not in recorded
    assert "app run" in recorded
