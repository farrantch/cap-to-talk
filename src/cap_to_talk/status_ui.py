"""Small desktop status overlay."""

from __future__ import annotations

import logging
import socket
import threading
import tkinter as tk

from cap_to_talk.config import Settings, load_settings

LOGGER = logging.getLogger(__name__)
RIGHT_MARGIN = 20
BOTTOM_MARGIN = 20


class StatusWindow:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.label = tk.Label(
            self.root,
            text="",
            padx=14,
            pady=8,
            font=("Sans", 11),
        )
        self.label.pack()
        self.root.withdraw()
        self.hide_job: str | None = None
        threading.Thread(target=self._socket_server, daemon=True).start()

    def _position_window(self) -> None:
        self.root.update_idletasks()
        x = self.root.winfo_screenwidth() - self.root.winfo_width() - RIGHT_MARGIN
        y = self.root.winfo_screenheight() - self.root.winfo_height() - BOTTOM_MARGIN
        self.root.geometry(f"+{x}+{y}")

    def _hide(self) -> None:
        self.root.withdraw()
        self.hide_job = None

    def _set_status(self, text: str) -> None:
        if self.hide_job is not None:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None

        if text.lower() in ("ready", "cap to talk ready", "caps talk ready", "idle"):
            self._hide()
            return

        self.label.config(text=text)
        self.root.deiconify()
        self._position_window()
        if any(
            marker in text.lower()
            for marker in (
                "done",
                "failed",
                "error",
                "no speech",
                "no audio",
                "too short",
            )
        ):
            self.hide_job = self.root.after(1_200, self._hide)

    def _socket_server(self) -> None:
        try:
            with socket.socket() as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((self.settings.status_host, self.settings.status_port))
                server.listen()
                while True:
                    connection, _ = server.accept()
                    with connection:
                        text = (
                            connection.recv(1_024)
                            .decode("utf-8", errors="replace")
                            .strip()
                        )
                        if text:
                            self.root.after(0, self._set_status, text)
        except OSError:
            LOGGER.exception("Status overlay socket stopped")

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    StatusWindow(load_settings()).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
