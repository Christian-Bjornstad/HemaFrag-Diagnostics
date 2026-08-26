"""HemaFrag — Compare tab.

Load FSA files from folders (like Batch Run), group them by patient ID,
and compare the selected files through the normal single-file pipeline.
Produces a multi-file side-by-side HTML comparison report grouped per
assay. If any file's ladder fit needs manual review, the analysis is
handed off to the Ladder Studio review flow (same gate as Batch Run).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class TabCompare(QWidget):
    """Patient-based multi-file comparison report generator."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker = None  # _CompareWorker, lazily imported (QThread)
        self._last_html: Path | None = None
        self._pending_review: dict | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        title = QLabel("<b>Sammenlign filer per pasient</b>")
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)

        info = QLabel(
            "Velg mappe(r) eller enkeltfiler (som i Kjør-fanen). Filene grupperes "
            "per pasient-ID — huk av pasientene (eller enkeltfiler) du vil "
            "sammenligne, og velg Sammenlign. Alle valgte filer analyseres og du "
            "får én HTML-rapport med plott og peak-tabeller gruppet per analyse."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Input rows ------------------------------------------------------
        row_folder = QHBoxLayout()
        self.input_dir = QLineEdit()
        self.input_dir.setPlaceholderText("Mappe med .fsa-filer (skannes rekursivt) …")
        btn_browse_dir = QPushButton("Velg mappe …")
        btn_browse_dir.clicked.connect(self._pick_dir)
        row_folder.addWidget(btn_browse_dir)
        row_folder.addWidget(self.input_dir, stretch=1)
        layout.addLayout(row_folder)

        row_files = QHBoxLayout()
        self.input_files = QLineEdit()
        self.input_files.setPlaceholderText("Eventuelle ekstra enkeltfiler …")
        btn_browse_files = QPushButton("Legg til filer …")
        btn_browse_files.clicked.connect(self._pick_files)
        row_files.addWidget(btn_browse_files)
        row_files.addWidget(self.input_files, stretch=1)
        layout.addLayout(row_files)

        # Patient-ID regex -------------------------------------------------
        row_regex = QHBoxLayout()
        row_regex.addWidget(QLabel("Pasient-ID regex:"))
        self.input_regex = QLineEdit()
        self.input_regex.setPlaceholderText(r"standard: \d{2}OUM\d{5}")
        row_regex.addWidget(self.input_regex, stretch=1)
        layout.addLayout(row_regex)

        # Scan + selection --------------------------------------------------
        actions = QHBoxLayout()
        self.btn_scan = QPushButton("Skann filer")
        self.btn_scan.clicked.connect(self._on_scan)
        self.btn_select_all = QPushButton("Velg alle pasienter")
        self.btn_select_all.clicked.connect(lambda: self._set_all_patients_checked(True))
        self.btn_select_none = QPushButton("Velg ingen")
        self.btn_select_none.clicked.connect(lambda: self._set_all_patients_checked(False))
        self.chk_exclude_qc = QCheckBox("Ekskluder QC-kontroller (PK/NK)")
        self.chk_exclude_qc.setChecked(False)
        actions.addWidget(self.btn_scan)
        actions.addWidget(self.btn_select_all)
        actions.addWidget(self.btn_select_none)
        actions.addWidget(self.chk_exclude_qc)
        actions.addStretch()
        layout.addLayout(actions)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Pasient / fil", "Antall"])
        self.tree.setColumnWidth(0, 460)
        layout.addWidget(self.tree, stretch=1)

        run_row = QHBoxLayout()
        self.btn_run = QPushButton("Sammenlign")
        self.btn_run.clicked.connect(self._on_compare)
        self.btn_open_ladder = QPushButton("Åpne Ladder Review")
        self.btn_open_ladder.setEnabled(False)
        self.btn_open_ladder.clicked.connect(self._open_ladder_review)
        self.btn_open_folder = QPushButton("Åpne rapportmappe")
        self.btn_open_folder.setEnabled(False)
        self.btn_open_folder.clicked.connect(self._open_report_dir)
        run_row.addWidget(self.btn_run)
        run_row.addWidget(self.btn_open_ladder)
        run_row.addWidget(self.btn_open_folder)
        run_row.addStretch()
        layout.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)  # indeterminate while running
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    # ------------------------------------------------------------------ I/O
    def _pick_dir(self) -> None:
        start = self.input_dir.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Velg mappe med .fsa-filer", start)
        if folder:
            self.input_dir.setText(folder)

    def _pick_files(self) -> None:
        start = str(Path(self.input_dir.text().strip())) if self.input_dir.text().strip() else ""
        paths, _ = QFileDialog.getOpenFileNames(self, "Velg FSA-filer", start, "FSA-filer (*.fsa)")
        if paths:
            self.input_files.setText("; ".join(paths))

    def _collect_input_files(self) -> list[Path]:
        files: list[Path] = []
        d = Path(self.input_dir.text().strip()).expanduser()
        if d.is_dir():
            files.extend(sorted(p for p in d.rglob("*.fsa") if p.is_file()))
        for raw in self.input_files.text().split(";"):
            p = Path(raw.strip()).expanduser()
            if p.is_file() and p not in files:
                files.append(p)
        return files

    # ----------------------------------------------------------------- scan
    def _on_scan(self) -> None:
        files = self._collect_input_files()
        if not files:
            QMessageBox.warning(
                self, "Compare", "Ingen .fsa-filer funnet. Velg en gyldig mappe eller filer."
            )
            return

        regex_text = self.input_regex.text().strip()
        from core.batch import group_files_by_patient

        groups = group_files_by_patient(files, regex_text or None)

        exclude_qc = self.chk_exclude_qc.isChecked()

        self.tree.clear()
        for pid in sorted(groups.keys()):
            group_files = sorted(groups[pid], key=lambda p: p.name.lower())
            if exclude_qc and pid == "QC":
                continue
            patient_item = QTreeWidgetItem([str(pid), str(len(group_files))])
            patient_item.setFlags(
                patient_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )
            patient_item.setCheckState(0, Qt.CheckState.Unchecked)
            for f in group_files:
                child = QTreeWidgetItem([f.name, ""])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                child.setData(0, Qt.ItemDataRole.UserRole, str(f))
                patient_item.addChild(child)
            # Checking/unchecking a patient toggles all its children
            patient_item.itemChanged.connect = None  # placeholder; handled globally below
            self.tree.addTopLevelItem(patient_item)

        total = sum(len(v) for k, v in groups.items() if not (exclude_qc and k == "QC"))
        n_patients = len([k for k in groups if not (exclude_qc and k == "QC")])
        self.status_label.setText(
            f"Funnet {len(files)} filer i {n_patients} grupper. "
            "Huk av pasientene du vil sammenligne."
        )

        if not hasattr(self, "_tree_wired"):
            self.tree.itemChanged.connect(self._on_item_changed)
            self._tree_wired = True

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        state = item.checkState(column)
        if item.parent() is None:
            # Patient toggled -> propagate to children without recursion storms
            self.tree.blockSignals(True)
            for i in range(item.childCount()):
                item.child(i).setCheckState(0, state)
            self.tree.blockSignals(False)

    def _set_all_patients_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            item.setCheckState(0, state)
            for j in range(item.childCount()):
                item.child(j).setCheckState(0, state)
        self.tree.blockSignals(False)

    def _selected_files(self) -> list[Path]:
        selected: list[Path] = []
        for i in range(self.tree.topLevelItemCount()):
            patient = self.tree.topLevelItem(i)
            for j in range(patient.childCount()):
                child = patient.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    selected.append(Path(str(child.data(0, Qt.ItemDataRole.UserRole))))
        return selected

    # --------------------------------------------------------------- compare
    def _on_compare(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Compare", "En sammenligning kjører allerede.")
            return

        paths = self._selected_files()
        if len(paths) < 2:
            QMessageBox.warning(
                self, "Compare", "Velg minst to filer å sammenligne."
            )
            return

        outdir = self._report_outdir()
        self.btn_run.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_open_folder.setEnabled(False)
        self.btn_open_ladder.setEnabled(False)
        self.progress.setRange(0, 0)  # busy
        self.status_label.setText(f"Starter analyse av {len(paths)} filer …")

        from gui_qt.tabs.tab_compare_worker import CompareWorker

        self._worker = CompareWorker(paths, outdir, parent=self)
        self._worker.progress.connect(self.status_label.setText)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.ladder_review_needed.connect(self._on_ladder_review_needed)
        self._worker.start()

    def _report_outdir(self) -> Path:
        from config import APP_SETTINGS

        base = APP_SETTINGS.get("output_root") or Path.home() / "Documents" / "HemaFrag"
        return Path(base) / "Comparisons"

    # ------------------------------------------------------------- callbacks
    def _on_done(self, html_path) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.btn_run.setEnabled(True)
        self.btn_scan.setEnabled(True)
        self.btn_open_folder.setEnabled(True)
        self._last_html = html_path
        self.status_label.setText(f"Rapport lagret: {html_path}")

        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(html_path)))

    def _on_failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.btn_run.setEnabled(True)
        self.btn_scan.setEnabled(True)
        self.status_label.setText(message.splitlines()[0] if message else message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Compare — feil")
        box.setText(message.splitlines()[0] if message else "Ukjent feil.")
        if len(message.splitlines()) > 1:
            # Traceback attached: show it in an expandable, copyable detail area.
            box.setDetailedText(message)
        box.exec()

    def _on_ladder_review_needed(self, payload: dict) -> None:
        """Ladder fit failed/review needed — offer handoff to Ladder Studio."""
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.btn_run.setEnabled(True)
        self.btn_scan.setEnabled(True)
        self._pending_review = payload

        bundle_dir = payload.get("bundle_dir")
        count = int(payload.get("count") or 0)
        names = ", ".join(payload.get("file_names", [])[:5])
        more = " …" if len(payload.get("file_names", [])) > 5 else ""

        self.btn_open_ladder.setEnabled(bool(bundle_dir))
        self.status_label.setText(
            f"{count} fil(er) trenger ladder-review: {names}{more}"
        )

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("Ladder Review Needed")
        message.setText(
            f"{count} fil(er) trenger manuell ladder-review før de kan sammenlignes."
        )
        message.setInformativeText(
            "Åpne Ladder Studio for å rette eller godkjenne ladder-fit. "
            "Filene som ble analysert OK er allerede klare — etter review kan du "
            "kjøre sammenligningen på nytt."
        )
        open_btn = message.addButton("Åpne Ladder Review", QMessageBox.ButtonRole.AcceptRole)
        message.addButton("Avbryt", QMessageBox.ButtonRole.RejectRole)
        message.exec()

        if message.clickedButton() == open_btn:
            self._open_ladder_review()

    def _open_ladder_review(self) -> None:
        payload = self._pending_review or {}
        bundle_dir = payload.get("bundle_dir")
        entries = payload.get("entries") or []
        if not bundle_dir:
            return
        window = self.window()
        ladder_tab = getattr(window, "tab_ladder", None)
        if ladder_tab is not None and hasattr(ladder_tab, "load_review_bundle_from_path"):
            ladder_tab.load_review_bundle_from_path(
                Path(bundle_dir),
                preloaded_entries=list(entries),
                auto_open_first=True,
            )
            if hasattr(window, "on_sub_tab_clicked"):
                current = getattr(window, "_current_analysis_id", None) or "clonality"
                window.on_sub_tab_clicked(current, 1)
            return
        # Fallback: reveal the bundle folder in Explorer
        import subprocess
        import sys

        subprocess.Popen(["explorer" if sys.platform == "win32" else "xdg-open", str(bundle_dir)])

    def _open_report_dir(self) -> None:
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        target = self._last_html
        folder = target.parent if target else self._report_outdir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
