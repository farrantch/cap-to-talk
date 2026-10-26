import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cap_to_talk import cli
from cap_to_talk.desktop import DesktopBackend, DesktopCheck


def test_check_json_success(monkeypatch, capsys):
    backend = Mock(spec=DesktopBackend)
    backend.check.return_value = [DesktopCheck("test desktop", True, "available")]
    monkeypatch.setattr(cli, "create_desktop_backend", lambda settings: backend)
    monkeypatch.setattr(cli.sd, "query_devices", lambda **kwargs: {"name": "Test Mic"})
    monkeypatch.setattr(
        cli, "check_provider", lambda _config, **_kwargs: (True, "HTTP 200")
    )

    assert cli.main(["check", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert all(check["ok"] for check in result["checks"])


def test_service_only_check_uses_selected_providers(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"
    path.write_text(
        '[transcription]\nprovider = "openai"\nmodel = "speech-model"\n'
        '[rewrite]\nprovider = "none"\n'
    )
    selected = []

    def check(config, **_kwargs):
        selected.append(config.provider)
        return True, "configured"

    monkeypatch.setattr(cli, "check_provider", check)

    def unexpected(*args, **kwargs):
        raise AssertionError("Desktop and microphone must not be checked")

    monkeypatch.setattr(cli.sd, "query_devices", unexpected)
    monkeypatch.setattr(cli, "create_desktop_backend", unexpected)

    assert cli.main(["check", "--services-only", "--json", "--config", str(path)]) == 0
    assert selected == ["openai", "none"]
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert len(result["checks"]) == 2


def test_unavailable_cleanup_is_optional(tmp_path, monkeypatch, capsys):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(
        cli,
        "check_provider",
        lambda config, **_kwargs: (config.provider == "openasr", "test status"),
    )
    assert cli.main(["check", "--services-only", "--config", str(path)]) == 0
    output = capsys.readouterr().out
    assert "[WARN] cleanup" in output
    assert "Raw transcripts will be used" in output


def test_unavailable_transcription_fails_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "check_provider", lambda config, **_kwargs: (False, "test failure")
    )
    assert (
        cli.main(
            [
                "check",
                "--services-only",
                "--json",
                "--config",
                str(tmp_path / "config.toml"),
            ]
        )
        == 1
    )
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False


@pytest.mark.parametrize("available", [False, True])
def test_single_mode_checks_only_required_dictation_provider(
    tmp_path, monkeypatch, capsys, available
):
    path = tmp_path / "config.toml"
    path.write_text("""
[pipeline]
mode = "single"
[dictation]
provider = "openai"
model = "audio-model"
[transcription]
provider = "openai"
[rewrite]
provider = "anthropic"
""")
    check = Mock(return_value=(available, "test status"))
    monkeypatch.setattr(cli, "check_provider", check)
    assert cli.main(
        [
            "check",
            "--services-only",
            "--json",
            "--wait-seconds",
            "10",
            "--config",
            str(path),
        ]
    ) == (0 if available else 1)
    check.assert_called_once()
    assert check.call_args.args[0].model == "audio-model"
    assert check.call_args.kwargs == {"wait_seconds": 10}
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is available
    assert result["checks"] == [
        {
            "name": "dictation (openai)",
            "ok": available,
            "required": True,
            "detail": "test status",
        }
    ]


@pytest.mark.parametrize("platform_name", ["freebsd", "haiku"])
def test_run_on_unsupported_platform_returns_clear_error(
    tmp_path, monkeypatch, capsys, platform_name
):
    from cap_to_talk import desktop

    monkeypatch.setattr(desktop, "sys", SimpleNamespace(platform=platform_name))
    monkeypatch.setattr(cli.signal, "signal", Mock())
    assert cli.main(["run", "--config", str(tmp_path / "config.toml")]) == 1
    output = capsys.readouterr()
    assert "Desktop error:" in output.err
    assert "not available" in output.err
    assert "Xlib" not in output.err
    assert "Traceback" not in output.err


def test_full_check_reports_unsupported_desktop_as_required_failure(
    tmp_path, monkeypatch, capsys
):
    from cap_to_talk import desktop

    monkeypatch.setattr(desktop, "sys", SimpleNamespace(platform="freebsd"))
    monkeypatch.setattr(cli.sd, "query_devices", lambda **kwargs: {"name": "Test Mic"})
    monkeypatch.setattr(cli, "check_provider", lambda *args, **kwargs: (True, "ready"))
    assert cli.main(["check", "--json", "--config", str(tmp_path / "config.toml")]) == 1
    result = json.loads(capsys.readouterr().out)
    failed = [item for item in result["checks"] if not item["ok"]]
    assert len(failed) == 1
    assert failed[0]["name"] == "desktop"
    assert failed[0]["required"] is True
    assert "freebsd" in failed[0]["detail"]


def test_run_injects_selected_desktop_into_app(tmp_path, monkeypatch):
    from cap_to_talk import app

    backend = Mock(spec=DesktopBackend)
    select = Mock(return_value=backend)
    application = Mock()
    monkeypatch.setattr(cli, "create_desktop_backend", select)
    monkeypatch.setattr(cli.signal, "signal", Mock())
    monkeypatch.setattr(app, "VoiceDictationApp", application)
    assert cli.main(["run", "--config", str(tmp_path / "config.toml")]) == 0
    select.assert_called_once()
    assert application.call_args.kwargs == {"desktop": backend}
    application.return_value.run.assert_called_once()
