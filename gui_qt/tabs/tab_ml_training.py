"""TabMlTraining — train per-assay ML models from inside the app.

Pick a tracking workbook, pick the assays to fit, point at an output
folder, and click Train. Mirrors ``clonality-ml-phase-5-real-data-2026-07-11``
``scripts/train_clonality_interpretation_models.py`` and the existing
``gui_qt/worker.py`` runner pattern.

The tab is intentionally simple — it deliberately does not start an
``QThread`` for predict; the training run is owned by an in-process
``QThread`` so the UI stays responsive. Status text + a Status bar
report what happened.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config import APP_SETTINGS


DEFAULT_ASSAYS = [
    "FR1", "FR2", "FR3",
    "IGK", "KDE",
    "TCRbA", "TCRbB", "TCRbC",
    "TCRgA", "TCRgB",
    "DHJH_D", "DHJH_E",
]


class _TrainWorker(QThread):
    """Spawn the CLI driver as a subprocess so we don't import heavy
    sklearn on the GUI thread. Status updates stream to stdout."""

    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str, str)  # (ok, summary, output_dir)

    def __init__(self, *, cmd: list[str], output_dir: str):
        super().__init__()
        self._cmd = cmd
        self._output_dir = output_dir

    def run(self) -> None:
        try:
            proc = subprocess.Popen(
                self._cmd,
                cwd=str(Path(__file__).resolve().parents[2]),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            self.log_signal.emit(f"Failed to launch python: {exc}")
            self.finished_signal.emit(False, "python not found", self._output_dir)
            return

        assert proc.stdout is not None
        summary_lines = []
        for line in proc.stdout:
            line = line.rstrip()
            self.log_signal.emit(line)
            summary_lines.append(line)
        rc = proc.wait()
        ok = rc == 0
        summary = "\n".join(summary_lines[-30:])
        self.finished_signal.emit(ok, summary, self._output_dir)


class TabMlTraining(QWidget):
    """In-app ML training launcher."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._worker: _TrainWorker | None = None
        self._build_ui()
        self._load_default_state()

    # ---- UI ----------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Clonality ML — Train Per-Assay Models")
        title.setObjectName("PageTitle")
        sub = QLabel(
            "Pick the tracking workbook with your labeled samples, choose the "
            "assays you want to fit, set the output folder, and click Train."
        )
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(sub)

        # --- source workbook card ---
        card = QWidget()
        card.setObjectName("Card")
        form = QFormLayout(card)

        self._xlsx_edit = QLineEdit()
        self._xlsx_edit.setPlaceholderText(
            "Path to Clonality_Tracking_All_*.xlsx (must contain ClonalityChemistLabel)"
        )
        xlsx_row = QHBoxLayout()
        xlsx_row.addWidget(self._xlsx_edit, stretch=1)
        xlsx_browse = QPushButton("Browse...")
        xlsx_browse.clicked.connect(self._browse_xlsx)
        xlsx_row.addWidget(xlsx_browse)
        form.addRow("Tracking Workbook:", xlsx_row)

        self._features_edit = QLineEdit()
        self._features_edit.setPlaceholderText(
            "Path to clonality_ml_trace_features.csv"
        )
        features_row = QHBoxLayout()
        features_row.addWidget(self._features_edit, stretch=1)
        features_browse = QPushButton("Browse...")
        features_browse.clicked.connect(self._browse_features)
        features_row.addWidget(features_browse)
        form.addRow("Trace Feature Dataset:", features_row)

        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText(
            "Defaults to <output_dir>/ml_models/<YYYY-MM-DD_HHMMSS>"
        )
        out_row = QHBoxLayout()
        out_row.addWidget(self._output_edit, stretch=1)
        out_browse = QPushButton("Browse...")
        out_browse.clicked.connect(self._browse_output)
        out_row.addWidget(out_browse)
        form.addRow("Model Output Folder:", out_row)

        self._classifier_combo = QComboBox()
        self._classifier_combo.addItems(["random_forest", "qda_calibrated"])
        form.addRow("Classifier:", self._classifier_combo)

        self._min_samples = QSpinBox()
        self._min_samples.setRange(10, 5000)
        self._min_samples.setValue(30)
        self._min_samples.setSingleStep(5)
        form.addRow("Min samples per assay:", self._min_samples)

        self._tau = QSpinBox()
        self._tau.setRange(50, 100)
        self._tau.setValue(80)
        self._tau.setSingleStep(5)
        self._tau.setSuffix(" %")
        form.addRow("Accept threshold τ:", self._tau)

        layout.addWidget(card)

        # --- assay picker ---
        assays_card = QWidget()
        assays_card.setObjectName("Card")
        a_layout = QVBoxLayout(assays_card)
        a_layout.addWidget(QLabel("<b>Assays to train</b>"))
        self._assays_list = QListWidget()
        self._assays_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for assay in DEFAULT_ASSAYS:
            item = QListWidgetItem(assay)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._assays_list.addItem(item)
        a_layout.addWidget(self._assays_list)

        all_off = QPushButton("Toggle all")
        all_off.clicked.connect(self._toggle_all_assays)
        a_layout.addWidget(all_off)
        layout.addWidget(assays_card)

        # --- run button + progress ---
        run_row = QHBoxLayout()
        self._train_btn = QPushButton("Train")
        self._train_btn.setObjectName("PrimaryButton")
        self._train_btn.clicked.connect(self._train_clicked)
        run_row.addWidget(self._train_btn)
        self._open_folder_btn = QPushButton("Open output folder")
        self._open_folder_btn.setEnabled(False)
        self._open_folder_btn.clicked.connect(self._open_output_clicked)
        run_row.addWidget(self._open_folder_btn)
        layout.addLayout(run_row)

        self._status_label = QLabel("")
        self._status_label.setObjectName("StatusBarText")
        layout.addWidget(self._status_label)
        layout.addStretch()

    def _load_default_state(self) -> None:
        # Pre-fill defaults from current Settings (matches
        # gui_qt/tabs/tab_settings.py).
        try:
            profile = APP_SETTINGS.get("analyses", {}).get("clonality", {})
            batch = profile.get("batch", {})
            xlsx = batch.get("tracking_excel_path", "")
            output_base = batch.get("output_base", "")
            if xlsx and Path(xlsx).exists():
                self._xlsx_edit.setText(str(xlsx))
                feature_candidate = (
                    Path(xlsx).parent
                    / "clonality_ml_features"
                    / "clonality_ml_trace_features.csv"
                )
                if feature_candidate.exists():
                    self._features_edit.setText(str(feature_candidate))
            elif output_base:
                # Default to a sensible tracking.xlsx location
                candidate = Path(output_base) / "Clonality_Tracking.xlsx"
                if candidate.exists():
                    self._xlsx_edit.setText(str(candidate))
            if output_base:
                stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
                self._output_edit.setText(
                    str(Path(output_base) / "ml_models" / f"run_{stamp}")
                )
        except Exception:
            pass  # Defaults are best-effort.

    # ---- handlers ----------------------------------------------------

    def _toggle_all_assays(self) -> None:
        any_checked = False
        for i in range(self._assays_list.count()):
            if self._assays_list.item(i).checkState() == Qt.CheckState.Checked:
                any_checked = True
                break
        target = Qt.CheckState.Unchecked if any_checked else Qt.CheckState.Checked
        for i in range(self._assays_list.count()):
            self._assays_list.item(i).setCheckState(target)

    def _selected_assays(self) -> list[str]:
        out: list[str] = []
        for i in range(self._assays_list.count()):
            item = self._assays_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out

    def _browse_xlsx(self) -> None:
        start = self._xlsx_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Tracking Workbook", start,
            "Excel files (*.xlsx);;All files (*.*)",
        )
        if path:
            self._xlsx_edit.setText(path)

    def _browse_output(self) -> None:
        start = self._output_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Output Folder", start)
        if folder:
            self._output_edit.setText(folder)

    def _browse_features(self) -> None:
        start = self._features_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Trace Feature Dataset",
            start,
            "CSV files (*.csv);;All files (*.*)",
        )
        if path:
            self._features_edit.setText(path)

    def _train_clicked(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._status_label.setText("Training already in progress.")
            return

        xlsx = self._xlsx_edit.text().strip()
        if not xlsx or not Path(xlsx).exists():
            self._status_label.setText("Pick a tracking workbook first.")
            return
        features_csv = self._features_edit.text().strip()
        if not features_csv or not Path(features_csv).is_file():
            self._status_label.setText("Pick a trace feature dataset first.")
            return
        output_dir = self._output_edit.text().strip()
        if not output_dir:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
            output_dir = str(Path(xlsx).parent / f"ml_models_{stamp}")
            self._output_edit.setText(output_dir)
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        assays = self._selected_assays()
        if not assays:
            self._status_label.setText("Pick at least one assay.")
            return

        cmd = [
            sys.executable,
            "-m",
            "scripts.train_clonality_interpretation_models",
            "--xls", xlsx,
            "--features-csv", features_csv,
            "--output-dir", output_dir,
            "--min-samples", str(self._min_samples.value()),
            "--classifier-kind", self._classifier_combo.currentText(),
            "--accept-threshold-tau", f"{self._tau.value() / 100.0:.2f}",
            "--assays", ",".join(assays),
        ]

        self._train_btn.setEnabled(False)
        self._status_label.setText(f"Training {len(assays)} assay(s) → {output_dir}")
        self._worker = _TrainWorker(cmd=cmd, output_dir=output_dir)
        self._worker.log_signal.connect(self._on_log_line)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.start()

    def _on_log_line(self, line: str) -> None:
        # Append to the global log tab if possible.
        try:
            from gui_qt.log_handler import qt_log_handler
            qt_log_handler.append(line)
        except Exception:
            pass

    def _on_finished(self, ok: bool, summary: str, output_dir: str) -> None:
        self._train_btn.setEnabled(True)
        self._open_folder_btn.setEnabled(True)
        if ok:
            self._status_label.setText(
                f"Training complete — candidate models and validation reports are in {output_dir}."
            )
        else:
            self._status_label.setText(
                f"FAILED — see log. Output dir kept at {output_dir}."
            )

    def _open_output_clicked(self) -> None:
        folder = self._output_edit.text().strip()
        if not folder:
            return
        Path(folder).mkdir(parents=True, exist_ok=True)
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception as exc:
            self._status_label.setText(f"Open failed: {exc}")
