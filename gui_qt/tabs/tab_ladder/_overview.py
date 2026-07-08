"""HemaFrag GUI Qt — Phase 12.3 chip-strip overview widget.

Renders one chip per loaded bundle case at the top of TabLadder so
the chemist sees all cases (reviewed / needs review / file
unreachable / untouched) at a glance instead of scrolling the
file list.

Architecture:

- `ChipStripOverview` is a single QWidget with a horizontal
  `QHBoxLayout` for chips, hosted inside a `QScrollArea` so a long
  bundle (>50 cases) scrolls horizontally on overflow.
- One chip = one QLabel with a colored background per
  `CHIP_STATE_COLORS` (green / amber / red / gray).
- Public surface:
    setRows(rows): replace the chip set.
    setFilter(allowed_states): dim chips whose state isn't in the
      set (None = no filter, all chips at full opacity).
    chipActivated(path) signal: emitted when a chip is clicked.

Pure-Python tests pin `chip_state()` and `count_chip_states()` in
`_summary.py` — those are what `_refresh()` consumes.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from gui_qt.tabs.tab_ladder._summary import (
    CHIP_STATE_COLORS,
    chip_state,
)


class ChipStripOverview(QWidget):
    """Horizontal strip of colored chips, one per loaded case."""

    chipActivated = pyqtSignal(object)  # emitted with the file's Path

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._scroll.setFixedHeight(46)
        outer.addWidget(self._scroll)

        self._chip_host = QWidget(self._scroll)
        self._chip_layout = QHBoxLayout(self._chip_host)
        self._chip_layout.setContentsMargins(4, 4, 4, 4)
        self._chip_layout.setSpacing(4)
        self._chip_layout.addStretch(1)
        self._scroll.setWidget(self._chip_host)

        self._rows: list[dict] = []
        self._labels: list[tuple[Path, str, QLabel]] = []
        self._allowed_states: set[str] | None = None

    def setRows(self, rows: list[dict]) -> None:
        """Replace the chip set entirely."""
        self._rows = list(rows or [])
        self._refresh()

    def setFilter(self, allowed_states: set[str] | None) -> None:
        """Dim chips whose state isn't in the set (None = no filter)."""
        self._allowed_states = (
            set(allowed_states) if allowed_states is not None else None
        )
        self._refresh()

    def chipCount(self) -> int:
        return len(self._labels)

    def _refresh(self) -> None:
        # Wipe the saved chip widgets (chips only, keep the tail stretch).
        while self._chip_layout.count() > 1:
            item = self._chip_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()
        self._labels = []

        for row in self._rows:
            try:
                state = chip_state(row)
            except Exception:
                state = "untouched"
            color = CHIP_STATE_COLORS.get(state, "#94a3b8")
            raw_name = str(row.get("file") or "").strip()
            if not raw_name:
                fp_raw = str(row.get("full_path", "") or "").strip()
                raw_name = Path(fp_raw).name if fp_raw else "untitled"

            chip = QLabel(raw_name, self._chip_host)
            chip.setObjectName(f"Chip_{state}")
            opacity = (
                0.35
                if (
                    self._allowed_states is not None
                    and state not in self._allowed_states
                )
                else 1.0
            )
            chip.setStyleSheet(
                f"background-color: {color}; color: white; padding: 4px 8px; "
                f"border-radius: 10px; font-weight: 600; opacity: {opacity};"
            )

            # Tooltip — short, with the row's primary reason so the
            # chemist can see the bucket reason without clicking.
            tooltip_lines = [
                raw_name,
                f"state: {state}",
            ]
            reason = str(row.get("primary_reason", "") or "").strip()
            if reason:
                tooltip_lines.append(f"reason: {reason}")
            linear_max = row.get("linear_max")
            if linear_max not in (None, ""):
                tooltip_lines.append(f"linear max: {linear_max}")
            chip.setToolTip("\n".join(tooltip_lines))

            # Click → emit chipActivated with the path. Bind via
            # mousePressEvent override; capture `path` so we don't
            # accidentally read stale row data.
            file_path = Path(str(row.get("full_path", "") or ""))
            self._bind_chip_click(chip, file_path)

            self._chip_layout.insertWidget(
                self._chip_layout.count() - 1, chip
            )
            self._labels.append((file_path, state, chip))

    def _bind_chip_click(self, chip: QLabel, path: Path) -> None:
        def handler(event: QMouseEvent) -> None:
            if event is None or event.button() != Qt.MouseButton.LeftButton:
                return
            self.chipActivated.emit(path)

        chip.mousePressEvent = handler  # type: ignore[assignment]
