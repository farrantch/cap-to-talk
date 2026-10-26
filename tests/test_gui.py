from __future__ import annotations

import os
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from cap_to_talk import gui, gui_runtime  # noqa: E402
from cap_to_talk.config import Settings, load_settings  # noqa: E402


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(application, tmp_path):
    window = gui.SettingsWindow(
        tmp_path / "config.toml", probe_devices=False, enable_tray=False
    )
    yield window
    window.controller.stop()
    if window.controller.thread:
        window.controller.thread.join(5)
    window.hide()
    window.deleteLater()
    application.processEvents()


def test_switching_provider_resets_endpoint_and_credentials(window):
    form = window.forms["transcription"]
    form.provider.setCurrentIndex(form.provider.findData("openai"))
    assert form.endpoint.text() == "https://api.openai.com/v1/audio/transcriptions"
    assert form.source.currentData() == "keyring"
    assert form.model.text() == ""
    form.provider.setCurrentIndex(form.provider.findData("openasr"))
    assert form.endpoint.text().startswith("http://127.0.0.1:8080/")
    assert form.model.text() == "qwen3-asr-0.6b"


def test_single_pipeline_saves_model_and_key_without_plaintext(window, monkeypatch):
    stored = Mock()
    monkeypatch.setattr(gui, "save_key", stored)
    window.pipeline.setCurrentIndex(window.pipeline.findData("single"))
    form = window.forms["dictation"]
    form.model.setText("test-audio-model")
    form.source.setCurrentIndex(form.source.findData("keyring"))
    form.secret.setText("private-api-token")
    assert window.save()
    stored.assert_called_once()
    assert stored.call_args.args[1] == "private-api-token"
    assert "private-api-token" not in window.config_path.read_text()
    assert form.secret.text() == ""
    settings = load_settings(window.config_path)
    assert settings.pipeline_mode == "single"
    assert settings.dictation_config.api_key_source == "keyring"
    assert settings.dictation_config.model == "test-audio-model"


def test_invalid_config_does_not_mutate_credential_store(window, monkeypatch):
    stored = Mock()
    monkeypatch.setattr(gui, "save_key", stored)
    window.pipeline.setCurrentIndex(window.pipeline.findData("single"))
    window.forms["dictation"].secret.setText("new-token")
    assert not window.save()
    stored.assert_not_called()
    assert not window.config_path.exists()


def test_failed_credential_save_does_not_overwrite_config(window, monkeypatch):
    assert window.save()
    old = window.config_path.read_bytes()
    window.pipeline.setCurrentIndex(window.pipeline.findData("single"))
    form = window.forms["dictation"]
    form.model.setText("test-model")
    form.source.setCurrentIndex(form.source.findData("keyring"))
    form.secret.setText("new-token")
    monkeypatch.setattr(
        gui, "save_key", Mock(side_effect=RuntimeError("Store is locked"))
    )
    assert not window.save()
    assert window.config_path.read_bytes() == old


def test_microphone_names_include_host_api(window, monkeypatch):
    monkeypatch.setattr(
        gui.sd,
        "query_devices",
        lambda: [
            {"name": "USB Mic", "hostapi": 0, "max_input_channels": 1},
            {"name": "USB Mic", "hostapi": 1, "max_input_channels": 1},
        ],
    )
    monkeypatch.setattr(
        gui.sd, "query_hostapis", lambda: [{"name": "WASAPI"}, {"name": "MME"}]
    )
    window.refresh_microphones()
    assert window.microphone.itemData(1) == "USB Mic, WASAPI"
    assert window.microphone.itemData(2) == "USB Mic, MME"


def test_controller_stop_during_startup_never_grabs_keyboard(application, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def checking(config):
        started.set()
        assert release.wait(3)
        return True, "ready"

    monkeypatch.setattr(gui_runtime, "check_provider", checking)
    factory = Mock()
    monkeypatch.setattr(gui_runtime, "create_desktop_backend", factory)
    controller = gui_runtime.DictationController()
    controller.start(Settings().with_runtime_paths(Path("/tmp")))
    assert started.wait(3)
    controller.stop()
    release.set()
    controller.thread.join(3)
    assert not controller.thread.is_alive()
    factory.assert_not_called()


def test_controller_signals_completion_when_cleanup_fails(
    application, monkeypatch, tmp_path
):
    backend = Mock()
    backend.check.return_value = []
    instance = Mock()
    instance.close.side_effect = RuntimeError("Could not close microphone")
    monkeypatch.setattr(gui_runtime, "create_desktop_backend", lambda settings: backend)
    monkeypatch.setattr(
        gui_runtime, "VoiceDictationApp", lambda *args, **kwargs: instance
    )
    monkeypatch.setattr(gui_runtime, "check_provider", lambda config: (True, "ready"))
    monkeypatch.setattr(gui_runtime, "sys", SimpleNamespace(platform="win32"))
    controller = gui_runtime.DictationController()
    finished = []
    controller.finished.connect(finished.append)
    controller.start(Settings().with_runtime_paths(tmp_path))
    controller.thread.join(3)
    application.processEvents()
    assert finished == ["Could not close microphone"]


def test_microphone_test_stays_local(monkeypatch):
    import numpy as np

    record = Mock(return_value=np.ones((48000, 1), dtype=np.float32) * 0.5)
    monkeypatch.setattr(gui_runtime.sd, "rec", record)
    assert "50%" in gui_runtime.test_microphone(
        replace(Settings(), audio_device="USB Mic")
    )
    assert record.call_args.kwargs["device"] == "USB Mic"
    assert record.call_args.kwargs["blocking"] is True
