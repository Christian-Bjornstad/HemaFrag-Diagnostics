from __future__ import annotations

import copy
import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

# `_constants.py` owns the guarded optional `pyqtgraph` import (`pg`) and the
# ladder QC thresholds (PASS_R2, CHECK_R2, PASS_MAX_ABS_RESIDUAL,
# CHECK_MAX_ABS_RESIDUAL). Importing them explicitly here keeps `_legacy.py`'s
# module namespace self-sufficient: without these lines the dialog crashes with
#   NameError: name 'pg' is not defined                    (at __init__)
#   NameError: name 'CHECK_MAX_ABS_RESIDUAL' is not defined  (at _refresh_*/_plot_residuals)
# because the package `__init__.py`'s `*`-re-export injects them into the package
# namespace, NOT into this submodule's globals.
from gui_qt.dialogs.ladder_dialog._constants import (
    pg,
    PASS_R2,
    CHECK_R2,
    PASS_MAX_ABS_RESIDUAL,
    CHECK_MAX_ABS_RESIDUAL,
)



class LadderAdjustmentDialog(QDialog):
    def __init__(self, fsa, parent=None, *, review_context: dict | None = None, review_comment: str = ""):
        super().__init__(parent)
        self.fsa = fsa
        self.review_context = review_context or {}
        self._initial_review_comment = review_comment
        self._review_action = "apply"
        self.setWindowTitle(f"Ladder Adjustment - {fsa.file_name}")
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if available is not None:
            target_w = min(available.width() - 64, 1700)
            target_h = min(available.height() - 64, 1040)
            self.resize(max(target_w, 980), max(target_h, 680))
            self.setMinimumSize(min(980, available.width()), min(680, available.height()))
        else:
            self.resize(1660, 980)
            self.setMinimumSize(980, 680)

        self.fitted_ladder_steps = np.asarray(fsa.ladder_steps, dtype=float)
        self.ladder_steps = np.asarray(
            getattr(fsa, "expected_ladder_steps", self.fitted_ladder_steps),
            dtype=float,
        )
        self.candidates = self._get_candidates().reset_index(drop=True)
        self.mapping: dict[int, int] = {}
        self._initial_mapping: dict[int, int] = {}
        self._manual_candidate_times: list[float] = []
        self._add_peak_mode = False
        self._preview_fsa = None
        self._preview_metrics: dict | None = None
        self._fit_rows: list[dict] = []
        self._fit_grade = "unknown"
        self._fit_reason = "Preview not run"
        self._missing_order = "ascending"
        self._plot_has_drawn = False
        self._forced_ymax: float | None = None
        self._is_panning = False
        self._pan_start: tuple[float, float, tuple[float, float], tuple[float, float]] | None = None
        self._trace_backend = "pyqtgraph" if pg is not None else "matplotlib"
        self.pg_plot = None
        self.figure = None
        self.ax = None
        self.canvas = None
        self.toolbar = None
        self._shortcuts = []

        self._init_ui()
        self._suggest_auto(store_initial=True)
        self._refresh_preview_state(show_errors=False)
        self._refresh_all()
        self._focus_initial_step()

    def _get_candidates(self):
        from core.analysis import get_ladder_candidates

        df = get_ladder_candidates(self.fsa).copy()
        if "source" not in df.columns:
            df["source"] = "auto"
        trace = np.asarray(getattr(self.fsa, "size_standard", []), dtype=float)
        rows = []
        best_raw = getattr(self.fsa, "best_size_standard", None)
        best = np.asarray(best_raw if best_raw is not None else [], dtype=float)
        existing_times = df["time"].astype(float).to_numpy() if "time" in df.columns and not df.empty else np.array([], dtype=float)
        for peak_time in best:
            if not np.isfinite(peak_time):
                continue
            if existing_times.size and np.any(np.abs(existing_times - float(peak_time)) <= 2.0):
                idx = int(np.argmin(np.abs(existing_times - float(peak_time))))
                df.loc[idx, "source"] = "model_selected"
                continue
            peak_idx = int(round(float(peak_time)))
            if peak_idx < 0 or peak_idx >= trace.size:
                continue
            rows.append(
                {
                    "index": len(df) + len(rows),
                    "time": float(peak_time),
                    "intensity": float(trace[peak_idx]),
                    "source": "model_selected",
                }
            )
        if rows:
            df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
        if not df.empty:
            df = df.sort_values("time").reset_index(drop=True)
            df["index"] = np.arange(len(df))
        return df

    def _init_ui(self):
        self.setObjectName("LadderDialog")
        self.setStyleSheet(
            """
            QDialog#LadderDialog {
                background: #f3f7fb;
            }
            QWidget#WorkspaceCard {
                background: #ffffff;
                border: 1px solid #d9e4ef;
                border-radius: 16px;
            }
            QWidget#PlotCard {
                background: #ffffff;
                border: 1px solid #ccd9e8;
                border-radius: 18px;
            }
            QWidget#EditorRail {
                background: #f8fbff;
                border: 1px solid #d9e4ef;
                border-radius: 16px;
            }
            QWidget#PanelSection,
            QWidget#SizingQcPanel {
                background: #ffffff;
                border: 1px solid #e7eef7;
                border-radius: 12px;
            }
            QWidget#LadderActionBar {
                background: #ffffff;
                border: 1px solid #d9e4ef;
                border-radius: 14px;
            }
            QWidget#TraceToolbar {
                background: #f4f9ff;
                border: 1px solid #deebf7;
                border-radius: 10px;
            }
            QWidget#TraceViewControls,
            QWidget#TraceAssignControls {
                background: transparent;
            }
            QLabel#TraceControlGroupLabel {
                color: #64748b;
                font-size: 9px;
                font-weight: 800;
                letter-spacing: 1px;
            }
            QScrollArea#SizingQcScroll {
                background: transparent;
                border: none;
            }
            QLabel#WorkspaceTitle {
                font-size: 16px;
                font-weight: 800;
                color: #0f172a;
            }
            QLabel#WorkspaceSubtitle {
                color: #53657f;
                font-size: 12px;
                font-weight: 500;
            }
            QLabel#WorkspaceEyebrow {
                color: #6b7b95;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QWidget#MetaChip {
                background: #ffffff;
                border: 1px solid #e3ebf5;
                border-radius: 10px;
            }
            QLabel#MetaValue {
                color: #10233d;
                font-weight: 700;
            }
            QLabel#MetaChipValue {
                color: #10233d;
                font-weight: 800;
                font-size: 11px;
            }
            QLabel#MetaChipLabel {
                color: #69809d;
                font-size: 9px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#CardTitle {
                color: #10233d;
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 0.6px;
            }
            QLabel#ModeBadge {
                background: #0f172a;
                color: white;
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 0.8px;
            }
            QLabel#TraceLegend {
                color: #475569;
                font-size: 10px;
                font-weight: 650;
            }
            QTabWidget::pane {
                background: #ffffff;
                border: 1px solid #e1ebf5;
                border-radius: 12px;
                top: -1px;
            }
            QTabBar::tab {
                background: #f3f7fc;
                color: #516784;
                border: 1px solid #dbe6f2;
                border-bottom: none;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                padding: 7px 14px;
                font-weight: 800;
                min-width: 94px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #10233d;
            }
            QTableWidget {
                background: #fbfdff;
                border: 1px solid #e1ebf5;
                border-radius: 10px;
                gridline-color: #e8eef6;
                alternate-background-color: #f4f8fc;
                selection-background-color: #d9ebff;
                selection-color: #10233d;
            }
            QHeaderView::section {
                background: #f3f7fc;
                color: #516784;
                border: none;
                border-right: 1px solid #e3ebf5;
                border-bottom: 1px solid #e3ebf5;
                padding: 6px 8px;
                font-weight: 700;
            }
            QSplitter::handle {
                background: #dbe6f2;
                border-radius: 3px;
            }
            QSplitter::handle:horizontal {
                width: 8px;
            }
            QSplitter::handle:vertical {
                height: 8px;
            }
            QPushButton {
                background: #f7faff;
                color: #17314f;
                border: 1px solid #d4e2f1;
                border-radius: 10px;
                padding: 6px 10px;
                font-weight: 700;
                min-height: 30px;
            }
            QPushButton#TraceButton {
                padding: 3px 9px;
                min-height: 24px;
                max-height: 28px;
                border-radius: 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #edf5ff;
                border-color: #bdd3ea;
            }
            QPushButton:pressed {
                background: #e3eefb;
            }
            QPushButton#PrimaryButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0891b2, stop:1 #4f46e5);
                color: white;
                border: none;
                padding: 8px 16px;
            }
            QPushButton#PrimaryButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5c7, stop:1 #5b54f0);
            }
            QPushButton#ModeButton:checked {
                background: #dcfce7;
                color: #14532d;
                border-color: #86efac;
            }
            QPushButton#SecondaryButton {
                background: #ffffff;
                color: #334155;
                border-color: #cbd5e1;
            }
            QPushButton#DangerButton {
                background: #ffffff;
                color: #dc2626;
                border-color: #fca5a5;
            }
            QPushButton#DangerButton:hover {
                background: #fef2f2;
                border-color: #dc2626;
            }
            QPushButton:focus {
                border: 2px solid #2563eb;
            }
            QMessageBox {
                background: #f8fbff;
                border: 1px solid #d9e6f2;
                border-radius: 18px;
            }
            QMessageBox QLabel {
                color: #10233d;
                font-weight: 600;
            }
            QMessageBox QPushButton {
                min-width: 112px;
                min-height: 34px;
                border-radius: 10px;
            }
            """
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setSpacing(10)
        outer_layout.setContentsMargins(10, 10, 10, 10)

        content = QWidget(self)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer_layout.addWidget(content, stretch=1)

        layout = QVBoxLayout(content)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        summary_card = QWidget()
        summary_card.setObjectName("WorkspaceCard")
        summary_card.setMaximumHeight(100)
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(10, 6, 10, 6)
        summary_layout.setSpacing(4)

        summary_header = QHBoxLayout()
        summary_header.setSpacing(14)
        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)
        summary_title = QLabel("Ladder Studio")
        summary_title.setObjectName("WorkspaceTitle")
        title_stack.addWidget(summary_title)

        summary_subtitle = QLabel("Correct selected ladder peaks, inspect residuals, and save the adjustment.")
        summary_subtitle.setObjectName("WorkspaceSubtitle")
        title_stack.addWidget(summary_subtitle)
        summary_subtitle.setVisible(False)
        summary_header.addLayout(title_stack, stretch=2)

        help_label = QLabel(
            "Left click assigns nearest candidate. Wheel/drag zooms and pans. Shortcuts: Ctrl+Shift+A add, Ctrl+N next, Ctrl+Return preview."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #475569; font-weight: 650;")
        summary_header.addWidget(help_label, stretch=3)
        help_label.setVisible(False)
        summary_layout.addLayout(summary_header)

        info_row = QHBoxLayout()
        info_row.setSpacing(6)
        self.meta_labels: dict[str, QLabel] = {}
        meta_rows = [
            ("file", "File"),
            ("ladder", "Ladder"),
            ("expected_count", "Expected Ladder Sizes"),
            ("candidate_count", "Detected Ladder Peaks"),
            ("mapped_count", "Mapped Steps"),
            ("preview", "Preview"),
        ]
        for key, label in meta_rows:
            chip = QWidget()
            chip.setObjectName("MetaChip")
            chip.setMinimumHeight(34)
            chip.setMaximumHeight(40)
            chip_layout = QVBoxLayout(chip)
            chip_layout.setContentsMargins(8, 3, 8, 3)
            chip_layout.setSpacing(0)
            left = QLabel(label.upper())
            left.setObjectName("MetaChipLabel")
            right = QLabel("—")
            right.setObjectName("MetaChipValue")
            right.setWordWrap(False)
            self.meta_labels[key] = right
            chip_layout.addWidget(left)
            chip_layout.addWidget(right)
            info_row.addWidget(chip, 1)
        summary_layout.addLayout(info_row)
        layout.addWidget(summary_card)

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.setHandleWidth(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        plot_container = QWidget()
        plot_container.setObjectName("PlotCard")
        plot_container.setMinimumHeight(360)
        plot_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        plot_layout = QVBoxLayout(plot_container)
        plot_layout.setContentsMargins(8, 8, 8, 8)
        plot_layout.setSpacing(5)

        plot_header = QHBoxLayout()
        plot_header.setSpacing(10)
        plot_title = QLabel("LADDER TRACE")
        plot_title.setObjectName("WorkspaceEyebrow")
        plot_header.addWidget(plot_title)
        self.trace_backend_label = QLabel("INTERACTIVE CANVAS" if self._trace_backend == "pyqtgraph" else "MATPLOTLIB FALLBACK")
        self.trace_backend_label.setObjectName("ModeBadge")
        plot_header.addWidget(self.trace_backend_label)
        plot_header.addStretch()
        self.trace_legend_label = QLabel(
            "red = candidates · amber = model · teal = manual · blue/green = selected ladder"
        )
        self.trace_legend_label.setObjectName("TraceLegend")
        plot_header.addWidget(self.trace_legend_label)
        plot_layout.addLayout(plot_header)

        trace_toolbar = QWidget()
        trace_toolbar.setObjectName("TraceToolbar")
        toolbar_layout = QVBoxLayout(trace_toolbar)
        toolbar_layout.setContentsMargins(6, 4, 6, 4)
        toolbar_layout.setSpacing(2)

        view_controls_widget = QWidget()
        view_controls_widget.setObjectName("TraceViewControls")
        view_controls = QHBoxLayout(view_controls_widget)
        view_controls.setContentsMargins(0, 0, 0, 0)
        view_controls.setSpacing(5)
        view_label = QLabel("VIEW")
        view_label.setObjectName("TraceControlGroupLabel")
        view_label.setFixedWidth(48)
        view_controls.addWidget(view_label)

        assign_controls_widget = QWidget()
        assign_controls_widget.setObjectName("TraceAssignControls")
        assign_controls = QHBoxLayout(assign_controls_widget)
        assign_controls.setContentsMargins(0, 0, 0, 0)
        assign_controls.setSpacing(5)
        assign_label = QLabel("ASSIGN")
        assign_label.setObjectName("TraceControlGroupLabel")
        assign_label.setFixedWidth(48)
        assign_controls.addWidget(assign_label)
        self.btn_zoom_full = QPushButton("Full Trace")
        self.btn_zoom_full.clicked.connect(self._zoom_full_trace)
        self.btn_zoom_ladder = QPushButton("Ladder Region")
        self.btn_zoom_ladder.clicked.connect(self._zoom_ladder_region)
        self.btn_zoom_selected = QPushButton("Zoom Selected")
        self.btn_zoom_selected.clicked.connect(self._zoom_selected_peak)
        self.btn_y_auto = QPushButton("Y Auto")
        self.btn_y_auto.clicked.connect(lambda: self._set_forced_ymax(None))
        self.btn_y_300 = QPushButton("Y 300")
        self.btn_y_300.clicked.connect(lambda: self._set_forced_ymax(300.0))
        self.btn_y_1000 = QPushButton("Y 1000")
        self.btn_y_1000.clicked.connect(lambda: self._set_forced_ymax(1000.0))
        self.btn_trace_add_peak = QPushButton("Trace Assign")
        self.btn_trace_add_peak.setObjectName("ModeButton")
        self.btn_trace_add_peak.setCheckable(True)
        self.btn_trace_add_peak.setToolTip("Keep this on, then click the trace to add/assign peaks without switching tabs.")
        self.btn_trace_add_peak.toggled.connect(self._toggle_add_peak_mode)
        self.btn_trace_next_missing = QPushButton("Next Missing")
        self.btn_trace_next_missing.clicked.connect(self._select_next_missing_step)
        self.btn_trace_missing_order = QPushButton()
        self.btn_trace_missing_order.setCheckable(True)
        self.btn_trace_missing_order.toggled.connect(self._toggle_missing_order)
        for btn in (
            self.btn_zoom_full,
            self.btn_zoom_ladder,
            self.btn_zoom_selected,
            self.btn_y_auto,
            self.btn_y_300,
            self.btn_y_1000,
        ):
            btn.setObjectName("TraceButton")
            btn.setMinimumHeight(24)
            btn.setMaximumHeight(28)
            view_controls.addWidget(btn)
        view_controls.addStretch()
        for btn in (
            self.btn_trace_add_peak,
            self.btn_trace_next_missing,
            self.btn_trace_missing_order,
        ):
            btn.setMinimumHeight(24)
            btn.setMaximumHeight(28)
            assign_controls.addWidget(btn)
        assign_controls.addStretch()
        toolbar_layout.addWidget(view_controls_widget)
        toolbar_layout.addWidget(assign_controls_widget)
        plot_layout.addWidget(trace_toolbar)

        if self._trace_backend == "pyqtgraph":
            pg.setConfigOptions(antialias=True)
            self.pg_plot = pg.PlotWidget()
            self.pg_plot.setBackground("#ffffff")
            self.pg_plot.setMenuEnabled(False)
            self.pg_plot.showGrid(x=True, y=True, alpha=0.18)
            self.pg_plot.setLabel("bottom", "Time")
            self.pg_plot.setLabel("left", "Intensity")
            self.pg_plot.getPlotItem().hideButtons()
            self.pg_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.pg_plot.scene().sigMouseClicked.connect(self._on_pg_mouse_clicked)
            self.canvas = self.pg_plot
        else:
            self.figure, self.ax = plt.subplots(figsize=(11, 5))
            self.canvas = FigureCanvas(self.figure)
            self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.toolbar = NavigationToolbar(self.canvas, self)
            self.toolbar.setFixedHeight(32)
            plot_layout.addWidget(self.toolbar)
        plot_layout.addWidget(self.canvas)
        splitter.addWidget(plot_container)

        side_container = QWidget()
        side_container.setObjectName("EditorRail")
        side_container.setMinimumWidth(360)
        side_container.setMaximumWidth(560)
        side_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        side_layout = QVBoxLayout(side_container)
        side_layout.setContentsMargins(10, 10, 10, 10)
        side_layout.setSpacing(7)
        side_title = QLabel("EDITOR")
        side_title.setObjectName("WorkspaceEyebrow")
        side_layout.addWidget(side_title)
        side_title.setVisible(False)

        self.editor_tabs = QTabWidget()
        self.editor_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        steps_card = QWidget()
        steps_layout = QVBoxLayout(steps_card)
        steps_layout.setContentsMargins(8, 8, 8, 8)
        steps_layout.setSpacing(6)
        steps_title = QLabel("LADDER MATCHES")
        steps_title.setObjectName("CardTitle")
        steps_layout.addWidget(steps_title)

        self.missing_steps_label = QLabel("Missing ladder sizes: none")
        self.missing_steps_label.setWordWrap(True)
        self.missing_steps_label.setStyleSheet("color: #64748b; font-weight: 600;")
        steps_layout.addWidget(self.missing_steps_label)

        self.missing_list = QListWidget()
        self.missing_list.setMaximumHeight(70)
        self.missing_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.missing_list.itemSelectionChanged.connect(self._sync_selection_from_missing_list)
        steps_layout.addWidget(self.missing_list)

        self.table = QTableWidget(len(self.ladder_steps), 4)
        self.table.setHorizontalHeaderLabels(["bp", "time", "resid", "status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(220)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.cellDoubleClicked.connect(self._on_step_double_clicked)
        self.table.itemSelectionChanged.connect(self._sync_selection_from_match_table)
        steps_layout.addWidget(self.table)
        self.editor_tabs.addTab(steps_card, "Matches")

        candidates_card = QWidget()
        candidates_layout = QVBoxLayout(candidates_card)
        candidates_layout.setContentsMargins(8, 8, 8, 8)
        candidates_layout.setSpacing(6)
        candidates_title = QLabel("CANDIDATE PEAKS")
        candidates_title.setObjectName("CardTitle")
        candidates_layout.addWidget(candidates_title)

        self.candidate_table = QTableWidget(0 if self.candidates.empty else len(self.candidates), 5)
        self.candidate_table.setHorizontalHeaderLabels(["#", "time", "RFU", "type", "use"])
        self.candidate_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.candidate_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.candidate_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.candidate_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.candidate_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.candidate_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.candidate_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.candidate_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.candidate_table.setAlternatingRowColors(True)
        self.candidate_table.verticalHeader().setVisible(False)
        self.candidate_table.verticalHeader().setDefaultSectionSize(30)
        self.candidate_table.setMinimumHeight(170)
        self.candidate_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.candidate_table.cellDoubleClicked.connect(self._assign_selected_candidate)
        self.candidate_table.itemSelectionChanged.connect(self._sync_selection_from_candidate_table)
        candidates_layout.addWidget(self.candidate_table)

        candidate_btns_top = QHBoxLayout()
        self.btn_add_peak = QPushButton("Add Peaks From Trace")
        self.btn_add_peak.setObjectName("ModeButton")
        self.btn_add_peak.setCheckable(True)
        self.btn_add_peak.toggled.connect(self._toggle_add_peak_mode)
        self.btn_next_missing = QPushButton("Next Missing")
        self.btn_next_missing.clicked.connect(self._select_next_missing_step)
        self.btn_missing_order = QPushButton()
        self.btn_missing_order.setCheckable(True)
        self.btn_missing_order.toggled.connect(self._toggle_missing_order)
        candidate_btns_top.addWidget(self.btn_add_peak)
        candidate_btns_top.addWidget(self.btn_next_missing)
        candidate_btns_top.addWidget(self.btn_missing_order)
        candidates_layout.addLayout(candidate_btns_top)

        candidate_btns_bottom = QHBoxLayout()
        self.btn_assign_candidate = QPushButton("Assign Selected Candidate")
        self.btn_assign_candidate.clicked.connect(self._assign_selected_candidate)
        self.btn_clear_step = QPushButton("Clear Selected Step")
        self.btn_clear_step.clicked.connect(self._clear_selected_step)
        candidate_btns_bottom.addWidget(self.btn_assign_candidate)
        candidate_btns_bottom.addWidget(self.btn_clear_step)
        candidates_layout.addLayout(candidate_btns_bottom)
        self.editor_tabs.addTab(candidates_card, "Candidates")

        side_layout.addWidget(self.editor_tabs, stretch=1)

        splitter.addWidget(side_container)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([1120, 460])

        qc_card = QWidget()
        qc_card.setObjectName("SizingQcPanel")
        qc_layout = QVBoxLayout(qc_card)
        qc_layout.setContentsMargins(12, 10, 12, 10)
        qc_layout.setSpacing(8)
        qc_title = QLabel("SIZING QC")
        qc_title.setObjectName("CardTitle")
        qc_layout.addWidget(qc_title)

        qc_header = QHBoxLayout()
        from gui_qt.widgets.status_pill import StatusPill
        self.qc_grade_label = StatusPill("UNKNOWN")
        self.qc_grade_label.set_state("idle")
        self.qc_summary_label = QLabel("Preview not run")
        self.qc_summary_label.setWordWrap(True)
        self.qc_summary_label.setStyleSheet("color: #475569; font-weight: 600;")
        self.linear_fit_label = QLabel("Linear: not enough mapped peaks")
        self.linear_fit_label.setWordWrap(True)
        self.linear_fit_label.setStyleSheet(
            "background:#f8fafc; border:1px solid #dbeafe; border-radius:10px; padding:8px 10px; "
            "color:#1e3a8a; font-weight:800;"
        )
        qc_header.addWidget(self.qc_grade_label)
        qc_header.addSpacing(12)
        qc_header.addWidget(self.qc_summary_label, stretch=1)
        qc_header.addWidget(self.linear_fit_label)
        qc_layout.addLayout(qc_header)

        self.qc_reason_label = QLabel("Map all ladder steps to inspect residuals and sizing quality.")
        self.qc_reason_label.setWordWrap(True)
        self.qc_reason_label.setStyleSheet("color: #64748b;")
        qc_layout.addWidget(self.qc_reason_label)

        if self.review_context:
            review_card = QWidget()
            review_card.setObjectName("PanelSection")
            review_layout = QVBoxLayout(review_card)
            review_layout.setContentsMargins(14, 12, 14, 12)
            review_layout.setSpacing(8)

            review_title = QLabel("REVIEW NOTES")
            review_title.setObjectName("CardTitle")
            review_layout.addWidget(review_title)

            review_bits = []
            assay = str(self.review_context.get("assay", "") or "").strip()
            if assay:
                review_bits.append(assay)
            well = str(self.review_context.get("well", "") or "").strip()
            if well:
                review_bits.append(f"well {well}")
            ladder = str(self.review_context.get("ladder", "") or "").strip()
            if ladder:
                review_bits.append(ladder)
            self.review_case_label = QLabel(" · ".join(review_bits) if review_bits else self.fsa.file_name)
            self.review_case_label.setWordWrap(True)
            self.review_case_label.setStyleSheet("color: #10233d; font-weight: 700;")
            review_layout.addWidget(self.review_case_label)

            metrics_bits = []
            for key, label in (
                ("linear_max", "Linear max"),
                ("linear_mean", "Linear mean"),
                ("linear_r2", "Linear R²"),
            ):
                value = self.review_context.get(key)
                if value in (None, ""):
                    continue
                try:
                    number = float(value)
                    if "r2" in key:
                        metrics_bits.append(f"{label}: {number:.6f}")
                    else:
                        metrics_bits.append(f"{label}: {number:.2f} bp")
                except Exception:
                    metrics_bits.append(f"{label}: {value}")

            self.review_metrics_label = QLabel(" | ".join(metrics_bits) if metrics_bits else "No bundle metrics available")
            self.review_metrics_label.setWordWrap(True)
            self.review_metrics_label.setStyleSheet("color: #64748b; font-weight: 600;")
            review_layout.addWidget(self.review_metrics_label)

            self.review_comment_edit = QTextEdit()
            self.review_comment_edit.setMinimumHeight(46)
            self.review_comment_edit.setMaximumHeight(68)
            self.review_comment_edit.setPlaceholderText(
                "Comment on the fit, missing ladder, chosen peaks, or why the current fit is acceptable."
            )
            self.review_comment_edit.setPlainText(
                self._initial_review_comment or str(self.review_context.get("label_note", "") or "")
            )
            review_layout.addWidget(self.review_comment_edit)
            qc_layout.addWidget(review_card)
        else:
            self.review_case_label = None
            self.review_metrics_label = None
            self.review_comment_edit = None

        self.residual_figure, self.residual_ax = plt.subplots(figsize=(11, 1.85))
        self.residual_canvas = FigureCanvas(self.residual_figure)
        self.residual_canvas.setMinimumHeight(78)
        self.residual_canvas.setMaximumHeight(105)
        self.residual_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        qc_layout.addWidget(self.residual_canvas)
        qc_scroll = QScrollArea()
        qc_scroll.setObjectName("SizingQcScroll")
        qc_scroll.setWidgetResizable(True)
        qc_scroll.setFrameShape(QFrame.Shape.NoFrame)
        qc_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        qc_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        qc_scroll.setWidget(qc_card)
        qc_scroll.setMinimumHeight(130)

        main_splitter.addWidget(splitter)
        main_splitter.addWidget(qc_scroll)
        main_splitter.setStretchFactor(0, 5)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([820, 150])
        layout.addWidget(main_splitter, stretch=1)

        action_bar = QWidget()
        action_bar.setObjectName("LadderActionBar")
        bottom_layout = QHBoxLayout(action_bar)
        bottom_layout.setContentsMargins(12, 8, 12, 8)
        bottom_layout.setSpacing(8)
        self.stats_label = QLabel("Preview: not run")
        self.stats_label.setStyleSheet("color: #64748b; font-weight: 600;")
        self.stats_label.setWordWrap(True)
        self.stats_label.setMinimumWidth(0)
        bottom_layout.addWidget(self.stats_label, stretch=1)

        btn_auto = QPushButton("Suggest Auto")
        btn_auto.clicked.connect(lambda: self._suggest_auto(store_initial=False))
        bottom_layout.addWidget(btn_auto)

        btn_reset = QPushButton("Reset To Initial")
        btn_reset.setObjectName("SecondaryButton")
        btn_reset.clicked.connect(self._reset_to_initial)
        bottom_layout.addWidget(btn_reset)

        btn_clear_all = QPushButton("Clear All")
        btn_clear_all.setObjectName("DangerButton")
        btn_clear_all.clicked.connect(self._clear_all)
        bottom_layout.addWidget(btn_clear_all)

        btn_preview = QPushButton("Preview Fit")
        btn_preview.clicked.connect(self._preview_fit)
        bottom_layout.addWidget(btn_preview)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("SecondaryButton")
        btn_cancel.clicked.connect(self.reject)
        bottom_layout.addWidget(btn_cancel)

        if self.review_context:
            btn_save_note = QPushButton("Save Note Only")
            btn_save_note.setObjectName("SecondaryButton")
            btn_save_note.clicked.connect(self._on_save_note_only)
            bottom_layout.addWidget(btn_save_note)

        btn_apply = QPushButton("Save Adjustment")
        btn_apply.setObjectName("PrimaryButton")
        btn_apply.clicked.connect(self._on_apply)
        bottom_layout.addWidget(btn_apply)

        layout.addWidget(action_bar)
        if self._trace_backend == "matplotlib":
            self.canvas.mpl_connect("button_press_event", self._on_plot_button_press)
            self.canvas.mpl_connect("button_release_event", self._on_plot_button_release)
            self.canvas.mpl_connect("motion_notify_event", self._on_plot_motion)
            self.canvas.mpl_connect("scroll_event", self._on_scroll_zoom)
        self._sync_missing_order_button()
        self._install_shortcuts()

    @staticmethod
    def _apply_matplotlib_layout(figure, **kwargs):
        """Use fixed margins instead of tight_layout; Qt resize races can make tight_layout singular."""
        try:
            figure.subplots_adjust(**kwargs)
        except Exception:
            # Layout failure must never block editing/saving manual ladder picks.
            pass

    def _install_shortcuts(self) -> None:
        bindings = [
            ("Ctrl+Shift+A", lambda: self._toggle_add_peak_mode(not self._add_peak_mode)),
            ("Ctrl+N", self._select_next_missing_step),
            ("Ctrl+Backspace", self._clear_selected_step),
            ("Ctrl+Return", self._preview_fit),
            ("Ctrl+F", self._zoom_full_trace),
            ("Ctrl+L", self._zoom_ladder_region),
            ("Ctrl+Shift+Z", self._zoom_selected_peak),
        ]
        self._shortcuts = []
        for key, callback in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _refresh_all(self):
        self._update_meta()
        self._update_match_table()
        self._update_candidate_table()
        self._update_missing_steps_label()
        self._plot_ladder()
        self._update_qc_panel()
        self._plot_residuals()

    def _update_meta(self):
        self.meta_labels["file"].setText(self.fsa.file_name)
        self.meta_labels["ladder"].setText(str(self.fsa.ladder))
        self.meta_labels["expected_count"].setText(str(len(self.ladder_steps)))
        manual_count = 0
        if "source" in self.candidates.columns:
            manual_count = int(self.candidates["source"].astype(str).eq("manual").sum())
        candidate_text = str(len(self.candidates))
        if manual_count:
            candidate_text += f" ({manual_count} manual)"
        self.meta_labels["candidate_count"].setText(candidate_text)
        self.meta_labels["mapped_count"].setText(f"{len(self.mapping)} / {len(self.ladder_steps)}")

        if self._preview_metrics:
            r2 = self._preview_metrics.get("r2", float("nan"))
            n = self._preview_metrics.get("n_ladder_steps", 0)
            txt = f"{self._fit_grade.upper()} · R² {r2:.6f} · n={n}"
        else:
            txt = "Not previewed yet"
        self.meta_labels["preview"].setText(txt)

    def _candidate_used_by(self, cand_idx: int) -> int | None:
        for step_idx, mapped_idx in self.mapping.items():
            if mapped_idx == cand_idx:
                return step_idx
        return None

    def _row_fit_state(self, row: int) -> dict:
        base = {
            "expected_bp": float(self.ladder_steps[row]),
            "observed_pos": None,
            "assignment": "Missing",
            "residual": None,
            "confidence": "None",
            "status": "Missing",
        }
        if row >= len(self._fit_rows):
            return base
        return {**base, **self._fit_rows[row]}

    def _missing_step_indices(self) -> list[int]:
        missing = [idx for idx in range(len(self.ladder_steps)) if idx not in self.mapping]
        if self._missing_order == "descending":
            missing.reverse()
        return missing

    def _focus_initial_step(self):
        missing = self._missing_step_indices()
        if missing:
            self.table.selectRow(missing[0])
            return
        if self.table.rowCount():
            self.table.selectRow(0)

    def _update_missing_steps_label(self):
        missing = self._missing_step_indices()
        self.missing_list.clear()
        if not missing:
            self.missing_steps_label.setText("Missing ladder sizes: none")
            self.missing_steps_label.setStyleSheet("color: #16a34a; font-weight: 700;")
            self.missing_list.setVisible(False)
            return
        self.missing_list.setVisible(True)
        for idx in missing:
            item = QListWidgetItem(f"{self.ladder_steps[idx]:.0f} bp")
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self.missing_list.addItem(item)
        bp_text = ", ".join(f"{self.ladder_steps[idx]:.0f} bp" for idx in missing)
        self.missing_steps_label.setText(f"Missing ladder sizes ({len(missing)} remaining): {bp_text}")
        self.missing_steps_label.setStyleSheet("color: #dc2626; font-weight: 700;")

    def _sync_selection_from_missing_list(self):
        items = self.missing_list.selectedItems()
        if not items:
            return
        step_idx = items[0].data(Qt.ItemDataRole.UserRole)
        if step_idx is not None:
            self.table.selectRow(int(step_idx))

    def _next_missing_step(self, current_step: int | None = None) -> int | None:
        missing = self._missing_step_indices()
        if not missing:
            return None
        if current_step is None:
            return missing[0]
        if self._missing_order == "descending":
            for step in missing:
                if step < current_step:
                    return step
        else:
            for step in missing:
                if step > current_step:
                    return step
        return missing[0]

    def _sync_missing_order_button(self):
        buttons = [self.btn_missing_order]
        trace_button = getattr(self, "btn_trace_missing_order", None)
        if trace_button is not None:
            buttons.append(trace_button)
        if self._missing_order == "descending":
            text = "Order: High → Low"
            checked = True
        else:
            text = "Order: Low → High"
            checked = False
        for button in buttons:
            previous = button.blockSignals(True)
            button.setText(text)
            button.setChecked(checked)
            button.blockSignals(previous)

    def _sync_add_peak_buttons(self):
        for button in [getattr(self, "btn_add_peak", None), getattr(self, "btn_trace_add_peak", None)]:
            if button is None:
                continue
            previous = button.blockSignals(True)
            button.setChecked(bool(self._add_peak_mode))
            button.blockSignals(previous)

    def _recommended_missing_order(self) -> str:
        missing = [idx for idx in range(len(self.ladder_steps)) if idx not in self.mapping]
        if not missing:
            return "ascending"

        ladder_len = len(self.ladder_steps)
        low_end_missing = sum(1 for idx in missing if idx < max(3, ladder_len // 3))
        high_end_mapped = sum(1 for idx in self.mapping if idx >= ladder_len // 2)
        if low_end_missing and high_end_mapped:
            return "descending"
        return "ascending"

    def _toggle_missing_order(self, checked: bool):
        self._missing_order = "descending" if checked else "ascending"
        self._sync_missing_order_button()
        self._update_missing_steps_label()
        step_idx = self._selected_step_row()
        next_missing = self._next_missing_step(step_idx)
        if next_missing is not None:
            self.table.selectRow(next_missing)

    def _select_next_missing_step(self):
        step_idx = self._next_missing_step(self._selected_step_row())
        if step_idx is None:
            QMessageBox.information(self, "No Missing Steps", "All ladder steps are currently assigned.")
            return
        self.table.selectRow(step_idx)
        self.stats_label.setText(
            f"Selected missing ladder step {self.ladder_steps[step_idx]:.0f} bp. Click the trace to add its peak."
        )
        self.stats_label.setStyleSheet("color: #0f766e; font-weight: 700;")

    def _update_match_table(self):
        selected_step = self._selected_step_row()
        for row in range(len(self.ladder_steps)):
            row_state = self._row_fit_state(row)
            items = [
                QTableWidgetItem(f"{row_state['expected_bp']:.0f} bp"),
                QTableWidgetItem("—" if row_state["observed_pos"] is None else f"{row_state['observed_pos']:.0f}"),
                QTableWidgetItem("—" if row_state["residual"] is None else f"{row_state['residual']:+.2f} bp"),
                QTableWidgetItem(str(row_state["status"])),
            ]
            status = str(row_state["status"])
            if status == "Missing":
                items[3].setForeground(Qt.GlobalColor.red)
            elif status == "Outlier":
                items[3].setForeground(Qt.GlobalColor.darkYellow)
            elif status == "Weak":
                items[3].setForeground(Qt.GlobalColor.darkYellow)
            else:
                items[3].setForeground(Qt.GlobalColor.darkGreen)
            if str(row_state["assignment"]).startswith("Manual"):
                items[1].setForeground(Qt.GlobalColor.darkBlue)
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)
        if selected_step is not None and 0 <= selected_step < self.table.rowCount():
            self.table.selectRow(selected_step)

    def _update_candidate_table(self):
        selected_candidate = self._selected_candidate_row()
        self.candidate_table.setRowCount(len(self.candidates))
        for row in range(len(self.candidates)):
            cand = self.candidates.iloc[row]
            assigned_step = self._candidate_used_by(row)
            assigned_text = f"{self.ladder_steps[assigned_step]:.0f} bp" if assigned_step is not None else "Free"
            source = str(cand.get("source", "auto"))
            row_label = str(row)
            if source == "manual":
                row_label += " *"

            items = [
                QTableWidgetItem(row_label),
                QTableWidgetItem(f"{float(cand['time']):.0f}"),
                QTableWidgetItem(f"{float(cand['intensity']):.0f}"),
                QTableWidgetItem(source),
                QTableWidgetItem(assigned_text),
            ]
            if assigned_step is not None:
                items[4].setForeground(Qt.GlobalColor.darkGreen)
            if source == "manual":
                items[0].setForeground(Qt.GlobalColor.darkBlue)
                items[1].setForeground(Qt.GlobalColor.darkBlue)
                items[3].setForeground(Qt.GlobalColor.darkBlue)
            elif source == "model_selected":
                items[0].setForeground(Qt.GlobalColor.darkGreen)
                items[1].setForeground(Qt.GlobalColor.darkGreen)
                items[3].setForeground(Qt.GlobalColor.darkGreen)
            for col, item in enumerate(items):
                self.candidate_table.setItem(row, col, item)
        if selected_candidate is not None and 0 <= selected_candidate < self.candidate_table.rowCount():
            self.candidate_table.selectRow(selected_candidate)

    def _build_adjustment_payload(self) -> dict:
        mapping_times: dict[int, float] = {}
        for step_idx, cand_idx in self.mapping.items():
            if 0 <= cand_idx < len(self.candidates):
                mapping_times[int(step_idx)] = float(self.candidates.iloc[cand_idx]["time"])
        return {
            "mapping": dict(self.mapping),
            "mapping_times": mapping_times,
            "manual_candidates": list(self._manual_candidate_times),
        }

    def _candidate_time_exists(self, peak_time: float, tolerance: float = 2.0) -> int | None:
        if self.candidates.empty:
            return None
        diff = (self.candidates["time"].astype(float) - float(peak_time)).abs()
        matches = diff[diff <= tolerance]
        if matches.empty:
            return None
        return int(matches.index[0])

    def _find_local_peak_time(self, x_value: float, search_radius: int = 18) -> tuple[float, float]:
        trace = np.asarray(self.fsa.size_standard, dtype=float)
        if trace.size == 0:
            raise ValueError("No size-standard trace available.")
        center = int(round(float(x_value)))
        lo = max(center - search_radius, 0)
        hi = min(center + search_radius + 1, trace.size)
        if lo >= hi:
            raise ValueError("Could not inspect the selected ladder region.")
        window = trace[lo:hi]
        local_index = int(np.argmax(window))
        peak_index = lo + local_index
        return float(peak_index), float(trace[peak_index])

    def _insert_manual_candidate(self, peak_time: float, intensity: float) -> int:
        existing_idx = self._candidate_time_exists(peak_time)
        if existing_idx is not None:
            return existing_idx

        if not any(math.isclose(float(existing), float(peak_time), abs_tol=1e-6) for existing in self._manual_candidate_times):
            self._manual_candidate_times.append(float(peak_time))
            self._manual_candidate_times.sort()

        manual_row = pd.DataFrame(
            [
                {
                    "index": len(self.candidates),
                    "time": float(peak_time),
                    "intensity": float(intensity),
                    "source": "manual",
                }
            ]
        )
        self.candidates = pd.concat([self.candidates, manual_row], ignore_index=True)
        return int(self.candidates.index[-1])

    def _add_manual_peak_from_plot(self, x_value: float, assign_to_step: int | None = None) -> None:
        peak_time, intensity = self._find_local_peak_time(x_value)
        cand_idx = self._insert_manual_candidate(peak_time, intensity)
        if assign_to_step is not None:
            self._assign_candidate_to_step(assign_to_step, cand_idx)
            return
        self._refresh_preview_state(show_errors=False)
        self._refresh_all()
        self.candidate_table.selectRow(cand_idx)

    def _fit_method_name(self) -> str:
        model = getattr(self._preview_fsa or self.fsa, "ladder_model", None)
        if model is None:
            return "unknown"
        name = model.__class__.__name__.lower()
        if "spline" in name:
            return "spline"
        if "poly" in name:
            return "polynomial"
        return name.replace("model", "")

    def _lookup_fitted_bp(self, peak_time: float) -> float | None:
        preview_fsa = self._preview_fsa
        if preview_fsa is None:
            return None
        df = getattr(preview_fsa, "sample_data_with_basepairs", None)
        if df is not None and {"time", "basepairs"}.issubset(df.columns):
            row = df.loc[df["time"] == int(peak_time)]
            if not row.empty:
                return float(row["basepairs"].iloc[0])
        ladder_model = getattr(preview_fsa, "ladder_model", None)
        if ladder_model is not None:
            try:
                return float(ladder_model.predict(np.array([[peak_time]], dtype=float))[0])
            except Exception:
                return None
        return None

    def _candidate_intensity_median(self) -> float:
        if self.candidates.empty:
            return 0.0
        return float(self.candidates["intensity"].median())

    def _current_linear_fit(self) -> dict | None:
        rows = []
        for step_idx, cand_idx in self.mapping.items():
            if step_idx < 0 or step_idx >= len(self.ladder_steps):
                continue
            if cand_idx < 0 or cand_idx >= len(self.candidates):
                continue
            rows.append((step_idx, float(self.candidates.iloc[cand_idx]["time"]), float(self.ladder_steps[step_idx])))
        if len(rows) < 2:
            return None
        rows.sort(key=lambda item: item[0])
        step_indices = np.asarray([row[0] for row in rows], dtype=int)
        times = np.asarray([row[1] for row in rows], dtype=float)
        bps = np.asarray([row[2] for row in rows], dtype=float)
        try:
            coeff = np.polyfit(times, bps, 1)
            predicted = np.polyval(coeff, times)
        except Exception:
            return None
        residuals = predicted - bps
        try:
            r2 = float(1.0 - (np.sum((bps - predicted) ** 2) / np.sum((bps - np.mean(bps)) ** 2))) if bps.size > 1 else float("nan")
        except Exception:
            r2 = float("nan")
        return {
            "n": int(len(rows)),
            "mean_abs": float(np.mean(np.abs(residuals))) if residuals.size else float("inf"),
            "max_abs": float(np.max(np.abs(residuals))) if residuals.size else float("inf"),
            "r2": r2,
            "residuals_by_step": {int(step): float(resid) for step, resid in zip(step_indices, residuals)},
        }

    def _build_fit_rows(self) -> list[dict]:
        rows: list[dict] = []
        intensity_median = self._candidate_intensity_median()
        linear_fit = self._current_linear_fit()
        linear_residuals = linear_fit.get("residuals_by_step", {}) if linear_fit else {}
        for step_idx, bp in enumerate(self.ladder_steps):
            if step_idx not in self.mapping or self.candidates.empty:
                rows.append(
                    {
                        "expected_bp": float(bp),
                        "observed_pos": None,
                        "assignment": "Missing",
                        "residual": None,
                        "confidence": "None",
                        "status": "Missing",
                    }
                )
                continue

            cand_idx = self.mapping[step_idx]
            cand = self.candidates.iloc[cand_idx]
            peak_time = float(cand["time"])
            intensity = float(cand["intensity"])
            fitted_bp = self._lookup_fitted_bp(peak_time)
            residual = None if fitted_bp is None else float(fitted_bp - bp)
            if residual is None and step_idx in linear_residuals:
                residual = float(linear_residuals[step_idx])

            assignment_prefix = "Auto" if self._initial_mapping.get(step_idx) == cand_idx else "Manual"
            status = "Mapped"
            if residual is not None and abs(residual) > CHECK_MAX_ABS_RESIDUAL:
                status = "Outlier"
            elif intensity_median > 0 and intensity < intensity_median * 0.35:
                status = "Weak"
            elif assignment_prefix == "Manual":
                status = "Manual"

            if residual is None:
                confidence = "Low"
            elif abs(residual) <= 0.35 and (intensity_median <= 0 or intensity >= intensity_median * 0.6):
                confidence = "High"
            elif abs(residual) <= 1.0:
                confidence = "Medium"
            else:
                confidence = "Low"

            rows.append(
                {
                    "expected_bp": float(bp),
                    "observed_pos": peak_time,
                    "assignment": f"{assignment_prefix} #{cand_idx}",
                    "residual": residual,
                    "confidence": confidence,
                    "status": status,
                }
            )
        return rows

    def _grade_preview_state(self) -> tuple[str, str]:
        missing_count = sum(1 for row in self._fit_rows if row["status"] == "Missing")
        outlier_count = sum(1 for row in self._fit_rows if row["status"] == "Outlier")
        if self._preview_metrics is None:
            if len(self.mapping) < 3:
                return "check", "Map at least 3 ladder steps to preview the fit."
            if missing_count:
                return "check", f"{missing_count} ladder step(s) are still missing from the current edit."
            return "unknown", "Preview not run"

        r2 = float(self._preview_metrics.get("r2", float("nan")))
        max_abs = float(self._preview_metrics.get("max_abs_error_bp", float("inf")))
        if missing_count or outlier_count or r2 < CHECK_R2 or max_abs > CHECK_MAX_ABS_RESIDUAL:
            return "fail", "Fit needs attention: missing steps, low R², or high residual outlier detected."
        if r2 < PASS_R2 or max_abs > PASS_MAX_ABS_RESIDUAL:
            return "check", "Fit is usable, but one or more residuals still need review."
        return "pass", "Stable ladder fit with low residuals across mapped steps."

    def _refresh_preview_state(self, show_errors: bool) -> None:
        self._preview_fsa = None
        self._preview_metrics = None
        self._fit_rows = []
        self._fit_grade = "unknown"
        self._fit_reason = "Preview not run"

        if len(self.mapping) < 3:
            self._fit_rows = self._build_fit_rows()
            self._fit_grade, self._fit_reason = self._grade_preview_state()
            return

        missing_steps = [idx for idx in range(len(self.ladder_steps)) if idx not in self.mapping]
        if missing_steps:
            self._fit_rows = self._build_fit_rows()
            self._fit_grade, self._fit_reason = self._grade_preview_state()
            return

        from core.analysis import apply_manual_ladder_mapping, compute_ladder_qc_metrics

        try:
            preview_fsa = copy.deepcopy(self.fsa)
            preview_fsa.expected_ladder_steps = np.array(self.ladder_steps, dtype=float).copy()
            preview_fsa.ladder_steps = np.array(self.ladder_steps, dtype=float).copy()
            preview_fsa = apply_manual_ladder_mapping(preview_fsa, self._build_adjustment_payload())
            self._preview_fsa = preview_fsa
            self._preview_metrics = compute_ladder_qc_metrics(preview_fsa)
        except Exception as exc:
            self._preview_fsa = None
            self._preview_metrics = None
            self._fit_reason = str(exc)
            if show_errors:
                QMessageBox.critical(self, "Preview Failed", f"Could not fit this mapping:\n{exc}")
        self._fit_rows = self._build_fit_rows()
        self._fit_grade, self._fit_reason = self._grade_preview_state()

    def _update_qc_panel(self):
        color_map = {
            "pass": "#16a34a",
            "check": "#d97706",
            "fail": "#dc2626",
            "unknown": "#64748b",
        }
        def _format_linear(linear: dict | None) -> str:
            if not linear:
                return "Linear: map at least 2 peaks"
            return (
                f"Linear {linear.get('n', 0)}/{len(self.ladder_steps)} | "
                f"max {float(linear.get('max_abs', float('nan'))):.2f} bp | "
                f"mean {float(linear.get('mean_abs', float('nan'))):.2f} bp | "
                f"R2 {float(linear.get('r2', float('nan'))):.6f}"
            )

        current_linear = self._current_linear_fit()
        label = self._fit_grade.upper()
        self.qc_grade_label.setText(label)
        self.qc_grade_label.set_state(self._fit_grade if self._fit_grade in ("pass", "check", "fail") else "idle")

        missing_count = sum(1 for row in self._fit_rows if row["status"] == "Missing")
        extra_count = max(len(self.candidates) - len(self.mapping), 0)
        if self._preview_metrics is None:
            self.linear_fit_label.setText(_format_linear(current_linear))
            self.qc_summary_label.setText(
                f"{self._fit_method_name()} · mapped {len(self.mapping)}/{len(self.ladder_steps)} · missing {missing_count} · extra {extra_count}"
            )
            self.qc_reason_label.setText(self._fit_reason)
            self.stats_label.setText(f"Preview pending: {self._fit_reason}")
            self.stats_label.setStyleSheet("color: #d97706; font-weight: 700;")
            return

        r2 = float(self._preview_metrics.get("r2", float("nan")))
        mean_abs = float(self._preview_metrics.get("mean_abs_error_bp", float("inf")))
        max_abs = float(self._preview_metrics.get("max_abs_error_bp", float("inf")))
        linear = {
            "n": int(self._preview_metrics.get("n_ladder_steps", len(self.mapping)) or len(self.mapping)),
            "mean_abs": float(self._preview_metrics.get("linear_trend_mean_abs_error_bp", float("inf"))),
            "max_abs": float(self._preview_metrics.get("linear_trend_max_abs_error_bp", float("inf"))),
            "r2": float(self._preview_metrics.get("linear_trend_r2", float("nan"))),
        }
        self.linear_fit_label.setText(_format_linear(linear))
        self.qc_summary_label.setText(
            f"{self._fit_method_name()} · R² {r2:.6f} · mean {mean_abs:.2f} bp · max {max_abs:.2f} bp · missing {missing_count} · extra {extra_count}"
        )
        self.qc_reason_label.setText(self._fit_reason)
        self.stats_label.setText(
            f"Preview fit {label}: R² {r2:.6f} | mean {mean_abs:.2f} bp | max {max_abs:.2f} bp"
        )
        self.stats_label.setStyleSheet(f"color: {color_map.get(self._fit_grade, '#64748b')}; font-weight: 700;")

    def _plot_residuals(self):
        self.residual_ax.clear()
        xs = []
        ys = []
        colors = []
        for row in self._fit_rows:
            if row["residual"] is None:
                continue
            xs.append(row["expected_bp"])
            ys.append(row["residual"])
            if abs(row["residual"]) <= PASS_MAX_ABS_RESIDUAL:
                colors.append("#16a34a")
            elif abs(row["residual"]) <= CHECK_MAX_ABS_RESIDUAL:
                colors.append("#d97706")
            else:
                colors.append("#dc2626")

        self.residual_ax.axhline(0.0, color="#94a3b8", linestyle="--", linewidth=1.0)
        if xs:
            self.residual_ax.scatter(xs, ys, c=colors, s=42, zorder=3)
            self.residual_ax.plot(xs, ys, color="#cbd5e1", linewidth=1.0, zorder=2)
            self.residual_ax.set_ylabel("Residual (bp)")
        else:
            self.residual_ax.text(
                0.5,
                0.5,
                "Residuals will appear after a valid fit preview.",
                transform=self.residual_ax.transAxes,
                ha="center",
                va="center",
                color="#64748b",
            )
        self.residual_ax.set_xlabel("Expected ladder step (bp)")
        self.residual_ax.grid(True, alpha=0.2)
        self._apply_matplotlib_layout(self.residual_figure, left=0.07, right=0.985, top=0.86, bottom=0.30)
        self.residual_canvas.draw_idle()

    def _trace_current_limits(self) -> tuple[tuple[float, float], tuple[float, float]] | tuple[None, None]:
        if self._trace_backend == "pyqtgraph" and self.pg_plot is not None:
            x_range, y_range = self.pg_plot.getPlotItem().vb.viewRange()
            return (float(x_range[0]), float(x_range[1])), (float(y_range[0]), float(y_range[1]))
        if self.ax is not None:
            return tuple(map(float, self.ax.get_xlim())), tuple(map(float, self.ax.get_ylim()))
        return None, None

    def _set_trace_limits(
        self,
        xlim: tuple[float, float] | None = None,
        ylim: tuple[float, float] | None = None,
        *,
        draw: bool = True,
    ) -> None:
        if self._trace_backend == "pyqtgraph" and self.pg_plot is not None:
            if xlim is not None:
                self.pg_plot.setXRange(float(xlim[0]), float(xlim[1]), padding=0.0)
            if ylim is not None:
                self.pg_plot.setYRange(float(ylim[0]), float(ylim[1]), padding=0.0)
            return
        if self.ax is None:
            return
        if xlim is not None:
            self.ax.set_xlim(*xlim)
        if ylim is not None:
            self.ax.set_ylim(*ylim)
        if draw and self.canvas is not None:
            self.canvas.draw_idle()

    def _nearest_candidate_from_position(
        self,
        x_value: float,
        y_value: float | None = None,
        *,
        max_time_delta: float = 45.0,
    ) -> int | None:
        if self.candidates.empty:
            return None
        xlim, ylim = self._trace_current_limits()
        times = self.candidates["time"].to_numpy(dtype=float)
        intensities = self.candidates["intensity"].to_numpy(dtype=float)
        if xlim is not None:
            visible = (times >= min(xlim)) & (times <= max(xlim))
        else:
            visible = np.ones(times.shape, dtype=bool)
        if not np.any(visible):
            return None
        indices = np.where(visible)[0]
        time_diffs = np.abs(times[indices] - float(x_value))
        if y_value is not None and ylim is not None:
            x_span = max(abs(float(xlim[1]) - float(xlim[0])), 1.0) if xlim is not None else 1.0
            y_span = max(abs(float(ylim[1]) - float(ylim[0])), 1.0)
            y_diffs = np.abs(intensities[indices] - float(y_value))
            score = (time_diffs / x_span) + (y_diffs / y_span) * 0.55
            best_pos = int(np.argmin(score))
            if float(time_diffs[best_pos]) <= max_time_delta or float(score[best_pos]) <= 0.035:
                return int(indices[best_pos])
            return None
        best_pos = int(np.argmin(time_diffs))
        if float(time_diffs[best_pos]) <= max_time_delta:
            return int(indices[best_pos])
        return None

    def _handle_trace_click(self, x_value: float, y_value: float | None = None, *, cand_idx: int | None = None) -> None:
        step_idx = self._active_or_next_step()
        if self._add_peak_mode:
            if step_idx is None:
                QMessageBox.information(self, "No Step Selected", "Select a ladder step first, then add the missing peak from the plot.")
                return
            cand_idx = cand_idx if cand_idx is not None else self._nearest_candidate_from_position(x_value, y_value)
            if cand_idx is not None:
                self._assign_candidate_to_step(step_idx, cand_idx)
                return
            self._add_manual_peak_from_plot(float(x_value), assign_to_step=step_idx)
            return

        if self.candidates.empty:
            return
        if step_idx is None:
            step_idx = self._next_missing_step(None)
            if step_idx is not None:
                self.table.selectRow(step_idx)
        if step_idx is None:
            QMessageBox.information(self, "No Step Selected", "Select a ladder step first, then click a candidate peak.")
            return

        cand_idx = cand_idx if cand_idx is not None else self._nearest_candidate_from_position(x_value, y_value)
        if cand_idx is not None:
            self._assign_candidate_to_step(step_idx, cand_idx)
            return

        peak_time, _intensity = self._find_local_peak_time(float(x_value))
        existing_idx = self._candidate_time_exists(peak_time, tolerance=3.0)
        if existing_idx is not None:
            self._assign_candidate_to_step(step_idx, existing_idx)
            return

        self.stats_label.setText("No nearby candidate found. Turn on Add Peaks From Trace to create a manual peak here.")
        self.stats_label.setStyleSheet("color: #d97706; font-weight: 700;")

    def _on_pg_mouse_clicked(self, event):
        if self.pg_plot is None or event.button() != Qt.MouseButton.LeftButton:
            return
        scene_pos = event.scenePos()
        if not self.pg_plot.sceneBoundingRect().contains(scene_pos):
            return
        view_pos = self.pg_plot.getPlotItem().vb.mapSceneToView(scene_pos)
        x_value = float(view_pos.x())
        y_value = float(view_pos.y())
        cand_idx = self._nearest_candidate_from_position(x_value, y_value)
        self._handle_trace_click(x_value, y_value, cand_idx=cand_idx)
        event.accept()

    def _trace_default_limits(self) -> tuple[tuple[float, float], tuple[float, float]]:
        trace = np.asarray(self.fsa.size_standard, dtype=float)
        if trace.size == 0:
            return (0.0, 1.0), (0.0, 1.0)
        if not self.candidates.empty:
            x_min = max(float(self.candidates["time"].min()) - 180.0, 0.0)
            x_max = min(float(self.candidates["time"].max()) + 180.0, float(len(trace)))
            y_auto = max(float(self.candidates["intensity"].max()) * 1.28, float(np.max(trace)) * 0.95, 1.0)
        else:
            x_min, x_max = 0.0, float(len(trace))
            y_auto = max(float(np.max(trace)) * 1.05, 1.0)
        y_max = self._forced_ymax if self._forced_ymax is not None else y_auto
        y_min = min(-150.0, float(np.min(trace)) * 1.05)
        return (x_min, x_max), (y_min, float(y_max))

    def _zoom_full_trace(self):
        self._forced_ymax = None
        trace = np.asarray(self.fsa.size_standard, dtype=float)
        if trace.size == 0:
            return
        self._set_trace_limits(
            (0.0, float(len(trace))),
            (min(-150.0, float(np.min(trace)) * 1.05), max(float(np.max(trace)) * 1.05, 1.0)),
        )

    def _zoom_ladder_region(self):
        xlim, ylim = self._trace_default_limits()
        self._set_trace_limits(xlim, ylim)

    def _zoom_selected_peak(self):
        step_idx = self._selected_step_row()
        center = None
        if step_idx is not None and step_idx in self.mapping:
            cand_idx = self.mapping[step_idx]
            if 0 <= cand_idx < len(self.candidates):
                center = float(self.candidates.iloc[cand_idx]["time"])
        if center is None:
            cand_idx = self._selected_candidate_row()
            if cand_idx is not None and 0 <= cand_idx < len(self.candidates):
                center = float(self.candidates.iloc[cand_idx]["time"])
        if center is None:
            QMessageBox.information(self, "No Peak Selected", "Select a mapped ladder row or candidate peak first.")
            return

        trace = np.asarray(self.fsa.size_standard, dtype=float)
        lo = max(center - 260.0, 0.0)
        hi = min(center + 260.0, float(len(trace)))
        ylim = None
        if trace.size:
            ilo = max(int(lo), 0)
            ihi = min(int(hi) + 1, trace.size)
            local_max = float(np.max(trace[ilo:ihi])) if ilo < ihi else float(np.max(trace))
            y_max = self._forced_ymax if self._forced_ymax is not None else max(local_max * 1.25, 1.0)
            ylim = (min(-50.0, float(np.min(trace[ilo:ihi])) * 1.05 if ilo < ihi else 0.0), y_max)
        self._set_trace_limits((lo, hi), ylim)

    def _set_forced_ymax(self, y_max: float | None):
        self._forced_ymax = y_max
        xlim, _ylim = self._trace_current_limits() if self._plot_has_drawn else (None, None)
        self._plot_ladder(preserve_view=False)
        if xlim is not None:
            self._set_trace_limits(xlim, None)

    def _plot_ladder_pyqtgraph(self, preserve_view: bool = True) -> None:
        if self.pg_plot is None:
            return
        previous_xlim, previous_ylim = self._trace_current_limits() if preserve_view and self._plot_has_drawn else (None, None)
        self.pg_plot.clear()
        trace = np.asarray(self.fsa.size_standard, dtype=float)
        if trace.size:
            x = np.arange(trace.size, dtype=float)
            self.pg_plot.plot(x, trace, pen=pg.mkPen("#6f86a3", width=1.35), name="Size Standard")

        selected_candidate = self._selected_candidate_row()
        selected_step = self._selected_step_row()

        if not self.candidates.empty:
            times = self.candidates["time"].to_numpy(dtype=float)
            intensities = self.candidates["intensity"].to_numpy(dtype=float)
            source_values = self.candidates["source"].astype(str) if "source" in self.candidates.columns else pd.Series(["auto"] * len(self.candidates))
            manual_mask = source_values.eq("manual").to_numpy(dtype=bool)
            model_mask = source_values.eq("model_selected").to_numpy(dtype=bool)
            auto_mask = ~(manual_mask | model_mask)
            if np.any(auto_mask):
                self.pg_plot.addItem(
                    pg.ScatterPlotItem(
                        x=times[auto_mask],
                        y=intensities[auto_mask],
                        symbol="x",
                        size=11,
                        pen=pg.mkPen("#ef4444", width=1.6),
                        brush=None,
                    )
                )
            if np.any(model_mask):
                self.pg_plot.addItem(
                    pg.ScatterPlotItem(
                        x=times[model_mask],
                        y=intensities[model_mask],
                        symbol="o",
                        size=10,
                        pen=pg.mkPen("#b45309", width=1.2),
                        brush=pg.mkBrush("#fef3c7"),
                    )
                )
            if np.any(manual_mask):
                self.pg_plot.addItem(
                    pg.ScatterPlotItem(
                        x=times[manual_mask],
                        y=intensities[manual_mask],
                        symbol="d",
                        size=10,
                        pen=pg.mkPen("#0f766e", width=1.2),
                        brush=pg.mkBrush("#0f766e"),
                    )
                )

            if selected_candidate is not None and 0 <= selected_candidate < len(self.candidates):
                c = self.candidates.iloc[selected_candidate]
                self.pg_plot.addItem(
                    pg.ScatterPlotItem(
                        x=[float(c["time"])],
                        y=[float(c["intensity"])],
                        symbol="o",
                        size=18,
                        pen=pg.mkPen("#2563eb", width=2.2),
                        brush=pg.mkBrush(0, 0, 0, 0),
                    )
                )

        for step_idx, cand_idx in self.mapping.items():
            if cand_idx < 0 or cand_idx >= len(self.candidates):
                continue
            cand = self.candidates.iloc[cand_idx]
            peak_time = float(cand["time"])
            peak_intensity = float(cand["intensity"])
            bp = self.ladder_steps[step_idx]
            marker_color = "#2563eb" if step_idx == selected_step else "#16a34a"
            self.pg_plot.addItem(
                pg.ScatterPlotItem(
                    x=[peak_time],
                    y=[peak_intensity],
                    symbol="o",
                    size=12,
                    pen=pg.mkPen(marker_color, width=1.4),
                    brush=pg.mkBrush(marker_color),
                )
            )
            label = pg.TextItem(
                html=(
                    f"<div style='background:#ffffff; color:{marker_color}; "
                    f"border:1px solid {marker_color}; border-radius:4px; padding:1px 4px; "
                    f"font-weight:700; font-size:9pt;'>{bp:.0f}</div>"
                ),
                anchor=(0.5, 1.35),
            )
            label.setPos(peak_time, peak_intensity)
            self.pg_plot.addItem(label)

        self.pg_plot.getPlotItem().setTitle(f"Ladder Trace - {self.fsa.ladder}", color="#10233d", size="11pt")
        xlim, ylim = self._trace_default_limits()
        self._set_trace_limits(xlim, ylim, draw=False)
        if previous_xlim is not None:
            self._set_trace_limits(previous_xlim, None, draw=False)
        if previous_ylim is not None and self._forced_ymax is None:
            self._set_trace_limits(None, previous_ylim, draw=False)
        self._plot_has_drawn = True

    def _plot_ladder(self, preserve_view: bool = True):
        if self._trace_backend == "pyqtgraph":
            self._plot_ladder_pyqtgraph(preserve_view=preserve_view)
            return
        previous_xlim = self.ax.get_xlim() if preserve_view and self._plot_has_drawn else None
        previous_ylim = self.ax.get_ylim() if preserve_view and self._plot_has_drawn and self._forced_ymax is None else None
        self.ax.clear()
        trace = self.fsa.size_standard
        self.ax.plot(trace, color="#8fa6c1", alpha=0.95, linewidth=1.35, label="Size Standard")

        selected_candidate = self._selected_candidate_row()
        selected_step = self._selected_step_row()

        if not self.candidates.empty:
            times = self.candidates["time"].to_numpy(dtype=float)
            intensities = self.candidates["intensity"].to_numpy(dtype=float)
            source_values = self.candidates["source"].astype(str) if "source" in self.candidates.columns else pd.Series(["auto"] * len(self.candidates))
            manual_mask = source_values.eq("manual").to_numpy(dtype=bool)
            model_mask = source_values.eq("model_selected").to_numpy(dtype=bool)
            auto_mask = ~(manual_mask | model_mask)
            if np.any(auto_mask):
                self.ax.scatter(
                    times[auto_mask],
                    intensities[auto_mask],
                    marker="x",
                    color="#ef4444",
                    s=48,
                    linewidths=1.4,
                    label="Candidates",
                )
            if np.any(model_mask):
                self.ax.scatter(
                    times[model_mask],
                    intensities[model_mask],
                    marker="o",
                    facecolors="#fef3c7",
                    edgecolors="#b45309",
                    s=62,
                    linewidths=1.2,
                    label="Model selected",
                )
            if np.any(manual_mask):
                self.ax.scatter(
                    times[manual_mask],
                    intensities[manual_mask],
                    marker="D",
                    color="#0f766e",
                    s=46,
                    linewidths=1.0,
                    edgecolors="#0f766e",
                    label="Manual peaks",
                )

            if selected_candidate is not None and 0 <= selected_candidate < len(self.candidates):
                c = self.candidates.iloc[selected_candidate]
                self.ax.scatter(
                    [float(c["time"])],
                    [float(c["intensity"])],
                    s=120,
                    facecolors="none",
                    edgecolors="#2563eb",
                    linewidths=2,
                    label="Selected Candidate",
                )

        for step_idx, cand_idx in self.mapping.items():
            cand = self.candidates.iloc[cand_idx]
            peak_time = float(cand["time"])
            peak_intensity = float(cand["intensity"])
            bp = self.ladder_steps[step_idx]
            marker_color = "#2563eb" if step_idx == selected_step else "#22c55e"
            self.ax.scatter([peak_time], [peak_intensity], s=70, color=marker_color, zorder=3)
            offset_y = 10 if step_idx % 2 == 0 else 22
            self.ax.annotate(
                f"{bp:.0f}",
                (peak_time, peak_intensity),
                textcoords="offset points",
                xytext=(0, offset_y),
                ha="center",
                fontsize=8,
                color=marker_color,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.16", fc="white", ec=marker_color, lw=0.8, alpha=0.92),
            )

        xlim, ylim = self._trace_default_limits()
        self.ax.set_xlim(*xlim)
        self.ax.set_ylim(*ylim)
        if previous_xlim is not None:
            self.ax.set_xlim(*previous_xlim)
        if previous_ylim is not None:
            self.ax.set_ylim(*previous_ylim)

        self.ax.set_title(f"Ladder Trace · {self.fsa.ladder}", fontsize=14, fontweight="bold")
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Intensity")
        self.ax.grid(True, alpha=0.25)
        self.ax.legend(loc="upper right", frameon=True, facecolor="white", edgecolor="#dbe4ef")
        self._apply_matplotlib_layout(self.figure, left=0.055, right=0.985, top=0.92, bottom=0.10)
        self._plot_has_drawn = True
        self.canvas.draw_idle()

    def _selected_step_row(self) -> int | None:
        selected_rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return selected_rows[0].row() if selected_rows else None

    def _selected_candidate_row(self) -> int | None:
        selected_rows = self.candidate_table.selectionModel().selectedRows() if self.candidate_table.selectionModel() else []
        return selected_rows[0].row() if selected_rows else None

    def _sync_selection_from_match_table(self):
        step = self._selected_step_row()
        if step is not None and step in self.mapping:
            self.candidate_table.selectRow(self.mapping[step])
        self._plot_ladder()

    def _sync_selection_from_candidate_table(self):
        cand_idx = self._selected_candidate_row()
        if cand_idx is not None:
            step_idx = self._candidate_used_by(cand_idx)
            if step_idx is not None:
                self.table.selectRow(step_idx)
        self._plot_ladder()

    def _toolbar_is_active(self) -> bool:
        if self.toolbar is None:
            return False
        return bool(str(getattr(self.toolbar, "mode", "") or ""))

    def _nearest_candidate_from_event(self, event, *, max_pixels: float = 22.0, max_time_delta: float = 45.0) -> int | None:
        if self.candidates.empty or event.xdata is None:
            return None
        times = self.candidates["time"].to_numpy(dtype=float)
        intensities = self.candidates["intensity"].to_numpy(dtype=float)
        xlim = self.ax.get_xlim()
        visible = (times >= min(xlim)) & (times <= max(xlim))
        if not np.any(visible):
            return None
        indices = np.where(visible)[0]
        points = self.ax.transData.transform(np.column_stack([times[indices], intensities[indices]]))
        click = np.asarray([float(event.x), float(event.y)], dtype=float)
        distances = np.sqrt(np.sum((points - click) ** 2, axis=1))
        best_pos = int(np.argmin(distances))
        best_idx = int(indices[best_pos])
        if float(distances[best_pos]) <= max_pixels:
            return best_idx

        time_diffs = np.abs(times[indices] - float(event.xdata))
        best_time_pos = int(np.argmin(time_diffs))
        if float(time_diffs[best_time_pos]) <= max_time_delta:
            return int(indices[best_time_pos])
        return None

    def _active_or_next_step(self) -> int | None:
        step_idx = self._selected_step_row()
        if step_idx is None or (self._add_peak_mode and step_idx in self.mapping):
            step_idx = self._next_missing_step(step_idx)
            if step_idx is not None:
                self.table.selectRow(step_idx)
        return step_idx

    def _toggle_add_peak_mode(self, checked: bool):
        self._add_peak_mode = checked
        self._sync_add_peak_buttons()
        if checked:
            step_idx = self._selected_step_row()
            if step_idx is None or step_idx in self.mapping:
                next_missing = self._next_missing_step(step_idx)
                if next_missing is not None:
                    self.table.selectRow(next_missing)
                    step_idx = next_missing
            if step_idx is None:
                self.stats_label.setText("Add-missing mode: all ladder steps are already assigned.")
                self.stats_label.setStyleSheet("color: #64748b; font-weight: 700;")
                return
            direction = "high -> low" if self._missing_order == "descending" else "low -> high"
            self.stats_label.setText(
                f"Add-peaks mode ({direction}): click the trace to place {self.ladder_steps[step_idx]:.0f} bp at the local maximum. Mode stays on for the next missing peak."
            )
            self.stats_label.setStyleSheet("color: #0f766e; font-weight: 700;")
        else:
            self._update_qc_panel()

    def _assign_candidate_to_step(self, step_idx: int, cand_idx: int):
        if step_idx < 0 or step_idx >= len(self.ladder_steps):
            return
        if cand_idx < 0 or cand_idx >= len(self.candidates):
            return

        # Enforce one candidate per ladder step and one ladder step per candidate.
        for other_step, other_cand in list(self.mapping.items()):
            if other_step == step_idx:
                continue
            if other_cand == cand_idx:
                del self.mapping[other_step]
        self.mapping[step_idx] = cand_idx
        self._refresh_preview_state(show_errors=False)
        self._refresh_all()

        if self._add_peak_mode:
            next_missing = self._next_missing_step(step_idx)
            if next_missing is not None:
                self.table.selectRow(next_missing)
                self.stats_label.setText(
                    f"Added {self.ladder_steps[step_idx]:.0f} bp. Click to place the next missing step: {self.ladder_steps[next_missing]:.0f} bp."
                )
                self.stats_label.setStyleSheet("color: #0f766e; font-weight: 700;")
            else:
                self.btn_add_peak.setChecked(False)
                self.stats_label.setText("All ladder steps are now assigned. Review the fit and save if it looks good.")
                self.stats_label.setStyleSheet("color: #16a34a; font-weight: 700;")
        elif step_idx + 1 < len(self.ladder_steps):
            self.table.selectRow(step_idx + 1)

    def _clear_selected_step(self):
        step_idx = self._selected_step_row()
        if step_idx is None:
            QMessageBox.information(self, "No Step Selected", "Select a ladder step to clear first.")
            return
        if step_idx in self.mapping:
            del self.mapping[step_idx]
            self._refresh_preview_state(show_errors=False)
            self._refresh_all()
            self.table.selectRow(step_idx)

    def _clear_all(self):
        self.mapping = {}
        self._refresh_preview_state(show_errors=False)
        self._refresh_all()
        if self.table.rowCount():
            self.table.selectRow(0)

    def _reset_to_initial(self):
        self.mapping = dict(self._initial_mapping)
        self._refresh_preview_state(show_errors=False)
        self._refresh_all()
        if self.table.rowCount():
            self.table.selectRow(0)

    def _on_plot_button_press(self, event):
        if event.inaxes != self.ax or event.xdata is None:
            return
        if event.button in (2, 3):
            if event.xdata is not None and event.ydata is not None:
                self._is_panning = True
                self._pan_start = (float(event.xdata), float(event.ydata), self.ax.get_xlim(), self.ax.get_ylim())
            return
        if event.button != 1 or self._toolbar_is_active():
            return

        cand_idx = self._nearest_candidate_from_event(event)
        self._handle_trace_click(float(event.xdata), float(event.ydata) if event.ydata is not None else None, cand_idx=cand_idx)

    def _on_plot_motion(self, event):
        if not self._is_panning or self._pan_start is None or event.inaxes != self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        start_x, start_y, start_xlim, start_ylim = self._pan_start
        dx = start_x - float(event.xdata)
        dy = start_y - float(event.ydata)
        self.ax.set_xlim(start_xlim[0] + dx, start_xlim[1] + dx)
        self.ax.set_ylim(start_ylim[0] + dy, start_ylim[1] + dy)
        self.canvas.draw_idle()

    def _on_plot_button_release(self, _event):
        self._is_panning = False
        self._pan_start = None

    def _on_scroll_zoom(self, event):
        if event.inaxes != self.ax or event.xdata is None:
            return
        if self._toolbar_is_active():
            return
        scale = 0.82 if event.button == "up" else 1.22
        x_left, x_right = self.ax.get_xlim()
        y_bottom, y_top = self.ax.get_ylim()
        x = float(event.xdata)
        y = float(event.ydata) if event.ydata is not None else (y_bottom + y_top) / 2.0
        new_width = (x_right - x_left) * scale
        new_height = (y_top - y_bottom) * scale
        rel_x = (x_right - x) / (x_right - x_left) if x_right != x_left else 0.5
        rel_y = (y_top - y) / (y_top - y_bottom) if y_top != y_bottom else 0.5
        self.ax.set_xlim(x - new_width * (1.0 - rel_x), x + new_width * rel_x)
        self.ax.set_ylim(y - new_height * (1.0 - rel_y), y + new_height * rel_y)
        self.canvas.draw_idle()

    def _on_step_double_clicked(self, row, _column):
        if row in self.mapping:
            del self.mapping[row]
            self._refresh_preview_state(show_errors=False)
            self._refresh_all()
            self.table.selectRow(row)

    def _assign_selected_candidate(self, *_args):
        step_idx = self._selected_step_row()
        cand_idx = self._selected_candidate_row()
        if step_idx is None:
            QMessageBox.information(self, "No Step Selected", "Select a ladder step first.")
            return
        if cand_idx is None:
            QMessageBox.information(self, "No Candidate Selected", "Select a candidate peak first.")
            return
        self._assign_candidate_to_step(step_idx, cand_idx)

    def _suggest_auto(self, store_initial: bool):
        best = getattr(self.fsa, "best_size_standard", None)
        auto_mapping: dict[int, int] = {}
        if best is not None and len(best) > 0 and not self.candidates.empty:
            fitted_steps = np.asarray(getattr(self.fsa, "ladder_steps", self.ladder_steps), dtype=float)
            for fitted_idx, peak_time in enumerate(best):
                if peak_time <= 0:
                    continue
                matches = np.where(np.isclose(self.ladder_steps, fitted_steps[fitted_idx], atol=1e-6))[0]
                if matches.size == 0:
                    continue
                candidate_times = self.candidates["time"].astype(float).to_numpy()
                diffs = np.abs(candidate_times - float(peak_time))
                if diffs.size == 0:
                    continue
                cand_idx = int(np.argmin(diffs))
                if float(diffs[cand_idx]) > 3.0:
                    continue
                step_idx = int(matches[0])
                auto_mapping[step_idx] = cand_idx

        self.mapping = auto_mapping
        if not store_initial:
            self._manual_candidate_times = []
            self.candidates = self._get_candidates().reset_index(drop=True)
        if store_initial:
            self._initial_mapping = dict(auto_mapping)
        self._missing_order = self._recommended_missing_order()
        self._sync_missing_order_button()
        self._refresh_preview_state(show_errors=False)

    def _preview_fit(self):
        if len(self.mapping) < 3:
            QMessageBox.warning(self, "Invalid Fit", "Select at least 3 peaks to preview fit.")
            return
        self._refresh_preview_state(show_errors=True)
        self._refresh_all()

    def _on_apply(self):
        self._review_action = "apply"
        if not self.mapping:
            QMessageBox.warning(self, "No Mapping", "Map at least one ladder step before applying.")
            return
        missing_steps = self._missing_step_indices()
        if missing_steps:
            missing_text = ", ".join(f"{self.ladder_steps[idx]:.0f} bp" for idx in missing_steps[:8])
            if len(missing_steps) > 8:
                missing_text += ", ..."
            QMessageBox.warning(
                self,
                "Incomplete Ladder Mapping",
                "All expected ladder steps must be assigned before saving this adjustment.\n\n"
                f"Missing: {missing_text}",
            )
            return

        self._refresh_preview_state(show_errors=True)
        self._refresh_all()
        if self._preview_metrics is None:
            QMessageBox.warning(
                self,
                "Preview Required",
                "This ladder correction could not be previewed successfully yet. Fix the fit before saving.",
            )
            return
        self.accept()

    def _on_save_note_only(self):
        self._review_action = "note_only"
        self.accept()

    def get_mapping(self):
        return dict(self.mapping)

    def get_adjustment_payload(self):
        return self._build_adjustment_payload()

    def get_review_payload(self):
        return {
            "action": self._review_action,
            "comment": self.review_comment_edit.toPlainText().strip() if self.review_comment_edit else "",
            "linear_max": self.review_context.get("linear_max"),
            "linear_mean": self.review_context.get("linear_mean"),
            "linear_r2": self.review_context.get("linear_r2"),
        }
