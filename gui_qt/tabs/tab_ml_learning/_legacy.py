"""MlLearning tab widget (Phase A).

A first-class Tab in the Clonality group: browse -> pick folder -> analyse ->
group by assay -> pick sub-bucket -> render annotation panel.

Phase A ships the scaffold (helpers + widget skeleton + tests). Phase B
adds the Plotly annotation panel; Phase C adds the JSONL trainer bridge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.analyses.clonality.config import ASSAY_DISPLAY_ORDER
from gui_qt.tabs.tab_ml_learning._summary import (
    group_by_assay,
    infer_assay,
    summarize_run,
)
from gui_qt.tabs.tab_ml_learning._io import list_fsa_files, write_json
from gui_qt.tabs.tab_ml_learning._workers import AnalyzeWorker


class TabMlLearning(QWidget):
    """Klonalitet / ML Learning tab.

    Public surface (kept stable as Phase B/C/D add features):
        set_root(folder): set the input folder and refresh the file table.
        set_assay(assay_key): pick a single assay from the dropdown.
        run_now(): trigger the AnalyzeWorker over the candidate files.
        selected_paths() -> list[Path]: paths currently checked in the table.
    """

    HEADERS = (
        "Selected",
        "Ord",
        "File",
        "Assay",
        "Kind",
        "DIT",
        "Peaks (raw/in)",
        "Dom bp",
        "Dom h",
        "QC",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._root: Path | None = None
        self._assay_order: tuple[str, ...] = tuple(ASSAY_DISPLAY_ORDER)
        self._candidate_paths: list[Path] = []
        self._grouped: dict[str, list[Path]] = {}
        self._running = False
        self._build_ui()

    # ---- UI --------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        title = QLabel("Clonality — ML Learning Annotation")
        title.setObjectName("PageTitle")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self._root_label = QLabel("(no folder loaded)")
        self._root_label.setObjectName("StatusBarText")
        toolbar.addWidget(self._root_label)

        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.clicked.connect(self._browse_clicked)
        toolbar.addWidget(self._browse_btn)

        layout.addLayout(toolbar)

        # Run row + assay + summary
        run_row = QHBoxLayout()
        self._assay_combo = QComboBox()
        self._assay_combo.setMinimumWidth(220)
        self._assay_combo.addItem("(all assays)")
        for assay in self._assay_order:
            self._assay_combo.addItem(assay)
        self._assay_combo.currentIndexChanged.connect(self._refresh_table)
        run_row.addWidget(QLabel("Assay:"))
        run_row.addWidget(self._assay_combo)

        self._disagreements_only = QCheckBox("Skip controls")
        self._disagreements_only.toggled.connect(self._refresh_table)
        run_row.addWidget(self._disagreements_only)

        run_row.addStretch()

        self._summary_label = QLabel("Pick a folder to start")
        self._summary_label.setObjectName("StatusBarText")
        run_row.addWidget(self._summary_label)
        layout.addLayout(run_row)

        # Run buttons row
        action_row = QHBoxLayout()
        self._run_btn = QPushButton("Run analysis")
        self._run_btn.clicked.connect(self._run_clicked)
        action_row.addWidget(self._run_btn)

        self._open_panel_btn = QPushButton("Open annotation panel")
        self._open_panel_btn.setEnabled(False)  # wired in Phase B
        self._open_panel_btn.clicked.connect(self._open_panel_clicked)
        action_row.addWidget(self._open_panel_btn)

        self._export_btn = QPushButton("Export annotations JSONL")
        self._export_btn.setEnabled(False)  # wired in Phase C
        action_row.addWidget(self._export_btn)

        action_row.addStretch()
        layout.addLayout(action_row)

        # File table
        self._table = QTableWidget(0, len(self.HEADERS), self)
        self._table.setHorizontalHeaderLabels(self.HEADERS)
        header = self._table.horizontalHeader()
        for i in range(len(self.HEADERS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.HEADERS.index("File"), QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table, stretch=1)

        self._status_label = QLabel("No folders loaded.")
        self._status_label.setObjectName("StatusBarText")
        layout.addWidget(self._status_label)

    # ---- Phase A API -----------------------------------------------------

    def set_root(self, folder: Path | str | None) -> int:
        """Set the input folder; refresh file inventory; return file count."""
        if folder is None:
            self._root = None
            self._candidate_paths = []
            self._grouped = {}
        else:
            self._root = Path(folder)
            self._candidate_paths = list_fsa_files(self._root)
            self._grouped = group_by_assay(
                self._candidate_paths, assay_order=self._assay_order
            )
        return len(self._candidate_paths)

    def set_assay(self, assay_key: str) -> None:
        if not assay_key:
            self._assay_combo.setCurrentIndex(0)
            return
        idx = self._assay_combo.findText(assay_key)
        if idx >= 0:
            self._assay_combo.setCurrentIndex(idx)

    def run_now(self) -> int:
        """Trigger a synchronous-feel async AnalyzeWorker; return path count."""
        if self._running or not self._candidate_paths:
            return 0
        self._run_btn.setEnabled(False)
        self._running = True
        # Phase A: surface the working subset for the GUI; the actual
        # data is captured by entries saved in local_triage / ML_Learning
        # in Phase B/C.
        self._worker = AnalyzeWorker(self._candidate_paths)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_with_entries.connect(self._on_finished)
        self._worker.status.connect(self._status_label.setText)
        self._worker.start()
        return len(self._candidate_paths)

    def selected_paths(self) -> list[Path]:
        """Return the subset of paths currently ``Checked`` in the file table."""
        out: list[Path] = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                path = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(path, Path):
                    out.append(path)
        return out

    # ---- internal slots --------------------------------------------------

    def _browse_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Pick FSA folder", str(self._root or Path.cwd())
        )
        if not folder:
            return
        count = self.set_root(folder)
        self._refresh_summary(n_files=count)
        self._refresh_table()
        self._root_label.setText(str(self._root))

    def _run_clicked(self) -> None:
        self.run_now()

    def _open_panel_clicked(self) -> None:
        # Phase B ships the actual implementation. Placeholder keeps the
        # button clickable + responsive for headless tests today.
        self._status_label.setText("Annotation panel: Phase B will wire this.")

    def _on_progress(self, current: int, total: int) -> None:
        self._status_label.setText(f"Analyzed {current}/{total} files...")

    def _on_finished(self, entries: list[dict[str, Any]]) -> None:
        self._running = False
        self._run_btn.setEnabled(True)
        self._status_label.setText(
            f"Run done. {len(entries)} files annotated. Phase B will open the panel."
        )

    def _refresh_table(self) -> None:
        self._table.setRowCount(0)
        if not self._candidate_paths:
            return

        # Pick the list to display
        assay_idx = self._assay_combo.currentIndex()
        if assay_idx == 0:
            files_to_show = list(self._candidate_paths)
        else:
            assay_key = self._assay_combo.itemText(assay_idx)
            files_to_show = list(self._grouped.get(assay_key) or [])

        if self._disagreements_only.isChecked():
            files_to_show = [
                f for f in files_to_show
                if not f.name.upper().startswith(("NK_", "PK_", "RK_"))
            ]

        for ordinal, raw_path in enumerate(files_to_show, start=1):
            row = self._table.rowCount()
            self._table.insertRow(row)

            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
            )
            check_item.setCheckState(Qt.CheckState.Checked)
            check_item.setData(Qt.ItemDataRole.UserRole, raw_path)
            self._table.setItem(row, 0, check_item)

            self._table.setItem(row, 1, QTableWidgetItem(f"{ordinal:03d}"))
            self._table.setItem(row, 2, QTableWidgetItem(raw_path.name))
            self._table.setItem(
                row, 3,
                QTableWidgetItem(infer_assay(raw_path) or ""),
            )
            stem = raw_path.name.upper()
            kind = "control" if stem.startswith(("NK_", "PK_", "RK_")) else "patient"
            self._table.setItem(row, 4, QTableWidgetItem(kind))
            self._table.setItem(row, 5, QTableWidgetItem(""))  # DIT column filled after Analyse
            self._table.setItem(row, 6, QTableWidgetItem("0/0"))
            self._table.setItem(row, 7, QTableWidgetItem(""))
            self._table.setItem(row, 8, QTableWidgetItem(""))
            self._table.setItem(row, 9, QTableWidgetItem(""))

    def _refresh_summary(self, *, n_files: int) -> None:
        summary = summarize_run(self._candidate_paths, assay_order=self._assay_order)
        per_assay = ", ".join(
            f"{a}={n}"
            for a, n in summary["by_assay"].items()
            if n > 0
        )
        self._summary_label.setText(
            f"{n_files} files | {per_assay or '0 assays'} | "
            f"DITs={summary['dit_distinct']} | "
            f"ctrl={summary['control_count']} pat={summary['patient_count']}"
        )


__all__ = ["TabMlLearning"]
