"""Bottom-right dictation status for the desktop app."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QLabel

LOGGER = logging.getLogger(__name__)
MARGIN = 20


class StatusOverlay(QLabel):
    """Shows dictation status without taking focus from the target window."""

    def __init__(self) -> None:
        super().__init__()
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if sys.platform == "linux":
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        for attribute in (
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            Qt.WidgetAttribute.WA_TranslucentBackground,
            Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow,
        ):
            self.setAttribute(attribute)
        self.setStyleSheet(
            "QLabel { background: rgba(32, 36, 40, 230); color: white;"
            " border-radius: 8px; padding: 8px 14px; font-size: 14px; }"
        )
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)
        self.macos_configured = False

    def show_message(self, message: str, timeout_ms: int) -> None:
        self.setText(message)
        self.adjustSize()
        screen = (
            QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        )
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - MARGIN, area.bottom() - self.height() - MARGIN
        )
        self.show()
        if sys.platform == "darwin" and not self.macos_configured:
            self.macos_configured = True
            self._configure_macos_window()
        self.hide_timer.start(timeout_ms)

    def _configure_macos_window(self) -> None:
        # Qt has no flags for these: stay visible while another app is active,
        # above full-screen apps, and on every Space.
        try:
            import AppKit
            import objc

            window = objc.objc_object(c_void_p=int(self.winId())).window()
            window.setHidesOnDeactivate_(False)
            window.setLevel_(AppKit.NSStatusWindowLevel)
            window.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                | AppKit.NSWindowCollectionBehaviorStationary
            )
        except Exception:
            LOGGER.warning(
                "Could not configure the macOS status overlay", exc_info=True
            )
