from __future__ import annotations

from pathlib import Path
import copy
import subprocess
import sys
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QGridLayout,
    QMessageBox,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, QThreadPool, QTimer, pyqtSignal

from config import APP_SETTINGS, get_analysis_settings
from core.ladder_adjustment_io import deactivate_ladder_adjustment, load_ladder_adjustment, save_ladder_adjustment
from core.analyses.clonality.ladder_review_labels import (
    is_review_rerunnable,
    is_review_resolved,
)
from gui_qt.worker import Worker
from gui_qt.operation_coordinator import OperationStartRejected


def _open_ladder_adjustment_dialog(*args, **kwargs):
    """Import the ladder dialog lazily (it drags in matplotlib/pandas)."""
    from gui_qt.dialogs.ladder_dialog import LadderAdjustmentDialog

    return LadderAdjustmentDialog(*args, **kwargs)



def _open_path(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class TabLadder(QWidget):
    reportsRefreshed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.threadpool = QThreadPool.globalInstance()
        self._operation_coordinator = None
        self._all_files: list[Path] = []
        self._current_file: Path | None = None
        self._current_meta: dict | None = None
        self._current_fsa = None
        self._report_matches: list[Path] = []
        self._review_bundle_dir: Path | None = None
        self._review_bundle_run_manifest_path: Path | None = None
        self._review_bundle_cases: list[dict] = []
        self._review_case_by_path: dict[Path, dict] = {}
        self._review_runtime_cache: dict[Path, dict] = {}
        self._review_session_entries_by_path: dict[Path, dict] = {}
        self._manual_rerun_consumption_by_path: dict[Path, dict] = {}
        self._recent_reviewed_files: set[Path] = set()
        self._auto_open_review_editor_once = False
        self._pending_open_editor_after_metadata = False
        self._current_analysis_id = APP_SETTINGS.get("active_analysis", "clonality")
        self._scan_request_id = 0
        self._source_load_active = False
        self._metadata_request_id = 0
        self._metadata_request_context: tuple[int, str, Path] | None = None
        self._report_request_id = 0
        self._single_rerun_request_id = 0
        self._review_bundle_rerun_request_id = 0
        self._metadata_loading = False
        self._single_rerun_active = False
        self._review_bundle_rerun_active = False

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)

        header = QVBoxLayout()
        title = QLabel("Ladder Studio")
        title.setObjectName("PageTitle")
        sub = QLabel("Pick one .fsa file, inspect its ladder metadata, and open a focused ladder-adjustment workflow.")
        sub.setObjectName("PageSubtitle")
        header.addWidget(title)
        header.addWidget(sub)
        main_layout.addLayout(header)

        main_layout.addWidget(self._build_source_card(), stretch=1)

        self._empty_state = QLabel(
            "No file selected. Scan a folder or open one .fsa file to inspect its ladder."
        )
        self._empty_state.setObjectName("EmptyStateCard")
        self._empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self._empty_state)

        self._details_card = self._build_details_card()
        self._report_card = self._build_report_card()
        main_layout.addWidget(self._details_card)
        main_layout.addWidget(self._report_card, stretch=1)

        # Initially no file loaded — show empty state, hide details + report
        self._empty_state.setVisible(True)
        self._details_card.setVisible(False)
        self._report_card.setVisible(False)

        self.status_lbl = QLabel("Ready — scan a folder or browse directly to a single .fsa file.")
        self.status_lbl.setStyleSheet("color: #64748b; font-weight: 500;")
        main_layout.addWidget(self.status_lbl)

        self._load_defaults()

    def set_operation_coordinator(self, coordinator) -> None:
        """Attach the application worker lifecycle coordinator."""
        self._operation_coordinator = coordinator

    def _start_registered_worker(self, worker: Worker, *, kind: str, restore_ui,
                                 critical_write: bool = False) -> bool:
        handle = None
        if self._operation_coordinator is not None:
            try:
                # These workers have no safe in-flight interruption boundary.
                handle = self._operation_coordinator.register(kind, cancel=lambda: None)
            except OperationStartRejected:
                restore_ui()
                self._set_status("Application is closing; Ladder work was not started.", error=True)
                return False
            worker.signals.finished.connect(handle.settle)
            handle.mark_running()
            if critical_write:
                handle.mark_critical_write()
        try:
            self.threadpool.start(worker)
        except Exception as exc:
            if handle is not None:
                handle.settle()
            restore_ui()
            self._set_status(f"Ladder work could not start: {exc}", error=True)
            return False
        return True

    def _restore_single_rerun_ui(self) -> None:
        self._single_rerun_active = False
        self._set_rerun_context_locked(False)
        self.btn_rerun_file.setEnabled(self._current_file is not None)
        self.btn_open_editor.setEnabled(self._current_file is not None and not self._metadata_loading)
        self.btn_refresh_meta.setEnabled(self._current_file is not None)

    def _restore_bundle_rerun_ui(self) -> None:
        self._review_bundle_rerun_active = False
        self._set_rerun_context_locked(False)
        self.btn_rerun_file.setEnabled(self._current_file is not None)
        self.btn_open_editor.setEnabled(self._current_file is not None and not self._metadata_loading)
        self.btn_refresh_meta.setEnabled(self._current_file is not None)
        self._refresh_review_bundle_run_button()

    def _restore_metadata_load_ui(self) -> None:
        self._metadata_loading = False
        self._metadata_request_context = None
        self._pending_open_editor_after_metadata = False
        self.btn_open_editor.setEnabled(self._current_file is not None)

    def _build_source_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)

        title = QLabel("SOURCE FILES")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        row1 = QHBoxLayout()
        self.source_dir = QLineEdit()
        self.source_dir.setPlaceholderText("/path/to/folder with .fsa files")
        self.btn_browse_dir = QPushButton("Browse Folder...")
        self.btn_browse_dir.clicked.connect(self._choose_source_dir)
        self.btn_scan = QPushButton("Scan .fsa Files")
        self.btn_scan.clicked.connect(self._scan_files)
        self.btn_browse_file = QPushButton("Open Single File...")
        self.btn_browse_file.clicked.connect(self._choose_single_file)
        row1.addWidget(QLabel("Input Folder:"))
        row1.addWidget(self.source_dir, stretch=1)
        row1.addWidget(self.btn_browse_dir)
        row1.addWidget(self.btn_scan)
        row1.addWidget(self.btn_browse_file)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.file_filter = QLineEdit()
        self.file_filter.setPlaceholderText("Filter by filename, DIT, assay, plate position...")
        self.file_filter.textChanged.connect(self._rebuild_file_list)
        row2.addWidget(QLabel("Filter:"))
        row2.addWidget(self.file_filter, stretch=1)
        layout.addLayout(row2)

        self.btn_toggle_review_bundle = QPushButton("Review bundle options…")
        self.btn_toggle_review_bundle.setObjectName("SecondaryButton")
        self.btn_toggle_review_bundle.setCheckable(True)
        self.btn_toggle_review_bundle.setToolTip(
            "Show optional controls for loading and rerunning a ladder review bundle."
        )
        self.btn_toggle_review_bundle.toggled.connect(
            self._set_review_bundle_options_visible
        )
        layout.addWidget(self.btn_toggle_review_bundle, alignment=Qt.AlignmentFlag.AlignLeft)

        self.review_bundle_options = QWidget()
        self.review_bundle_options.setObjectName("ReviewBundleOptions")
        review_layout = QVBoxLayout(self.review_bundle_options)
        review_layout.setContentsMargins(0, 0, 0, 0)
        row3 = QHBoxLayout()
        self.review_bundle_dir = QLineEdit()
        self.review_bundle_dir.setPlaceholderText("/optional/path/to/review bundle with ladder_review_cases.csv")
        self.btn_browse_bundle = QPushButton("Browse Bundle...")
        self.btn_browse_bundle.clicked.connect(self._choose_review_bundle)
        self.btn_load_bundle = QPushButton("Load Review Bundle")
        self.btn_load_bundle.clicked.connect(self._load_review_bundle)
        self.btn_load_bundle.setEnabled(False)
        self.review_bundle_dir.textChanged.connect(self._update_bundle_load_button)
        self.btn_rerun_review_bundle = QPushButton("Run Reviewed Files + Reports")
        self.btn_rerun_review_bundle.setToolTip(
            "Rerun files marked as manually adjusted or reviewed, then rebuild their reports."
        )
        self.btn_rerun_review_bundle.clicked.connect(self._rerun_review_bundle_reports)
        self.btn_rerun_review_bundle.setEnabled(False)
        row3.addWidget(QLabel("Review Bundle:"))
        row3.addWidget(self.review_bundle_dir, stretch=1)
        row3.addWidget(self.btn_browse_bundle)
        row3.addWidget(self.btn_load_bundle)
        row3.addWidget(self.btn_rerun_review_bundle)
        review_layout.addLayout(row3)

        self.review_progress_label = QLabel("Reviewed 0 / 0 — Remaining 0")
        self.review_progress_label.setObjectName("PageSubtitle")
        review_layout.addWidget(self.review_progress_label)

        # Phase 12.3 — chip-strip overview above the file list.
        # One chip per loaded bundle case (reviewed/needs_review/
        # file_unreachable/untouched). Click a chip to select that
        # file in the list below.
        from gui_qt.tabs.tab_ladder._overview import ChipStripOverview

        self._chip_strip = ChipStripOverview(parent=card)
        self._chip_strip.chipActivated.connect(self._on_chip_activated)
        self._chip_strip.chipLocateRequested.connect(self._on_locate_file)
        review_layout.addWidget(self._chip_strip)
        self.review_bundle_options.setVisible(False)
        layout.addWidget(self.review_bundle_options)

        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(220)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_list.itemSelectionChanged.connect(self._on_file_selected)
        self.file_list.itemDoubleClicked.connect(lambda _: self._open_ladder_editor())
        layout.addWidget(self.file_list)

        return card

    def _set_review_bundle_options_visible(self, visible: bool) -> None:
        self.review_bundle_options.setVisible(visible)
        self.btn_toggle_review_bundle.setText(
            "Hide review bundle options" if visible else "Review bundle options…"
        )

    def _build_details_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)

        title = QLabel("SELECTED FILE")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        details = QGridLayout()
        details.setHorizontalSpacing(18)
        details.setVerticalSpacing(10)
        self.detail_labels: dict[str, QLabel] = {}

        fields = [
            ("file", "File"),
            ("assay", "Assay"),
            ("ladder", "Ladder"),
            ("fit_strategy", "Fit Strategy"),
            ("fit_counts", "Expected / Fitted"),
            ("review_state", "Review State"),
            ("confidence", "Candidate Confidence"),
            ("missing_steps", "Missing Steps"),
            ("adjustment", "Saved Adjustment"),
        ]

        for row, (key, label) in enumerate(fields):
            lbl_key = QLabel(f"{label}:")
            lbl_key.setStyleSheet("color: #64748b; font-weight: 700;")
            lbl_val = QLabel("—")
            lbl_val.setWordWrap(True)
            self.detail_labels[key] = lbl_val
            details.addWidget(lbl_key, row, 0, alignment=Qt.AlignmentFlag.AlignTop)
            details.addWidget(lbl_val, row, 1)

        layout.addLayout(details)

        actions = QHBoxLayout()
        self.btn_refresh_meta = QPushButton("Refresh Metadata")
        self.btn_refresh_meta.clicked.connect(self._refresh_current_metadata)
        self.btn_open_editor = QPushButton("Open Ladder Editor")
        self.btn_open_editor.setObjectName("PrimaryButton")
        self.btn_open_editor.clicked.connect(self._open_ladder_editor)
        self.btn_exclude_missing_ladder = QPushButton("No ladder / human error")
        self.btn_exclude_missing_ladder.clicked.connect(
            self._exclude_current_missing_ladder_signal
        )
        self.btn_rerun_file = QPushButton("Run This File + Reports")
        self.btn_rerun_file.clicked.connect(self._rerun_current_file_reports)
        self.btn_remove_adjustment = QPushButton("Remove Saved Adjustment")
        self.btn_remove_adjustment.clicked.connect(self._remove_saved_adjustment)
        self.btn_open_file_folder = QPushButton("Open File Folder")
        self.btn_open_file_folder.clicked.connect(self._open_file_folder)

        for btn in [self.btn_refresh_meta, self.btn_open_editor,
                    self.btn_exclude_missing_ladder, self.btn_rerun_file,
                    self.btn_remove_adjustment, self.btn_open_file_folder]:
            btn.setEnabled(False)
            actions.addWidget(btn)
        actions.addStretch()
        layout.addLayout(actions)

        hint = QLabel(
            "Tip: double-click a file to jump straight into the ladder editor. "
            "Inside the editor you can re-map peaks, preview the fit, and save the adjustment for re-runs."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b;")
        layout.addWidget(hint)
        return card

    def _build_report_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)

        title = QLabel("MATCHING REPORTS")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        row1 = QHBoxLayout()
        self.report_root = QLineEdit()
        self.report_root.setPlaceholderText("/optional/path/to/report root")
        btn_browse = QPushButton("Browse Reports...")
        btn_browse.clicked.connect(self._choose_report_root)
        self.btn_find_reports = QPushButton("Find Matching Reports")
        self.btn_find_reports.clicked.connect(self._refresh_report_matches)
        row1.addWidget(QLabel("Report Root:"))
        row1.addWidget(self.report_root, stretch=1)
        row1.addWidget(btn_browse)
        row1.addWidget(self.btn_find_reports)
        layout.addLayout(row1)

        self.report_list = QListWidget()
        self.report_list.itemDoubleClicked.connect(self._open_selected_report)
        layout.addWidget(self.report_list)

        row2 = QHBoxLayout()
        self.btn_open_report = QPushButton("Open Selected Report")
        self.btn_open_report.clicked.connect(self._open_selected_report)
        self.btn_open_report_folder = QPushButton("Open Report Folder")
        self.btn_open_report_folder.clicked.connect(self._open_selected_report_folder)
        self.btn_open_report.setEnabled(False)
        self.btn_open_report_folder.setEnabled(False)
        row2.addWidget(self.btn_open_report)
        row2.addWidget(self.btn_open_report_folder)
        row2.addStretch()
        layout.addLayout(row2)

        self.report_list.itemSelectionChanged.connect(self._update_report_buttons)
        return card

    def _load_defaults(self) -> None:
        profile = get_analysis_settings(self._current_analysis_id)
        input_dir = profile.get("batch", {}).get("base_input_dir", "")
        output_dir = profile.get("batch", {}).get("output_base", "")

        if input_dir:
            self.source_dir.setText(input_dir)
        elif self._current_analysis_id == "clonality":
            for default_source in (Path("data/Euroclonality"), Path("data/euroclonality"), Path("data/kontroll")):
                if default_source.exists():
                    self.source_dir.setText(str(default_source))
                    break

        if output_dir:
            self.report_root.setText(output_dir)
        elif Path("final").exists():
            self.report_root.setText("final")

    def set_analysis(self, analysis_id: str) -> bool:
        if self.is_operation_active():
            self._set_status(
                "A ladder rerun is active. Wait for it to finish before changing analysis.",
                error=True,
            )
            return False

        previous_profile = get_analysis_settings(self._current_analysis_id)
        next_profile = get_analysis_settings(analysis_id)

        previous_input = previous_profile.get("batch", {}).get("base_input_dir", "")
        previous_output = previous_profile.get("batch", {}).get("output_base", "")

        if not self.source_dir.text().strip() or self.source_dir.text().strip() == previous_input:
            self.source_dir.setText(next_profile.get("batch", {}).get("base_input_dir", ""))
        if not self.report_root.text().strip() or self.report_root.text().strip() == previous_output:
            self.report_root.setText(next_profile.get("batch", {}).get("output_base", ""))

        analysis_changed = analysis_id != self._current_analysis_id
        self._current_analysis_id = analysis_id
        if analysis_changed:
            self._invalidate_source_request()
            self._invalidate_metadata_request()
            self._review_runtime_cache = {}
        self._current_meta = None
        self._current_fsa = None
        self._clear_details()
        self.btn_open_editor.setEnabled(False)
        self.btn_rerun_file.setEnabled(False)
        self.btn_remove_adjustment.setEnabled(False)
        self.btn_exclude_missing_ladder.setEnabled(False)
        self.btn_refresh_meta.setEnabled(self._current_file is not None)
        if self._current_file:
            self._set_status(
                f"Analysis switched to {analysis_id}. Refresh metadata to re-evaluate the current file."
            )
        return True

    @staticmethod
    def _format_file_item(file_path: Path, case: dict | None) -> str:
        # Phase 12.1 — delegate to the pure-Python helper module.
        from gui_qt.tabs.tab_ladder._summary import format_file_item

        return format_file_item(file_path, case)

    def _choose_source_dir(self) -> None:
        if self._reject_context_switch_during_rerun():
            return
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder With .fsa Files",
            self.source_dir.text() or str(Path.home()),
        )
        if folder:
            self.source_dir.setText(folder)

    def _choose_report_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Report Root",
            self.report_root.text() or str(Path.home()),
        )
        if folder:
            self.report_root.setText(folder)
            self._refresh_report_matches()

    def _choose_review_bundle(self) -> None:
        if self._reject_context_switch_during_rerun():
            return
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Review Bundle Folder",
            self.review_bundle_dir.text() or str(Path.home()),
        )
        if folder:
            self.load_review_bundle_from_path(folder)

    def _choose_single_file(self) -> None:
        if self._reject_context_switch_during_rerun():
            return
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open .fsa File",
            self.source_dir.text() or str(Path.home()),
            "FSA files (*.fsa)",
        )
        if file_name:
            file_path = Path(file_name)
            if file_path.parent.exists():
                self.source_dir.setText(str(file_path.parent))
            if file_path not in self._all_files:
                self._all_files.append(file_path)
                self._all_files.sort(key=lambda p: p.name.lower())
            self._rebuild_file_list()
            self._select_file(file_path)

    def _scan_files(self) -> None:
        if self._reject_context_switch_during_rerun():
            return
        if self._reject_concurrent_source_load():
            return
        source = Path(self.source_dir.text().strip()).expanduser()
        if not source.exists() or not source.is_dir():
            self._set_status("Input folder does not exist.", error=True)
            return

        self._scan_request_id += 1
        request_id = self._scan_request_id
        self._set_source_load_active(True)
        self._set_status(f"Scanning {source} for .fsa files...")

        worker = Worker(self._scan_fsa_files_worker, source)
        worker.signals.result.connect(lambda files, rid=request_id, src=source: self._on_scan_result(rid, src, files))
        worker.signals.error.connect(lambda err, rid=request_id: self._on_scan_error(rid, err))
        self._start_registered_worker(
            worker, kind="Ladder source scan",
            restore_ui=lambda: self._set_source_load_active(False),
        )

    def _load_review_bundle(self) -> None:
        if self._reject_context_switch_during_rerun():
            return
        if self._reject_concurrent_source_load():
            return
        bundle_dir = Path(self.review_bundle_dir.text().strip()).expanduser()
        if not bundle_dir.exists() or not bundle_dir.is_dir():
            self._set_status("Review bundle folder does not exist.", error=True)
            return

        self._scan_request_id += 1
        request_id = self._scan_request_id
        self._set_source_load_active(True)
        self.btn_rerun_review_bundle.setEnabled(False)
        self._set_status(f"Loading review bundle from {bundle_dir.name}...")

        worker = Worker(self._load_review_bundle_worker, bundle_dir)
        worker.signals.result.connect(lambda result, rid=request_id: self._on_review_bundle_result(rid, result))
        worker.signals.error.connect(lambda err, rid=request_id: self._on_review_bundle_error(rid, err))
        self._start_registered_worker(
            worker, kind="Ladder review-bundle load",
            restore_ui=lambda: (self._set_source_load_active(False), self._refresh_review_bundle_run_button()),
        )

    def load_review_bundle_from_path(
        self,
        bundle_dir: Path | str,
        *,
        preloaded_entries: list[dict] | None = None,
        auto_open_first: bool = False,
    ) -> None:
        if self._reject_context_switch_during_rerun():
            return
        if self._reject_concurrent_source_load():
            return
        bundle_path = Path(bundle_dir).expanduser()
        if bundle_path.is_file():
            bundle_path = bundle_path.parent
        review_case_paths = self._review_case_paths_from_bundle(bundle_path)
        self._set_review_session_entries(preloaded_entries or [])
        self._set_review_runtime_cache(preloaded_entries or [], review_case_paths)
        self._recent_reviewed_files.clear()
        self._auto_open_review_editor_once = bool(auto_open_first)
        self.btn_toggle_review_bundle.setChecked(True)
        self.review_bundle_dir.setText(str(bundle_path))
        self._load_review_bundle()

    def _rebuild_file_list(self) -> None:
        active_path = self._current_file
        text = self.file_filter.text().strip().lower()
        self.file_list.clear()

        matches = []
        for path in self._all_files:
            case = self._review_case_by_path.get(self._resolve_cache_key(path))
            display_text = self._format_file_item(path, case)
            haystack = f"{path} {display_text}".lower()
            if text and text not in haystack:
                continue
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.file_list.addItem(item)
            matches.append(path)

        if matches and active_path in matches:
            self._select_file(active_path)
        elif matches and self.file_list.currentRow() < 0:
            self.file_list.setCurrentRow(0)
        else:
            self._update_current_file(None)

    def _select_file(self, file_path: Path) -> None:
        file_str = str(file_path)
        for idx in range(self.file_list.count()):
            item = self.file_list.item(idx)
            if item.data(Qt.ItemDataRole.UserRole) == file_str:
                self.file_list.setCurrentItem(item)
                return

    def _on_file_selected(self) -> None:
        items = self.file_list.selectedItems()
        if not items:
            self._update_current_file(None)
            return
        self._update_current_file(Path(items[0].data(Qt.ItemDataRole.UserRole)))

    def _update_current_file(self, file_path: Path | None) -> None:
        if file_path != self._current_file and self._reject_context_switch_during_rerun():
            self.file_list.blockSignals(True)
            try:
                if self._current_file is not None:
                    self._select_file(self._current_file)
                else:
                    self.file_list.clearSelection()
            finally:
                self.file_list.blockSignals(False)
            return
        self._current_file = file_path
        self._current_meta = None
        self._current_fsa = None
        self._clear_details()

        enabled = file_path is not None
        review_case = (
            self._review_case_by_path.get(self._resolve_cache_key(file_path))
            if enabled and self._review_bundle_dir is not None
            else None
        )
        exclusion_enabled = bool(
            review_case is not None
            and not str(review_case.get("label") or "").strip()
            and not str(review_case.get("adjustment_path") or "").strip()
        )
        self.btn_refresh_meta.setEnabled(enabled)
        self.btn_open_file_folder.setEnabled(enabled)
        for btn in (self.btn_open_editor, self.btn_rerun_file, self.btn_remove_adjustment):
            btn.setEnabled(False)
        self.btn_exclude_missing_ladder.setEnabled(exclusion_enabled)

        self._empty_state.setVisible(not enabled)
        self._details_card.setVisible(enabled)
        self._report_card.setVisible(enabled)

        if not file_path:
            self.report_list.clear()
            self._report_matches = []
            self._update_report_buttons()
            return

        self.detail_labels["file"].setText(str(file_path))
        self._refresh_current_metadata()
        self._refresh_report_matches()

    def _refresh_current_metadata(self) -> None:
        if not self._current_file:
            return

        self.detail_labels["file"].setText(str(self._current_file))
        self.detail_labels["assay"].setText("Loading...")
        self.detail_labels["ladder"].setText("Loading...")
        self.detail_labels["adjustment"].setText("Loading...")
        self.detail_labels["fit_strategy"].setText("Loading...")
        self.detail_labels["fit_counts"].setText("—")
        self.detail_labels["review_state"].setText("—")
        self.detail_labels["confidence"].setText("—")
        self.detail_labels["missing_steps"].setText("—")
        cached = self._cached_review_payload_for(self._current_file)
        if cached:
            self._metadata_request_id += 1
            self._metadata_request_context = None
            self._metadata_loading = False
            self._apply_metadata_result(
                {
                    "file_path": self._current_file,
                    "meta": copy.deepcopy(cached["meta"]),
                    "fsa": cached["fsa"],
                    "from_cache": True,
                }
            )
            self._maybe_auto_open_review_editor(self._current_file)
            return
        self._start_metadata_load(self._current_file)

    def _clear_details(self) -> None:
        for label in self.detail_labels.values():
            label.setText("—")

    @staticmethod
    def _resolve_cache_key(file_path: Path) -> Path:
        # Phase 12.1 — delegate to the pure-Python helper module.
        from gui_qt.tabs.tab_ladder._summary import resolve_cache_key

        return resolve_cache_key(file_path)

    @staticmethod
    def _entry_original_path(entry: dict) -> Path | None:
        # Phase 12.1 — delegate.
        from gui_qt.tabs.tab_ladder._summary import entry_original_path

        return entry_original_path(entry)

    @staticmethod
    def _metadata_from_entry(file_path: Path, entry: dict) -> dict:
        # Phase 12.1 — delegate.
        from gui_qt.tabs.tab_ladder._summary import metadata_from_entry

        return metadata_from_entry(file_path, entry)

    @classmethod
    def _entry_cache_key(cls, entry: dict) -> Path | None:
        # Phase 12.1 — delegate.
        from gui_qt.tabs.tab_ladder._summary import entry_cache_key

        return entry_cache_key(entry)

    @staticmethod
    def _review_case_paths_from_bundle(bundle_dir: Path) -> set[Path]:
        # Phase 12.1 — delegate.
        from gui_qt.tabs.tab_ladder._io import review_case_paths_from_bundle

        return review_case_paths_from_bundle(bundle_dir)

    def _set_review_runtime_cache(
        self,
        entries: list[dict],
        review_case_paths: set[Path] | None = None,
    ) -> None:
        self._review_runtime_cache = {}
        if not entries:
            return

        review_case_paths = review_case_paths or set()
        entries_by_name: dict[str, list[tuple[Path, dict]]] = {}

        def cache_entry(cache_key: Path, entry: dict) -> None:
            fsa = entry.get("fsa")
            if fsa is None:
                return
            cached_fsa = copy.deepcopy(fsa)
            try:
                cached_fsa.file = str(cache_key)
                cached_fsa.file_name = cache_key.name
            except Exception:
                pass
            self._review_runtime_cache[cache_key] = {
                "fsa": cached_fsa,
                "meta": self._metadata_from_entry(cache_key, entry),
            }

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            fsa = entry.get("fsa")
            if fsa is None:
                continue
            original_path = self._entry_original_path(entry)
            if original_path is None:
                continue
            cache_key = self._resolve_cache_key(original_path)
            entries_by_name.setdefault(cache_key.name, []).append((cache_key, entry))
            if review_case_paths and cache_key not in review_case_paths:
                continue
            cache_entry(cache_key, entry)

        if not review_case_paths:
            return

        # Some batch inputs pass through staging paths; use file-name fallback only
        # when there is exactly one already-analyzed entry with the same raw name.
        for review_path in review_case_paths:
            if review_path in self._review_runtime_cache:
                continue
            matches = entries_by_name.get(review_path.name, [])
            if len(matches) != 1:
                continue
            _source_key, entry = matches[0]
            cache_entry(review_path, entry)

    def _set_review_session_entries(self, entries: list[dict]) -> None:
        self._review_session_entries_by_path = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cache_key = self._entry_cache_key(entry)
            if cache_key is None:
                continue
            self._review_session_entries_by_path[cache_key] = entry

    def _cached_review_payload_for(self, file_path: Path) -> dict | None:
        return self._review_runtime_cache.get(self._resolve_cache_key(file_path))

    def _open_ladder_editor(self) -> None:
        if not self._current_file:
            return

        if self._metadata_loading:
            self._pending_open_editor_after_metadata = True
            self._set_status(f"Metadata is loading for {self._current_file.name}; editor will open automatically.")
            return
        if self._current_meta is None or self._current_fsa is None:
            self._pending_open_editor_after_metadata = True
            self._refresh_current_metadata()
            self._set_status(f"Loading ladder metadata for {self._current_file.name}; editor will open automatically.")
            return

        fsa = copy.deepcopy(self._current_fsa)
        review_case = self._review_case_by_path.get(self._resolve_cache_key(self._current_file))
        review_comment = ""
        if review_case:
            review_comment = str(review_case.get("label_note", "") or "")
        initial_adjustment = load_ladder_adjustment(fsa)
        dialog = _open_ladder_adjustment_dialog(
            fsa,
            self,
            review_context=review_case,
            review_comment=review_comment,
            initial_adjustment=initial_adjustment,
        )
        if dialog.exec():
            review_payload = dialog.get_review_payload()
            if review_payload.get("action") != "note_only":
                adjustment = dialog.get_adjustment_payload()
                try:
                    saved_path = save_ladder_adjustment(
                        fsa,
                        adjustment,
                        operator=str(
                            APP_SETTINGS.get("general", {}).get("author", "") or ""
                        ),
                        comment=str(review_payload.get("comment", "") or ""),
                        before_qc={
                            "linear_max": review_payload.get("linear_max"),
                            "linear_mean": review_payload.get("linear_mean"),
                            "linear_r2": review_payload.get("linear_r2"),
                        },
                        after_qc=dict(review_payload.get("after_qc") or {}),
                        partial_approved=bool(
                            review_payload.get("partial_approved", False)
                        ),
                    )
                    if load_ladder_adjustment(fsa) is None:
                        raise RuntimeError(f"Saved adjustment could not be loaded from {saved_path}.")
                    review_payload["adjustment_path"] = str(saved_path)
                except Exception as exc:
                    self._set_status(
                        f"Could not save ladder adjustment for {self._current_file.name}: {exc}",
                        error=True,
                    )
                    QMessageBox.critical(
                        self,
                        "Adjustment Not Saved",
                        (
                            "The ladder correction was not saved, so this review case remains unresolved.\n\n"
                            f"{exc}"
                        ),
                    )
                    return
                preview_fsa = getattr(dialog, "_preview_fsa", None)
                if preview_fsa is not None:
                    cache_key = self._resolve_cache_key(self._current_file)
                    cached_preview = copy.deepcopy(preview_fsa)
                    try:
                        cached_preview.file = str(cache_key)
                        cached_preview.file_name = cache_key.name
                    except Exception:
                        pass
                    if bool(
                        adjustment.get("partial_mapping")
                        and review_payload.get("partial_approved", False)
                    ):
                        cached_preview.manual_ladder_partial_approved = True
                        cached_preview.ladder_review_required = False
                        cached_preview.ladder_qc_status = "manual_partial_reviewed"
                    self._review_runtime_cache[cache_key] = {
                        "fsa": cached_preview,
                        "meta": copy.deepcopy(self._current_meta or {}),
                    }
            if review_case and self._review_bundle_dir is not None:
                try:
                    self._save_review_bundle_annotation(review_case, review_payload)
                except Exception as exc:
                    adjustment_saved = bool(
                        review_payload.get("action") != "note_only"
                        and review_payload.get("adjustment_path")
                    )
                    if adjustment_saved:
                        detail = (
                            f"The ladder adjustment was saved for {self._current_file.name}, "
                            "but the review bundle was not saved. The review case remains "
                            f"unresolved: {exc}"
                        )
                    else:
                        detail = (
                            f"The review bundle was not saved for {self._current_file.name}. "
                            f"The review case remains unresolved: {exc}"
                        )
                    self._set_status(detail, error=True)
                    QMessageBox.critical(
                        self,
                        "Review Bundle Not Saved",
                        detail,
                    )
                    return
            self._refresh_current_metadata()
            if review_payload.get("action") == "save_draft":
                self._set_status(
                    f"Saved ladder draft for {self._current_file.name}. Add at least 3 anchors before rerunning."
                )
                return
            if review_payload.get("action") == "note_only":
                self._set_status(f"Saved review note for {self._current_file.name}.")
                if self._is_run_tab_owned_review():
                    message = QMessageBox(self)
                    message.setIcon(QMessageBox.Icon.Information)
                    message.setWindowTitle("Review Saved")
                    message.setText(f"Review saved for {self._current_file.name}.")
                    message.setInformativeText(
                        "Return to Run and use Run Manual Fixes + Build DIT when review is complete."
                    )
                    back_btn = message.addButton("Back To Run", QMessageBox.ButtonRole.AcceptRole)
                    message.addButton("Stay Here", QMessageBox.ButtonRole.RejectRole)
                    message.exec()
                    if message.clickedButton() == back_btn:
                        self._return_to_run_tab_for_review()
                else:
                    QMessageBox.information(
                        self,
                        "Review Note Saved",
                        f"Review note saved for {self._current_file.name}.",
                    )
            else:
                self._set_status(
                    f"Saved ladder adjustment for {self._current_file.name}. Re-run the analysis to use the new fit."
                )
                if self._is_run_tab_owned_review():
                    message = QMessageBox(self)
                    message.setIcon(QMessageBox.Icon.Information)
                    message.setWindowTitle("Adjustment Saved")
                    message.setText(f"Ladder adjustment saved for {self._current_file.name}.")
                    message.setInformativeText(
                        "Return to Run and use Run Manual Fixes + Build DIT so the linked patient/job group is rerun."
                    )
                    back_btn = message.addButton("Back To Run", QMessageBox.ButtonRole.AcceptRole)
                    message.addButton("Stay Here", QMessageBox.ButtonRole.RejectRole)
                    message.exec()
                    if message.clickedButton() == back_btn:
                        self._return_to_run_tab_for_review()
                    return
                message = QMessageBox(self)
                message.setIcon(QMessageBox.Icon.Information)
                message.setWindowTitle("Adjustment Saved")
                message.setText(f"Ladder adjustment saved for {self._current_file.name}.")
                message.setInformativeText("Run this single file now to rebuild tracking/DIT reports with the saved ladder fit.")
                run_btn = message.addButton("Run This File Now", QMessageBox.ButtonRole.AcceptRole)
                message.addButton("Later", QMessageBox.ButtonRole.RejectRole)
                message.exec()
                if message.clickedButton() == run_btn:
                    self._rerun_current_file_reports()
        else:
            self._set_status(f"Closed ladder editor for {self._current_file.name}.")

    def _exclude_current_missing_ladder_signal(self) -> None:
        if self._current_file is None or self._review_bundle_dir is None:
            return

        cache_key = self._resolve_cache_key(self._current_file)
        if cache_key not in self._review_case_by_path:
            return

        reply = QMessageBox.question(
            self,
            "No Ladder / Human Error",
            (
                f"Mark {self._current_file.name} as excluded because it has no usable "
                "ladder signal? This resolves the review case without saving a ladder "
                "adjustment and will not rerun the file."
            ),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        note = "No usable ladder signal; preparation error."
        reviewed_at_utc = datetime.now(timezone.utc).isoformat()
        self.btn_exclude_missing_ladder.setEnabled(False)
        self._set_status(f"Saving no-ladder exclusion for {self._current_file.name}...")
        worker = Worker(
            self._save_missing_ladder_exclusion_worker,
            self._review_bundle_dir,
            cache_key,
            note=note,
            reviewed_at_utc=reviewed_at_utc,
        )
        worker.signals.result.connect(
            lambda annotation, key=cache_key: self._on_missing_ladder_exclusion_saved(
                key, annotation
            )
        )
        worker.signals.error.connect(
            lambda err, key=cache_key: self._on_missing_ladder_exclusion_error(
                key, err
            )
        )
        self._start_registered_worker(
            worker, kind="Ladder missing-ladder exclusion",
            restore_ui=lambda: self.btn_exclude_missing_ladder.setEnabled(True),
            critical_write=True,
        )

    def _on_missing_ladder_exclusion_saved(
        self, cache_key: Path, annotation: dict
    ) -> None:
        review_case = self._review_case_by_path.get(cache_key)
        if review_case is not None:
            review_case.update(annotation)
        for row in self._review_bundle_cases:
            try:
                if self._resolve_cache_key(Path(str(row.get("full_path", "") or ""))) != cache_key:
                    continue
            except Exception:
                continue
            row.update(annotation)
            break
        self._recent_reviewed_files.discard(cache_key)
        self._review_session_entries_by_path.pop(cache_key, None)
        self._manual_rerun_consumption_by_path.pop(cache_key, None)
        tab_run = self._run_tab_for_review()
        if tab_run is not None and hasattr(
            tab_run, "unregister_ladder_review_update"
        ):
            tab_run.unregister_ladder_review_update(cache_key)
        self._sync_chip_strip()
        self._rebuild_file_list()
        if self._current_file is not None:
            self._select_file(self._current_file)
        self._refresh_review_bundle_run_button()
        self._set_status(f"Excluded {cache_key.name}: no usable ladder signal.")

    def _on_missing_ladder_exclusion_error(self, cache_key: Path, err_tuple) -> None:
        if self._current_file is not None and self._resolve_cache_key(self._current_file) == cache_key:
            review_case = self._review_case_by_path.get(cache_key) or {}
            self.btn_exclude_missing_ladder.setEnabled(
                not str(review_case.get("label") or "").strip()
                and not str(review_case.get("adjustment_path") or "").strip()
            )
        self._set_status(
            f"Could not save no-ladder exclusion for {cache_key.name}: {err_tuple[1]}",
            error=True,
        )
        QMessageBox.critical(
            self,
            "No-Ladder Exclusion Not Saved",
            f"The review case remains unresolved.\n\n{err_tuple[1]}",
        )

    def is_operation_active(self) -> bool:
        return self._single_rerun_active or self._review_bundle_rerun_active

    def _reject_context_switch_during_rerun(self) -> bool:
        if not self.is_operation_active():
            return False
        self._set_status(
            "A ladder rerun is active. Wait for it to finish before changing source, file, or review bundle.",
            error=True,
        )
        return True

    def _reject_concurrent_source_load(self) -> bool:
        if not self._source_load_active:
            return False
        self._set_status(
            "A source load is already active. Wait for it to finish before scanning or loading another review bundle.",
            error=True,
        )
        return True

    def _update_bundle_load_button(self, text: str | None = None) -> None:
        bundle_text = self.review_bundle_dir.text() if text is None else text
        source_controls_enabled = (
            not self._source_load_active and not self.is_operation_active()
        )
        self.btn_scan.setEnabled(source_controls_enabled)
        self.btn_load_bundle.setEnabled(
            bool(str(bundle_text).strip()) and source_controls_enabled
        )

    def _set_source_load_active(self, active: bool) -> None:
        self._source_load_active = active
        self._update_bundle_load_button()

    def _set_rerun_context_locked(self, locked: bool) -> None:
        for control in (
            self.source_dir,
            self.btn_browse_dir,
            self.btn_scan,
            self.btn_browse_file,
            self.file_list,
            self.btn_toggle_review_bundle,
            self.review_bundle_dir,
            self.btn_browse_bundle,
        ):
            control.setEnabled(not locked)
        if locked:
            self.btn_load_bundle.setEnabled(False)
        else:
            self._update_bundle_load_button()

    def _invalidate_metadata_request(self) -> None:
        self._metadata_request_id += 1
        self._metadata_request_context = None
        self._metadata_loading = False
        self._auto_open_review_editor_once = False
        self._pending_open_editor_after_metadata = False

    def _invalidate_source_request(self) -> None:
        self._scan_request_id += 1
        self._set_source_load_active(False)

    def _invalidate_context_requests_for_rerun(self) -> None:
        """Make every earlier context-loading callback stale before rerun starts."""
        self._invalidate_source_request()
        self._report_request_id += 1
        self._invalidate_metadata_request()

    def _remove_saved_adjustment(self) -> None:
        if not self._current_file:
            return
        if self.is_operation_active():
            self._set_status("Wait for the active ladder rerun before removing an adjustment.", error=True)
            return
        if self._current_fsa is None or self._metadata_loading:
            self._set_status("Load the selected file's ladder metadata before removing its adjustment.", error=True)
            return
        fsa = self._current_fsa
        try:
            existing = load_ladder_adjustment(fsa)
        except Exception as exc:
            self._set_status(f"Could not inspect ladder adjustment: {exc}", error=True)
            return
        if existing is None:
            QMessageBox.information(self, "No Adjustment", "There is no saved ladder adjustment for this file.")
            return

        reply = QMessageBox.question(
            self,
            "Remove Adjustment",
            f"Deactivate the saved ladder adjustment for {self._current_file.name}? Identical source copies share this adjustment.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            deactivate_ladder_adjustment(fsa)
        except Exception as exc:
            self._set_status(f"Could not remove ladder adjustment for {self._current_file.name}: {exc}", error=True)
            QMessageBox.critical(self, "Adjustment Not Removed", str(exc))
            return
        cache_key = self._resolve_cache_key(self._current_file)
        self._review_runtime_cache.pop(cache_key, None)
        self._manual_rerun_consumption_by_path.pop(cache_key, None)
        self._recent_reviewed_files.discard(cache_key)
        self._review_session_entries_by_path.pop(cache_key, None)
        review_case = self._review_case_by_path.get(cache_key)
        review_error = None
        if review_case is not None:
            if self._review_bundle_dir is not None:
                try:
                    self._save_review_bundle_annotation_worker(
                        self._review_bundle_dir, cache_key,
                        {"label": "", "label_note": "", "adjustment_path": "", "rerun_status": ""},
                    )
                except Exception as exc:
                    review_error = exc
            for row in (review_case, *self._review_bundle_cases):
                if row is review_case or self._resolve_cache_key(Path(str(row.get("full_path") or ""))) == cache_key:
                    for field in ("label", "label_note", "adjustment_path", "rerun_status"):
                        row[field] = ""
        tab_run = self._run_tab_for_review()
        if tab_run is not None and hasattr(tab_run, "unregister_ladder_review_update"):
            tab_run.unregister_ladder_review_update(cache_key)
        self._sync_chip_strip()
        self._rebuild_file_list()
        self._refresh_review_bundle_run_button()
        self._refresh_current_metadata()
        if review_error is not None:
            self._set_status(f"Adjustment deactivated, but review state could not be saved: {review_error}", error=True)
        else:
            self._set_status(f"Removed saved ladder adjustment for {self._current_file.name}.")

    def _open_file_folder(self) -> None:
        if self._current_file:
            _open_path(self._current_file.parent)

    def _review_bundle_output_context(self) -> tuple[Path | None, str | None]:
        """Infer original batch output root/report folder from a loaded review bundle."""
        if self._review_bundle_dir is None:
            return None, None

        report_dir = self._review_bundle_dir.parent
        if report_dir.name.startswith("reports_") and report_dir.parent.exists():
            return report_dir.parent, report_dir.name
        return None, None

    def _resolve_rerun_settings(self, fallback_file_path: Path | None = None) -> dict | None:
        analysis_id = APP_SETTINGS.get("active_analysis", self._current_analysis_id)
        profile = get_analysis_settings(analysis_id)
        batch_settings = profile.get("batch", {})
        pipeline_settings = profile.get("pipeline", {})
        bundle_output_root, aggregate_outdir_name = self._review_bundle_output_context()

        output_text = self.report_root.text().strip() or str(batch_settings.get("output_base", "") or "")
        if (not output_text) and bundle_output_root is not None:
            output_text = str(bundle_output_root)
        if (not output_text) and fallback_file_path is not None:
            output_text = str(fallback_file_path.parent / "HemaFrag_single_file_reports")
        if not output_text:
            self._set_status("Report output folder is not set.", error=True)
            return None

        output_root = Path(output_text).expanduser()
        try:
            output_root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._set_status(f"Could not create output folder: {exc}", error=True)
            return None
        self.report_root.setText(str(output_root))

        return {
            "analysis_id": str(analysis_id),
            "output_root": output_root,
            "aggregate_outdir_name": aggregate_outdir_name,
            "aggregate_dit_reports": bool(batch_settings.get("aggregate_dit_reports", True)),
            "aggregate_by_patient": bool(batch_settings.get("aggregate_by_patient", True)),
            "patient_regex": str(batch_settings.get("patient_id_regex", r"\d{2}OUM\d{5}") or ""),
            "pipeline_scope": str(pipeline_settings.get("mode", "all") or "all"),
            "assay_filter": str(pipeline_settings.get("assay_filter_substring", "") or ""),
        }

    def _rerun_current_file_reports(self) -> None:
        if self.is_operation_active():
            self._set_status("A ladder rerun is already active.", error=True)
            return
        if not self._current_file:
            return
        file_path = self._current_file
        if not file_path.exists():
            self._set_status(f"Selected file no longer exists: {file_path}", error=True)
            return

        tab_run = self._run_tab_for_review()
        if tab_run is not None and hasattr(tab_run, "has_active_review_session_for"):
            if tab_run.has_active_review_session_for(file_path):
                QMessageBox.information(
                    self,
                    "Use Run Tab",
                    (
                        "This file belongs to the active batch review session. "
                        "Return to Run and use Run Manual Fixes + Build DIT so the linked patient/job group "
                        "is rerun and final DIT reports are built from the whole session."
                    ),
                )
                self._return_to_run_tab_for_review()
                return

        settings = self._resolve_rerun_settings(file_path)
        if settings is None:
            return

        self._invalidate_context_requests_for_rerun()
        self._single_rerun_request_id += 1
        request_id = self._single_rerun_request_id
        self._single_rerun_active = True
        self._set_rerun_context_locked(True)
        for btn in (self.btn_rerun_file, self.btn_open_editor, self.btn_refresh_meta):
            btn.setEnabled(False)
        self._set_status(f"Running single-file reports for {file_path.name}...")

        worker = Worker(
            self._single_file_rerun_worker,
            file_path,
            settings["output_root"],
            settings["analysis_id"],
            settings["pipeline_scope"],
            settings["assay_filter"],
            settings["aggregate_dit_reports"],
            settings["aggregate_by_patient"],
            settings["patient_regex"],
            settings["aggregate_outdir_name"],
            self._review_bundle_run_manifest_path,
        )
        worker.signals.result.connect(lambda result, rid=request_id: self._on_single_rerun_finished(rid, result))
        worker.signals.error.connect(lambda err, rid=request_id: self._on_single_rerun_error(rid, err))
        self._start_registered_worker(
            worker, kind="Ladder single-file rerun",
            restore_ui=self._restore_single_rerun_ui,
            critical_write=True,
        )

    @staticmethod
    def _single_file_rerun_worker(
        file_path: Path,
        output_root: Path,
        analysis_id: str,
        pipeline_scope: str,
        assay_filter: str,
        aggregate_dit_reports: bool,
        aggregate_by_patient: bool,
        patient_regex: str,
        aggregate_outdir_name: str | None,
        run_manifest_path: Path | None = None,
    ) -> dict:
        # Phase 12.1 — delegate to the worker module.
        from gui_qt.tabs.tab_ladder._workers import single_file_rerun_worker

        return single_file_rerun_worker(
            file_path,
            output_root,
            analysis_id,
            pipeline_scope,
            assay_filter,
            aggregate_dit_reports,
            aggregate_by_patient,
            patient_regex,
            aggregate_outdir_name,
            run_manifest_path,
        )

    def _review_bundle_counts(self) -> tuple[int, int]:
        resolved = 0
        unresolved = 0
        for row in self._review_bundle_cases:
            label = str(row.get("label", "") or "").strip()
            if is_review_resolved(label):
                resolved += 1
            else:
                unresolved += 1
        return resolved, unresolved

    def _review_bundle_rerun_counts(self) -> tuple[int, int]:
        """Return rerunnable cases and the rerunnable cases reviewed this session."""
        rerunnable = 0
        recent_rerunnable = 0
        for row in self._review_bundle_cases:
            if not is_review_rerunnable(row.get("label")):
                continue
            rerunnable += 1
            raw_path = str(row.get("full_path", "") or "").strip()
            cache_key = self._resolve_cache_key(Path(raw_path)) if raw_path else None
            if cache_key is not None and cache_key in self._recent_reviewed_files:
                recent_rerunnable += 1
        return rerunnable, recent_rerunnable

    def _refresh_review_bundle_run_button(self) -> None:
        if self._is_run_tab_owned_review():
            self.btn_rerun_review_bundle.setText("Back To Run: Build DIT")
            self.btn_rerun_review_bundle.setEnabled(True)
            return

        rerunnable, recent_ready = self._review_bundle_rerun_counts()
        ready_count = recent_ready or rerunnable
        self.btn_rerun_review_bundle.setEnabled(ready_count > 0)
        if recent_ready > 0:
            self.btn_rerun_review_bundle.setText(f"Run Recent Reviewed Files + Reports ({recent_ready})")
        elif rerunnable > 0:
            self.btn_rerun_review_bundle.setText(f"Run Reviewed Files + Reports ({rerunnable})")
        else:
            self.btn_rerun_review_bundle.setText("Run Reviewed Files + Reports")

    def _run_tab_for_review(self):
        window = self.window()
        tab_run = getattr(window, "tab_run", None)
        if tab_run is None:
            return None
        return tab_run

    def _is_run_tab_owned_review(self) -> bool:
        tab_run = self._run_tab_for_review()
        if tab_run is None or self._review_bundle_dir is None:
            return False
        if not bool(getattr(tab_run, "_review_session_active", False)):
            return False
        run_bundle = getattr(tab_run, "_review_session_bundle_dir", None)
        try:
            return Path(run_bundle).resolve() == self._review_bundle_dir.resolve()
        except Exception:
            return Path(run_bundle) == self._review_bundle_dir

    def _return_to_run_tab_for_review(self) -> bool:
        if not self._is_run_tab_owned_review():
            return False
        window = self.window()
        if hasattr(window, "on_sub_tab_clicked"):
            window.on_sub_tab_clicked(self._current_analysis_id, 0)
        return True

    def _resolved_review_bundle_files(self) -> tuple[list[Path], list[Path], int]:
        files: list[Path] = []
        missing: list[Path] = []
        unresolved = 0
        seen: set[Path] = set()

        for row in self._review_bundle_cases:
            label = str(row.get("label", "") or "").strip()
            if not is_review_resolved(label):
                unresolved += 1
                continue
            if not is_review_rerunnable(label):
                continue

            raw_path = str(row.get("full_path", "") or "").strip()
            if not raw_path:
                continue
            file_path = Path(raw_path).expanduser()
            try:
                resolved_path = file_path.resolve()
            except Exception:
                resolved_path = file_path

            cache_key = self._resolve_cache_key(file_path)
            if self._recent_reviewed_files and cache_key not in self._recent_reviewed_files:
                continue
            if not file_path.exists():
                missing.append(file_path)
                continue
            if resolved_path in seen:
                continue
            seen.add(resolved_path)
            files.append(file_path)

        return files, missing, unresolved

    def _rerun_review_bundle_reports(self) -> None:
        if self.is_operation_active():
            self._set_status("A ladder rerun is already active.", error=True)
            return
        if self._return_to_run_tab_for_review():
            return

        if not self._review_bundle_cases:
            self._set_status("Load a review bundle before rerunning reviewed files.", error=True)
            return

        file_paths, missing_paths, unresolved = self._resolved_review_bundle_files()
        if not file_paths:
            self._set_status("No reviewed/manual-adjusted files are ready for rerun.", error=True)
            QMessageBox.information(
                self,
                "No Reviewed Files",
                "Mark at least one review case as manually adjusted or reviewed before rerunning.",
            )
            return

        if unresolved:
            reply = QMessageBox.question(
                self,
                "Unresolved Review Cases",
                (
                    f"{unresolved} case(s) are still unresolved in this bundle.\n\n"
                    f"Run only the {len(file_paths)} reviewed file(s) now?"
                ),
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if missing_paths:
            QMessageBox.warning(
                self,
                "Missing Files Skipped",
                f"{len(missing_paths)} reviewed file(s) no longer exist and will be skipped.",
            )

        settings = self._resolve_rerun_settings(file_paths[0])
        if settings is None:
            return

        self._invalidate_context_requests_for_rerun()
        self._review_bundle_rerun_request_id += 1
        request_id = self._review_bundle_rerun_request_id
        self._review_bundle_rerun_active = True
        self._set_rerun_context_locked(True)
        for btn in (
            self.btn_rerun_review_bundle,
            self.btn_load_bundle,
            self.btn_rerun_file,
            self.btn_open_editor,
            self.btn_exclude_missing_ladder,
            self.btn_refresh_meta,
        ):
            btn.setEnabled(False)
        self._set_status(f"Running {len(file_paths)} reviewed file(s) and rebuilding reports...")

        worker = Worker(
            self._review_bundle_rerun_worker,
            file_paths,
            list(self._review_session_entries_by_path.values()),
            settings["output_root"],
            settings["analysis_id"],
            settings["pipeline_scope"],
            settings["assay_filter"],
            settings["aggregate_dit_reports"],
            settings["aggregate_by_patient"],
            settings["patient_regex"],
            settings["aggregate_outdir_name"],
            self._review_bundle_run_manifest_path,
        )
        worker.signals.result.connect(lambda result, rid=request_id: self._on_review_bundle_rerun_finished(rid, result))
        worker.signals.error.connect(lambda err, rid=request_id: self._on_review_bundle_rerun_error(rid, err))
        self._start_registered_worker(
            worker, kind="Ladder review-bundle rerun",
            restore_ui=self._restore_bundle_rerun_ui,
            critical_write=True,
        )

    @staticmethod
    def _review_bundle_rerun_worker(
        file_paths: list[Path],
        session_entries: list[dict],
        output_root: Path,
        analysis_id: str,
        pipeline_scope: str,
        assay_filter: str,
        aggregate_dit_reports: bool,
        aggregate_by_patient: bool,
        patient_regex: str,
        aggregate_outdir_name: str | None,
        run_manifest_path: Path | None = None,
    ) -> dict:
        """Phase 12.1 — body lives in `_workers.py`.

        Kept as a static method on the class so the GUI worker
        connection at line 997 (`Worker(self._review_bundle_rerun_worker, ...)`)
        keeps working unchanged. The body delegates to the helper.
        """
        from gui_qt.tabs.tab_ladder._workers import review_bundle_rerun_worker

        return review_bundle_rerun_worker(
            file_paths,
            session_entries,
            output_root,
            analysis_id,
            pipeline_scope,
            assay_filter,
            aggregate_dit_reports,
            aggregate_by_patient,
            patient_regex,
            aggregate_outdir_name,
            run_manifest_path,
        )

    def _on_single_rerun_finished(self, request_id: int, payload: dict) -> None:
        if request_id != self._single_rerun_request_id:
            return
        self._single_rerun_active = False
        self._set_rerun_context_locked(False)
        self.btn_rerun_file.setEnabled(self._current_file is not None)
        self.btn_open_editor.setEnabled(self._current_file is not None and not self._metadata_loading)
        self.btn_refresh_meta.setEnabled(self._current_file is not None)

        result = payload.get("result") or {}
        failed_jobs = result.get("failed_jobs", [])
        output_root = Path(payload.get("output_root"))
        matches = list(payload.get("matches") or [])
        file_path = Path(payload["file_path"])
        consumption = dict(payload.get("manual_adjustment_consumption") or {})
        self._manual_rerun_consumption_by_path[
            self._resolve_cache_key(file_path)
        ] = consumption
        self._refresh_current_metadata()
        self._refresh_report_matches()

        if failed_jobs:
            self._set_status(f"Single-file rerun finished with {len(failed_jobs)} failed job(s).", error=True)
            QMessageBox.warning(
                self,
                "Single File Rerun Failed",
                f"Rerun finished with failed job(s): {', '.join(map(str, failed_jobs))}",
            )
            return

        self._set_status(f"Single-file rerun complete for {file_path.name}.")

        gate = result.get("ladder_review_gate") or {}
        review_count = int(gate.get("review_case_count") or 0) if isinstance(gate, dict) else 0
        if review_count > 0:
            QMessageBox.warning(
                self,
                "Ladder Review Still Needed",
                f"The rerun completed, but {review_count} ladder review case(s) were still flagged.",
            )
            return
        if (
            consumption.get("adjustment_present")
            and not consumption.get("consumed")
        ):
            self._set_status(
                f"Rerun did not consume the saved correction for {file_path.name}.",
                error=True,
            )
            QMessageBox.warning(
                self,
                "Saved Correction Not Consumed",
                str(
                    consumption.get("reason")
                    or "The rerun did not use the saved manual correction."
                ),
            )
            return

        self.reportsRefreshed.emit(str(output_root))
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle("Single File Rerun Complete")
        if matches:
            message.setText(f"Built/updated reports for {Path(payload['file_path']).name}.")
            message.setInformativeText(f"Found {len(matches)} matching HTML report(s).")
            open_report_btn = message.addButton("Open Report", QMessageBox.ButtonRole.AcceptRole)
            open_folder_btn = message.addButton("Open Output Folder", QMessageBox.ButtonRole.ActionRole)
            message.addButton("Close", QMessageBox.ButtonRole.RejectRole)
            message.exec()
            clicked = message.clickedButton()
            if clicked == open_report_btn:
                _open_path(Path(matches[0]))
            elif clicked == open_folder_btn:
                _open_path(output_root)
        else:
            message.setText(f"Rerun complete for {Path(payload['file_path']).name}.")
            message.setInformativeText("No matching HTML report was found yet; tracking/workbook outputs may still have been updated.")
            open_folder_btn = message.addButton("Open Output Folder", QMessageBox.ButtonRole.AcceptRole)
            message.addButton("Close", QMessageBox.ButtonRole.RejectRole)
            message.exec()
            if message.clickedButton() == open_folder_btn:
                _open_path(output_root)

    def _on_single_rerun_error(self, request_id: int, err_tuple) -> None:
        if request_id != self._single_rerun_request_id:
            return
        self._single_rerun_active = False
        self._set_rerun_context_locked(False)
        self.btn_rerun_file.setEnabled(self._current_file is not None)
        self.btn_open_editor.setEnabled(self._current_file is not None and not self._metadata_loading)
        self.btn_refresh_meta.setEnabled(self._current_file is not None)
        self._set_status(f"Single-file rerun failed: {err_tuple[1]}", error=True)
        QMessageBox.critical(self, "Single File Rerun Failed", str(err_tuple[1]))

    def _on_review_bundle_rerun_finished(self, request_id: int, payload: dict) -> None:
        if request_id != self._review_bundle_rerun_request_id:
            return
        self._review_bundle_rerun_active = False
        self._set_rerun_context_locked(False)

        self.btn_load_bundle.setEnabled(True)
        self.btn_rerun_file.setEnabled(self._current_file is not None)
        self.btn_open_editor.setEnabled(self._current_file is not None and not self._metadata_loading)
        self.btn_refresh_meta.setEnabled(self._current_file is not None)
        self._refresh_review_bundle_run_button()
        self._sync_chip_strip()

        result = payload.get("result") or {}
        failed_jobs = result.get("failed_jobs", [])
        output_root = Path(payload.get("output_root"))
        file_paths = [Path(path) for path in payload.get("file_paths", [])]
        consumption_by_file = {
            str(path): dict(status)
            for path, status in (payload.get("consumption_by_file") or {}).items()
        }
        for raw_path, status in consumption_by_file.items():
            self._manual_rerun_consumption_by_path[
                self._resolve_cache_key(Path(raw_path))
            ] = status
        if self._review_bundle_dir is not None and consumption_by_file:
            from gui_qt.tabs.tab_ladder._io import (
                save_review_bundle_rerun_status_worker,
            )

            try:
                save_review_bundle_rerun_status_worker(
                    self._review_bundle_dir,
                    consumption_by_file,
                    run_manifest_path=(
                        Path(result["run_manifest_path"])
                        if result.get("run_manifest_path")
                        else None
                    ),
                    rerun_at_utc=datetime.now(timezone.utc).isoformat(),
                )
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Rerun Evidence Not Saved",
                    "The analysis finished, but Ladder Studio could not save its "
                    f"rerun evidence to the review bundle: {exc}",
                )
        matches_by_file = payload.get("matches_by_file") or {}
        match_count = sum(len(matches or []) for matches in matches_by_file.values())
        final_session_reports_built = bool(payload.get("final_session_reports_built"))
        final_session_entry_count = int(payload.get("final_session_entry_count") or 0)

        if self._current_file is not None:
            self._refresh_current_metadata()
            self._refresh_report_matches()

        if failed_jobs:
            self._set_status(f"Reviewed-file rerun finished with {len(failed_jobs)} failed job(s).", error=True)
            QMessageBox.warning(
                self,
                "Reviewed File Rerun Failed",
                f"Rerun finished with failed job(s): {', '.join(map(str, failed_jobs))}",
            )
            return

        gate = result.get("ladder_review_gate") or {}
        review_count = int(gate.get("review_case_count") or 0) if isinstance(gate, dict) else 0
        cases_path = gate.get("cases_path") if isinstance(gate, dict) else None
        if review_count > 0:
            if result.get("collected_entries"):
                self._set_review_session_entries(list(result.get("collected_entries") or []))
            self._set_status(
                f"Reran {len(file_paths)} reviewed file(s), but {review_count} still need ladder review.",
                error=True,
            )
            message = QMessageBox(self)
            message.setIcon(QMessageBox.Icon.Warning)
            message.setWindowTitle("Ladder Review Still Needed")
            message.setText(
                f"Rerun completed, but {review_count} ladder review case(s) were still flagged."
            )
            message.setInformativeText(
                "Open the new review bundle if these files still need manual ladder correction."
            )
            open_bundle_btn = None
            if cases_path:
                open_bundle_btn = message.addButton("Open New Review Bundle", QMessageBox.ButtonRole.AcceptRole)
            open_folder_btn = message.addButton("Open Output Folder", QMessageBox.ButtonRole.ActionRole)
            message.addButton("Close", QMessageBox.ButtonRole.RejectRole)
            message.exec()
            clicked = message.clickedButton()
            if open_bundle_btn is not None and clicked == open_bundle_btn:
                self.load_review_bundle_from_path(
                    Path(str(cases_path)).parent,
                    preloaded_entries=list(result.get("collected_entries") or []),
                )
            elif clicked == open_folder_btn:
                _open_path(output_root)
            return
        unconsumed = [
            Path(raw_path).name
            for raw_path, status in consumption_by_file.items()
            if status.get("adjustment_present")
            and not status.get("consumed")
        ]
        if unconsumed:
            self._set_status(
                f"{len(unconsumed)} saved correction(s) were not consumed.",
                error=True,
            )
            QMessageBox.warning(
                self,
                "Saved Corrections Not Consumed",
                "The rerun finished, but did not consume the saved correction "
                f"for: {', '.join(unconsumed)}",
            )
            return

        if final_session_reports_built:
            self._set_status(
                f"Reviewed-file rerun complete; final reports built from {final_session_entry_count} cached session entries."
            )
        else:
            self._set_status(f"Reviewed-file rerun complete for {len(file_paths)} file(s).")
        self._review_runtime_cache.clear()
        self._review_session_entries_by_path.clear()
        self._recent_reviewed_files.clear()
        self._refresh_review_bundle_run_button()
        self.reportsRefreshed.emit(str(output_root))
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle("Reviewed File Rerun Complete")
        if final_session_reports_built:
            message.setText("Built final DIT/tracking reports for the cached batch session.")
            message.setInformativeText(
                f"Updated {len(file_paths)} reviewed file(s), then rebuilt reports from "
                f"{final_session_entry_count} total cached entry/entries."
            )
        else:
            message.setText(f"Built/updated reports for {len(file_paths)} reviewed file(s).")
            message.setInformativeText(f"Found {match_count} matching HTML report(s).")
        open_folder_btn = message.addButton("Open Output Folder", QMessageBox.ButtonRole.AcceptRole)
        message.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        message.exec()
        if message.clickedButton() == open_folder_btn:
            _open_path(output_root)

    def _on_review_bundle_rerun_error(self, request_id: int, err_tuple) -> None:
        if request_id != self._review_bundle_rerun_request_id:
            return
        self._review_bundle_rerun_active = False
        self._set_rerun_context_locked(False)
        self.btn_load_bundle.setEnabled(True)
        self.btn_rerun_file.setEnabled(self._current_file is not None)
        self.btn_open_editor.setEnabled(self._current_file is not None and not self._metadata_loading)
        self.btn_refresh_meta.setEnabled(self._current_file is not None)
        self._refresh_review_bundle_run_button()
        self._set_status(f"Reviewed-file rerun failed: {err_tuple[1]}", error=True)
        QMessageBox.critical(self, "Reviewed File Rerun Failed", str(err_tuple[1]))

    def _refresh_report_matches(self) -> None:
        root_text = self.report_root.text().strip()
        if not self._current_file or not root_text:
            self.report_list.clear()
            self._report_matches = []
            self._update_report_buttons()
            return

        self._report_request_id += 1
        request_id = self._report_request_id
        self.btn_find_reports.setEnabled(False)
        self.report_list.clear()
        self._report_matches = []
        self._update_report_buttons()

        worker = Worker(self._find_report_matches_worker, self._current_file, root_text)
        worker.signals.result.connect(lambda result, rid=request_id: self._on_report_matches_result(rid, result))
        worker.signals.error.connect(lambda err, rid=request_id: self._on_report_matches_error(rid, err))
        self._start_registered_worker(
            worker, kind="Ladder report search",
            restore_ui=lambda: self.btn_find_reports.setEnabled(True),
        )

    def _update_report_buttons(self) -> None:
        has_selection = bool(self.report_list.selectedItems())
        self.btn_open_report.setEnabled(has_selection)
        self.btn_open_report_folder.setEnabled(has_selection)

    def _open_selected_report(self) -> None:
        items = self.report_list.selectedItems()
        if not items:
            return
        _open_path(Path(items[0].data(Qt.ItemDataRole.UserRole)))

    def _open_selected_report_folder(self) -> None:
        items = self.report_list.selectedItems()
        if not items:
            return
        _open_path(Path(items[0].data(Qt.ItemDataRole.UserRole)).parent)

    def _set_status(self, text: str, error: bool = False) -> None:
        color = "#ef4444" if error else "#64748b"
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color: {color}; font-weight: 500;")

    def _adjustment_status_for(self, file_path: Path) -> str:
        payload = load_ladder_adjustment(type("Dummy", (), {"file": file_path})())
        if not payload:
            return "None"
        partial = bool(payload.get("partial_mapping"))
        partial_approved = bool((payload.get("review") or {}).get("partial_approved"))
        if partial and not partial_approved:
            return "Draft · 1–2 anchors · not eligible for rerun"
        cache_key = self._resolve_cache_key(file_path)
        consumption = self._manual_rerun_consumption_by_path.get(cache_key)
        if consumption is None:
            review_case = self._review_case_by_path.get(cache_key) or {}
            persisted_status = str(review_case.get("rerun_status") or "")
            if persisted_status:
                consumption = {
                    "status": persisted_status,
                    "consumed": persisted_status == "consumed",
                }
        if consumption and consumption.get("consumed"):
            return "Applied · consumed by successful rerun"
        if consumption:
            return (
                "Approved partial fit · rerun did not consume"
                if partial_approved
                else "Saved complete adjustment · rerun did not consume"
            )
        if partial_approved:
            return "Approved partial fit · not rerun yet"
        return "Saved complete adjustment · not rerun yet"

    def _save_review_bundle_annotation(self, review_case: dict, review_payload: dict) -> None:
        if self._review_bundle_dir is None or self._current_file is None:
            return

        action = str(review_payload.get("action", "apply") or "apply")
        comment = str(review_payload.get("comment", "") or "").strip()
        if action == "note_only":
            label = "reviewed_no_change"
        elif action == "save_draft":
            label = "manual_partial_draft"
        elif bool(review_payload.get("partial_mapping")):
            label = "manual_partial_adjusted"
        else:
            label = "manual_adjusted"
        annotation = {
            "label": label,
            "label_note": comment,
            "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
            "adjustment_path": (
                str(review_payload.get("adjustment_path") or "")
                if label
                in {
                    "manual_adjusted",
                    "manual_partial_adjusted",
                    "manual_partial_draft",
                }
                else ""
            ),
            "action": action,
            "linear_max": review_payload.get("linear_max"),
            "linear_mean": review_payload.get("linear_mean"),
            "linear_r2": review_payload.get("linear_r2"),
        }

        cache_key = self._resolve_cache_key(self._current_file)
        self._save_review_bundle_annotation_worker(self._review_bundle_dir, cache_key, annotation)
        review_case.update(annotation)
        self._review_case_by_path[cache_key] = review_case
        # Phase 12.3 — propagate to the cases list so the chip strip
        # sees the updated label/color.
        for row in self._review_bundle_cases:
            try:
                if self._resolve_cache_key(Path(str(row.get("full_path", "") or ""))) == cache_key:
                    row["label"] = annotation["label"]
                    row["label_note"] = annotation["label_note"]
                    row["reviewed_at_utc"] = annotation["reviewed_at_utc"]
                    row["adjustment_path"] = annotation["adjustment_path"]
                    break
            except Exception:
                continue
        self._sync_chip_strip()
        tab_run = self._run_tab_for_review()
        if is_review_resolved(label):
            self._recent_reviewed_files.add(cache_key)
            if tab_run is not None and hasattr(tab_run, "register_ladder_review_update"):
                tab_run.register_ladder_review_update(cache_key)
        else:
            self._recent_reviewed_files.discard(cache_key)
            if tab_run is not None and hasattr(tab_run, "unregister_ladder_review_update"):
                tab_run.unregister_ladder_review_update(cache_key)
        self._rebuild_file_list()
        self._select_file(self._current_file)
        self._refresh_review_bundle_run_button()

    def _start_metadata_load(self, file_path: Path) -> None:
        self._metadata_request_id += 1
        request_id = self._metadata_request_id
        analysis_id = self._current_analysis_id
        context = (
            request_id,
            str(analysis_id),
            self._resolve_cache_key(file_path),
        )
        self._metadata_request_context = context
        self._metadata_loading = True
        self.btn_open_editor.setEnabled(False)
        self._set_status(f"Loading ladder metadata for {file_path.name}...")

        worker = Worker(self._load_metadata_worker, file_path, analysis_id)
        worker.signals.result.connect(
            lambda result, ctx=context: self._on_metadata_result(ctx, result)
        )
        worker.signals.error.connect(
            lambda err, ctx=context: self._on_metadata_error(ctx, err)
        )
        self._start_registered_worker(
            worker, kind="Ladder metadata load",
            restore_ui=self._restore_metadata_load_ui,
        )

    @staticmethod
    def _scan_fsa_files_worker(source: Path) -> list[Path]:
        # Phase 12.1 — delegate.
        from gui_qt.tabs.tab_ladder._workers import scan_fsa_files_worker

        return scan_fsa_files_worker(source)

    @staticmethod
    def _load_review_bundle_worker(bundle_dir: Path) -> dict:
        # Phase 12.1 — delegate. The Phase 12.0 fix lives in
        # _io.load_review_bundle_worker.
        from gui_qt.tabs.tab_ladder._io import load_review_bundle_worker

        return load_review_bundle_worker(bundle_dir)

    @staticmethod
    def _load_metadata_worker(file_path: Path, analysis_id: str | None) -> dict:
        # Phase 12.1 — delegate.
        from gui_qt.tabs.tab_ladder._workers import load_metadata_worker

        return load_metadata_worker(file_path, analysis_id)

    @staticmethod
    def _find_report_matches_worker(file_path: Path, root_text: str) -> dict:
        # Phase 12.1 — delegate.
        from gui_qt.tabs.tab_ladder._workers import find_report_matches_worker

        return find_report_matches_worker(file_path, root_text)

    @staticmethod
    def _save_review_bundle_annotation_worker(bundle_dir: Path, full_path: Path, annotation: dict) -> dict:
        # Phase 12.1 — delegate.
        from gui_qt.tabs.tab_ladder._io import save_review_bundle_annotation_worker

        return save_review_bundle_annotation_worker(bundle_dir, full_path, annotation)

    @staticmethod
    def _save_missing_ladder_exclusion_worker(
        bundle_dir: Path,
        full_path: Path,
        *,
        note: str,
        reviewed_at_utc: str,
    ) -> dict:
        from gui_qt.tabs.tab_ladder._io import save_missing_ladder_exclusion_worker

        return save_missing_ladder_exclusion_worker(
            bundle_dir,
            full_path,
            note=note,
            reviewed_at_utc=reviewed_at_utc,
        )

    def _on_chip_activated(self, file_path) -> None:
        """Phase 12.3 — chip click selects the file in the list."""
        if file_path is None:
            return
        try:
            self._select_file(Path(file_path))
        except Exception:
            pass

    def _on_locate_file(self, old_path) -> None:
        """Phase 12.4 — right-click "Locate File..." on a red chip.

        Opens a file dialog, calls `relocate_review_case` to
        atomically swap the row's full_path in the CSV + write the
        relocations audit log, then reloads the bundle.
        """
        from PyQt6.QtWidgets import QFileDialog

        from core.analyses.clonality.ladder_review_gate import relocate_review_case

        if old_path is None or not self._review_bundle_dir:
            return
        old_path = Path(str(old_path))

        new_path_str, _ = QFileDialog.getOpenFileName(
            self,
            f"Locate replacement for {old_path.name}",
            str(old_path.parent) if old_path.parent else "",
            "FSA Files (*.fsa);;All Files (*)",
        )
        if not new_path_str:
            return
        new_path = Path(new_path_str)
        try:
            entry = relocate_review_case(
                Path(self._review_bundle_dir), old_path, new_path
            )
        except FileNotFoundError as exc:
            self._set_status(f"Locate failed: {exc}", error=True)
            return
        self._set_status(
            f"Relocated {old_path.name} → {new_path.name}"
        )
        # Reload the bundle so the chip strip reflects the new path.
        self._load_review_bundle()

    def _sync_chip_strip(self, cases=None) -> None:
        """Phase 12.3 — re-render chip strip from current cases.

        Pass `cases=None` to use whatever the worker saved into
        `self._review_bundle_cases`. The chip strip clears to empty
        when no bundle is loaded.
        """
        rows = cases if cases is not None else getattr(
            self, "_review_bundle_cases", None
        ) or []
        progress_label = getattr(self, "review_progress_label", None)
        if progress_label is not None:
            from gui_qt.tabs.tab_ladder._summary import review_progress_text

            progress_label.setText(review_progress_text(rows))
        try:
            from gui_qt.tabs.tab_ladder._overview import ChipStripOverview
        except Exception:
            return
        # Lazy lookup — _build_source_card sets self._chip_strip.
        strip = getattr(self, "_chip_strip", None)
        if strip is None or not isinstance(strip, ChipStripOverview):
            return
        strip.setRows(rows)

    def _on_scan_result(self, request_id: int, source: Path, files: list[Path]) -> None:
        if request_id != self._scan_request_id:
            return
        self._set_source_load_active(False)
        self._all_files = files
        self._rebuild_file_list()
        self._set_status(f"Found {len(self._all_files)} .fsa files in {source}.")

    def _on_scan_error(self, request_id: int, err_tuple) -> None:
        if request_id != self._scan_request_id:
            return
        self._set_source_load_active(False)
        self._set_status(f"Could not scan .fsa files: {err_tuple[1]}", error=True)

    def _on_review_bundle_result(self, request_id: int, result: dict) -> None:
        if request_id != self._scan_request_id:
            return
        self._set_source_load_active(False)
        self._review_bundle_dir = result["bundle_dir"]
        self._review_bundle_run_manifest_path = result.get("run_manifest_path")
        self._review_bundle_cases = result["rows"]
        bundle_output_root, _ = self._review_bundle_output_context()
        if bundle_output_root is not None:
            self.report_root.setText(str(bundle_output_root))
        self._review_case_by_path = {
            self._resolve_cache_key(Path(str(row["full_path"]))): row
            for row in self._review_bundle_cases
        }
        self._all_files = list(self._review_case_by_path.keys())
        self._rebuild_file_list()
        self._refresh_review_bundle_run_button()
        resolved, unresolved = self._review_bundle_counts()
        cached_count = sum(
            1
            for row in self._review_bundle_cases
            if self._cached_review_payload_for(Path(str(row.get("full_path", "") or ""))) is not None
        )
        missing_paths = result.get("missing_paths", []) or []
        status_msg = (
            f"Loaded review bundle {self._review_bundle_dir.name} with "
            f"{len(self._review_bundle_cases)} case(s): {resolved} reviewed, "
            f"{unresolved} unresolved, {cached_count} cached."
        )
        if missing_paths:
            # Phase 12.0 — never let the editor silently load with
            # unreachable rows. Paint the status bar red so the
            # chemist immediately knows Locate File is in play.
            status_msg += (
                f"  ⚠ {len(missing_paths)} case(s) reference a path "
                f"that is currently unreachable — open those via "
                f"'Locate File' before saving."
            )
            self._set_status(status_msg, error=True)
        else:
            self._set_status(status_msg)
        # Phase 12.3 — refresh the chip strip whenever bundle loads.
        self._sync_chip_strip()

    def _on_review_bundle_error(self, request_id: int, err_tuple) -> None:
        if request_id != self._scan_request_id:
            return
        self._set_source_load_active(False)
        self._auto_open_review_editor_once = False
        self._pending_open_editor_after_metadata = False
        self._review_bundle_cases = []
        self._review_case_by_path = {}
        self._refresh_review_bundle_run_button()
        self._sync_chip_strip(cases=[])
        self._set_status(f"Could not load review bundle: {err_tuple[1]}", error=True)

    def _metadata_context_is_current(
        self,
        context: tuple[int, str, Path],
        result_file_path: Path | None = None,
    ) -> bool:
        if context != self._metadata_request_context:
            return False
        _request_id, analysis_id, file_path = context
        if analysis_id != self._current_analysis_id or self._current_file is None:
            return False
        if file_path != self._resolve_cache_key(self._current_file):
            return False
        if (
            result_file_path is not None
            and file_path != self._resolve_cache_key(result_file_path)
        ):
            return False
        return True

    def _on_metadata_result(
        self,
        context: tuple[int, str, Path],
        result: dict,
    ) -> None:
        result_path = Path(result["file_path"])
        if not self._metadata_context_is_current(context, result_path):
            return
        self._metadata_request_context = None
        self._metadata_loading = False

        self._apply_metadata_result(result)
        self._maybe_auto_open_review_editor(result_path)

    def _maybe_auto_open_review_editor(self, file_path: Path) -> None:
        if not (self._auto_open_review_editor_once or self._pending_open_editor_after_metadata):
            return
        if file_path != self._current_file or self._current_meta is None or self._metadata_loading:
            return
        if self._auto_open_review_editor_once and self._resolve_cache_key(file_path) not in self._review_case_by_path:
            return
        self._auto_open_review_editor_once = False
        self._pending_open_editor_after_metadata = False
        QTimer.singleShot(0, self._open_ladder_editor)

    def _apply_metadata_result(self, result: dict) -> None:
        file_path = result["file_path"]
        if file_path != self._current_file:
            return

        meta = result["meta"]
        if not meta:
            self._auto_open_review_editor_once = False
            self._pending_open_editor_after_metadata = False
            for key in [
                "assay",
                "ladder",
                "fit_strategy",
                "fit_counts",
                "review_state",
                "confidence",
                "missing_steps",
                "adjustment",
            ]:
                self.detail_labels[key].setText("Could not classify")
            self._set_status(f"Could not classify {file_path.name}.", error=True)
            return

        self._current_meta = meta
        self._current_fsa = result["fsa"]
        review_case = self._review_case_by_path.get(self._resolve_cache_key(file_path))
        adj_status = self._adjustment_status_for(file_path)
        assay_label = meta.get("assay") or meta.get("analysis", "").capitalize() or "—"
        self.detail_labels["assay"].setText(assay_label)
        self.detail_labels["ladder"].setText(meta["ladder"])
        if review_case and str(review_case.get("label_note", "") or "").strip():
            adj_status = f"{adj_status} · comment saved"
        self.detail_labels["adjustment"].setText(adj_status)

        fsa = self._current_fsa
        fit_strategy = str(getattr(fsa, "ladder_fit_strategy", "auto_full")).replace("_", " ")
        expected_steps = list(map(float, getattr(fsa, "expected_ladder_steps", getattr(fsa, "ladder_steps", []))))
        fitted_steps = list(map(float, getattr(fsa, "ladder_steps", [])))
        missing_steps = list(map(float, getattr(fsa, "ladder_missing_expected_steps", [])))
        fit_note = str(getattr(fsa, "ladder_fit_note", ""))
        review_required = bool(getattr(fsa, "ladder_review_required", bool(missing_steps)))

        strategy_value = str(getattr(fsa, "ladder_fit_strategy", "") or "")
        if strategy_value == "manual_partial":
            review_state = (
                "Operator-approved partial · missing anchors remain visible"
                if getattr(fsa, "manual_ladder_partial_approved", False)
                else "Unapproved partial · review required"
            )
        elif strategy_value == "manual_adjustment":
            review_state = "Manual correction active"
        elif review_required:
            review_state = "Usable but incomplete"
        else:
            review_state = "Full fit"

        self.detail_labels["fit_strategy"].setText(fit_strategy)
        self.detail_labels["fit_counts"].setText(f"{len(expected_steps)} / {len(fitted_steps)}")
        self.detail_labels["review_state"].setText(review_state)
        from gui_qt.tabs.tab_ladder._summary import (
            format_ladder_confidence_shadow,
        )

        self.detail_labels["confidence"].setText(
            format_ladder_confidence_shadow(result.get("confidence_shadow"))
        )
        self.detail_labels["missing_steps"].setText(
            ", ".join(f"{bp:.0f}" for bp in missing_steps) if missing_steps else "None"
        )
        self.btn_open_editor.setEnabled(True)
        self.btn_rerun_file.setEnabled(True)
        self.btn_remove_adjustment.setEnabled(
            load_ladder_adjustment(self._current_fsa) is not None
        )
        if result.get("from_cache"):
            self._set_status(f"Loaded cached run data for {file_path.name}.")
        else:
            self._set_status(fit_note or f"Loaded metadata for {file_path.name}.")

    def _on_metadata_error(
        self,
        context: tuple[int, str, Path],
        err_tuple,
    ) -> None:
        if not self._metadata_context_is_current(context):
            return
        self._metadata_request_context = None
        self._metadata_loading = False
        self._auto_open_review_editor_once = False
        self._pending_open_editor_after_metadata = False
        self.btn_open_editor.setEnabled(self._current_file is not None)
        self.detail_labels["fit_strategy"].setText("Could not load")
        self.detail_labels["fit_counts"].setText("—")
        self.detail_labels["review_state"].setText("Unknown")
        self.detail_labels["missing_steps"].setText("—")
        self._set_status(f"Loaded metadata, but not ladder state: {err_tuple[1]}", error=True)

    def _on_report_matches_result(self, request_id: int, result: dict) -> None:
        if request_id != self._report_request_id:
            return
        self.btn_find_reports.setEnabled(True)
        root = result["root"]
        self._report_matches = result["matches"]
        self.report_list.clear()
        for path in self._report_matches:
            item = QListWidgetItem(str(path.relative_to(root)))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.report_list.addItem(item)

        if self._report_matches:
            self.report_list.setCurrentRow(0)
            self._set_status(f"Found {len(self._report_matches)} matching reports.")
        else:
            self._set_status("No matching reports found under the selected report root.")
        self._update_report_buttons()

    def _on_report_matches_error(self, request_id: int, err_tuple) -> None:
        if request_id != self._report_request_id:
            return
        self.btn_find_reports.setEnabled(True)
        self.report_list.clear()
        self._report_matches = []
        self._update_report_buttons()
        self._set_status(str(err_tuple[1]), error=True)
