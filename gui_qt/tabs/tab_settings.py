from __future__ import annotations

import copy
import re
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QGroupBox,
)

import config
from config import APP_SETTINGS, get_analysis_settings, save_settings


ANALYSIS_LABELS = {
    "clonality": "Klonalitet",
    "flt3": "FLT3 Analysis",
    "general": "General",
}


class TabAnalysisSettings(QWidget):
    settings_saved = pyqtSignal(str)

    def __init__(self, analysis_id: str, parent=None):
        super().__init__(parent)
        self.analysis_id = analysis_id
        self.analysis_label = ANALYSIS_LABELS.get(analysis_id, analysis_id.capitalize())
        self._refreshing = False

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)

        header = QVBoxLayout()
        title = QLabel(f"{self.analysis_label} Settings")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            f"Choose the saved folders and defaults that should be used when you switch to {self.analysis_label.lower()}."
        )
        subtitle.setObjectName("PageSubtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        self.dirty_lbl = QLabel("")
        self.dirty_lbl.setAccessibleName("Unsaved changes status")
        header.addWidget(self.dirty_lbl)
        self.status_lbl = QLabel("")
        self.status_lbl.setAccessibleName("Profile save status")
        self.status_lbl.setWordWrap(True)
        header.addWidget(self.status_lbl)
        self.btn_save_top = QPushButton(f"Save {self.analysis_label} Profile")
        self.btn_save_top.setObjectName("PrimaryButton")
        self.btn_save_top.clicked.connect(self.save)
        header.addWidget(self.btn_save_top)
        main_layout.addLayout(header)

        self.paths_card = self._build_paths_card()
        self.run_card = self._build_run_card()
        self.interpretation_card = self._build_interpretation_card()
        self.save_card = self._build_save_card()

        main_layout.addWidget(self.paths_card)
        main_layout.addWidget(self.run_card)
        if self.analysis_id == "clonality":
            main_layout.addWidget(self.interpretation_card)
        main_layout.addWidget(self.save_card)
        main_layout.addStretch()

        self.refresh_from_settings()
        self._connect_dirty_signals()

    def _build_paths_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        layout = QFormLayout(card)

        layout.addRow(QLabel("<b>Saved Paths</b>"))

        row_in = QHBoxLayout()
        self.default_input = QLineEdit()
        btn_browse_in = QPushButton("Browse...")
        btn_browse_in.clicked.connect(lambda: self._browse_dir(self.default_input))
        row_in.addWidget(self.default_input, stretch=1)
        row_in.addWidget(btn_browse_in)
        layout.addRow("Default Input Folder:", row_in)

        row_out = QHBoxLayout()
        self.default_output = QLineEdit()
        btn_browse_out = QPushButton("Browse...")
        btn_browse_out.clicked.connect(lambda: self._browse_dir(self.default_output))
        row_out.addWidget(self.default_output, stretch=1)
        row_out.addWidget(btn_browse_out)
        layout.addRow("Default Output Folder:", row_out)

        row_excel = QHBoxLayout()
        self.tracking_excel_path = QLineEdit()
        self.tracking_excel_path.setPlaceholderText("Leave blank to save beside the report output")
        btn_browse_excel = QPushButton("Browse...")
        btn_browse_excel.clicked.connect(self._browse_excel_path)
        row_excel.addWidget(self.tracking_excel_path, stretch=1)
        row_excel.addWidget(btn_browse_excel)
        layout.addRow("Tracking Excel File:", row_excel)

        self.global_tracking_excel_path = QLineEdit()
        self.global_tracking_excel_path.setPlaceholderText(
            "Optional; leave blank to disable the shared master workbook"
        )
        if self.analysis_id in {"clonality", "flt3"}:
            row_master_excel = QHBoxLayout()
            btn_browse_master = QPushButton("Browse...")
            btn_browse_master.clicked.connect(self._browse_global_tracking_excel_path)
            row_master_excel.addWidget(self.global_tracking_excel_path, stretch=1)
            row_master_excel.addWidget(btn_browse_master)
            layout.addRow("Master Tracking Excel File:", row_master_excel)

        return card

    def _build_run_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        layout = QFormLayout(card)

        layout.addRow(QLabel("<b>Run Defaults</b>"))

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["all", "controls", "custom"])
        self.mode_combo.currentTextChanged.connect(self._sync_scope_controls)
        layout.addRow("Scope:", self.mode_combo)

        self.assay_filter = QLineEdit()
        self.assay_filter.setPlaceholderText("Only used when Scope is set to custom")
        layout.addRow("Custom Assay Filter:", self.assay_filter)

        self.chk_agg_pat = QCheckBox("Group scans by Patient ID")
        self.chk_agg_pat.toggled.connect(self._sync_patient_regex_enabled)
        layout.addRow("", self.chk_agg_pat)

        self.patient_regex = QLineEdit()
        self.patient_regex.setPlaceholderText(r"\d{2}OUM\d{5}")
        layout.addRow("Patient ID Regex:", self.patient_regex)

        self.chk_agg_dit = QCheckBox("Combine DIT reports across jobs")
        layout.addRow("", self.chk_agg_dit)

        note = QLabel(
            "These values are saved separately for each analysis and are used automatically in Run and Ladder."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b;")
        layout.addRow("", note)
        return card

    def _build_interpretation_card(self) -> QWidget:
        card = QGroupBox("Rule-based interpretation")
        card.setObjectName("Card")
        card.setCheckable(True)
        outer = QVBoxLayout(card)
        self.advanced_content = QWidget()
        layout = QFormLayout(self.advanced_content)
        outer.addWidget(self.advanced_content)

        layout.addRow(QLabel("<b>Rule-based clonality interpretation</b>"))

        self.chk_clonality_interpretation = QCheckBox("Enable rule-based interpretation")
        layout.addRow("", self.chk_clonality_interpretation)

        note = QLabel(
            "When enabled, deterministic analysis rules add interpretation guidance "
            "to clonality results."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b;")
        layout.addRow("", note)
        card.toggled.connect(self.advanced_content.setVisible)
        card.setChecked(False)
        self.advanced_content.setVisible(False)
        return card

    def _build_save_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        layout = QFormLayout(card)

        btn_save = QPushButton(f"Save {self.analysis_label} Profile")
        btn_save.setObjectName("PrimaryButton")
        btn_save.clicked.connect(self.save)
        layout.addRow("", btn_save)

        return card

    def refresh_from_settings(self) -> None:
        if self.is_dirty():
            return
        self._refreshing = True
        analysis_settings = get_analysis_settings(self.analysis_id)
        batch_settings = analysis_settings.get("batch", {})
        pipeline_settings = analysis_settings.get("pipeline", {})
        interpretation_settings = analysis_settings.get("interpretation", {})
        self.default_input.setText(batch_settings.get("base_input_dir", str(Path.home())))
        self.default_output.setText(batch_settings.get("output_base", str(Path.home())))
        self.tracking_excel_path.setText(batch_settings.get("tracking_excel_path", ""))
        self.global_tracking_excel_path.setText(
            str(batch_settings.get("global_tracking_excel_path", "") or "")
        )

        self.mode_combo.setCurrentText(pipeline_settings.get("mode", "all"))
        self.assay_filter.setText(pipeline_settings.get("assay_filter_substring", ""))
        self.chk_agg_pat.setChecked(bool(batch_settings.get("aggregate_by_patient", True)))
        self.patient_regex.setText(batch_settings.get("patient_id_regex", r"\d{2}OUM\d{5}"))
        self.chk_agg_dit.setChecked(bool(batch_settings.get("aggregate_dit_reports", True)))
        if self.analysis_id == "clonality":
            self.chk_clonality_interpretation.setChecked(bool(interpretation_settings.get("enabled", False)))
        self._sync_patient_regex_enabled()
        self._sync_scope_controls()

        self._refreshing = False
        self._set_dirty(False)

    def save(self) -> bool:
        window = self.window()
        changes_allowed = getattr(window, "settings_changes_allowed", None)
        if callable(changes_allowed) and not changes_allowed():
            self.status_lbl.setText("Settings cannot be saved while an operation is running.")
            self.status_lbl.setStyleSheet("color: #b45309; font-weight: 500;")
            return False

        proposed = copy.deepcopy(APP_SETTINGS)
        analyses = proposed.setdefault("analyses", {})
        profile = analyses.setdefault(self.analysis_id, {})
        batch_settings = profile.setdefault("batch", {})
        pipeline_settings = profile.setdefault("pipeline", {})
        interpretation_settings = profile.setdefault("interpretation", {})

        batch_settings["base_input_dir"] = self.default_input.text().strip()
        batch_settings["output_base"] = self.default_output.text().strip()
        batch_settings["tracking_excel_path"] = self.tracking_excel_path.text().strip()
        batch_settings["global_tracking_excel_path"] = self.global_tracking_excel_path.text().strip()
        batch_settings["aggregate_by_patient"] = self.chk_agg_pat.isChecked()
        batch_settings["patient_id_regex"] = self.patient_regex.text().strip()
        batch_settings["aggregate_dit_reports"] = self.chk_agg_dit.isChecked()

        pipeline_settings["mode"] = self.mode_combo.currentText()
        pipeline_settings["assay_filter_substring"] = self.assay_filter.text().strip()
        if self.analysis_id == "clonality":
            interpretation_settings["enabled"] = self.chk_clonality_interpretation.isChecked()

        if proposed.get("active_analysis") == self.analysis_id:
            proposed.setdefault("batch", {}).update(batch_settings)
            proposed.setdefault("pipeline", {}).update(pipeline_settings)

        error = self._validation_error()
        if error:
            self.status_lbl.setText(error)
            self.status_lbl.setStyleSheet("color: #b91c1c; font-weight: 500;")
            return False

        if not save_settings(proposed):
            self.status_lbl.setText(config.LAST_SETTINGS_SAVE_ERROR or "Failed to save settings.")
            self.status_lbl.setStyleSheet("color: #b91c1c; font-weight: 500;")
            return False
        APP_SETTINGS.clear()
        APP_SETTINGS.update(proposed)
        self.settings_saved.emit(self.analysis_id)
        self.status_lbl.setText(f"{self.analysis_label} settings saved.")
        self.status_lbl.setStyleSheet("color: #15803d; font-weight: 500;")
        self._set_dirty(False)
        return True

    def is_dirty(self) -> bool:
        return self.dirty_lbl.text() != ""

    def _set_dirty(self, dirty: bool = True) -> None:
        if self._refreshing:
            return
        self.dirty_lbl.setText("Unsaved profile changes" if dirty else "")
        self.dirty_lbl.setStyleSheet("color: #b45309; font-weight: 500;")

    def _connect_dirty_signals(self) -> None:
        for widget in self.findChildren(QLineEdit):
            widget.textChanged.connect(lambda _value: self._set_dirty())
        for widget in self.findChildren(QCheckBox):
            widget.toggled.connect(lambda _value: self._set_dirty())
        self.mode_combo.currentTextChanged.connect(lambda _value: self._set_dirty())

    def _validation_error(self) -> str | None:
        if self.chk_agg_pat.isChecked():
            try:
                re.compile(self.patient_regex.text().strip())
            except re.error as exc:
                message = f"Patient ID Regex is invalid: {exc}"
                self.patient_regex.setToolTip(message)
                self.patient_regex.setFocus()
                return message
        for label, field in (
            ("Tracking Excel File", self.tracking_excel_path),
            ("Master Tracking Excel File", self.global_tracking_excel_path),
        ):
            value = field.text().strip()
            if value and Path(value).suffix and Path(value).suffix.lower() != ".xlsx":
                message = f"{label} must use the .xlsx file type."
                field.setToolTip(message)
                field.setFocus()
                return message
        return None

    def _browse_dir(self, line_edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Directory",
            line_edit.text() or str(Path.home()),
        )
        if folder:
            line_edit.setText(folder)

    def _browse_excel_path(self) -> None:
        start_path = self.tracking_excel_path.text().strip() or self.default_output.text().strip() or str(Path.home())
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Select Tracking Excel File",
            start_path,
            "Excel Workbook (*.xlsx)",
        )
        if selected:
            self.tracking_excel_path.setText(selected)

    def _browse_global_tracking_excel_path(self) -> None:
        start_path = (
            self.global_tracking_excel_path.text().strip()
            or self.default_output.text().strip()
            or str(Path.home())
        )
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Select Master Tracking Excel File",
            start_path,
            "Excel Workbook (*.xlsx)",
        )
        if selected:
            if not selected.lower().endswith(".xlsx"):
                selected += ".xlsx"
            self.global_tracking_excel_path.setText(selected)

    def _sync_patient_regex_enabled(self) -> None:
        self.patient_regex.setEnabled(self.chk_agg_pat.isChecked())

    def _sync_scope_controls(self) -> None:
        is_custom = self.mode_combo.currentText() == "custom"
        self.assay_filter.setEnabled(is_custom)
