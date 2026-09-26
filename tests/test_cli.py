import json

from cap_to_talk import cli


def test_check_json_success(monkeypatch, capsys):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("DISPLAY", ":1")
    monkeypatch.setattr(cli, "missing_commands", lambda: [])
    monkeypatch.setattr(cli.sd, "query_devices", lambda kind: {"name": "Test Mic"})
    monkeypatch.setattr(cli, "_endpoint_check", lambda _url: (True, "HTTP 200"))

    assert cli.main(["check", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert all(check["ok"] for check in result["checks"])
