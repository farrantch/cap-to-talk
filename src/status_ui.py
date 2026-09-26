#!/usr/bin/env python3

import socket
import tkinter as tk
import threading

HOST = "127.0.0.1"
PORT = 47653

RIGHT_MARGIN = 20
BOTTOM_MARGIN = 20


class StatusWindow:
    def __init__(self):
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
        self.hide_job = None

        threading.Thread(
            target=self.socket_server,
            daemon=True,
        ).start()

    def position_window(self):
        self.root.update_idletasks()

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = self.root.winfo_width()
        h = self.root.winfo_height()

        x = sw - w - RIGHT_MARGIN
        y = sh - h - BOTTOM_MARGIN

        self.root.geometry(f"+{x}+{y}")

    def hide(self):
        self.root.withdraw()
        self.hide_job = None

    def set_status(self, text):
        if self.hide_job is not None:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None

        if text.lower() in ("ready", "voice: ready", "idle"):
            self.hide()
            return

        self.label.config(text=text)
        self.root.deiconify()
        self.position_window()

        lower = text.lower()

        if (
            "done" in lower
            or "failed" in lower
            or "error" in lower
            or "no speech" in lower
            or "too short" in lower
        ):
            self.hide_job = self.root.after(
                1200,
                self.hide,
            )

    def socket_server(self):
        sock = socket.socket()
        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1,
        )
        sock.bind((HOST, PORT))
        sock.listen()

        while True:
            conn, _ = sock.accept()

            try:
                text = conn.recv(1024).decode().strip()

                if text:
                    self.root.after(
                        0,
                        self.set_status,
                        text,
                    )
            finally:
                conn.close()

    def run(self):
        self.root.mainloop()


StatusWindow().run()
