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
  1=monoklonal, 2=monoklonal_pa_poly, 3=polyklonal, 4=oligoklonal,
  5=irregulaer, 6=lite_pcr_produkt, 7=intet_pcr_produkt,
  8=qc_teknisk_fail, 9=usikker_review
  Up/Down = navigate
  Backspace = clear label
  Ctrl+S = save to Excel
  F = filter labeled/unlabeled toggle
"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QKeySequence, QShortcut

logger = logging.getLogger(__name__)


class _PlotWorker(QThread):
    """Analyze one or more parallel FSAs away from the GUI thread."""

    completed = pyqtSignal(int, str, object, str)

    def __init__(self, generation: int, fsa_paths: list[tuple[int, Path]], parent=None):
        super().__init__(parent)
        self._generation = generation
        self._fsa_paths = [(index, Path(path)) for index, path in fsa_paths]
        self.cached_items: list[dict] = []

    def run(self):
        try:
            from core.analyses.clonality.pipeline import _analyze_single_file
            from core.labeling.labeling_plot import build_labeling_plot_data

            items = []
            errors = []
            for sample_index, fsa_path in self._fsa_paths:
                try:
                    entry = _analyze_single_file(fsa_path)
                    if entry is None:
                        raise ValueError("The file was not recognized as a clonality assay.")
                    items.append(
                        {
                            "sample_index": sample_index,
                            "fsa_path": str(fsa_path),
                            "plot_data": build_labeling_plot_data(entry),
                            "error": "",
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - keep other parallels visible
                    logger.exception("Labeling plot analysis failed for %s", fsa_path)
                    errors.append(f"{fsa_path.name}: {exc}")
                    items.append(
                        {
                            "sample_index": sample_index,
                            "fsa_path": str(fsa_path),
                            "plot_data": None,
                            "error": str(exc),
                        }
                    )
            self.completed.emit(
                self._generation,
                "",
                items,
                "; ".join(errors),
            )
        except Exception as exc:
            logger.exception("Labeling plot analysis failed")
            self.completed.emit(
                self._generation,
                "",
                None,
                str(exc),
            )


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
        self._plot_generation = 0
        self._plot_worker = None
        self._pending_plot_request = None
        self._plot_cache = {}
        self._plot_widgets = []
        self._plot_all_items = []
        self._plot_page_index = 0
        self._plot_page_size = 2
        self._pending_plot_order = []
        self._selected_channel = ""
        self._wide_mode = False
        self._sidebar_widget = None
        self._build_ui()
        self._setup_shortcuts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

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

        self.btn_wide = QPushButton("Wide view")
        self.btn_wide.setCheckable(True)
        self.btn_wide.clicked.connect(self._on_toggle_wide_view)
        top.addWidget(self.btn_wide)

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
        detail_layout.setContentsMargins(4, 0, 0, 0)
        detail_layout.setSpacing(3)

        # Metadata block
        self.lbl_metadata = QLabel("Select a sample to view its plot")
        self.lbl_metadata.setStyleSheet(
            "font-size: 12px; padding: 4px 6px; background: #f5f5f5; border-radius: 4px;"
        )
        self.lbl_metadata.setWordWrap(True)
        detail_layout.addWidget(self.lbl_metadata)

        channel_row = QHBoxLayout()
        self.channel_selector = QComboBox()
        self.channel_selector.setToolTip("Trace channel and biological target")
        self.channel_selector.currentIndexChanged.connect(
            self._on_channel_changed
        )
        channel_row.addWidget(self.channel_selector, stretch=1)
        self.btn_overlay_channels = QPushButton("Overlay")
        self.btn_overlay_channels.setCheckable(True)
        self.btn_overlay_channels.setChecked(True)
        self.btn_overlay_channels.setToolTip(
            "Show other assay channels faintly for context"
        )
        self.btn_overlay_channels.clicked.connect(self._render_current_plot)
        channel_row.addWidget(self.btn_overlay_channels)
        self.btn_apply_all_channels = QPushButton("Apply to all")
        self.btn_apply_all_channels.setToolTip(
            "Apply the selected channel's current label to every assay channel"
        )
        self.btn_apply_all_channels.clicked.connect(
            self._on_apply_label_to_all_channels
        )
        channel_row.addWidget(self.btn_apply_all_channels)
        detail_layout.addLayout(channel_row)

        # Label hint
        self.lbl_hint = QLabel(
            "Keys: <b>1</b>=monoklonal &nbsp; <b>2</b>=monoklonal på poly &nbsp; "
            "<b>3</b>=polyklonal &nbsp; <b>4</b>=oligoklonal &nbsp; "
            "<b>5</b>=irregulær &nbsp; "
            "<b>6</b>=lite PCR &nbsp; <b>7</b>=intet PCR &nbsp; "
            "<b>8</b>=QC feil &nbsp; <b>9</b>=usikker &nbsp; "
            "<b>↑/↓</b>=navigate &nbsp; <b>Backspace</b>=clear &nbsp; <b>Ctrl+S</b>=save"
        )
        self.lbl_hint.setStyleSheet("font-size: 11px; color: #666; padding: 1px 4px;")
        detail_layout.addWidget(self.lbl_hint)

        self.lbl_plot_status = QLabel("Select an FSA root to load calibrated traces")
        self.lbl_plot_status.setStyleSheet("font-size: 11px; color: #555; padding: 0 4px;")
        self.lbl_plot_status.setWordWrap(True)
        detail_layout.addWidget(self.lbl_plot_status)

        page_row = QHBoxLayout()
        page_row.setContentsMargins(0, 0, 0, 0)
        page_row.setSpacing(4)
        self.btn_prev_plot_page = QPushButton("Prev")
        self.btn_prev_plot_page.clicked.connect(self._on_prev_plot_page)
        page_row.addWidget(self.btn_prev_plot_page)
        self.lbl_plot_page = QLabel("")
        self.lbl_plot_page.setStyleSheet("font-size: 11px; color: #475569;")
        page_row.addWidget(self.lbl_plot_page)
        self.btn_next_plot_page = QPushButton("Next")
        self.btn_next_plot_page.clicked.connect(self._on_next_plot_page)
        page_row.addWidget(self.btn_next_plot_page)
        page_row.addStretch()
        self.plot_page_nav = QWidget()
        self.plot_page_nav.setLayout(page_row)
        self.plot_page_nav.setVisible(False)
        detail_layout.addWidget(self.plot_page_nav)

        # Plot area (pyqtgraph) — lazy import
        try:
            pg = _import_pyqtgraph()
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setLabel("left", "RFU")
            self.plot_widget.setLabel("bottom", "Base pairs", units="bp")
            self.plot_widget.showGrid(x=False, y=True, alpha=0.3)
            self.plot_widget.addLegend()
            self._plot_widgets = [self.plot_widget]
            self.plot_stack = QWidget()
            self.plot_stack_layout = QVBoxLayout(self.plot_stack)
            self.plot_stack_layout.setContentsMargins(0, 0, 0, 0)
            self.plot_stack_layout.setSpacing(2)
            self.plot_stack_layout.addWidget(self.plot_widget, stretch=1)
            detail_layout.addWidget(self.plot_stack, stretch=1)
        except Exception:
            self.plot_widget = QLabel("pyqtgraph not available — plots disabled")
            detail_layout.addWidget(self.plot_widget, stretch=1)

        splitter.addWidget(detail_panel)
        splitter.setSizes([220, 900])

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
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._on_toggle_wide_view)
        QShortcut(QKeySequence("Tab"), self, activated=self._on_next_channel)

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
            self._render_current_plot()

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
            labels = [
                (
                    unit.channel.replace("DATA", "D"),
                    sample.label_for_channel(unit.channel),
                )
                for unit in sample.interpretation_units
            ]
            if labels:
                label_text = " | ".join(
                    f"{channel}:{label or '-'}" for channel, label in labels
                )
            else:
                key = LABEL_TO_KEY.get(sample.current_label, "")
                label_text = f"{key}:{sample.current_label}" if key else "-"
            text = (
                f"{sample.dit} {sample.assay} {sample.well}"
                f"  ->  {label_text}"
            )
            item = QListWidgetItem(text)
            self.sample_list.addItem(item)
        self._update_progress()

    def _update_progress(self):
        if not self._session:
            self.progress.setFormat("0 / 0 labeled")
            return
        total = self._session.total_unit_count
        labeled = self._session.labeled_unit_count
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
            self._plot_generation += 1
            self._pending_plot_request = None
            if hasattr(self.plot_widget, "clear"):
                self.plot_widget.clear()
            return
        sample = self._session.samples[idx]
        self._populate_channel_selector(sample)
        channel = self._selected_channel
        channel_label = sample.label_for_channel(channel)
        unit = next(
            (
                candidate
                for candidate in sample.interpretation_units
                if candidate.channel == channel
            ),
            None,
        )
        target = unit.target_name if unit is not None else channel
        parallel_indices = self._session.parallel_indices_for(idx)
        self.lbl_metadata.setText(
            f"<b>{sample.dit}</b> &nbsp; {sample.assay} &nbsp; {sample.well} &nbsp; "
            f"<span style='background: {'#e8f5e9' if channel_label else '#fff3e0'}; "
            f"padding: 2px 6px; border-radius: 3px;'>"
            f"{target} / {channel}: {channel_label or 'unlabeled'}</span>"
        )
        self._render_plot_group(parallel_indices)

    def _populate_channel_selector(self, sample) -> None:
        previous = self._selected_channel
        self.channel_selector.blockSignals(True)
        self.channel_selector.clear()
        for unit in sample.interpretation_units:
            label = sample.label_for_channel(unit.channel) or "unlabeled"
            self.channel_selector.addItem(
                f"{unit.channel} | {unit.target_name} | {label}",
                unit.channel,
            )
        self.channel_selector.blockSignals(False)
        index = self.channel_selector.findData(previous)
        if index < 0 and self.channel_selector.count():
            index = 0
        if index >= 0:
            self.channel_selector.setCurrentIndex(index)
            self._selected_channel = str(
                self.channel_selector.itemData(index) or ""
            )
        else:
            self._selected_channel = ""
        self.btn_apply_all_channels.setVisible(
            len(sample.interpretation_units) > 1
        )

    def _on_channel_changed(self) -> None:
        self._selected_channel = str(
            self.channel_selector.currentData() or ""
        )
        idx = self._current_sample_index()
        if idx >= 0:
            self._on_sample_selected(self.sample_list.currentRow())

    def _render_current_plot(self):
        idx = self._current_sample_index()
        if idx < 0 or not self._session:
            return
        self._render_plot_group(self._session.parallel_indices_for(idx))

    def _render_plot_group(self, sample_indices: list[int]):
        """Queue calibrated FSA plots without blocking sample navigation."""
        if not hasattr(self.plot_widget, "clear"):
            return
        self._plot_generation += 1
        generation = self._plot_generation
        self._pending_plot_request = None
        self._pending_plot_order = list(sample_indices)
        self.plot_page_nav.setVisible(False)
        current_index = self._current_sample_index()
        if current_index in sample_indices:
            self._plot_page_index = sample_indices.index(current_index) // self._plot_page_size
        else:
            self._plot_page_index = 0
        for widget in self._plot_widgets:
            widget.clear()
        if not self._fsa_root:
            self.lbl_plot_status.setText("Select an FSA root to load the calibrated trace")
            return
        cached_items: list[dict] = []
        requests: list[tuple[int, Path]] = []
        for sample_index in sample_indices:
            fsa_path = self._session.fsa_path_for(sample_index, self._fsa_root)
            if fsa_path is None:
                cached_items.append(
                    {
                        "sample_index": sample_index,
                        "fsa_path": "",
                        "plot_data": None,
                        "error": "FSA file not found under the selected root",
                    }
                )
                continue
            fsa_path = Path(fsa_path)
            cache_key = str(fsa_path.resolve())
            cached = self._plot_cache.get(cache_key)
            if cached is not None and cached[0] == _file_mtime(fsa_path):
                cached_items.append(
                    {
                        "sample_index": sample_index,
                        "fsa_path": str(fsa_path),
                        "plot_data": cached[1],
                        "error": "",
                    }
                )
            else:
                requests.append((sample_index, fsa_path))
        if not requests:
            self._apply_plot_group(cached_items)
            return

        first = self._session.samples[sample_indices[0]]
        self.lbl_plot_status.setText(
            f"Analyzing {first.assay} parallels ({len(sample_indices)} traces)..."
        )
        request = (generation, requests, cached_items)
        if self._plot_worker is not None and self._plot_worker.isRunning():
            self._pending_plot_request = request
            return
        self._start_plot_worker(*request)

    def _start_plot_worker(
        self,
        generation: int,
        fsa_paths: list[tuple[int, Path]],
        cached_items: list[dict] | None = None,
    ):
        self._pending_plot_request = None
        worker = _PlotWorker(generation, fsa_paths, self)
        worker.cached_items = list(cached_items or [])
        self._plot_worker = worker
        worker.completed.connect(self._on_plot_ready)
        worker.finished.connect(
            lambda current=worker: self._on_plot_worker_finished(current)
        )
        worker.start()

    def _on_plot_ready(
        self,
        generation: int,
        fsa_path: str,
        plot_data,
        error: str,
    ):
        if generation != self._plot_generation:
            return
        if plot_data is None:
            for widget in self._plot_widgets:
                widget.clear()
            self.lbl_plot_status.setText(f"Plot unavailable: {error}")
            return
        items = [*getattr(self._plot_worker, "cached_items", []), *list(plot_data)]
        for item in items:
            item_data = item.get("plot_data")
            item_path = item.get("fsa_path")
            if item_data is not None and item_path:
                path = Path(item_path)
                self._plot_cache[str(path.resolve())] = (_file_mtime(path), item_data)
        while len(self._plot_cache) > 64:
            self._plot_cache.pop(next(iter(self._plot_cache)))
        self._apply_plot_group(items)

    def _on_plot_worker_finished(self, worker=None):
        worker = worker or self._plot_worker
        if worker is not None:
            worker.deleteLater()
        if worker is not self._plot_worker:
            return
        self._plot_worker = None
        pending = self._pending_plot_request
        self._pending_plot_request = None
        if pending is not None:
            self._start_plot_worker(*pending)

    def _apply_plot_data(self, plot_data):
        self._apply_plot_group(
            [{"sample_index": self._current_sample_index(), "plot_data": plot_data, "error": ""}]
        )

    def _apply_plot_group(self, items):
        if not hasattr(self.plot_widget, "clear"):
            return
        items = list(items or [])
        if not items:
            return
        try:
            self._plot_all_items = self._ordered_plot_items(items)
            self._show_plot_page()
        except Exception as exc:
            logger.exception("Plot rendering failed")
            self.lbl_plot_status.setText(f"Plot unavailable: {exc}")

    def _ordered_plot_items(self, items: list[dict]) -> list[dict]:
        order = {
            sample_index: position
            for position, sample_index in enumerate(self._pending_plot_order)
        }
        return sorted(
            items,
            key=lambda item: order.get(item.get("sample_index"), len(order)),
        )

    def _show_plot_page(self):
        items = list(self._plot_all_items or [])
        if not items:
            return
        page_count = max(1, (len(items) + self._plot_page_size - 1) // self._plot_page_size)
        self._plot_page_index = min(max(self._plot_page_index, 0), page_count - 1)
        start = self._plot_page_index * self._plot_page_size
        visible_items = items[start:start + self._plot_page_size]
        self._ensure_plot_widgets(len(visible_items))
        try:
            status_parts = []
            for widget, item in zip(self._plot_widgets, visible_items):
                plot_data = item.get("plot_data")
                sample_index = item.get("sample_index", -1)
                sample = (
                    self._session.samples[sample_index]
                    if self._session
                    and isinstance(sample_index, int)
                    and 0 <= sample_index < len(self._session.samples)
                    else None
                )
                if plot_data is None:
                    widget.clear()
                    title = f"{sample.well if sample else 'Parallel'}: plot unavailable"
                    widget.setTitle(title)
                    status_parts.append(f"{title} ({item.get('error') or 'error'})")
                    continue
                self._draw_plot_data(widget, plot_data, sample=sample)
                ranges = ", ".join(
                    f"{start:g}-{end:g} bp"
                    for start, end in plot_data.interpretation_ranges
                ) or "none configured"
                status_parts.append(
                    f"{sample.well if sample else plot_data.assay}: "
                    f"{plot_data.ladder_qc_status}, {len(plot_data.peaks)} peaks, "
                    f"review windows: {ranges}"
                )
            self.lbl_plot_status.setText(" | ".join(status_parts))
            self.plot_page_nav.setVisible(len(items) > self._plot_page_size)
            self.btn_prev_plot_page.setEnabled(self._plot_page_index > 0)
            self.btn_next_plot_page.setEnabled(self._plot_page_index + 1 < page_count)
            end = min(start + len(visible_items), len(items))
            self.lbl_plot_page.setText(f"Plots {start + 1}-{end} of {len(items)}")
        except Exception as exc:
            logger.exception("Plot rendering failed")
            self.lbl_plot_status.setText(f"Plot unavailable: {exc}")

    def _draw_plot_data(self, widget, plot_data, *, sample=None):
        pg = _import_pyqtgraph()
        colors = {
            "DATA1": "#2563eb",
            "DATA2": "#16a34a",
            "DATA3": "#ea580c",
        }
        widget.clear()
        title_parts = []
        if sample is not None:
            title_parts.extend([sample.well or "?", sample.file_name])
            if sample.current_label:
                title_parts.append(sample.current_label)
        widget.setTitle(" | ".join(title_parts) if title_parts else plot_data.assay)
        for start, end in plot_data.interpretation_ranges:
            region = pg.LinearRegionItem(
                values=(start, end),
                movable=False,
                brush=pg.mkBrush(214, 198, 105, 55),
                pen=pg.mkPen(168, 145, 42, 100),
            )
            region.setZValue(-20)
            widget.addItem(region)

        for bp in getattr(plot_data, "nonspecific_peaks", ()):
            line = pg.InfiniteLine(
                pos=float(bp),
                angle=90,
                movable=False,
                pen=pg.mkPen("#7c3aed", width=1.1, style=Qt.PenStyle.DotLine),
            )
            line.setZValue(-5)
            widget.addItem(line)

        selected_channel = self._selected_channel
        overlay = self.btn_overlay_channels.isChecked()
        for trace in plot_data.traces:
            is_selected = not selected_channel or trace.channel == selected_channel
            if not is_selected and not overlay:
                continue
            widget.plot(
                trace.basepairs,
                trace.rfu,
                pen=pg.mkPen(
                    colors.get(trace.channel, "#475569")
                    if is_selected
                    else "#cbd5e1",
                    width=1.4 if is_selected else 0.8,
                ),
                name=(
                    trace.channel
                    if is_selected
                    else f"{trace.channel} context"
                ),
            )

        for channel in sorted({peak.channel for peak in plot_data.peaks}):
            if selected_channel and channel != selected_channel:
                continue
            peaks = [peak for peak in plot_data.peaks if peak.channel == channel]
            widget.plot(
                [peak.basepair for peak in peaks],
                [peak.rfu for peak in peaks],
                pen=None,
                symbol="o",
                symbolSize=7,
                symbolPen=pg.mkPen(colors.get(channel, "#111827"), width=1.5),
                symbolBrush=pg.mkBrush("#ffffff"),
                name=f"{channel} peaks",
            )

        labeled_peaks = sorted(
            (
                peak
                for peak in plot_data.peaks
                if peak.kept
                and (
                    not selected_channel
                    or peak.channel == selected_channel
                )
            ),
            key=lambda peak: peak.rfu,
            reverse=True,
        )[:12]
        for peak in labeled_peaks:
            label = pg.TextItem(
                text=f"{peak.basepair:.1f}",
                color=colors.get(peak.channel, "#111827"),
                anchor=(0.5, 1.15),
            )
            label.setPos(peak.basepair, peak.rfu)
            widget.addItem(label)

        widget.setXRange(plot_data.bp_min, plot_data.bp_max, padding=0.02)
        widget.enableAutoRange(axis="y", enable=True)

    def _ensure_plot_widgets(self, count: int):
        if not hasattr(self, "plot_stack_layout"):
            return
        pg = _import_pyqtgraph()
        count = max(1, min(int(count), self._plot_page_size))
        while len(self._plot_widgets) < count:
            widget = pg.PlotWidget()
            widget.setLabel("left", "RFU")
            widget.setLabel("bottom", "Base pairs", units="bp")
            widget.showGrid(x=False, y=True, alpha=0.3)
            widget.addLegend()
            widget.setXLink(self._plot_widgets[0])
            self._plot_widgets.append(widget)
            self.plot_stack_layout.addWidget(widget, stretch=1)
        while len(self._plot_widgets) > count:
            widget = self._plot_widgets.pop()
            self.plot_stack_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()

    def _on_prev_plot_page(self):
        if self._plot_page_index <= 0:
            return
        self._plot_page_index -= 1
        self._show_plot_page()

    def _on_next_plot_page(self):
        if not self._plot_all_items:
            return
        max_page = (len(self._plot_all_items) - 1) // self._plot_page_size
        if self._plot_page_index >= max_page:
            return
        self._plot_page_index += 1
        self._show_plot_page()

    def _on_label_key(self, label: str):
        visible_row = self.sample_list.currentRow()
        idx = self._current_sample_index()
        if idx < 0 or not self._session:
            return
        self._session.label_sample(
            idx,
            label,
            channel=self._selected_channel or None,
        )
        sample = self._session.samples[idx]
        next_channel = next(
            (
                unit.channel
                for unit in sample.interpretation_units
                if not sample.label_for_channel(unit.channel)
            ),
            "",
        )
        self._refresh_sample_list()
        if self.sample_list.count() == 0:
            return
        if next_channel and self._filter_mode != "unlabeled":
            target_row = visible_row
        else:
            target_row = (
                visible_row
                if self._filter_mode == "unlabeled"
                else visible_row + 1
            )
        self.sample_list.setCurrentRow(
            min(max(target_row, 0), self.sample_list.count() - 1)
        )
        if next_channel and self._filter_mode != "unlabeled":
            index = self.channel_selector.findData(next_channel)
            if index >= 0:
                self.channel_selector.setCurrentIndex(index)

    def _on_clear_label(self):
        idx = self._current_sample_index()
        if idx < 0 or not self._session:
            return
        self._session.clear_label(
            idx,
            channel=self._selected_channel or None,
        )
        self._refresh_sample_list()

    def _on_apply_label_to_all_channels(self):
        idx = self._current_sample_index()
        if idx < 0 or not self._session:
            return
        sample = self._session.samples[idx]
        label = sample.label_for_channel(self._selected_channel)
        if not label:
            return
        self._session.label_all_channels(idx, label)
        current_row = self.sample_list.currentRow()
        self._refresh_sample_list()
        if self.sample_list.count():
            self.sample_list.setCurrentRow(
                min(max(current_row, 0), self.sample_list.count() - 1)
            )

    def _on_next_channel(self):
        if self.channel_selector.count() <= 1:
            self._on_next_sample()
            return
        current = self.channel_selector.currentIndex()
        if current + 1 < self.channel_selector.count():
            self.channel_selector.setCurrentIndex(current + 1)
        else:
            self.channel_selector.setCurrentIndex(0)
            self._on_next_sample()

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

    def _on_toggle_wide_view(self):
        self._wide_mode = not self._wide_mode
        self.btn_wide.setChecked(self._wide_mode)
        sidebar = self._sidebar_widget or self._find_sidebar_widget()
        self._sidebar_widget = sidebar
        if sidebar is not None:
            sidebar.setVisible(not self._wide_mode)
        window = self.window()
        if window is not None:
            container = getattr(window, "centralWidget", lambda: None)()
            layout = container.layout() if container is not None else None
            if layout is not None:
                layout.setContentsMargins(0, 0, 0, 0)
        self.btn_wide.setText("Show nav" if self._wide_mode else "Wide view")

    def _find_sidebar_widget(self):
        window = self.window()
        if window is None:
            return None
        for widget in window.findChildren(QWidget):
            if widget.objectName() == "Sidebar":
                return widget
        return None

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


def _file_mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None
