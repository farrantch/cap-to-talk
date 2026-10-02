from unittest.mock import Mock, call

import numpy as np
import pytest

from cap_to_talk import app
from cap_to_talk.config import ProviderSettings, Settings
from cap_to_talk.desktop import DesktopBackend
from cap_to_talk.providers import ProviderError


@pytest.fixture
def desktop():
    return Mock(spec=DesktopBackend)


@pytest.mark.parametrize("cleanup_provider", ["ollama", "none"])
def test_cleanup_failure_or_disabled_cleanup_keeps_raw_transcript(
    tmp_path, monkeypatch, desktop, cleanup_provider
):
    settings = Settings(
        rewrite=ProviderSettings(provider=cleanup_provider)
    ).with_runtime_paths(tmp_path)
    instance = app.VoiceDictationApp(settings, desktop=desktop)
    instance.services = Mock()
    raw = "This is the complete original transcript."
    instance.services.transcribe.return_value = raw
    instance.services.rewrite.side_effect = ProviderError("Cleanup unavailable")
    inserted = desktop.insert_text
    status = Mock()
    monkeypatch.setattr(app, "send_status", status)
    instance.transcribing = True

    instance._process_audio(np.zeros((4000, 1)), False, "original-window")

    inserted.assert_called_once_with(raw, "original-window", delay_ms=0)
    assert instance.transcribing is False
    if cleanup_provider == "none":
        instance.services.rewrite.assert_not_called()
        assert not any("Cleaning" in call.args[1] for call in status.call_args_list)


def test_transcription_failure_does_not_insert_text_or_call_cleanup(
    tmp_path, monkeypatch, desktop
):
    instance = app.VoiceDictationApp(
        Settings().with_runtime_paths(tmp_path), desktop=desktop
    )
    instance.services = Mock()
    instance.services.transcribe.side_effect = ProviderError(
        "Speech service unavailable"
    )
    inserted = desktop.insert_text
    monkeypatch.setattr(app, "send_status", Mock())
    instance.transcribing = True

    instance._process_audio(np.zeros((4000, 1)), False, "original-window")

    inserted.assert_not_called()
    instance.services.rewrite.assert_not_called()
    assert instance.transcribing is False


@pytest.mark.parametrize("raw_mode", [False, True])
def test_single_mode_inserts_one_model_result_without_running_other_stages(
    tmp_path, monkeypatch, desktop, raw_mode
):
    settings = Settings(pipeline_mode="single").with_runtime_paths(tmp_path)
    instance = app.VoiceDictationApp(settings, desktop=desktop)
    instance.services = Mock()
    instance.services.dictate.return_value = "Message from the audio model."
    inserted = desktop.insert_text
    status = Mock()
    monkeypatch.setattr(app, "send_status", status)
    instance.transcribing = True
    audio = np.zeros((4000, 1))

    instance._process_audio(audio, raw_mode, "original-window")

    instance.services.dictate.assert_called_once_with(audio, raw_mode=raw_mode)
    instance.services.transcribe.assert_not_called()
    instance.services.rewrite.assert_not_called()
    inserted.assert_called_once_with(
        "Message from the audio model.", "original-window", delay_ms=0
    )
    assert not any("Cleaning" in call.args[1] for call in status.call_args_list)
    assert instance.transcribing is False


@pytest.mark.parametrize("failed", [False, True])
def test_single_mode_empty_response_or_failure_does_not_insert_or_fall_back(
    tmp_path, monkeypatch, desktop, failed
):
    settings = Settings(pipeline_mode="single").with_runtime_paths(tmp_path)
    instance = app.VoiceDictationApp(settings, desktop=desktop)
    instance.services = Mock()
    instance.services.dictate.return_value = ""
    if failed:
        instance.services.dictate.side_effect = ProviderError("Audio model unavailable")
    inserted = desktop.insert_text
    status = Mock()
    monkeypatch.setattr(app, "send_status", status)
    instance.transcribing = True

    instance._process_audio(np.zeros((4000, 1)), False, "original-window")

    inserted.assert_not_called()
    instance.services.transcribe.assert_not_called()
    instance.services.rewrite.assert_not_called()
    assert status.call_args.args[1] == (
        "⚠ Dictation failed" if failed else "⚠ No speech"
    )
    assert instance.transcribing is False


def test_two_stage_raw_shortcut_still_skips_cleanup(tmp_path, monkeypatch, desktop):
    instance = app.VoiceDictationApp(
        Settings().with_runtime_paths(tmp_path), desktop=desktop
    )
    instance.services = Mock()
    instance.services.transcribe.return_value = "Uh, keep the words as spoken."
    inserted = desktop.insert_text
    monkeypatch.setattr(app, "send_status", Mock())

    instance._process_audio(np.zeros((4000, 1)), True, "original-window")

    instance.services.rewrite.assert_not_called()
    instance.services.dictate.assert_not_called()
    inserted.assert_called_once_with(
        "Uh, keep the words as spoken.", "original-window", delay_ms=0
    )


def test_recording_uses_desktop_target_and_closes_microphone_on_listener_exit(
    tmp_path, monkeypatch, desktop
):
    settings = Settings().with_runtime_paths(tmp_path)
    instance = app.VoiceDictationApp(settings, desktop=desktop)
    desktop.capture_target.return_value = "captured-window"
    stream = Mock()
    monkeypatch.setattr(app.sd, "InputStream", Mock(return_value=stream))
    monkeypatch.setattr(app, "send_status", Mock())

    def listen(*, on_press, on_release, on_ready):
        on_ready()
        on_press(True)
        assert instance.recording is True
        assert instance.current_raw_mode is True
        assert instance.current_target_window == "captured-window"
        raise KeyboardInterrupt

    desktop.run_hotkey_loop.side_effect = listen
    with pytest.raises(KeyboardInterrupt):
        instance.run()

    desktop.capture_target.assert_called_once()
    desktop.notify.assert_any_call("Cap To Talk ready", 1200)
    stream.start.assert_called_once()
    stream.stop.assert_called_once()
    stream.close.assert_called_once()
    assert instance.recording is False
    assert instance.stream is None


def test_desktop_press_and_release_drive_recording_callbacks(tmp_path, desktop):
    instance = app.VoiceDictationApp(
        Settings().with_runtime_paths(tmp_path), desktop=desktop
    )
    instance.start_recording = Mock()
    instance.stop_recording = Mock()

    def listen(*, on_press, on_release, on_ready):
        on_ready()
        on_press(False)
        on_release()
        on_press(True)
        on_release()

    desktop.run_hotkey_loop.side_effect = listen
    instance.run()
    assert instance.start_recording.call_args_list == [
        call(raw_mode=False),
        call(raw_mode=True),
    ]
    assert instance.stop_recording.call_count == 2


def test_target_capture_failure_keeps_listener_ready_for_another_recording(
    tmp_path, monkeypatch, desktop
):
    instance = app.VoiceDictationApp(
        Settings().with_runtime_paths(tmp_path), desktop=desktop
    )
    desktop.capture_target.side_effect = RuntimeError("no target")
    microphone = Mock()
    monkeypatch.setattr(app.sd, "InputStream", microphone)
    instance.start_recording()
    microphone.assert_not_called()
    assert not instance.recording
    assert instance.stream is None


def test_microphone_start_failure_closes_stream_and_releases_target(
    tmp_path, monkeypatch, desktop
):
    instance = app.VoiceDictationApp(
        Settings().with_runtime_paths(tmp_path), desktop=desktop
    )
    desktop.capture_target.return_value = "target"
    stream = Mock()
    stream.start.side_effect = RuntimeError("microphone denied")
    stream.stop.side_effect = RuntimeError("stream never started")
    monkeypatch.setattr(app.sd, "InputStream", Mock(return_value=stream))
    instance.start_recording()
    stream.close.assert_called_once()
    desktop.release_target.assert_called_once_with("target")
    assert not instance.recording
    assert instance.stream is None


@pytest.mark.parametrize("frames", [[], [np.zeros((10, 1))]])
def test_aborted_short_recording_releases_target(
    tmp_path, monkeypatch, desktop, frames
):
    settings = Settings(post_roll_seconds=0).with_runtime_paths(tmp_path)
    instance = app.VoiceDictationApp(settings, desktop=desktop)
    instance.frames = frames
    instance.recording = True
    instance.current_target_window = "target"
    monkeypatch.setattr(app, "send_status", Mock())
    instance.stop_recording()
    desktop.release_target.assert_called_once_with("target")


def test_stopping_during_provider_request_prevents_late_insertion(
    tmp_path, monkeypatch, desktop
):
    instance = app.VoiceDictationApp(
        Settings().with_runtime_paths(tmp_path), desktop=desktop
    )
    instance.services = Mock()

    def response(audio):
        instance.request_stop()
        return "This arrived after dictation stopped."

    instance.services.transcribe.side_effect = response
    monkeypatch.setattr(app, "send_status", Mock())
    instance._process_audio(np.zeros((4000, 1)), False, "target")
    desktop.stop.assert_called_once()
    desktop.insert_text.assert_not_called()
    instance.services.rewrite.assert_not_called()
    desktop.release_target.assert_called_once_with("target")
