from __future__ import annotations

import csv
import json
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
from PyQt6.QtCore import Qt, QThreadPool, QTimer

from config import APP_SETTINGS, get_analysis_settings
from core.analysis import load_ladder_adjustment, save_ladder_adjustment
from core.analyses.clonality.ladder_review_gate import RESOLVED_LABELS
from core.html_reports import extract_dit_from_name
from gui_qt.dialogs.ladder_dialog import LadderAdjustmentDialog
from gui_qt.ladder_utils import detect_fsa_for_ladder, load_adjustable_fsa
from gui_qt.worker import Worker



def _open_path(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class TabLadder(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.threadpool = QThreadPool.globalInstance()
        self._all_files: list[Path] = []
        self._current_file: Path | None = None
        self._current_meta: dict | None = None
        self._current_fsa = None
        self._report_matches: list[Path] = []
        self._review_bundle_dir: Path | None = None
        self._review_bundle_cases: list[dict] = []
        self._review_case_by_path: dict[Path, dict] = {}
        self._review_runtime_cache: dict[Path, dict] = {}
        self._review_session_entries_by_path: dict[Path, dict] = {}
        self._recent_reviewed_files: set[Path] = set()
        self._auto_open_review_editor_once = False
        self._pending_open_editor_after_metadata = False
        self._current_analysis_id = APP_SETTINGS.get("active_analysis", "clonality")
        self._scan_request_id = 0
        self._metadata_request_id = 0
        self._report_request_id = 0
        self._single_rerun_request_id = 0
        self._review_bundle_rerun_request_id = 0
        self._metadata_loading = False

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

        self._empty_state = QLabel("Pick one .fsa file to inspect its ladder.")
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
        btn_browse_dir = QPushButton("Browse Folder...")
        btn_browse_dir.clicked.connect(self._choose_source_dir)
        self.btn_scan = QPushButton("Scan .fsa Files")
        self.btn_scan.clicked.connect(self._scan_files)
        btn_browse_file = QPushButton("Open Single File...")
        btn_browse_file.clicked.connect(self._choose_single_file)
        row1.addWidget(QLabel("Input Folder:"))
        row1.addWidget(self.source_dir, stretch=1)
        row1.addWidget(btn_browse_dir)
        row1.addWidget(self.btn_scan)
        row1.addWidget(btn_browse_file)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.file_filter = QLineEdit()
        self.file_filter.setPlaceholderText("Filter by filename, DIT, assay, plate position...")
        self.file_filter.textChanged.connect(self._rebuild_file_list)
        row2.addWidget(QLabel("Filter:"))
        row2.addWidget(self.file_filter, stretch=1)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.review_bundle_dir = QLineEdit()
        self.review_bundle_dir.setPlaceholderText("/optional/path/to/review bundle with ladder_review_cases.csv")
        btn_browse_bundle = QPushButton("Browse Bundle...")
        btn_browse_bundle.clicked.connect(self._choose_review_bundle)
        self.btn_load_bundle = QPushButton("Load Review Bundle")
        self.btn_load_bundle.clicked.connect(self._load_review_bundle)
        self.btn_rerun_review_bundle = QPushButton("Run Reviewed Files + Reports")
        self.btn_rerun_review_bundle.setToolTip(
            "Rerun files marked as manually adjusted or reviewed, then rebuild their reports."
        )
        self.btn_rerun_review_bundle.clicked.connect(self._rerun_review_bundle_reports)
        self.btn_rerun_review_bundle.setEnabled(False)
        row3.addWidget(QLabel("Review Bundle:"))
        row3.addWidget(self.review_bundle_dir, stretch=1)
        row3.addWidget(btn_browse_bundle)
        row3.addWidget(self.btn_load_bundle)
        row3.addWidget(self.btn_rerun_review_bundle)
        layout.addLayout(row3)

        # Phase 12.3 — chip-strip overview above the file list.
        # One chip per loaded bundle case (reviewed/needs_review/
        # file_unreachable/untouched). Click a chip to select that
        # file in the list below.
        from gui_qt.tabs.tab_ladder._overview import ChipStripOverview

        self._chip_strip = ChipStripOverview(parent=card)
        self._chip_strip.chipActivated.connect(self._on_chip_activated)
        self._chip_strip.chipLocateRequested.connect(self._on_locate_file)
        layout.addWidget(self._chip_strip)

        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(220)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_list.itemSelectionChanged.connect(self._on_file_selected)
        self.file_list.itemDoubleClicked.connect(lambda _: self._open_ladder_editor())
        layout.addWidget(self.file_list)

        return card

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
        self.btn_rerun_file = QPushButton("Run This File + Reports")
        self.btn_rerun_file.clicked.connect(self._rerun_current_file_reports)
        self.btn_remove_adjustment = QPushButton("Remove Saved Adjustment")
        self.btn_remove_adjustment.clicked.connect(self._remove_saved_adjustment)
        self.btn_open_file_folder = QPushButton("Open File Folder")
        self.btn_open_file_folder.clicked.connect(self._open_file_folder)

        for btn in [
            self.btn_refresh_meta,
            self.btn_open_editor,
            self.btn_rerun_file,
            self.btn_remove_adjustment,
            self.btn_open_file_folder,
        ]:
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

    def set_analysis(self, analysis_id: str) -> None:
        previous_profile = get_analysis_settings(self._current_analysis_id)
        next_profile = get_analysis_settings(analysis_id)

        previous_input = previous_profile.get("batch", {}).get("base_input_dir", "")
        previous_output = previous_profile.get("batch", {}).get("output_base", "")

        if not self.source_dir.text().strip() or self.source_dir.text().strip() == previous_input:
            self.source_dir.setText(next_profile.get("batch", {}).get("base_input_dir", ""))
        if not self.report_root.text().strip() or self.report_root.text().strip() == previous_output:
            self.report_root.setText(next_profile.get("batch", {}).get("output_base", ""))

        self._current_analysis_id = analysis_id
        self._current_meta = None
        self._current_fsa = None
        self._clear_details()
        if self._current_file:
            self._set_status(
                f"Analysis switched to {analysis_id}. Refresh metadata to re-evaluate the current file."
            )

    @staticmethod
    def _format_file_item(file_path: Path, case: dict | None) -> str:
        # Phase 12.1 — delegate to the pure-Python helper module.
        from gui_qt.tabs.tab_ladder._summary import format_file_item

        return format_file_item(file_path, case)

    def _choose_source_dir(self) -> None:
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
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Review Bundle Folder",
            self.review_bundle_dir.text() or str(Path.home()),
        )
        if folder:
            self.load_review_bundle_from_path(folder)

    def _choose_single_file(self) -> None:
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
        source = Path(self.source_dir.text().strip()).expanduser()
        if not source.exists() or not source.is_dir():
            self._set_status("Input folder does not exist.", error=True)
            return

        self._scan_request_id += 1
        request_id = self._scan_request_id
        self.btn_scan.setEnabled(False)
        self._set_status(f"Scanning {source} for .fsa files...")

        worker = Worker(self._scan_fsa_files_worker, source)
        worker.signals.result.connect(lambda files, rid=request_id, src=source: self._on_scan_result(rid, src, files))
        worker.signals.error.connect(lambda err, rid=request_id: self._on_scan_error(rid, err))
        self.threadpool.start(worker)

    def _load_review_bundle(self) -> None:
        bundle_dir = Path(self.review_bundle_dir.text().strip()).expanduser()
        if not bundle_dir.exists() or not bundle_dir.is_dir():
            self._set_status("Review bundle folder does not exist.", error=True)
            return

        self._scan_request_id += 1
        request_id = self._scan_request_id
        self.btn_load_bundle.setEnabled(False)
        self.btn_rerun_review_bundle.setEnabled(False)
        self._set_status(f"Loading review bundle from {bundle_dir.name}...")

        worker = Worker(self._load_review_bundle_worker, bundle_dir)
        worker.signals.result.connect(lambda result, rid=request_id: self._on_review_bundle_result(rid, result))
        worker.signals.error.connect(lambda err, rid=request_id: self._on_review_bundle_error(rid, err))
        self.threadpool.start(worker)

    def load_review_bundle_from_path(
        self,
        bundle_dir: Path | str,
        *,
        preloaded_entries: list[dict] | None = None,
        auto_open_first: bool = False,
    ) -> None:
        bundle_path = Path(bundle_dir).expanduser()
        if bundle_path.is_file():
            bundle_path = bundle_path.parent
        review_case_paths = self._review_case_paths_from_bundle(bundle_path)
        self._set_review_session_entries(preloaded_entries or [])
        self._set_review_runtime_cache(preloaded_entries or [], review_case_paths)
        self._recent_reviewed_files.clear()
        self._auto_open_review_editor_once = bool(auto_open_first)
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
        self._current_file = file_path
        self._current_meta = None
        self._current_fsa = None
        self._clear_details()

        enabled = file_path is not None
        for btn in [
            self.btn_refresh_meta,
            self.btn_open_editor,
            self.btn_rerun_file,
            self.btn_remove_adjustment,
            self.btn_open_file_folder,
        ]:
            btn.setEnabled(enabled)

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
        self.detail_labels["missing_steps"].setText("—")
        cached = self._cached_review_payload_for(self._current_file)
        if cached:
            self._metadata_request_id += 1
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
        dialog = LadderAdjustmentDialog(
            fsa,
            self,
            review_context=review_case,
            review_comment=review_comment,
        )
        if dialog.exec():
            review_payload = dialog.get_review_payload()
            if review_payload.get("action") != "note_only":
                adjustment = dialog.get_adjustment_payload()
                save_ladder_adjustment(fsa, adjustment)
                preview_fsa = getattr(dialog, "_preview_fsa", None)
                if preview_fsa is not None:
                    cache_key = self._resolve_cache_key(self._current_file)
                    cached_preview = copy.deepcopy(preview_fsa)
                    try:
                        cached_preview.file = str(cache_key)
                        cached_preview.file_name = cache_key.name
                    except Exception:
                        pass
                    self._review_runtime_cache[cache_key] = {
                        "fsa": cached_preview,
                        "meta": copy.deepcopy(self._current_meta or {}),
                    }
            if review_case and self._review_bundle_dir is not None:
                self._save_review_bundle_annotation(review_case, review_payload)
            self._refresh_current_metadata()
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

    def _remove_saved_adjustment(self) -> None:
        if not self._current_file:
            return

        adj_path = self._current_file.with_suffix(".ladder_adj.json")
        if not adj_path.exists():
            QMessageBox.information(self, "No Adjustment", "There is no saved ladder adjustment for this file.")
            return

        reply = QMessageBox.question(
            self,
            "Remove Adjustment",
            f"Delete the saved ladder adjustment for {self._current_file.name}?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        adj_path.unlink(missing_ok=True)
        self._refresh_current_metadata()
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

        self._single_rerun_request_id += 1
        request_id = self._single_rerun_request_id
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
        )
        worker.signals.result.connect(lambda result, rid=request_id: self._on_single_rerun_finished(rid, result))
        worker.signals.error.connect(lambda err, rid=request_id: self._on_single_rerun_error(rid, err))
        self.threadpool.start(worker)

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
        )

    def _review_bundle_counts(self) -> tuple[int, int]:
        resolved = 0
        unresolved = 0
        for row in self._review_bundle_cases:
            label = str(row.get("label", "") or "").strip()
            if label in RESOLVED_LABELS:
                resolved += 1
            else:
                unresolved += 1
        return resolved, unresolved

    def _refresh_review_bundle_run_button(self) -> None:
        if self._is_run_tab_owned_review():
            self.btn_rerun_review_bundle.setText("Back To Run: Build DIT")
            self.btn_rerun_review_bundle.setEnabled(True)
            return

        resolved, _ = self._review_bundle_counts()
        recent_ready = len(self._recent_reviewed_files)
        ready_count = recent_ready or resolved
        self.btn_rerun_review_bundle.setEnabled(ready_count > 0)
        if recent_ready > 0:
            self.btn_rerun_review_bundle.setText(f"Run Recent Reviewed Files + Reports ({recent_ready})")
        elif resolved > 0:
            self.btn_rerun_review_bundle.setText(f"Run Reviewed Files + Reports ({resolved})")
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
            if label not in RESOLVED_LABELS:
                unresolved += 1
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

        self._review_bundle_rerun_request_id += 1
        request_id = self._review_bundle_rerun_request_id
        for btn in (
            self.btn_rerun_review_bundle,
            self.btn_load_bundle,
            self.btn_rerun_file,
            self.btn_open_editor,
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
        )
        worker.signals.result.connect(lambda result, rid=request_id: self._on_review_bundle_rerun_finished(rid, result))
        worker.signals.error.connect(lambda err, rid=request_id: self._on_review_bundle_rerun_error(rid, err))
        self.threadpool.start(worker)

    @staticmethod
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
        )

    def _on_single_rerun_finished(self, request_id: int, payload: dict) -> None:
        if request_id != self._single_rerun_request_id:
            return
        self.btn_rerun_file.setEnabled(self._current_file is not None)
        self.btn_open_editor.setEnabled(self._current_file is not None and not self._metadata_loading)
        self.btn_refresh_meta.setEnabled(self._current_file is not None)

        result = payload.get("result") or {}
        failed_jobs = result.get("failed_jobs", [])
        output_root = Path(payload.get("output_root"))
        matches = list(payload.get("matches") or [])
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

        self._set_status(f"Single-file rerun complete for {Path(payload['file_path']).name}.")

        gate = result.get("ladder_review_gate") or {}
        review_count = int(gate.get("review_case_count") or 0) if isinstance(gate, dict) else 0
        if review_count > 0:
            QMessageBox.warning(
                self,
                "Ladder Review Still Needed",
                f"The rerun completed, but {review_count} ladder review case(s) were still flagged.",
            )
            return

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
        self.btn_rerun_file.setEnabled(self._current_file is not None)
        self.btn_open_editor.setEnabled(self._current_file is not None and not self._metadata_loading)
        self.btn_refresh_meta.setEnabled(self._current_file is not None)
        self._set_status(f"Single-file rerun failed: {err_tuple[1]}", error=True)
        QMessageBox.critical(self, "Single File Rerun Failed", str(err_tuple[1]))

    def _on_review_bundle_rerun_finished(self, request_id: int, payload: dict) -> None:
        if request_id != self._review_bundle_rerun_request_id:
            return

        self.btn_load_bundle.setEnabled(True)
        self.btn_rerun_file.setEnabled(self._current_file is not None)
        self.btn_open_editor.setEnabled(self._current_file is not None and not self._metadata_loading)
        self.btn_refresh_meta.setEnabled(self._current_file is not None)
        self._refresh_review_bundle_run_button()

        result = payload.get("result") or {}
        failed_jobs = result.get("failed_jobs", [])
        output_root = Path(payload.get("output_root"))
        file_paths = [Path(path) for path in payload.get("file_paths", [])]
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
        self.threadpool.start(worker)

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

    @staticmethod
    def _adjustment_status_for(file_path: Path) -> str:
        payload = load_ladder_adjustment(type("Dummy", (), {"file": file_path})())
        return "Saved" if payload else "None"

    def _save_review_bundle_annotation(self, review_case: dict, review_payload: dict) -> None:
        if self._review_bundle_dir is None or self._current_file is None:
            return

        action = str(review_payload.get("action", "apply") or "apply")
        comment = str(review_payload.get("comment", "") or "").strip()
        label = "manual_adjusted" if action != "note_only" else "reviewed_no_change"
        annotation = {
            "label": label,
            "label_note": comment,
            "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
            "adjustment_path": (
                str(self._current_file.with_suffix(".ladder_adj.json")) if label == "manual_adjusted" else ""
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
        self._recent_reviewed_files.add(cache_key)
        tab_run = self._run_tab_for_review()
        if tab_run is not None and hasattr(tab_run, "register_ladder_review_update"):
            tab_run.register_ladder_review_update(cache_key)
        self._rebuild_file_list()
        self._select_file(self._current_file)
        self._refresh_review_bundle_run_button()

    def _start_metadata_load(self, file_path: Path) -> None:
        self._metadata_request_id += 1
        request_id = self._metadata_request_id
        analysis_id = APP_SETTINGS.get("active_analysis")
        self._metadata_loading = True
        self.btn_open_editor.setEnabled(False)
        self._set_status(f"Loading ladder metadata for {file_path.name}...")

        worker = Worker(self._load_metadata_worker, file_path, analysis_id)
        worker.signals.result.connect(lambda result, rid=request_id: self._on_metadata_result(rid, result))
        worker.signals.error.connect(lambda err, rid=request_id: self._on_metadata_error(rid, err))
        self.threadpool.start(worker)

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
        try:
            from gui_qt.tabs.tab_ladder._overview import ChipStripOverview
        except Exception:
            return
        # Lazy lookup — _build_source_card sets self._chip_strip.
        strip = getattr(self, "_chip_strip", None)
        if strip is None or not isinstance(strip, ChipStripOverview):
            return
        rows = cases if cases is not None else getattr(
            self, "_review_bundle_cases", None
        ) or []
        strip.setRows(rows)

    def _on_scan_result(self, request_id: int, source: Path, files: list[Path]) -> None:
        if request_id != self._scan_request_id:
            return
        self.btn_scan.setEnabled(True)
        self._all_files = files
        self._rebuild_file_list()
        self._set_status(f"Found {len(self._all_files)} .fsa files in {source}.")

    def _on_scan_error(self, request_id: int, err_tuple) -> None:
        if request_id != self._scan_request_id:
            return
        self.btn_scan.setEnabled(True)
        self._set_status(f"Could not scan .fsa files: {err_tuple[1]}", error=True)

    def _on_review_bundle_result(self, request_id: int, result: dict) -> None:
        if request_id != self._scan_request_id:
            return
        self.btn_load_bundle.setEnabled(True)
        self._review_bundle_dir = result["bundle_dir"]
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
        self.btn_load_bundle.setEnabled(True)
        self._auto_open_review_editor_once = False
        self._pending_open_editor_after_metadata = False
        self._review_bundle_cases = []
        self._review_case_by_path = {}
        self._refresh_review_bundle_run_button()
        self._sync_chip_strip(cases=[])
        self._set_status(f"Could not load review bundle: {err_tuple[1]}", error=True)

    def _on_metadata_result(self, request_id: int, result: dict) -> None:
        if request_id != self._metadata_request_id:
            return
        self._metadata_loading = False

        self._apply_metadata_result(result)
        self._maybe_auto_open_review_editor(result["file_path"])

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

        if getattr(fsa, "ladder_fit_strategy", "") == "manual_adjustment":
            review_state = "Manual correction active"
        elif review_required:
            review_state = "Usable but incomplete"
        else:
            review_state = "Full fit"

        self.detail_labels["fit_strategy"].setText(fit_strategy)
        self.detail_labels["fit_counts"].setText(f"{len(expected_steps)} / {len(fitted_steps)}")
        self.detail_labels["review_state"].setText(review_state)
        self.detail_labels["missing_steps"].setText(
            ", ".join(f"{bp:.0f}" for bp in missing_steps) if missing_steps else "None"
        )
        self.btn_open_editor.setEnabled(True)
        if result.get("from_cache"):
            self._set_status(f"Loaded cached run data for {file_path.name}.")
        else:
            self._set_status(fit_note or f"Loaded metadata for {file_path.name}.")

    def _on_metadata_error(self, request_id: int, err_tuple) -> None:
        if request_id != self._metadata_request_id:
            return
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
