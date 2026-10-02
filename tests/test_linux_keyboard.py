from unittest.mock import Mock

import pytest

from cap_to_talk.config import Settings
from cap_to_talk.desktop import linux_keyboard


def test_keyboard_map_is_restored_on_failure(monkeypatch):
    command = Mock(return_value=Mock(stdout="saved-keymap"))
    monkeypatch.setattr(linux_keyboard.subprocess, "run", command)
    monkeypatch.setenv("DISPLAY", ":99")
    with (
        pytest.raises(RuntimeError, match="worker failed"),
        linux_keyboard.prepared_keyboard(Settings()),
    ):
        raise RuntimeError("worker failed")
    assert command.call_args.args[0] == ["xkbcomp", "-", ":99"]
    assert command.call_args.kwargs["input"] == "saved-keymap"


def test_function_keys_leave_keyboard_map_alone(monkeypatch):
    command = Mock()
    monkeypatch.setattr(linux_keyboard.subprocess, "run", command)
    with linux_keyboard.prepared_keyboard(Settings(hotkey="f9")):
        pass
    command.assert_not_called()
