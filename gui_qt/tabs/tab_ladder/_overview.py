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
from PyQt6.QtGui import QAction, QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from gui_qt.tabs.tab_ladder._summary import (
    CHIP_STATE_COLORS,
    CHIP_STATE_LABELS,
    chip_state,
    count_states,
    is_chip_state_allowed,
)


# Display ordering for the four chip states — used by the filter bar
# in addition to the chip strip itself. Alphabetical-by-importance
# would put "file_unreachable" first (highest priority), but the
# chemist walks left→right and expects the natural-color order:
# reviewed → needs_review → unreachable → untouched.
FILTER_BAR_STATE_ORDER = (
    "reviewed",
    "needs_review",
    "file_unreachable",
    "untouched",
)


# Human-readable chip-state name → button label combo (kept terse so
# the filter row stays compact on a tab of modest width).
FILTER_BAR_LABELS = {
    "reviewed": "Reviewed",
    "needs_review": "Needs review",
    "file_unreachable": "Unreachable",
    "untouched": "Untouched",
}


class ChipStripOverview(QWidget):
    """Horizontal strip of colored chips, one per loaded case."""

    chipActivated = pyqtSignal(object)  # emitted with the file's Path
    chipLocateRequested = pyqtSignal(object)  # Phase 12.4 — right-click "Locate File..."
    chipDropRequested = pyqtSignal(object)  # Phase 12.10 — right-click "Drop row from bundle..."

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
        # Phase 12.11 — DIT prefix filter. An AND-composable
        # filter on top of `_allowed_states`: only chips whose
        # index is in this set pass through at full opacity.
        # None = no DIT filter applied.
        self._allowed_indices: set[int] | None = None

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

    def dit_filter_keep(self, kept_indices) -> None:
        """Phase 12.11 — keep only chips whose index is in ``kept_indices``.

        Pass ``None`` (or empty) to clear the DIT filter.
        AND-composes with ``set_filter(allowed_states)``: a chip
        is full opacity only when both filters allow it.
        Empty input means "no filter" so the GUI can short-circuit
        the dim path without resetting the chip-state filter.
        """
        if kept_indices is None:
            self._allowed_indices = None
        else:
            try:
                self._allowed_indices = set(kept_indices)
            except Exception:
                self._allowed_indices = None
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

        for index, row in enumerate(self._rows):
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
            # AND-compose the chip-state filter and the DIT filter.
            # A chip passes when: state filter allows OR is None
            # AND index filter allows OR is None.
            state_allowed = (
                self._allowed_states is None
                or state in self._allowed_states
            )
            index_allowed = (
                self._allowed_indices is None
                or index in self._allowed_indices
            )
            opacity = 1.0 if (state_allowed and index_allowed) else 0.35
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
            self._bind_chip_click(chip, file_path, state)

            self._chip_layout.insertWidget(
                self._chip_layout.count() - 1, chip
            )
            self._labels.append((file_path, state, chip))

    def _bind_chip_click(self, chip: QLabel, path: Path, state: str) -> None:
        def handler(event: QMouseEvent) -> None:
            if event is None:
                return
            if event.button() == Qt.MouseButton.LeftButton:
                self.chipActivated.emit(path)
            elif event.button() == Qt.MouseButton.RightButton:
                # Phase 12.10 — context menu now always offers two
                # actions: "Locate File..." (when reachable
                # resource moved) and "Drop row from bundle..."
                # for paths the chemist no longer wants tracked.
                menu = QMenu(chip)
                if state == "file_unreachable":
                    # Locate File only makes sense when the chip
                    # is currently unreachable — otherwise the
                    # path is already on disk and there's nothing
                    # to relocate.
                    locate_act = QAction("Locate File...", chip)
                    locate_act.triggered.connect(
                        lambda: self.chipLocateRequested.emit(path)
                    )
                    menu.addAction(locate_act)
                drop_act = QAction("Drop row from bundle...", chip)
                drop_act.triggered.connect(
                    lambda: self.chipDropRequested.emit(path)
                )
                menu.addAction(drop_act)
                menu.exec(event.globalPos())

        chip.mousePressEvent = handler  # type: ignore[assignment]


# Phase 12.7 — chip-state filter bar.
# -----------------------------------------------------------------------
#
# `ChipFilterBar` is the small row of toggleable, color-coded chips that
# lives directly above the chip strip. The chemist clicks a chip-state
# to toggle it in/out of the allowed set; non-matching chips in the
# strip drop to ~35% opacity (handled by `ChipStripOverview.set_filter`).
#
# Initial state: every chip-state allowed. "All" re-enables everything;
# "None" hides every chip. The bar stays purely-stateful so a freshly
# loaded bundle doesn't reset the chemist's prior filtering choices
# unless explicitly told to.

class ChipFilterBar(QWidget):
    """Toggleable chip-state filter row above the chip strip."""

    filterChanged = pyqtSignal(object)  # emitted with the allowed_states set (or None)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 0, 4, 0)
        outer.setSpacing(6)

        title = QLabel("Filter:")
        title.setObjectName("ChipFilterBarTitle")
        outer.addWidget(title)

        self._buttons: dict[str, QPushButton] = {}
        # Start with everything allowed; an explicit "off" set would be
        # confusing — chemist sees a fresh bundle with no chips highlighted.
        self._allowed_states: set[str] = set(CHIP_STATE_LABELS)
        self._rows: list[dict] = []

        for state in FILTER_BAR_STATE_ORDER:
            btn = QPushButton("")
            btn.setCheckable(True)
            btn.setChecked(True)
            color = CHIP_STATE_COLORS.get(state, "#94a3b8")
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color}; color: white; "
                f"border-radius: 8px; padding: 2px 10px; font-weight: 600; "
                f"opacity: 1.0; }}"
                f"QPushButton:checked {{ opacity: 1.0; }}"
                f"QPushButton:!checked {{ opacity: 0.35; }}"
            )
            btn.toggled.connect(lambda checked, s=state: self._on_toggle(s, checked))
            btn.setObjectName(f"ChipFilter_{state}")
            outer.addWidget(btn)
            self._buttons[state] = btn

        # 'all' and 'none' utility buttons at the far right.
        self.btn_all = QPushButton("All")
        self.btn_all.setObjectName("ChipFilter_All")
        self.btn_all.clicked.connect(self._select_all)
        outer.addWidget(self.btn_all)

        self.btn_none = QPushButton("None")
        self.btn_none.setObjectName("ChipFilter_None")
        self.btn_none.clicked.connect(self._select_none)
        outer.addWidget(self.btn_none)

        outer.addStretch(1)

        # Counts label sits at the right edge and re-renders on every
        # bar state change so the chemist sees "3 / 7" etc.
        self.counts_label = QLabel("")
        self.counts_label.setObjectName("ChipFilterCounts")
        outer.addWidget(self.counts_label)

        self._refresh_counts()

    # ---- public API --------------------------------------------------

    def allowedStates(self) -> set[str] | None:
        """Return the current allowed-states set, or None if no filter.

        ``None`` codifies "no filter — every chip passes", and is what
        consumers pass to ChipStripOverview.set_filter() to clear the
        dim path. A non-empty subset means only those states pass.
        An empty subset means "match nothing" (returns [] /
        dims everything). The GUI itself never produces an empty
        set under normal click patterns — the user has to click
        "None" deliberately. Either way, the surface stays one
        value with three discrete shapes.
        """
        if not self._allowed_states:
            # The filter bar model is "subset-of-CHIP_STATE_LABELS".
            # We propagate both None (no filter) and empty-set
            # (filter everything) semantics, but the GUI's
            # bottom-button ("None") produces empty-set on purpose.
            return set(self._allowed_states)
        if self._allowed_states == set(CHIP_STATE_LABELS):
            return None
        return set(self._allowed_states)

    def isStateAllowed(self, state: str) -> bool:
        """Convenience wrapper — passes through chip_state helper."""
        return is_chip_state_allowed(state, self._allowed_states)

    def setRows(self, rows: list[dict]) -> None:
        """Update the cached rows for counts rendering.

        Doesn't touch the filter state — the chemist's filtering
        choice persists across bundle loads. Pass ``rows=[]`` on a
        fresh load to reset counts.
        """
        self._rows = list(rows or [])
        self._refresh_counts()

    def clearFilter(self) -> None:
        """Re-enable every chip-state (sets the bar back to default)."""
        # Block signals so each button doesn't fire its own toggle
        # path; just emit one filterChanged at the end.
        for state, btn in self._buttons.items():
            blocker = btn.blockSignals(True)
            try:
                btn.setChecked(state in CHIP_STATE_LABELS)
            finally:
                btn.blockSignals(blocker)
        self._allowed_states = set(CHIP_STATE_LABELS)
        self._refresh_counts()
        self.filterChanged.emit(self.allowedStates())

    # ---- internals ---------------------------------------------------

    def _on_toggle(self, state: str, checked: bool) -> None:
        if checked:
            self._allowed_states.add(state)
        else:
            self._allowed_states.discard(state)
        self._refresh_counts()
        self.filterChanged.emit(self.allowedStates())

    def _select_all(self) -> None:
        self.clearFilter()

    def _select_none(self) -> None:
        # Uncheck every chip button; the filter is then "match nothing."
        for state, btn in self._buttons.items():
            blocker = btn.blockSignals(True)
            try:
                btn.setChecked(False)
            finally:
                btn.blockSignals(blocker)
        self._allowed_states = set()
        self._refresh_counts()
        self.filterChanged.emit(self.allowedStates())

    def _refresh_counts(self) -> None:
        # Tally rows by state regardless of filter — the chemist
        # wants to see "hidden 3 / total 7" not "visible 7 / total 7"
        # to understand the dim path's behavior.
        counts = count_states(self._rows)
        allowed = self._allowed_states
        visible = sum(counts[s] for s in counts if s in allowed)
        total = sum(counts.values())
        if not self._rows:
            self.counts_label.setText("")
            return
        if allowed == set(CHIP_STATE_LABELS):
            self.counts_label.setText(f"{visible} / {total}")
        else:
            # Show breakdown so the chemist sees which bucket is
            # being filtered.
            breakdown = ", ".join(
                f"{FILTER_BAR_LABELS[s]}:{counts[s]}"
                for s in FILTER_BAR_STATE_ORDER
                if counts[s]
            )
            self.counts_label.setText(
                f"visible {visible} / {total}  ({breakdown})"
            )
