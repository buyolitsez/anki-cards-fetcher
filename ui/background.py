"""Shared background-task helpers for UI dialogs.

Provides a unified ``run_in_background`` that uses Anki's ``taskman`` when
available and falls back to synchronous execution on older versions.
"""

from __future__ import annotations

from typing import Optional

from aqt import mw


class InlineFuture:
    """Minimal future-like wrapper for synchronous fallback."""

    def __init__(self, value=None, exc: Optional[Exception] = None):
        self._value = value
        self._exc = exc

    def result(self):
        if self._exc:
            raise self._exc
        return self._value


def run_in_background(task, on_done):
    """Run *task* in a background thread, calling *on_done* with the future.

    Uses ``mw.taskman.run_in_background`` when available (Anki 2.1.28+).
    Falls back to running the task synchronously so the add-on still works
    on older Anki builds.
    """
    if hasattr(mw, "taskman"):
        mw.taskman.run_in_background(task, on_done)
        return
    try:
        value = task()
        on_done(InlineFuture(value=value))
    except Exception as e:
        on_done(InlineFuture(exc=e))
