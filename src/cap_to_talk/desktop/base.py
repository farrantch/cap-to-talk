"""Desktop operations used by the dictation app."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DesktopCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


class DesktopUnavailableError(RuntimeError):
    """The desktop cannot provide the controls needed for dictation."""


class DesktopBackend(Protocol):
    def check(self) -> list[DesktopCheck]:
        """Check desktop requirements without recording or taking over keys."""
        ...

    def capture_target(self) -> str | None:
        """Return an opaque target ID to pass back to insert_text."""
        ...

    def release_target(self, target: str | None) -> None:
        """Release a target after insertion, failure, or an aborted recording."""
        ...

    def insert_text(self, text: str, target: str | None, *, delay_ms: int = 0) -> None:
        """Insert into the target and restore focus; fail if that target disappeared."""
        ...

    def notify(self, message: str, timeout: int = 1_500) -> None:
        """Show a best-effort notification; may be called from a worker thread."""
        ...

    def stop(self) -> None:
        """Request listener shutdown; safe to call from another thread."""
        ...

    def run_hotkey_loop(
        self,
        *,
        on_press: Callable[[bool], None],
        on_release: Callable[[], None],
        on_ready: Callable[[], None],
    ) -> None:
        """Run until interrupted, releasing native resources on every exit.

        Call on_ready after registering the shortcut. Call on_press(raw_mode)
        and on_release serially, once per press and release. Text insertion
        runs on the app's worker thread, so adapters must support that or
        marshal it to their native event loop.
        """
        ...
