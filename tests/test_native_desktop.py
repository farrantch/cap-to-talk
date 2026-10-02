from __future__ import annotations

import ctypes
import sys
import threading
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from cap_to_talk.config import Settings
from cap_to_talk.desktop.base import DesktopUnavailableError
from cap_to_talk.desktop.macos import EVENT_TAG as MAC_EVENT_TAG
from cap_to_talk.desktop.macos import MacOSAPI, MacOSDesktop, MacOSTarget
from cap_to_talk.desktop.windows import (
    DWORD,
    INPUT,
    KBDLLHOOKSTRUCT,
    LASTINPUTINFO,
    WindowsAPI,
    WindowsDesktop,
    WindowsTarget,
    keyboard_inputs,
)


class FakeAPI:
    def __init__(self):
        self.current = "original"
        self.windows = {"original", "other", "third"}
        self.typed = []
        self.modifiers = False
        self.cleaned = threading.Event()

    def check(self, hotkey):
        return []

    def foreground_target(self):
        return self.current

    def same_target(self, first, second):
        return first == second

    def window_exists(self, target):
        return target in self.windows

    def activate(self, target):
        self.current = target

    def modifiers_pressed(self):
        return self.modifiers

    def idle_ms(self):
        return 2000

    def type_character(self, char):
        self.typed.append((self.current, char))

    def listen(self, hotkey, emit, ready, stopped):
        try:
            ready()
            emit(True, True)
            emit(True, False)
            emit(False, False)
            emit(False, False)
            emit(True, False)
            emit(False, False)
            stopped.wait()
        finally:
            self.cleaned.set()


@pytest.fixture
def native_desktop():
    backend = WindowsDesktop(Settings())
    backend._api = FakeAPI()
    return backend


def test_native_insertion_targets_original_window_then_restores_focus(native_desktop):
    backend = native_desktop
    target = backend.capture_target()
    backend.api.current = "other"
    backend.insert_text("Hi 💬\nNext", target)
    assert backend.api.typed == [("original", char) for char in "Hi 💬\nNext"]
    assert backend.api.current == "other"
    backend.release_target(target)
    assert backend._targets == {}


def test_native_insertion_rejects_closed_or_released_target(native_desktop):
    backend = native_desktop
    target = backend.capture_target()
    backend.api.windows.remove("original")
    with pytest.raises(DesktopUnavailableError, match="no longer exists"):
        backend.insert_text("private text", target)
    assert backend.api.typed == []
    backend.release_target(target)
    with pytest.raises(DesktopUnavailableError, match="no longer exists"):
        backend.insert_text("private text", target)


def test_native_insertion_stops_when_user_changes_focus(native_desktop):
    backend = native_desktop
    target = backend.capture_target()
    backend.api.current = "other"

    def type_character(char):
        backend.api.typed.append((backend.api.current, char))
        backend.api.current = "third"

    backend.api.type_character = type_character
    with pytest.raises(DesktopUnavailableError, match="focus"):
        backend.insert_text("abc", target)
    assert backend.api.typed == [("original", "a")]
    assert backend.api.current == "third"


def test_native_insertion_refuses_to_type_when_activation_fails(native_desktop):
    backend = native_desktop
    target = backend.capture_target()
    backend.api.current = "other"
    backend.api.activate = Mock()  # The OS declines to change focus.
    with pytest.raises(DesktopUnavailableError, match="focus"):
        backend.insert_text("abc", target)
    assert backend.api.typed == []


def test_native_shutdown_prevents_pending_insertion(native_desktop):
    target = native_desktop.capture_target()
    native_desktop._stopped.set()
    with pytest.raises(DesktopUnavailableError, match="stopped"):
        native_desktop.insert_text("abc", target)
    assert native_desktop.api.typed == []


def test_native_loop_keeps_callbacks_off_hook_thread_and_freezes_raw_mode(
    native_desktop,
):
    calls = []
    main_thread = threading.get_ident()

    def record(*args):
        assert threading.get_ident() == main_thread
        calls.append(args)
        if len(calls) == 5:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        native_desktop.run_hotkey_loop(
            on_ready=lambda: record("ready"),
            on_press=lambda raw: record("press", raw),
            on_release=lambda: record("release"),
        )
    assert calls == [
        ("ready",),
        ("press", True),
        ("release",),
        ("press", False),
        ("release",),
    ]
    assert native_desktop.api.cleaned.is_set()


def test_native_callback_failure_stops_hook_and_releases_targets(native_desktop):
    native_desktop.capture_target()
    with pytest.raises(RuntimeError, match="callback"):
        native_desktop.run_hotkey_loop(
            on_ready=Mock(side_effect=RuntimeError("callback")),
            on_press=Mock(),
            on_release=Mock(),
        )
    assert native_desktop.api.cleaned.is_set()
    assert native_desktop._targets == {}


def test_native_startup_failure_does_not_announce_ready(native_desktop):
    native_desktop.api.listen = Mock(
        side_effect=DesktopUnavailableError("Permission denied")
    )
    ready = Mock()
    with pytest.raises(DesktopUnavailableError, match="Permission denied"):
        native_desktop.run_hotkey_loop(
            on_ready=ready, on_press=Mock(), on_release=Mock()
        )
    ready.assert_not_called()


def test_native_capture_requires_a_real_window(native_desktop):
    native_desktop.api.current = None
    with pytest.raises(DesktopUnavailableError, match="target window"):
        native_desktop.capture_target()
    assert native_desktop._targets == {}


@pytest.mark.parametrize("char, units", [("é", [0xE9]), ("💬", [0xD83D, 0xDCAC])])
def test_windows_unicode_input_contains_complete_utf16_pairs(char, units):
    events = keyboard_inputs(char)
    assert [event.ki.wScan for event in events] == [
        unit for unit in units for _ in range(2)
    ]
    assert [event.ki.dwFlags for event in events] == [4, 6] * len(units)
    assert all(event.type == 1 and event.ki.wVk == 0 for event in events)
    assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


def test_windows_newlines_are_enter_key_events():
    events = keyboard_inputs("\n")
    assert [event.ki.wVk for event in events] == [13, 13]
    assert [event.ki.dwFlags for event in events] == [0, 2]


@pytest.fixture
def windows_api():
    api = WindowsAPI.__new__(WindowsAPI)
    api.user32 = Mock()
    api.kernel32 = Mock()
    api.hook_type = lambda callback: callback
    api.user32.CallNextHookEx.return_value = 0
    return api


@pytest.mark.parametrize("sent", [0, 1])
def test_windows_blocked_or_partial_send_is_an_error(windows_api, sent):
    windows_api.user32.SendInput.return_value = sent
    with pytest.raises(DesktopUnavailableError, match="blocked"):
        windows_api.type_character("A")


def test_windows_target_detects_reused_window_handle(windows_api):
    windows_api.user32.GetForegroundWindow.return_value = 123
    windows_api.user32.IsWindow.return_value = 1

    def pid(hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(DWORD)).contents.value = 42
        return 7

    windows_api.user32.GetWindowThreadProcessId.side_effect = pid
    target = windows_api.foreground_target()
    assert target == WindowsTarget(123, 42)
    assert windows_api.window_exists(target)
    assert not windows_api.window_exists(WindowsTarget(123, 99))


def test_windows_idle_clock_handles_tick_wraparound(windows_api):
    def last_input(pointer):
        ctypes.cast(pointer, ctypes.POINTER(LASTINPUTINFO)).contents.dwTime = 0xFFFFFFF0
        return 1

    windows_api.user32.GetLastInputInfo.side_effect = last_input
    windows_api.kernel32.GetTickCount64.return_value = 0x100000010
    assert windows_api.idle_ms() == 32


def test_windows_hook_suppresses_only_selected_physical_key(windows_api):
    api = windows_api
    stopped = threading.Event()
    events = []
    results = []
    api.user32.SetWindowsHookExW.return_value = 123
    api.user32.GetAsyncKeyState.return_value = 0x8000

    def pump(*args):
        callback = api.user32.SetWindowsHookExW.call_args.args[1]
        for key, flags, message in [
            (0x41, 0, 0x100),
            (0x14, 0x10, 0x100),
            (0x14, 0, 0x100),
            (0x14, 0, 0x101),
        ]:
            event = KBDLLHOOKSTRUCT(vkCode=key, flags=flags)
            results.append(callback(0, message, ctypes.byref(event)))
        stopped.set()
        return 0

    api.user32.PeekMessageW.side_effect = pump
    ready = Mock()
    api.listen(
        "caps_lock", lambda down, raw: events.append((down, raw)), ready, stopped
    )
    assert results == [0, 0, 1, 1]
    assert events == [(True, True), (False, True)]
    ready.assert_called_once()
    api.user32.UnhookWindowsHookEx.assert_called_once_with(123)


def test_windows_hook_registration_failure_does_not_announce_ready(windows_api):
    windows_api.user32.SetWindowsHookExW.return_value = 0
    ready = Mock()
    with pytest.raises(DesktopUnavailableError, match="register"):
        windows_api.listen("f8", Mock(), ready, threading.Event())
    ready.assert_not_called()


def test_windows_hook_is_removed_if_ready_callback_fails(windows_api):
    windows_api.user32.SetWindowsHookExW.return_value = 123
    with pytest.raises(RuntimeError):
        windows_api.listen(
            "f8", Mock(), Mock(side_effect=RuntimeError()), threading.Event()
        )
    windows_api.user32.UnhookWindowsHookEx.assert_called_once_with(123)


@pytest.fixture
def mac_api():
    api = MacOSAPI.__new__(MacOSAPI)
    api.objc = SimpleNamespace(autorelease_pool=nullcontext)
    api.ax = Mock()
    api.ax.AXIsProcessTrusted.return_value = True
    api.av = Mock()
    api.av.AVCaptureDevice.authorizationStatusForMediaType_.return_value = 3
    api.quartz = Mock()
    api.quartz.CGPreflightListenEventAccess.return_value = True
    constants = {
        "kCGEventKeyDown": 10,
        "kCGEventKeyUp": 11,
        "kCGEventTapDisabledByTimeout": 0xFFFFFFFE,
        "kCGEventTapDisabledByUserInput": 0xFFFFFFFF,
        "kCGKeyboardEventKeycode": 9,
        "kCGEventSourceUserData": 42,
        "kCGEventFlagMaskShift": 1,
        "kCGHIDEventTap": 0,
        "kCGSessionEventTap": 1,
        "kCGHeadInsertEventTap": 0,
        "kCGEventTapOptionDefault": 0,
        "kCFRunLoopDefaultMode": "default",
    }
    for name, value in constants.items():
        setattr(api.quartz, name, value)
    api.quartz.CGEventGetIntegerValueField.side_effect = lambda event, field: event.get(
        field, 0
    )
    api.quartz.CGEventGetFlags.side_effect = lambda event: event.get("flags", 0)
    return api


def test_mac_checks_permissions_and_rejects_caps_lock(mac_api):
    mac_api.ax.AXIsProcessTrusted.return_value = False
    mac_api.quartz.CGPreflightListenEventAccess.return_value = False
    mac_api.av.AVCaptureDevice.authorizationStatusForMediaType_.return_value = 2
    checks = {item.name: item for item in mac_api.check("caps_lock")}
    assert all(not item.ok for item in checks.values())
    assert "Accessibility" in checks["Accessibility"].detail
    assert "reliable release" in checks["dictation shortcut"].detail


def test_mac_allows_undecided_microphone_permission_without_requesting_it(mac_api):
    mac_api.av.AVCaptureDevice.authorizationStatusForMediaType_.return_value = 0
    checks = mac_api.check("f8")
    assert all(item.ok for item in checks)
    mac_api.av.AVCaptureDevice.requestAccessForMediaType_completionHandler_.assert_not_called()


def test_mac_unicode_input_includes_both_surrogate_units(mac_api):
    mac_api.type_character("💬")
    assert mac_api.quartz.CGEventKeyboardSetUnicodeString.call_count == 2
    for item in mac_api.quartz.CGEventKeyboardSetUnicodeString.call_args_list:
        assert item.args[1:] == (2, "💬")
    assert mac_api.quartz.CGEventPost.call_count == 2


def test_mac_newline_uses_return_key_without_unicode_payload(mac_api):
    mac_api.type_character("\n")
    assert [
        item.args for item in mac_api.quartz.CGEventCreateKeyboardEvent.call_args_list
    ] == [(None, 0x24, True), (None, 0x24, False)]
    mac_api.quartz.CGEventKeyboardSetUnicodeString.assert_not_called()


def test_mac_permission_revocation_prevents_insertion(mac_api):
    mac_api.ax.AXIsProcessTrusted.return_value = False
    with pytest.raises(DesktopUnavailableError, match="revoked"):
        mac_api.type_character("A")
    mac_api.quartz.CGEventPost.assert_not_called()


def test_mac_tap_suppresses_only_shortcut_and_cleans_up(mac_api):
    q = mac_api.quartz
    stopped = threading.Event()
    emitted = []
    results = []

    def pump(*args):
        callback = q.CGEventTapCreate.call_args.args[4]
        for event_type, event in [
            (10, {9: 50}),
            (10, {9: 100, 42: MAC_EVENT_TAG}),
            (10, {9: 100, "flags": 1}),
            (11, {9: 100}),
        ]:
            results.append(callback(None, event_type, event, None))
        stopped.set()

    q.CFRunLoopRunInMode.side_effect = pump
    ready = Mock()
    mac_api.listen("f8", lambda down, raw: emitted.append((down, raw)), ready, stopped)
    assert emitted == [(True, True), (False, False)]
    assert results[:2] == [{9: 50}, {9: 100, 42: MAC_EVENT_TAG}]
    assert results[2:] == [None, None]
    ready.assert_called_once()
    q.CGEventTapEnable.assert_has_calls(
        [
            call(q.CGEventTapCreate.return_value, True),
            call(q.CGEventTapCreate.return_value, False),
        ]
    )
    q.CFRunLoopRemoveSource.assert_called_once()
    q.CFMachPortInvalidate.assert_called_once_with(q.CGEventTapCreate.return_value)


def test_mac_registration_denied_does_not_announce_ready(mac_api):
    mac_api.quartz.CGEventTapCreate.return_value = None
    ready = Mock()
    with pytest.raises(DesktopUnavailableError, match="permissions"):
        mac_api.listen("f8", Mock(), ready, threading.Event())
    ready.assert_not_called()


def test_mac_tap_cleanup_runs_when_ready_callback_fails(mac_api):
    with pytest.raises(RuntimeError):
        mac_api.listen(
            "f8", Mock(), Mock(side_effect=RuntimeError()), threading.Event()
        )
    mac_api.quartz.CFMachPortInvalidate.assert_called_once()
    mac_api.quartz.CFRunLoopRemoveSource.assert_called_once()


def test_mac_disabled_tap_is_reported(mac_api):
    q = mac_api.quartz

    def pump(*args):
        callback = q.CGEventTapCreate.call_args.args[4]
        callback(None, q.kCGEventTapDisabledByTimeout, {}, None)

    q.CFRunLoopRunInMode.side_effect = pump
    with pytest.raises(DesktopUnavailableError, match="disabled"):
        mac_api.listen("f8", Mock(), Mock(), threading.Event())
    q.CFMachPortInvalidate.assert_called_once()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows SDK smoke check")
def test_windows_sdk_bindings_load_without_registering_a_hook():
    api = WindowsAPI()
    assert api.user32.SendInput.restype is DWORD


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS SDK smoke check")
def test_mac_sdk_bindings_load_without_requesting_permissions():
    api = MacOSAPI()
    for name in [
        "CGPreflightListenEventAccess",
        "CGEventTapCreate",
        "CGEventKeyboardSetUnicodeString",
        "CFMachPortInvalidate",
    ]:
        assert callable(getattr(api.quartz, name))
    assert callable(api.ax.AXUIElementCopyAttributeValue)


def test_platform_hotkey_defaults():
    assert WindowsDesktop(Settings()).hotkey == "caps_lock"
    assert MacOSDesktop(Settings()).hotkey == "f8"
    assert WindowsDesktop(Settings(hotkey="f10")).hotkey == "f10"


def test_mac_closed_window_reference_is_rejected(mac_api):
    app = Mock()
    app.isTerminated.return_value = False
    target = MacOSTarget(123, app, object())
    mac_api.ax.AXUIElementCopyAttributeValue.return_value = (-25202, None)
    assert not mac_api.window_exists(target)


def test_mac_failed_run_loop_setup_invalidates_created_tap(mac_api):
    mac_api.quartz.CFMachPortCreateRunLoopSource.return_value = None
    ready = Mock()
    with pytest.raises(DesktopUnavailableError, match="event loop"):
        mac_api.listen("f8", Mock(), ready, threading.Event())
    ready.assert_not_called()
    mac_api.quartz.CFMachPortInvalidate.assert_called_once()
