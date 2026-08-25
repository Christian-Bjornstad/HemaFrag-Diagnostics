"""HemaFrag Diagnostics — Centralized Logging

Provides an observable LogBuffer that the GUI can watch, and a global
log() function for all modules.

The ``param`` dependency (~100 ms import, drags bokeh/panel ecosystem
modules) is loaded lazily: the buffer works as a plain object until the
GUI (or panel) attaches a real param-based watcher.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

logger = logging.getLogger()

_PARAM = None


def _param():
    """Lazy accessor for the heavy ``param`` module."""
    global _PARAM
    if _PARAM is None:
        import param

        _PARAM = param
    return _PARAM


class LogBuffer:
    """Observable text buffer for the GUI log viewer.

    Duck-types the previous ``param.Parameterized`` API (``text``,
    ``watch``) so existing GUI bindings keep working. ``param`` is only
    imported if someone actually registers a param-style watcher.
    """

    def __init__(self) -> None:
        self.text = ""
        self._watchers: dict[str, list] = {}

    def write(self, msg: str) -> None:
        self.text += str(msg) + "\n"
        self._notify()

    def clear(self) -> None:
        self.text = ""
        self._notify()

    # --- param-compatible watcher registration --------------------------
    def watch(self, watch_fn, what: str = "text"):
        """Accept both plain callables and param-style registrations."""
        self._watchers.setdefault(what, []).append(watch_fn)
        return len(self._watchers[what])

    def param(self):
        return self

    def trigger(self, what: str = "text") -> None:
        self._notify()

    def _notify(self) -> None:
        for fn in self._watchers.get("text", []):
            try:
                fn()
            except Exception:  # noqa: BLE001 - never let logging crash the app
                pass


# Singleton
log_buffer = LogBuffer()


def log(msg: str) -> None:
    """Append a timestamped message to the log buffer and stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    if sys.stdout is not None:
        print(line)
    log_buffer.write(line)
    logger.info(msg)
