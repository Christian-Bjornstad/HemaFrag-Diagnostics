"""TabLabeling — in-app clonality labeling with inline FSA plots.

Daily workflow for the chemist:
1. Browse to tracking Excel (Clonality_Tracking_All_T7.xlsx)
2. Browse to FSA root (D:/DATA/2025_data)
3. The tab loads patient assays from the Excel (controls and SL are excluded)
4. For each sample:
   - Metadata panel: DIT, assay, well, file, current label
   - Plot panel: FSA electropherogram trace (pyqtgraph)
   - Label by pressing 1-8 (keys map to Norwegian annotation labels)
5. Arrow up/down to navigate samples
6. Ctrl+S to save all labels to Excel
7. Progress bar shows X/N labeled

Keyboard-only:
  1=monoklonal, 2=polyklonal, 3=bi_oligoklonal, 4=irregulaer,
  5=pseudoklonal, 6=intet_pcr_produkt_darlig_dna, 7=qc_teknisk_fail,
  8=usikker_review
  Up/Down = navigate
  Backspace = clear label
  Ctrl+S = save to Excel
  F = filter labeled/unlabeled toggle
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QKeySequence, QShortcut

logger = logging.getLogger(__name__)

# Lazy import to avoid hard dependency in headless tests
def _import_pyqtgraph():
    import pyqtgraph as pg
    pg.setConfigOption("background", "w")
    pg.setConfigOption("foreground", "k")
    return pg


class TabLabeling(QWidget):
    """In-app labeling tab — view plots, assign labels with keyboard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session = None
        self._fsa_root = ""
        self._filter_mode = "all"
        self._assay_filter = ""
        self._show_unlabeled_only = False
        self._visible_sample_indices = []
        self._build_ui()
        self._setup_shortcuts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # --- Top bar: file pickers + progress ---
        top = QHBoxLayout()

        self.btn_browse_xlsx = QPushButton("Browse Excel …")
        self.btn_browse_xlsx.clicked.connect(self._on_browse_xlsx)
        top.addWidget(self.btn_browse_xlsx)

        self.lbl_xlsx = QLabel("No Excel loaded")
        self.lbl_xlsx.setStyleSheet("color: #888;")
        top.addWidget(self.lbl_xlsx, stretch=1)

        self.btn_browse_fsa = QPushButton("Browse FSA root …")
        self.btn_browse_fsa.clicked.connect(self._on_browse_fsa)
        top.addWidget(self.btn_browse_fsa)

        self.lbl_fsa = QLabel("No FSA root")
        self.lbl_fsa.setStyleSheet("color: #888;")
        top.addWidget(self.lbl_fsa, stretch=1)

        self.btn_save = QPushButton("Save to Excel (Ctrl+S)")
        self.btn_save.clicked.connect(self._on_save)
        top.addWidget(self.btn_save)

        layout.addLayout(top)

        # --- Progress ---
        self.progress = QProgressBar()
        self.progress.setFormat("0 / 0 labeled")
        layout.addWidget(self.progress)

        # --- Main splitter: sample list | plot + metadata ---
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: sample list
        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(4)

        self.lbl_filter = QLabel("All samples")
        list_layout.addWidget(self.lbl_filter)

        filter_row = QHBoxLayout()
        self.queue_filter = QComboBox()
        self.queue_filter.addItem("All", "all")
        self.queue_filter.addItem("Unlabeled", "unlabeled")
        self.queue_filter.addItem("Rule review", "review")
        self.queue_filter.currentIndexChanged.connect(self._on_queue_filter_changed)
        filter_row.addWidget(self.queue_filter)

        self.assay_filter = QComboBox()
        self.assay_filter.addItem("All assays", "")
        self.assay_filter.currentIndexChanged.connect(self._on_assay_filter_changed)
        filter_row.addWidget(self.assay_filter)
        list_layout.addLayout(filter_row)

        self.sample_list = QListWidget()
        self.sample_list.currentRowChanged.connect(self._on_sample_selected)
        list_layout.addWidget(self.sample_list)

        splitter.addWidget(list_panel)

        # Right: metadata + plot
        detail_panel = QWidget()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        detail_layout.setSpacing(8)

        # Metadata block
        self.lbl_metadata = QLabel("Select a sample to view its plot")
        self.lbl_metadata.setStyleSheet(
            "font-size: 14px; padding: 8px; background: #f5f5f5; border-radius: 4px;"
        )
        self.lbl_metadata.setWordWrap(True)
        detail_layout.addWidget(self.lbl_metadata)

        # Label hint
        self.lbl_hint = QLabel(
            "Keys: <b>1</b>=monoklonal &nbsp; <b>2</b>=polyklonal &nbsp; "
            "<b>3</b>=bi_oligoklonal &nbsp; <b>4</b>=irregulaer<br>"
            "<b>5</b>=pseudoklonal &nbsp; <b>6</b>=intet PCR &nbsp; "
            "<b>7</b>=QC fail &nbsp; <b>8</b>=usikker<br>"
            "<b>↑/↓</b>=navigate &nbsp; <b>Backspace</b>=clear &nbsp; "
            "<b>Ctrl+S</b>=save &nbsp; <b>F</b>=filter"
        )
        self.lbl_hint.setStyleSheet("font-size: 12px; color: #666; padding: 4px;")
        detail_layout.addWidget(self.lbl_hint)

        # Plot area (pyqtgraph) — lazy import
        try:
            pg = _import_pyqtgraph()
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setLabel("left", "RFU")
            self.plot_widget.setLabel("bottom", "data point")
            self.plot_widget.showGrid(x=False, y=True, alpha=0.3)
            self.plot_widget.addLegend()
            detail_layout.addWidget(self.plot_widget, stretch=1)
        except Exception:
            self.plot_widget = QLabel("pyqtgraph not available — plots disabled")
            detail_layout.addWidget(self.plot_widget, stretch=1)

        splitter.addWidget(detail_panel)
        splitter.setSizes([300, 700])

        layout.addWidget(splitter, stretch=1)

    def _setup_shortcuts(self):
        # Label shortcuts
        from core.labeling.labeling_session import LABEL_KEYS
        for key, label in LABEL_KEYS.items():
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda lbl=label: self._on_label_key(lbl))

        # Navigation
        QShortcut(QKeySequence("Up"), self, activated=self._on_prev_sample)
        QShortcut(QKeySequence("Down"), self, activated=self._on_next_sample)
        QShortcut(QKeySequence("Backspace"), self, activated=self._on_clear_label)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._on_save)
        QShortcut(QKeySequence("F"), self, activated=self._on_toggle_filter)

    def _on_browse_xlsx(self):
        from core.labeling.labeling_session import LabelingSession
        path, _ = QFileDialog.getOpenFileName(
            self, "Open tracking Excel", "", "Excel files (*.xlsx)"
        )
        if not path:
            return
        try:
            self._session = LabelingSession(excel_path=path)
            self._session.load()
            self.lbl_xlsx.setText(path)
            self.lbl_xlsx.setStyleSheet("color: #333;")
            self._populate_assay_filter()
            self._refresh_sample_list()
        except Exception as exc:
            self.lbl_xlsx.setText(f"Error: {exc}")
            self.lbl_xlsx.setStyleSheet("color: red;")

    def _on_browse_fsa(self):
        path = QFileDialog.getExistingDirectory(self, "Select FSA root directory")
        if path:
            self._fsa_root = path
            self.lbl_fsa.setText(path)
            self.lbl_fsa.setStyleSheet("color: #333;")

    def _refresh_sample_list(self):
        from core.labeling.labeling_session import LABEL_TO_KEY
        self.sample_list.clear()
        self._visible_sample_indices = []
        if not self._session:
            return
        for index, sample in enumerate(self._session.samples):
            if self._filter_mode == "unlabeled" and sample.is_labeled:
                continue
            if self._filter_mode == "review" and not sample.rule_review_needed:
                continue
            if self._assay_filter and sample.assay != self._assay_filter:
                continue
            self._visible_sample_indices.append(index)
            key = LABEL_TO_KEY.get(sample.current_label, "")
            prefix = f"[{key}] " if key else "  "
            short_label = sample.current_label if sample.is_labeled else "—"
            text = f"{prefix}{sample.dit} {sample.assay} {sample.well}  →  {short_label}"
            item = QListWidgetItem(text)
            self.sample_list.addItem(item)
        self._update_progress()

    def _update_progress(self):
        if not self._session:
            self.progress.setFormat("0 / 0 labeled")
            return
        total = self._session.total_count
        labeled = self._session.labeled_count
        pct = int(100 * labeled / total) if total else 0
        self.progress.setValue(pct)
        self.progress.setFormat(f"{labeled} / {total} labeled")

    def _current_sample_index(self) -> int:
        row = self.sample_list.currentRow()
        if row < 0 or not self._session:
            return -1
        if 0 <= row < len(self._visible_sample_indices):
            return self._visible_sample_indices[row]
        return -1

    def _on_sample_selected(self, row: int):
        idx = self._current_sample_index()
        if idx < 0 or not self._session:
            return
        sample = self._session.samples[idx]
        from core.labeling.labeling_session import LABEL_TO_KEY
        key = LABEL_TO_KEY.get(sample.current_label, "")
        self.lbl_metadata.setText(
            f"<b>DIT:</b> {sample.dit} &nbsp; "
            f"<b>Assay:</b> {sample.assay} &nbsp; "
            f"<b>Well:</b> {sample.well} &nbsp; "
            f"<b>Group:</b> {sample.group}<br>"
            f"<b>File:</b> {sample.file_name}<br>"
            f"<b>Run dir:</b> {sample.source_run_dir}<br>"
            f"<b>Rule:</b> {sample.rule_suggestion or 'none'}"
            f"{' (review)' if sample.rule_review_needed else ''}<br>"
            f"<b>Label:</b> "
            f"<span style='background: {'#e8f5e9' if key else '#fff3e0'}; "
            f"padding: 2px 6px; border-radius: 3px;'>"
            f"{key}: {sample.current_label or 'unlabeled'}</span>"
        )
        self._render_plot(sample)

    def _render_plot(self, sample):
        """Render the FSA electropherogram trace in the pyqtgraph widget."""
        if not hasattr(self.plot_widget, "clear") or not self._fsa_root:
            return
        self.plot_widget.clear()
        fsa_path = self._session.fsa_path_for(
            self._session.samples.index(sample),
            self._fsa_root
        )
        if fsa_path is None:
            return
        try:
            from Bio import SeqIO

            from core.analyses.clonality.config import ASSAY_CONFIG

            raw = SeqIO.read(str(fsa_path), "abi").annotations.get("abif_raw", {})
            channels = ASSAY_CONFIG.get(sample.assay, {}).get(
                "trace_channels",
                ["DATA1"],
            )
            colors = {
                "DATA1": "#2563eb",
                "DATA2": "#16a34a",
                "DATA3": "#f97316",
            }
            for channel in channels:
                trace = raw.get(channel)
                if trace is None:
                    continue
                self.plot_widget.plot(
                    range(len(trace)),
                    trace,
                    pen=colors.get(channel, "#475569"),
                    name=channel,
                )
        except Exception as exc:
            logger.debug("Plot render failed for %s: %s", fsa_path, exc)

    def _on_label_key(self, label: str):
        visible_row = self.sample_list.currentRow()
        idx = self._current_sample_index()
        if idx < 0 or not self._session:
            return
        self._session.label_sample(idx, label)
        self._refresh_sample_list()
        if self.sample_list.count() == 0:
            return
        target_row = visible_row if self._filter_mode == "unlabeled" else visible_row + 1
        self.sample_list.setCurrentRow(
            min(max(target_row, 0), self.sample_list.count() - 1)
        )

    def _on_clear_label(self):
        idx = self._current_sample_index()
        if idx < 0 or not self._session:
            return
        self._session.clear_label(idx)
        self._refresh_sample_list()

    def _on_next_sample(self):
        row = self.sample_list.currentRow()
        if row + 1 < self.sample_list.count():
            self.sample_list.setCurrentRow(row + 1)

    def _on_prev_sample(self):
        row = self.sample_list.currentRow()
        if row > 0:
            self.sample_list.setCurrentRow(row - 1)

    def _on_save(self):
        if not self._session:
            return
        try:
            written = self._session.save_to_excel()
            self.lbl_xlsx.setText(f"{self._session.excel_path} — saved {written} labels")
        except Exception as exc:
            self.lbl_xlsx.setText(f"Save error: {exc}")
            self.lbl_xlsx.setStyleSheet("color: red;")

    def _on_toggle_filter(self):
        target = "all" if self._filter_mode == "unlabeled" else "unlabeled"
        index = self.queue_filter.findData(target)
        self.queue_filter.setCurrentIndex(index)

    def _on_queue_filter_changed(self):
        self._filter_mode = str(self.queue_filter.currentData() or "all")
        self._show_unlabeled_only = self._filter_mode == "unlabeled"
        labels = {
            "all": "All samples",
            "unlabeled": "Unlabeled only",
            "review": "Rule review",
        }
        self.lbl_filter.setText(labels[self._filter_mode])
        self._refresh_sample_list()

    def _on_assay_filter_changed(self):
        self._assay_filter = str(self.assay_filter.currentData() or "")
        self._refresh_sample_list()

    def _populate_assay_filter(self):
        current = self._assay_filter
        self.assay_filter.blockSignals(True)
        self.assay_filter.clear()
        self.assay_filter.addItem("All assays", "")
        if self._session:
            assays = sorted({sample.assay for sample in self._session.samples if sample.assay})
            for assay in assays:
                self.assay_filter.addItem(assay, assay)
        index = self.assay_filter.findData(current)
        self.assay_filter.setCurrentIndex(max(index, 0))
        self.assay_filter.blockSignals(False)
        self._assay_filter = str(self.assay_filter.currentData() or "")
        self._refresh_sample_list()
