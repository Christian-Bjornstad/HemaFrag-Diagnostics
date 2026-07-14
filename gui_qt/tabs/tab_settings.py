from __future__ import annotations

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
    QDoubleSpinBox,
)

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
        main_layout.addLayout(header)

        self.paths_card = self._build_paths_card()
        self.run_card = self._build_run_card()
        self.interpretation_card = self._build_interpretation_card()
        self.peak_window_card = self._build_peak_window_card()
        self.shared_card = self._build_shared_card()

        main_layout.addWidget(self.paths_card)
        main_layout.addWidget(self.run_card)
        if self.analysis_id == "clonality":
            main_layout.addWidget(self.interpretation_card)
        if self.analysis_id == "flt3":
            main_layout.addWidget(self.peak_window_card)
        main_layout.addWidget(self.shared_card)
        main_layout.addStretch()

        self.refresh_from_settings()

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
        card = QWidget()
        card.setObjectName("Card")
        layout = QFormLayout(card)

        layout.addRow(QLabel("<b>Clonality Interpretation Assistance</b>"))

        self.chk_clonality_interpretation = QCheckBox("Enable clonality interpretation assistance")
        layout.addRow("", self.chk_clonality_interpretation)

        self.clonality_model_path = QLineEdit()
        self.clonality_model_path.setPlaceholderText("Optional offline model.joblib path")
        row_model = QHBoxLayout()
        btn_browse_model = QPushButton("Browse...")
        btn_browse_model.clicked.connect(self._browse_clonality_model_path)
        row_model.addWidget(self.clonality_model_path, stretch=1)
        row_model.addWidget(btn_browse_model)
        layout.addRow("Experimental Model:", row_model)

        note = QLabel(
            "When enabled, HemaFrag adds experimental interpretation columns to clonality tracking output. "
            "Final report text is not changed."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b;")
        layout.addRow("", note)

        self.chk_clonality_learning = QCheckBox("Enable clonality learning annotation export")
        layout.addRow("", self.chk_clonality_learning)

        self.clonality_learning_output_dir = QLineEdit()
        self.clonality_learning_output_dir.setPlaceholderText("Leave blank to save beside the run output")
        row_learning = QHBoxLayout()
        btn_browse_learning = QPushButton("Browse...")
        btn_browse_learning.clicked.connect(lambda: self._browse_dir(self.clonality_learning_output_dir))
        row_learning.addWidget(self.clonality_learning_output_dir, stretch=1)
        row_learning.addWidget(btn_browse_learning)
        layout.addRow("Learning Export Folder:", row_learning)

        learning_note = QLabel(
            "When enabled, each clonality batch run writes annotation seed JSON/CSV for later model learning."
        )
        learning_note.setWordWrap(True)
        learning_note.setStyleSheet("color: #64748b;")
        layout.addRow("", learning_note)
        return card

    def _build_peak_window_card(self) -> QWidget:
        """FLT3 peak-area window card — only rendered for the FLT3 analysis."""
        card = QWidget()
        card.setObjectName("Card")
        layout = QFormLayout(card)

        layout.addRow(QLabel("<b>FLT3 Peak-Area Window (NPM1)</b>"))

        # Defaults pulled from the FLT3 config so the card surfaces the
        # current backend values rather than hardcoded mirrors.
        try:
            from core.analyses.flt3.config import (
                FLT3_NPM1_DEFAULT_HALF_WIDTH_BP,
                FLT3_PLOT_BP_WINDOWS,
                get_flt3_peak_window_settings,
            )
            default_bundle = get_flt3_peak_window_settings()
            default_x_min, default_x_max = FLT3_PLOT_BP_WINDOWS.get("NPM1", (290.0, 330.0))
            default_half = FLT3_NPM1_DEFAULT_HALF_WIDTH_BP
        except Exception:
            default_bundle = {"npm1_half_width_bp": 1.0, "npm1_x_min": 290.0, "npm1_x_max": 330.0}
            default_x_min, default_x_max = 290.0, 330.0
            default_half = 1.0

        self.npm1_half_width = QDoubleSpinBox()
        self.npm1_half_width.setRange(0.3, 5.0)
        self.npm1_half_width.setSingleStep(0.1)
        self.npm1_half_width.setDecimals(2)
        self.npm1_half_width.setValue(float(default_bundle.get("npm1_half_width_bp", default_half)))
        self.npm1_half_width.setToolTip(
            "Half-width (bp) of the local-sideband integration window used for NPM1 peak areas.\n"
            "1.0 bp matches GeneMapper's tight Gaussian; widen if shoulders leak into the reference range."
        )
        layout.addRow("NPM1 Half-width (bp):", self.npm1_half_width)

        self.npm1_x_min = QDoubleSpinBox()
        self.npm1_x_min.setRange(0.0, 999.0)
        self.npm1_x_min.setSingleStep(1.0)
        self.npm1_x_min.setDecimals(2)
        self.npm1_x_min.setValue(float(default_bundle.get("npm1_x_min", default_x_min)))
        self.npm1_x_min.setToolTip(
            f"Initial x-axis lower bound for the NPM1 plot (default {default_x_min:.1f} bp)."
        )
        layout.addRow("NPM1 X-axis lower bound (bp):", self.npm1_x_min)

        self.npm1_x_max = QDoubleSpinBox()
        self.npm1_x_max.setRange(1.0, 2000.0)
        self.npm1_x_max.setSingleStep(1.0)
        self.npm1_x_max.setDecimals(2)
        self.npm1_x_max.setValue(float(default_bundle.get("npm1_x_max", default_x_max)))
        self.npm1_x_max.setToolTip(
            f"Initial x-axis upper bound for the NPM1 plot (default {default_x_max:.1f} bp)."
        )
        layout.addRow("NPM1 X-axis upper bound (bp):", self.npm1_x_max)

        # keep upper bound > lower bound as the chemist edits
        self.npm1_x_min.valueChanged.connect(self._sync_npm1_window_bounds)
        self.npm1_x_max.valueChanged.connect(self._sync_npm1_window_bounds)

        note = QLabel(
            "These knobs only apply to NPM1 plots in the FLT3 analysis. "
            "The half-width affects area integration (peak area used in classification). "
            "The x-axis bounds set the report's *initial* zoom; you can still widen the "
            "view by zoom/pan or double-click reset inside the Plotly chart."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #64748b;")
        layout.addRow("", note)
        return card

    def _sync_npm1_window_bounds(self) -> None:
        """Enforce xmax > xmin + 1 bp while the chemist is editing the spinboxes."""
        xmin_value = float(self.npm1_x_min.value())
        xmax_value = float(self.npm1_x_max.value())
        if xmax_value - xmin_value < 1.0:
            # nudge the just-edited one back to keep at least 1 bp of window
            sender = self.sender()
            if sender is self.npm1_x_min:
                self.npm1_x_min.blockSignals(True)
                self.npm1_x_min.setValue(max(0.0, xmax_value - 1.0))
                self.npm1_x_min.blockSignals(False)
            elif sender is self.npm1_x_max:
                self.npm1_x_max.blockSignals(True)
                self.npm1_x_max.setValue(xmin_value + 1.0)
                self.npm1_x_max.blockSignals(False)

    def _build_shared_card(self) -> QWidget:
        card = QWidget()
        card.setObjectName("Card")
        layout = QFormLayout(card)
        layout.addRow(QLabel("<b>Shared App Settings & Engine</b>"))

        self.author = QLineEdit()
        layout.addRow("Author (for PDF templates):", self.author)

        self.d_min_r2_ok = QDoubleSpinBox()
        self.d_min_r2_ok.setRange(0, 1)
        self.d_min_r2_ok.setSingleStep(0.001)
        self.d_min_r2_ok.setDecimals(3)
        layout.addRow("Min R² (OK):", self.d_min_r2_ok)

        self.d_min_r2_warn = QDoubleSpinBox()
        self.d_min_r2_warn.setRange(0, 1)
        self.d_min_r2_warn.setSingleStep(0.001)
        self.d_min_r2_warn.setDecimals(3)
        layout.addRow("Min R² (WARN):", self.d_min_r2_warn)

        self.chk_use_rust_engine = QCheckBox("Use high performance Rust engine (BETA)")
        layout.addRow("", self.chk_use_rust_engine)

        self.engine_note = QLabel(
            "When enabled, HemaFrag uses the integrated Rust ladder-fitting engine. "
            "Turn it off to force the legacy Python ladder-fit path."
        )
        self.engine_note.setWordWrap(True)
        self.engine_note.setStyleSheet("color: #2563eb;")
        layout.addRow("", self.engine_note)

        btn_save = QPushButton(f"Save {self.analysis_label} Settings")
        btn_save.setObjectName("PrimaryButton")
        btn_save.clicked.connect(self.save)
        layout.addRow("", btn_save)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #22c55e; font-weight: 500;")
        layout.addRow("", self.status_lbl)
        return card

    def refresh_from_settings(self) -> None:
        analysis_settings = get_analysis_settings(self.analysis_id)
        batch_settings = analysis_settings.get("batch", {})
        pipeline_settings = analysis_settings.get("pipeline", {})
        interpretation_settings = analysis_settings.get("interpretation", {})
        learning_settings = analysis_settings.get("learning", {})
        general_settings = APP_SETTINGS.get("general", {})
        qc_settings = APP_SETTINGS.get("qc", {})
        self.default_input.setText(batch_settings.get("base_input_dir", str(Path.home())))
        self.default_output.setText(batch_settings.get("output_base", str(Path.home())))
        self.tracking_excel_path.setText(batch_settings.get("tracking_excel_path", ""))

        self.mode_combo.setCurrentText(pipeline_settings.get("mode", "all"))
        self.assay_filter.setText(pipeline_settings.get("assay_filter_substring", ""))
        self.chk_agg_pat.setChecked(bool(batch_settings.get("aggregate_by_patient", True)))
        self.patient_regex.setText(batch_settings.get("patient_id_regex", r"\d{2}OUM\d{5}"))
        self.chk_agg_dit.setChecked(bool(batch_settings.get("aggregate_dit_reports", True)))
        if self.analysis_id == "clonality":
            self.chk_clonality_interpretation.setChecked(bool(interpretation_settings.get("enabled", False)))
            self.clonality_model_path.setText(str(interpretation_settings.get("model_path", "") or ""))
            self.chk_clonality_learning.setChecked(bool(learning_settings.get("enabled", False)))
            self.clonality_learning_output_dir.setText(str(learning_settings.get("output_dir", "") or ""))
        if self.analysis_id == "flt3":
            # FLT3 peak-window block — pulled straight from the FLT3 accessor
            # so the GUI surfaces the *current* backend defaults if the
            # settings dict never bore a `peak_window` key.
            try:
                from core.analyses.flt3.config import get_flt3_peak_window_settings
                bundle = get_flt3_peak_window_settings()
            except Exception:
                bundle = {"npm1_half_width_bp": 1.0, "npm1_x_min": 290.0, "npm1_x_max": 330.0}
            self.npm1_half_width.setValue(float(bundle["npm1_half_width_bp"]))
            self.npm1_x_min.setValue(float(bundle["npm1_x_min"]))
            self.npm1_x_max.setValue(float(bundle["npm1_x_max"]))
        self._sync_patient_regex_enabled()
        self._sync_scope_controls()

        self.author.setText(general_settings.get("author", "OUS"))
        self.d_min_r2_ok.setValue(float(qc_settings.get("min_r2_ok", 0.995)))
        self.d_min_r2_warn.setValue(float(qc_settings.get("min_r2_warn", 0.990)))
        self.chk_use_rust_engine.setChecked(bool(APP_SETTINGS.get("engine", {}).get("use_rust", True)))

    def save(self) -> None:
        analyses = APP_SETTINGS.setdefault("analyses", {})
        profile = analyses.setdefault(self.analysis_id, {})
        batch_settings = profile.setdefault("batch", {})
        pipeline_settings = profile.setdefault("pipeline", {})
        interpretation_settings = profile.setdefault("interpretation", {})
        learning_settings = profile.setdefault("learning", {})

        batch_settings["base_input_dir"] = self.default_input.text().strip()
        batch_settings["output_base"] = self.default_output.text().strip()
        batch_settings["tracking_excel_path"] = self.tracking_excel_path.text().strip()
        batch_settings["aggregate_by_patient"] = self.chk_agg_pat.isChecked()
        batch_settings["patient_id_regex"] = self.patient_regex.text().strip()
        batch_settings["aggregate_dit_reports"] = self.chk_agg_dit.isChecked()

        pipeline_settings["mode"] = self.mode_combo.currentText()
        pipeline_settings["assay_filter_substring"] = self.assay_filter.text().strip()
        if self.analysis_id == "clonality":
            interpretation_settings["enabled"] = self.chk_clonality_interpretation.isChecked()
            interpretation_settings["model_path"] = self.clonality_model_path.text().strip()
            learning_settings["enabled"] = self.chk_clonality_learning.isChecked()
            learning_settings["output_dir"] = self.clonality_learning_output_dir.text().strip()
        if self.analysis_id == "flt3":
            peak_window_settings = profile.setdefault("peak_window", {})
            peak_window_settings["npm1_half_width_bp"] = float(self.npm1_half_width.value())
            peak_window_settings["npm1_x_min"] = float(self.npm1_x_min.value())
            peak_window_settings["npm1_x_max"] = float(self.npm1_x_max.value())

        if APP_SETTINGS.get("active_analysis") == self.analysis_id:
            APP_SETTINGS.setdefault("batch", {}).update(batch_settings)
            APP_SETTINGS.setdefault("pipeline", {}).update(pipeline_settings)

        APP_SETTINGS.setdefault("general", {})["author"] = self.author.text().strip()
        APP_SETTINGS.setdefault("qc", {})["min_r2_ok"] = self.d_min_r2_ok.value()
        APP_SETTINGS.setdefault("qc", {})["min_r2_warn"] = self.d_min_r2_warn.value()
        APP_SETTINGS.setdefault("engine", {})["use_rust"] = self.chk_use_rust_engine.isChecked()

        save_settings(APP_SETTINGS)
        self.settings_saved.emit(self.analysis_id)
        self.status_lbl.setText(f"{self.analysis_label} settings saved.")

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

    def _browse_clonality_model_path(self) -> None:
        start_path = self.clonality_model_path.text().strip() or self.default_output.text().strip() or str(Path.home())
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select Clonality Interpretation Model",
            start_path,
            "Joblib Model (*.joblib);;All Files (*)",
        )
        if selected:
            self.clonality_model_path.setText(selected)

    def _sync_patient_regex_enabled(self) -> None:
        self.patient_regex.setEnabled(self.chk_agg_pat.isChecked())

    def _sync_scope_controls(self) -> None:
        is_custom = self.mode_combo.currentText() == "custom"
        self.assay_filter.setEnabled(is_custom)
