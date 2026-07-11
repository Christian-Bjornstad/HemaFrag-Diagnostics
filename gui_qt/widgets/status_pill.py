"""Reusable StatusPill widget — semantic pass/check/fail/idle states.

All styling is in the global QSS (VIBRANT_PRO_QSS) via attribute selectors
on the [state="X"] property. Use set_state() to change the pill's appearance.
"""

from PyQt6.QtWidgets import QLabel


class StatusPill(QLabel):
    """A compact pill-shaped status label with semantic states.

    States: "pass" (green), "check" (amber), "fail" (red), "idle" (gray).
    """

    _VALID_STATES = {"pass", "check", "fail", "idle"}

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("StatusPill")
        self.set_state("idle")

    def set_state(self, state: str) -> None:
        if state not in self._VALID_STATES:
            state = "idle"
        self.setProperty("state", state)
        # Force QSS re-evaluation
        self.style().unpolish(self)
        self.style().polish(self)
