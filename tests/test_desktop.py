from __future__ import annotations

import json
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call

import pytest

from cap_to_talk import desktop, x11
from cap_to_talk.config import Settings
from cap_to_talk.desktop import DesktopCheck, DesktopUnavailableError
from cap_to_talk.desktop.linux_x11 import LinuxX11Desktop


@pytest.mark.parametrize(
    ("platform_name", "label"), [("freebsd", "freebsd"), ("haiku", "haiku")]
)
def test_unsupported_platform_has_an_actionable_error(
    monkeypatch, platform_name, label
):
    monkeypatch.setattr(desktop, "sys", SimpleNamespace(platform=platform_name))
    with pytest.raises(DesktopUnavailableError, match=label):
        desktop.create_desktop_backend(Settings())


def test_linux_selects_x11_without_connecting_to_display(monkeypatch):
    monkeypatch.setattr(desktop, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.delenv("DISPLAY", raising=False)
    assert isinstance(desktop.create_desktop_backend(Settings()), LinuxX11Desktop)


@pytest.mark.parametrize("platform_name", ["darwin", "win32"])
def test_core_and_service_checks_work_with_x11_imports_blocked(tmp_path, platform_name):
    script = """
import sys
from types import SimpleNamespace

sys.modules["Xlib"] = None
sys.modules["cap_to_talk.x11"] = None
sys.modules["cap_to_talk.desktop.linux_x11"] = None

from cap_to_talk import app, cli, desktop, services, status
from cap_to_talk.config import Settings

desktop.sys = SimpleNamespace(platform=sys.argv[1])
backend = desktop.create_desktop_backend(Settings())
assert backend._api is None
expected = "MacOSDesktop" if sys.argv[1] == "darwin" else "WindowsDesktop"
assert type(backend).__name__ == expected

def unexpected(*args, **kwargs):
    raise AssertionError("Service checks must not touch the desktop or microphone")

cli.create_desktop_backend = unexpected
cli.sd.query_devices = unexpected
cli.check_provider = lambda *args, **kwargs: (True, "mocked provider")
assert cli.main(["check", "--services-only", "--json", "--config", sys.argv[2]]) == 0
"""
    result = subprocess.run(
        [sys.executable, "-c", script, platform_name, str(tmp_path / "config.toml")],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["ok"] is True


@pytest.fixture
def native_x11(monkeypatch):
    class DisplayError(Exception):
        pass

    class ConnectionClosedError(Exception):
        pass

    constants = SimpleNamespace(
        KeyPress=2,
        KeyRelease=3,
        ShiftMask=1,
        AnyModifier=32768,
        GrabModeAsync=1,
        AutoRepeatModeOn=1,
        AutoRepeatModeOff=0,
    )
    root = Mock()
    connection = Mock()
    connection.screen.return_value = SimpleNamespace(root=root)
    native = ModuleType("Xlib")
    native.X = constants
    native.XK = SimpleNamespace(string_to_keysym=lambda name: name)
    connection.keysym_to_keycode.return_value = 74
    connection.get_keyboard_control.return_value.auto_repeats = bytes([255] * 32)
    native.display = SimpleNamespace(Display=Mock(return_value=connection))
    native.error = SimpleNamespace(
        DisplayError=DisplayError, ConnectionClosedError=ConnectionClosedError
    )
    monkeypatch.setitem(sys.modules, "Xlib", native)
    backend = LinuxX11Desktop(Settings(ptt_keycode=42))
    monkeypatch.setattr(backend, "check", lambda: [])
    return SimpleNamespace(
        backend=backend, root=root, connection=connection, native=native, X=constants
    )


def key_event(event_type, *, keycode=42, state=0):
    return SimpleNamespace(type=event_type, detail=keycode, state=state)


def test_x11_listener_delivers_raw_mode_once_per_press_and_releases_key(native_x11):
    native = native_x11
    callbacks = Mock()
    native.connection.next_event.side_effect = [
        key_event(native.X.KeyPress, keycode=99),
        key_event(native.X.KeyRelease),  # Ignore a release without a press.
        key_event(native.X.KeyPress, state=native.X.ShiftMask),
        key_event(native.X.KeyPress),  # Duplicate presses do not change raw mode.
        key_event(native.X.KeyRelease, keycode=99),
        key_event(native.X.KeyRelease),
        key_event(native.X.KeyRelease),
        key_event(native.X.KeyPress),
        key_event(native.X.KeyRelease),
        KeyboardInterrupt(),
    ]

    with pytest.raises(KeyboardInterrupt):
        native.backend.run_hotkey_loop(
            on_press=callbacks.pressed,
            on_release=callbacks.released,
            on_ready=callbacks.ready,
        )

    assert callbacks.mock_calls == [
        call.ready(),
        call.pressed(True),
        call.released(),
        call.pressed(False),
        call.released(),
    ]
    assert native.root.grab_key.call_args.args[0] == 42
    native.root.ungrab_key.assert_called_once_with(42, native.X.AnyModifier)
    native.connection.close.assert_called_once()


@pytest.mark.parametrize("failing_callback", ["on_ready", "on_press", "on_release"])
def test_x11_listener_cleans_up_when_a_callback_fails(native_x11, failing_callback):
    native = native_x11
    callbacks = {name: Mock() for name in ("on_ready", "on_press", "on_release")}
    callbacks[failing_callback].side_effect = RuntimeError("callback failure")
    native.connection.next_event.side_effect = [
        key_event(native.X.KeyPress),
        key_event(native.X.KeyRelease),
    ]
    with pytest.raises(RuntimeError, match="callback failure"):
        native.backend.run_hotkey_loop(**callbacks)
    native.root.ungrab_key.assert_called_once_with(42, native.X.AnyModifier)
    native.connection.close.assert_called_once()


def test_shortcut_conflict_is_reported_before_ready(native_x11):
    native = native_x11
    ready = Mock()

    def sync():
        if native.connection.sync.call_count == 1:
            handler = native.root.grab_key.call_args.kwargs["onerror"]
            assert handler(object(), object()) is True

    native.connection.sync.side_effect = sync
    with pytest.raises(DesktopUnavailableError, match="shortcut"):
        native.backend.run_hotkey_loop(
            on_press=Mock(), on_release=Mock(), on_ready=ready
        )
    ready.assert_not_called()
    native.connection.next_event.assert_not_called()
    native.root.ungrab_key.assert_called_once()
    native.connection.close.assert_called_once()


@pytest.mark.parametrize("operation", ["screen", "grab", "ungrab"])
def test_native_resources_close_when_setup_or_cleanup_fails(native_x11, operation):
    native = native_x11
    if operation == "screen":
        native.connection.screen.side_effect = RuntimeError("native failure")
    elif operation == "grab":
        native.root.grab_key.side_effect = RuntimeError("native failure")
    else:
        native.connection.next_event.side_effect = KeyboardInterrupt()
        native.root.ungrab_key.side_effect = RuntimeError("native failure")
    with pytest.raises(RuntimeError, match="native failure"):
        native.backend.run_hotkey_loop(
            on_press=Mock(), on_release=Mock(), on_ready=Mock()
        )
    native.connection.close.assert_called_once()
    if operation == "ungrab":
        native.connection.change_keyboard_control.assert_called_with(
            key=42, auto_repeat_mode=native.X.AutoRepeatModeOn
        )


def test_display_disconnect_reports_failure_and_still_closes(native_x11):
    native = native_x11
    native.connection.next_event.side_effect = (
        native.native.error.ConnectionClosedError()
    )
    native.root.ungrab_key.side_effect = native.native.error.ConnectionClosedError()
    with pytest.raises(DesktopUnavailableError, match="connection closed"):
        native.backend.run_hotkey_loop(
            on_press=Mock(), on_release=Mock(), on_ready=Mock()
        )
    native.connection.close.assert_called_once()


def test_display_connection_failure_is_actionable(native_x11):
    native = native_x11
    native.native.display.Display.side_effect = native.native.error.DisplayError()
    with pytest.raises(DesktopUnavailableError, match="desktop session"):
        native.backend.run_hotkey_loop(
            on_press=Mock(), on_release=Mock(), on_ready=Mock()
        )


def test_failed_desktop_check_does_not_take_over_shortcut(native_x11, monkeypatch):
    native = native_x11
    monkeypatch.setattr(
        native.backend,
        "check",
        lambda: [DesktopCheck("X11 session", False, "wayland")],
    )
    with pytest.raises(DesktopUnavailableError, match="X11 session: wayland"):
        native.backend.run_hotkey_loop(
            on_press=Mock(), on_release=Mock(), on_ready=Mock()
        )
    native.native.display.Display.assert_not_called()


@pytest.mark.parametrize("session_type", ["x11", "wayland"])
def test_linux_checks_session_display_commands_and_native_library(
    monkeypatch, session_type
):
    from cap_to_talk.desktop import linux_x11

    monkeypatch.setenv("XDG_SESSION_TYPE", session_type)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(x11, "missing_commands", lambda: ["xdotool"])
    monkeypatch.setattr(linux_x11.importlib.util, "find_spec", lambda name: None)
    checks = {check.name: check for check in LinuxX11Desktop(Settings()).check()}
    assert checks["X11 session"].ok is (session_type == "x11")
    assert checks["DISPLAY"].ok is False
    assert checks["desktop commands"].detail == "missing: xdotool"
    assert checks["X11 library"].ok is False


def test_linux_insert_restores_focus_after_typing_into_original_window(monkeypatch):
    monkeypatch.setattr(x11, "window_exists", lambda window: True)
    monkeypatch.setattr(x11, "get_active_window_id", lambda: "current-window")
    pause = Mock()
    typed = Mock()
    run = Mock()
    monkeypatch.setattr(x11, "wait_for_user_pause", pause)
    monkeypatch.setattr(x11, "_type", typed)
    monkeypatch.setattr(x11.subprocess, "run", run)
    monkeypatch.setattr(x11.time, "sleep", Mock())

    LinuxX11Desktop(Settings()).insert_text(
        "First line.\nSecond line.", "original-window", delay_ms=3
    )

    pause.assert_called_once()
    typed.assert_called_once_with("First line.\nSecond line.", 3)
    assert [item.args[0] for item in run.call_args_list] == [
        ["xdotool", "windowactivate", "--sync", "original-window"],
        ["xdotool", "windowactivate", "--sync", "current-window"],
    ]


def test_linux_insert_refuses_a_closed_target(monkeypatch):
    monkeypatch.setattr(x11, "window_exists", lambda window: False)
    typed = Mock()
    monkeypatch.setattr(x11, "_type", typed)
    with pytest.raises(RuntimeError, match="no longer exists"):
        LinuxX11Desktop(Settings()).insert_text("Message", "closed-window")
    typed.assert_not_called()


def test_linux_notifications_keep_replacement_id_and_ignore_missing_command(
    monkeypatch,
):
    from cap_to_talk.desktop import linux_x11

    launch = Mock(side_effect=FileNotFoundError())
    monkeypatch.setattr(linux_x11.subprocess, "Popen", launch)
    LinuxX11Desktop(Settings(notify_id="1234")).notify("Recording", 3000)
    assert launch.call_args.args[0] == [
        "notify-send",
        "-r",
        "1234",
        "-t",
        "3000",
        "Cap To Talk",
        "Recording",
    ]


def test_named_linux_shortcut_disables_and_restores_only_its_repeat(native_x11):
    native = native_x11
    native.backend.settings = Settings(ptt_keycode=42, hotkey="f8")
    native.connection.next_event.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        native.backend.run_hotkey_loop(
            on_press=Mock(), on_release=Mock(), on_ready=Mock()
        )
    assert native.root.grab_key.call_args.args[0] == 74
    native.connection.change_keyboard_control.assert_has_calls(
        [
            call(key=74, auto_repeat_mode=0),
            call(key=74, auto_repeat_mode=1),
        ]
    )
    native.root.ungrab_key.assert_called_once_with(74, native.X.AnyModifier)
