"""Bottom-right dictation status for the desktop app."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPaintEvent
from PySide6.QtWidgets import QLabel

LOGGER = logging.getLogger(__name__)
MARGIN = 20
BACKGROUND = QColor(32, 36, 40, 235)


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
            "QLabel { color: white; padding: 8px 14px; font-size: 14px; }"
        )
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)
        # Configure the native window before its first show, which would
        # otherwise activate Cap To Talk and take focus from the target window.
        # Only the Cocoa platform has a native window; offscreen tests do not.
        self.macos_configured = (
            QGuiApplication.platformName() != "cocoa" or self._configure_macos_window()
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        # Style-sheet backgrounds are not drawn on translucent macOS windows.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BACKGROUND)
        painter.drawRoundedRect(self.rect(), 8, 8)
        painter.end()
        super().paintEvent(event)

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
        if not self.macos_configured:
            self.macos_configured = self._configure_macos_window()
        self.hide_timer.start(timeout_ms)

    def _configure_macos_window(self) -> bool:
        # Qt has no flags for these: never activate Cap To Talk, stay visible while
        # another app is active, and appear above full-screen apps on every Space.
        try:
            import AppKit
            import objc

            window = objc.objc_object(c_void_p=int(self.winId())).window()
            if window is None:
                return False
            if window.isKindOfClass_(AppKit.NSPanel):
                window.setStyleMask_(
                    window.styleMask() | AppKit.NSWindowStyleMaskNonactivatingPanel
                )
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
        return True
