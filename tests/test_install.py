import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="Linux installer must run as a normal user",
)
def test_skip_local_services_installs_app_without_downloads_or_system_services(
    tmp_path,
):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "install.sh", project / "install.sh")
    calls = tmp_path / "calls"
    stub_installer = project / "scripts/install-user.sh"
    stub_installer.write_text(
        '#!/usr/bin/env bash\nprintf "install-user %s\\n" "$*" >> "$TEST_CALLS"\n'
    )
    stub_installer.chmod(0o755)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command in (
        "curl",
        "flock",
        "notify-send",
        "python3",
        "setxkbmap",
        "xdotool",
        "xkbcomp",
        "xmodmap",
        "xprintidle",
        "xset",
        "systemctl",
        "openasr",
        "ollama",
    ):
        path = fake_bin / command
        path.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s %s\\n" "${0##*/}" "$*" >> "$TEST_CALLS"\n'
            '[[ "${0##*/}" == python3 ]]\n'
        )
        path.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "XDG_SESSION_TYPE": "x11",
        "TEST_CALLS": str(calls),
    }
    result = subprocess.run(
        [
            "bash",
            project / "install.sh",
            "--yes",
            "--no-start",
            "--skip-system-packages",
            "--skip-local-services",
            "--autostart",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    recorded = calls.read_text().splitlines()
    assert len(recorded) == 2
    assert recorded[0].startswith("python3 -c ")
    assert recorded[1] == "install-user --autostart"
    assert not (tmp_path / "home/.config/systemd").exists()
