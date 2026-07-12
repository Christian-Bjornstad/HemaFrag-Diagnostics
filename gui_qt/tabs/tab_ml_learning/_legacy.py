"""MlLearning tab widget (Phase A).

A first-class Tab in the Clonality group: browse -> pick folder -> analyse ->
group by assay -> pick sub-bucket -> render annotation panel.

Phase A ships the scaffold (helpers + widget skeleton + tests). Phase B
adds the Plotly annotation panel; Phase C adds the JSONL trainer bridge.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json

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
from gui_qt.tabs.tab_ml_learning._io import list_fsa_files, read_json, write_json
from gui_qt.tabs.tab_ml_learning._render import render_annotation_panel_html
from gui_qt.tabs.tab_ml_learning._feedback import (
    annotations_summary,
    feedback_paths,
    import_one,
    load_jsonl_records,
)
from gui_qt.tabs.tab_ml_learning._constants import (
    PANEL_ENTRIES_JSON_FILENAME,
    PANEL_HTML_FILENAME,
    SUBDIR_PANEL,
)
from gui_qt.tabs.tab_ml_learning._workers import AnalyzeWorker


def _default_panel_dir() -> Path:
    from config import APP_SETTINGS

    base = APP_SETTINGS.get("analyses", {}).get("clonality", {}).get(
        "learning", {}
    ).get("output_dir")
    return Path(base) if base else Path("ML_Learning")


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
        self._entries: list[dict[str, Any]] = []
        self._last_panel_path: Path | None = None
        self._last_panel_entries_path: Path | None = None
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
        self._open_panel_btn.setEnabled(False)  # enabled after the worker finishes
        self._open_panel_btn.clicked.connect(self._open_panel_clicked)
        action_row.addWidget(self._open_panel_btn)

        self._export_btn = QPushButton("Export annotations JSONL")
        self._export_btn.setEnabled(True)
        self._export_btn.clicked.connect(self._export_clicked)
        action_row.addWidget(self._export_btn)

        self._import_btn = QPushButton("Import panel annotations")
        self._import_btn.clicked.connect(self._import_clicked)
        action_row.addWidget(self._import_btn)

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
        # Re-render with the *current* selection (no re-persist if entries
        # unchanged - cheap disk write; alright for repeated clicks).
        if not self._entries:
            self._status_label.setText("Run analysis first.")
            return
        self._render_panel_now(persist=True)

    def _on_progress(self, current: int, total: int) -> None:
        self._status_label.setText(f"Analyzed {current}/{total} files...")

    def _on_finished(self, entries: list[dict[str, Any]]) -> None:
        self._running = False
        self._run_btn.setEnabled(True)
        self._entries = list(entries)
        self._render_panel_now(persist=True)
        self._open_panel_btn.setEnabled(bool(self._last_panel_path))
        if self._last_panel_path:
            self._status_label.setText(
                f"Run done. {len(entries)} cases. Panel at {self._last_panel_path}"
            )

    def _render_panel_now(self, *, persist: bool) -> None:
        """Render the single-file Plotly annotation panel and persist it.

        ``persist=True`` writes entries.json + review_panel.html to disk;
        ``persist=False`` keeps the in-memory data but skips disk (used when
        the chemist clicks ``Open annotation panel`` a second time).
        """
        if not self._entries:
            self._status_label.setText("Run analysis first; no entries yet.")
            return

        entries_subset = self._selected_subset() or self._entries
        try:
            panel_dir = _default_panel_dir() / "annotation"
            if persist:
                panel_dir.mkdir(parents=True, exist_ok=True)
                entries_path = panel_dir / PANEL_ENTRIES_JSON_FILENAME
                write_json(entries_path, entries_subset)
                self._last_panel_entries_path = entries_path
            panel_path = render_annotation_panel_html(
                entries_subset,
                out_dir=panel_dir,
                title="HemaFrag clone ML annotation",
                annotator="",
            )
            self._last_panel_path = panel_path
        except Exception as exc:  # pragma: no cover - safe failure
            self._status_label.setText(f"Panel render failed: {exc}")
            return

        # Open the panel in the system browser.
        try:
            import os
            import sys

            if sys.platform.startswith("win"):
                os.startfile(str(panel_path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{panel_path}"')
            else:
                os.system(f'xdg-open "{panel_path}"')
        except Exception:
            self._status_label.setText(
                f"Panel written: {panel_path} - open manually."
            )

    def _selected_subset(self) -> list[dict[str, Any]]:
        """Subset of _entries that user has *checked* in the table."""
        wanted = {str(p) for p in self.selected_paths()}
        return [
            e for e in self._entries
            if str(e.get("raw_path") or "") in wanted
        ]

    # ---- Phase C: import annotations exported by the panel --------------

    def _export_clicked(self) -> None:
        path = QFileDialog.getSaveFileName(
            self,
            "Save annotations JSONL",
            str(_default_panel_dir() / "annotations" / "learning.jsonl"),
            "JSONL (*.jsonl)",
        )[0]
        if not path:
            return
        target = Path(path)
        records = load_jsonl_records(
            feedback_paths(_default_panel_dir())["annotations_jsonl"]
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8") as fh:
                for rec in records:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as exc:
            self._status_label.setText(f"Export failed: {exc}")
            return
        self._status_label.setText(
            f"Exported {len(records)} annotations to {target}"
        )

    def _import_clicked(self) -> None:
        # Three options:
        #  (a) user picks a folder (default = ML_Learning/imports)
        #  (b) user picks a single file
        #  (c) the tab auto-scans the canonical imports dir regardless.
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Pick annotations-export folder (default = ML_Learning/imports)",
            str((_default_panel_dir() / "imports")),
        )
        folder = Path(chosen) if chosen else _default_panel_dir() / "imports"
        paths = feedback_paths(_default_panel_dir())
        paths["imports_dir"].parent.mkdir(parents=True, exist_ok=True)
        paths["imports_dir"].mkdir(parents=True, exist_ok=True)

        # If the user picked a different folder, symlink/copy its *.json
        # into the canonical imports dir so the manifest stays canonical.
        targets: list[Path] = []
        if folder.is_dir():
            for src in sorted(folder.glob("*.json")):
                # Copy into canonical imports dir for simplicity
                dst = paths["imports_dir"] / src.name
                try:
                    dst.write_bytes(src.read_bytes())
                    targets.append(dst)
                except Exception as exc:
                    self._status_label.setText(f"Copy {src.name} failed: {exc}")

        # Process every .json in the canonical imports dir
        total_imported = 0
        total_skipped = 0
        for src in sorted(paths["imports_dir"].glob("*.json")):
            try:
                payload = json.loads(src.read_text(encoding="utf-8"))
            except Exception:
                continue
            counts = import_one(
                source_path=src, payload=payload, paths=paths
            )
            total_imported += counts["imported"]
            total_skipped += counts["skipped"]

        summary = annotations_summary(
            load_jsonl_records(paths["annotations_jsonl"])
        )
        status_parts = [
            f"Imported {total_imported}",
            f"skipped {total_skipped}",
            f"total={summary['total']}",
        ]
        if summary["by_assay"]:
            ass = ", ".join(
                f"{a}={n}" for a, n in summary["by_assay"].items()
            )
            status_parts.append(f"by-assay=[{ass}]")
        self._status_label.setText(" | ".join(status_parts))

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
