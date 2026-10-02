"""Desktop settings, provider setup, and a tray/menu-bar controller."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import tempfile
import threading
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import sounddevice as sd
from PySide6.QtCore import (
    QLockFile,
    QObject,
    QSignalBlocker,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cap_to_talk import __version__
from cap_to_talk.config import (
    DICTATION_PROVIDERS,
    REWRITE_PROVIDERS,
    TRANSCRIPTION_PROVIDERS,
    ProviderSettings,
    Settings,
    _provider_defaults,
    default_config_dir,
    load_settings,
    validate_settings,
)
from cap_to_talk.credentials import delete_key, save_key
from cap_to_talk.gui_runtime import DictationController, check_setup, test_microphone
from cap_to_talk.settings_store import settings_document, write_settings

RELEASES_URL = "https://github.com/farrantch/cap-to-talk/releases"
GUIDE_URL = "https://github.com/farrantch/cap-to-talk/blob/main/docs/desktop-app.md"
ICON_PATH = Path(__file__).parent / "assets" / "icon.png"
PROVIDER_NAMES = {
    "openasr": "OpenASR (local)",
    "ollama": "Ollama (local)",
    "openai": "OpenAI",
    "openai-compatible": "Compatible endpoint",
    "anthropic": "Anthropic",
    "none": "No cleanup",
}


def provider_defaults(provider: str, section: str) -> ProviderSettings:
    defaults = Settings()
    if provider == "openasr":
        return defaults.transcription_config
    if provider == "ollama":
        return defaults.rewrite_config
    return _provider_defaults(provider, section)


class ProviderForm(QGroupBox):
    def __init__(self, title: str, section: str, profile: ProviderSettings) -> None:
        super().__init__(title)
        self.section = section
        self.profile = profile
        form = QFormLayout(self)
        self.form_layout = form
        self.provider = QComboBox()
        choices = {
            "transcription": TRANSCRIPTION_PROVIDERS,
            "rewrite": REWRITE_PROVIDERS,
            "dictation": DICTATION_PROVIDERS,
        }[section]
        for value in choices:
            self.provider.addItem(PROVIDER_NAMES[value], value)
        self.model = QLineEdit()
        self.model.setPlaceholderText("Model name from your provider")
        self.endpoint = QLineEdit()
        self.endpoint.setPlaceholderText("https://…/v1/…")
        self.source = QComboBox()
        self.source.addItem("No API key", "none")
        self.source.addItem("Saved on this computer", "keyring")
        self.source.addItem("Environment variable", "environment")
        self.key_name = QLineEdit()
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setPlaceholderText(
            "Paste a key to save or replace it; leave blank to keep it"
        )
        self.remove = QCheckBox("Remove the saved key when saving settings")
        self.note = QLabel(
            "Saved keys are specific to this endpoint. "
            "Changing servers requires a new key."
        )
        self.note.setWordWrap(True)
        form.addRow("Provider", self.provider)
        form.addRow("Model", self.model)
        form.addRow("Endpoint", self.endpoint)
        form.addRow("Credentials", self.source)
        form.addRow("Variable name", self.key_name)
        form.addRow("API key", self.secret)
        form.addRow("", self.remove)
        form.addRow(self.note)
        self.set_profile(profile)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.source.currentIndexChanged.connect(self._credential_mode)

    def set_profile(self, profile: ProviderSettings) -> None:
        self.profile = profile
        with QSignalBlocker(self.provider):
            self.provider.setCurrentIndex(self.provider.findData(profile.provider))
        self.model.setText(profile.model)
        self.endpoint.setText(profile.url)
        mode = profile.api_key_source if profile.api_key_env else "none"
        self.source.setCurrentIndex(self.source.findData(mode))
        self.key_name.setText(profile.api_key_env)
        self.secret.clear()
        self.remove.setChecked(False)
        self._credential_mode()

    def _provider_changed(self) -> None:
        profile = provider_defaults(self.provider.currentData(), self.section)
        if profile.provider in ("openai", "anthropic", "openai-compatible"):
            profile = replace(
                profile,
                api_key_source="keyring",
                api_key_env=profile.api_key_env
                or f"CAP_TO_TALK_{self.section.upper()}_KEY",
            )
        self.set_profile(profile)

    def _credential_mode(self) -> None:
        mode = self.source.currentData()
        enabled = self.provider.currentData() != "none"
        self.form_layout.setRowVisible(self.key_name, enabled and mode == "environment")
        self.form_layout.setRowVisible(self.secret, enabled and mode == "keyring")
        self.form_layout.setRowVisible(self.remove, enabled and mode == "keyring")
        for widget in (self.model, self.endpoint, self.source):
            self.form_layout.setRowVisible(widget, enabled)
        if not enabled:
            self.note.setText("Insert the raw transcript without a cleanup request.")
        elif mode == "none":
            self.note.setText(
                "This service must already be running at the configured endpoint."
            )
        else:
            self.note.setText(
                "Saved keys are specific to this endpoint. "
                "Changing servers requires a new key."
            )

    def collect(self) -> ProviderSettings:
        endpoint = self.endpoint.text().strip()
        key_name = self.key_name.text().strip()
        mode = self.source.currentData()
        if mode == "none":
            key_name = ""
            mode = "environment"
        if self.source.currentData() == "keyring" and not key_name:
            key_name = f"CAP_TO_TALK_{self.section.upper()}_KEY"
        return replace(
            self.profile,
            provider=self.provider.currentData(),
            model=self.model.text().strip(),
            url=endpoint,
            api_key_source=mode,
            api_key_env=key_name,
            health_url=self.profile.health_url if endpoint == self.profile.url else "",
        )

    def save_secret(self, profile: ProviderSettings) -> None:
        if profile.api_key_source != "keyring":
            return
        if self.remove.isChecked():
            delete_key(profile)
        elif self.secret.text().strip():
            save_key(profile, self.secret.text())


class TaskSignals(QObject):
    done = Signal(str, str)


class SettingsWindow(QMainWindow):
    def __init__(
        self, config_path: Path, *, probe_devices: bool = True, enable_tray: bool = True
    ) -> None:
        super().__init__()
        self.config_path = config_path
        self.settings = load_settings(config_path)
        self.original = config_path.read_bytes() if config_path.exists() else None
        self.active = False
        self.task_running = False
        self.quitting = False
        self.controller = DictationController()
        self.controller.status.connect(self.set_status)
        self.controller.finished.connect(self._dictation_finished)
        self.tasks = TaskSignals()
        self.tasks.done.connect(self._task_finished)
        self.setWindowTitle("Cap To Talk")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(830, 730)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        heading = QLabel("Cap To Talk")
        heading.setStyleSheet("font-size: 26px; font-weight: 650;")
        layout.addWidget(heading)
        layout.addWidget(QLabel("Dictation for the app you’re using."))
        self.status = QLabel("Stopped")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            "padding: 12px; border: 1px solid #82948d; border-radius: 6px;"
        )
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.general = QWidget()
        general = QVBoxLayout(self.general)
        form = QFormLayout()
        self.microphone = QComboBox()
        self.microphone.addItem("System default", None)
        if self.settings.audio_device is not None:
            self.microphone.addItem(
                str(self.settings.audio_device), self.settings.audio_device
            )
            self.microphone.setCurrentIndex(1)
        self.hotkey = QComboBox()
        for key in ("auto", "caps_lock", *(f"f{i}" for i in range(1, 13))):
            if sys.platform == "darwin" and key == "caps_lock":
                continue
            label = {
                "auto": "Default (F8 on Mac, Caps Lock on Windows/Linux)",
                "caps_lock": "Caps Lock",
            }.get(key, key.upper())
            self.hotkey.addItem(label, key)
        self.hotkey.setCurrentIndex(max(0, self.hotkey.findData(self.settings.hotkey)))
        form.addRow("Microphone", self.microphone)
        form.addRow("Dictation key", self.hotkey)
        general.addLayout(form)
        refresh = QPushButton("Refresh microphones")
        refresh.clicked.connect(self.refresh_microphones)
        general.addWidget(refresh, 0, Qt.AlignmentFlag.AlignLeft)
        help_text = QLabel(
            "Hold the dictation key to record, then release it to insert text.\n"
            "Hold Shift before pressing the key to request raw transcription.\n\n"
            "On Mac, allow Microphone, Accessibility, and Input Monitoring access. "
            "Your keyboard may need Fn + F8.\n\n"
            "Local providers must be installed separately. A remote provider receives "
            "your audio or transcript and may charge for usage."
        )
        help_text.setWordWrap(True)
        general.addWidget(help_text)
        guide = QPushButton("Setup and permissions guide")
        guide.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GUIDE_URL)))
        general.addWidget(guide, 0, Qt.AlignmentFlag.AlignLeft)
        general.addStretch()
        self.tabs.addTab(self.general, "General")
        self.providers_tab = QWidget()
        providers_layout = QVBoxLayout(self.providers_tab)
        self.pipeline = QComboBox()
        self.pipeline.addItem("Transcription + optional cleanup", "two-stage")
        self.pipeline.addItem("One audio model for transcription and cleanup", "single")
        self.pipeline.setCurrentIndex(
            self.pipeline.findData(self.settings.pipeline_mode)
        )
        providers_layout.addWidget(self.pipeline)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        profiles_layout = QVBoxLayout(content)
        self.forms = {
            section: ProviderForm(title, section, profile)
            for section, title, profile in (
                (
                    "transcription",
                    "Speech recognition",
                    self.settings.transcription_config,
                ),
                ("rewrite", "Text cleanup", self.settings.rewrite_config),
                ("dictation", "Audio dictation model", self.settings.dictation_config),
            )
        }
        for item in self.forms.values():
            profiles_layout.addWidget(item)
        profiles_layout.addStretch()
        scroll.setWidget(content)
        providers_layout.addWidget(scroll)
        self.tabs.addTab(self.providers_tab, "AI providers")
        self.pipeline.currentIndexChanged.connect(self._pipeline_changed)
        self._pipeline_changed()
        self.results = QTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText(
            "Check setup to see permission, microphone, and provider results."
        )
        self.tabs.addTab(self.results, "Checks")
        self.save_button = QPushButton("Save settings")
        self.save_button.clicked.connect(self.save)
        self.check_button = QPushButton("Check setup")
        self.check_button.clicked.connect(self.check)
        self.mic_button = QPushButton("Test microphone (3 s)")
        self.mic_button.clicked.connect(self.test_mic)
        self.start_button = QPushButton("Start dictation")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)
        actions = QHBoxLayout()
        for button in (self.save_button, self.check_button, self.mic_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions)
        footer = QHBoxLayout()
        footer.addWidget(QLabel(f"Version {__version__} • Experimental desktop build"))
        footer.addStretch()
        licenses = QPushButton("Licenses")
        licenses.clicked.connect(self.show_licenses)
        footer.addWidget(licenses)
        updates = QPushButton("Downloads and updates")
        updates.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        footer.addWidget(updates)
        layout.addLayout(footer)
        self.tray: QSystemTrayIcon | None = None
        self.start_action: QAction | None = None
        self.stop_action: QAction | None = None
        if enable_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            menu = QMenu(self)
            menu.addAction("Settings", self.show_settings)
            self.start_action = menu.addAction("Start dictation", self.start)
            self.stop_action = menu.addAction("Stop dictation", self.stop)
            menu.addSeparator()
            menu.addAction("Quit", self.quit)
            self.tray.setContextMenu(menu)
            self.tray.setToolTip("Cap To Talk — Stopped")
            self.tray.activated.connect(
                lambda reason: (
                    self.show_settings()
                    if reason == QSystemTrayIcon.ActivationReason.Trigger
                    else None
                )
            )
            self.tray.show()
        self._set_controls()
        if probe_devices:
            self.refresh_microphones()

    def _pipeline_changed(self) -> None:
        single = self.pipeline.currentData() == "single"
        self.forms["dictation"].setVisible(single)
        self.forms["transcription"].setVisible(not single)
        self.forms["rewrite"].setVisible(not single)

    def refresh_microphones(self) -> None:
        selected = self.microphone.currentData()
        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            self.microphone.clear()
            self.microphone.addItem("System default", None)
            for device in devices:
                if device["max_input_channels"] > 0:
                    label = f"{device['name']} ({hostapis[device['hostapi']]['name']})"
                    # A stable name survives device order changes on later launches.
                    identity = (
                        f"{device['name']}, {hostapis[device['hostapi']]['name']}"
                    )
                    self.microphone.addItem(label, identity)
            position = self.microphone.findData(selected)
            if selected is not None and position < 0:
                self.microphone.addItem(f"{selected} (saved device)", selected)
                position = self.microphone.count() - 1
            self.microphone.setCurrentIndex(max(0, position))
        except Exception:
            self.set_status(
                "Could not list microphones. Check microphone access, then refresh."
            )

    def collect(self) -> Settings:
        settings = replace(
            self.settings,
            audio_device=self.microphone.currentData(),
            hotkey=self.hotkey.currentData(),
            pipeline_mode=self.pipeline.currentData(),
            **{name: form.collect() for name, form in self.forms.items()},
        )
        validate_settings(settings)
        return settings

    def save(self) -> bool:
        try:
            settings = self.collect()
            document = settings_document(self.config_path, settings)
            current = (
                self.config_path.read_bytes() if self.config_path.exists() else None
            )
            if current != self.original:
                raise ValueError(
                    "Settings changed outside this window. "
                    "Reopen Settings before saving."
                )
            for name, form in self.forms.items():
                form.save_secret(getattr(settings, name))
            write_settings(self.config_path, document, expected=self.original)
            self.original = self.config_path.read_bytes()
            self.settings = load_settings(self.config_path)
            for name, form in self.forms.items():
                form.set_profile(getattr(self.settings, name))
            self.pipeline.setCurrentIndex(
                self.pipeline.findData(self.settings.pipeline_mode)
            )
            self.hotkey.setCurrentIndex(self.hotkey.findData(self.settings.hotkey))
            self.set_status(
                "Settings saved. Environment overrides apply if configured."
            )
            return True
        except Exception as error:
            self.set_status(str(error))
            return False

    def start(self) -> None:
        if self.active or self.task_running or not self.save():
            return
        self.active = True
        self._set_controls()
        self.controller.start(self.settings)

    def stop(self) -> None:
        if self.active:
            self.set_status("Stopping…")
            self.stop_button.setEnabled(False)
            self.controller.stop()

    def _dictation_finished(self, error: str) -> None:
        self.active = False
        self.set_status(error or "Stopped")
        if error:
            self.results.setPlainText(error)
            self.show_settings()
        self._set_controls()
        self._finish_quit()

    def _set_controls(self) -> None:
        idle = not self.active and not self.task_running and not self.quitting
        for widget in (
            self.general,
            self.providers_tab,
            self.save_button,
            self.check_button,
            self.mic_button,
            self.start_button,
        ):
            widget.setEnabled(idle)
        self.stop_button.setEnabled(self.active and not self.quitting)
        if self.start_action is not None:
            self.start_action.setEnabled(idle)
        if self.stop_action is not None:
            self.stop_action.setEnabled(self.active)

    def set_status(self, message: str) -> None:
        self.status.setText(message)
        if self.tray is not None:
            self.tray.setToolTip(f"Cap To Talk — {message}"[:128])

    def _task(self, function: Any, message: str) -> None:
        if self.active or self.task_running or not self.save():
            return
        self.task_running = True
        self._set_controls()
        self.set_status(message)
        settings = self.settings

        def run() -> None:
            result, error = "", ""
            try:
                result = function(settings)
            except Exception as failure:
                error = str(failure)
            self.tasks.done.emit(result, error)

        threading.Thread(target=run, daemon=True).start()

    def check(self) -> None:
        self._task(check_setup, "Checking setup…")

    def test_mic(self) -> None:
        self._task(
            test_microphone,
            "Recording a 3-second microphone test. Speak now; "
            "audio stays on this computer.",
        )

    def _task_finished(self, result: str, error: str) -> None:
        self.task_running = False
        self.results.setPlainText(error or result)
        self.tabs.setCurrentWidget(self.results)
        self.set_status(error or "Check complete. See the results below.")
        self._set_controls()
        self._finish_quit()

    def show_licenses(self) -> None:
        QMessageBox.about(
            self,
            "Cap To Talk licenses",
            "Cap To Talk is licensed under MIT. This application uses Qt and "
            "Qt for Python under LGPLv3. You may modify and rebuild the app "
            "and its libraries. Component licenses and source information "
            "are included with the download.",
        )
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        path = root / "licenses"
        if not path.is_dir():
            path = root / "packaging" / "THIRD_PARTY.md"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def show_settings(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit(self) -> None:
        self.quitting = True
        self.stop()
        self._set_controls()
        self._finish_quit()

    def _finish_quit(self) -> None:
        if self.quitting and not self.active and not self.task_running:
            if self.tray is not None:
                self.tray.hide()
            QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        if self.tray is not None and not self.quitting:
            self.hide()
        else:
            self.quit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cap To Talk desktop settings")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication([sys.argv[0]])
    application.setApplicationName("Cap To Talk")
    application.setOrganizationName("CapToTalk")
    application.setQuitOnLastWindowClosed(False)
    temporary = (
        tempfile.TemporaryDirectory(prefix="cap-to-talk-smoke-")
        if args.smoke_test
        else None
    )
    config_path = (
        Path(temporary.name) / "config.toml"
        if temporary is not None
        else args.config or default_config_dir() / "config.toml"
    )
    lock = None
    if not args.smoke_test:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(config_path.parent / ".desktop.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            QMessageBox.information(
                None,
                "Cap To Talk",
                "Cap To Talk is already open. "
                "Use its tray or menu-bar icon to open Settings.",
            )
            return 0
        logs = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppLocalDataLocation
            )
        )
        logs.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            handlers=[
                RotatingFileHandler(
                    logs / "cap-to-talk.log",
                    maxBytes=512_000,
                    backupCount=2,
                    encoding="utf-8",
                )
            ],
            format="%(asctime)s %(levelname)s %(message)s",
        )
    try:
        window = SettingsWindow(
            config_path,
            probe_devices=not args.smoke_test,
            enable_tray=not args.smoke_test,
        )
        window.show()
        if not args.smoke_test:
            signal.signal(signal.SIGTERM, lambda *_: window.quit())
            signal.signal(signal.SIGINT, lambda *_: window.quit())
            signal_timer = QTimer(window)
            signal_timer.timeout.connect(lambda: None)
            signal_timer.start(250)
        if args.smoke_test:
            # Exercise bundled platform imports without recording or grabbing keys.
            from cap_to_talk.credentials import _backend
            from cap_to_talk.desktop import create_desktop_backend

            _backend()
            backend = create_desktop_backend(window.settings)
            if hasattr(backend, "_load_api"):
                backend._load_api()
            else:
                import Xlib  # noqa: F401
            QTimer.singleShot(100, application.quit)
        return application.exec()
    except Exception as error:
        if args.smoke_test:
            raise
        QMessageBox.critical(
            None, "Cap To Talk settings", f"{error}\n\nConfiguration: {config_path}"
        )
        return 1
    finally:
        if lock is not None:
            lock.unlock()
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
