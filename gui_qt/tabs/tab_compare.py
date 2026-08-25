"""HemaFrag — Compare tab.

Pick two FSA files (same assay), analyze both through the normal
single-file pipeline, and produce a side-by-side HTML comparison
report that opens in the default browser.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _CompareWorker(QThread):
    """Analyzes two files and builds the comparison report off the UI thread."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(object)   # Path to generated HTML
    failed = pyqtSignal(str)

    def __init__(self, path_a: str, path_b: str, outdir: Path, parent=None) -> None:
        super().__init__(parent)
        self._paths = (path_a, path_b)
        self._outdir = outdir

    def run(self) -> None:  # noqa: D102 - QThread override
        try:
            entries: list[dict] = []
            for idx, raw in enumerate(self._paths):
                label = "A" if idx == 0 else "B"
                self.progress.emit(f"Analyserer fil {label}: {Path(raw).name} …")
                entry = self._analyze_one(Path(raw))
                if entry is None:
                    self.failed.emit(
                        f"Kunne ikke analysere fil {label} ({Path(raw).name}). "
                        "Sjekk at det er en gyldig FSA-fil for aktiv analyse."
                    )
                    return
                entries.append(entry)

            assay_a = entries[0].get("assay", "")
            assay_b = entries[1].get("assay", "")
            if assay_a != assay_b:
                self.failed.emit(
                    f"Filene tilhører forskjellige analyser ({assay_a} vs {assay_b}) "
                    "og kan ikke sammenlignes."
                )
                return

            self.progress.emit("Bygger sammenligningsrapport …")
            from core.html_reports.comparison import build_comparison_html_report

            html_path = build_comparison_html_report(
                entries[0],
                entries[1],
                self._outdir,
            )
            self.finished_ok.emit(html_path)
        except Exception as ex:  # pragma: no cover - defensive UI guard
            self.failed.emit(f"{type(ex).__name__}: {ex}")

    @staticmethod
    def _analyze_one(path: Path) -> dict | None:
        from core.analyses.clonality.pipeline import _analyze_single_file

        try:
            return _analyze_single_file(path)
        except Exception:
            return None


class TabCompare(QWidget):
    """Two-file side-by-side comparison report generator."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: _CompareWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        title = QLabel("<b>Sammenlign to FSA-filer</b>")
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)

        info = QLabel(
            "Velg to filer fra samme analyse (f.eks. samme pasient kjørt to ganger, "
            "eller to ulike pasienter). Begge filene analyseres, og du får en "
            "HTML-rapport med plott og peak-tabeller side om side."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # File A row -----------------------------------------------------
        row_a = QHBoxLayout()
        self.input_a = QLineEdit()
        self.input_a.setPlaceholderText("Fil A …")
        btn_a = QPushButton("Velg fil A …")
        btn_a.clicked.connect(lambda: self._pick(self.input_a))
        row_a.addWidget(btn_a)
        row_a.addWidget(self.input_a, stretch=1)
        layout.addLayout(row_a)

        # File B row -----------------------------------------------------
        row_b = QHBoxLayout()
        self.input_b = QLineEdit()
        self.input_b.setPlaceholderText("Fil B …")
        btn_b = QPushButton("Velg fil B …")
        btn_b.clicked.connect(lambda: self._pick(self.input_b))
        row_b.addWidget(btn_b)
        row_b.addWidget(self.input_b, stretch=1)
        layout.addLayout(row_b)

        # Actions --------------------------------------------------------
        actions = QHBoxLayout()
        self.btn_run = QPushButton("Sammenlign")
        self.btn_run.clicked.connect(self._on_compare)
        self.btn_open_folder = QPushButton("Åpne rapportmappe")
        self.btn_open_folder.setEnabled(False)
        self.btn_open_folder.clicked.connect(self._open_report_dir)
        actions.addWidget(self.btn_run)
        actions.addWidget(self.btn_open_folder)
        actions.addStretch()
        layout.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)  # indeterminate while running
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch()

    # ------------------------------------------------------------------
    def _pick(self, line_edit: QLineEdit) -> None:
        start_dir = str(Path(line_edit.text()).parent) if line_edit.text() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Velg FSA-fil", start_dir, "FSA-filer (*.fsa)"
        )
        if path:
            line_edit.setText(path)

    def _on_compare(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Compare", "En sammenligning kjører allerede.")
            return

        path_a = self.input_a.text().strip()
        path_b = self.input_b.text().strip()
        missing = [lbl for lbl, p in (("A", path_a), ("B", path_b)) if not p]
        if missing:
            QMessageBox.warning(self, "Compare", f"Mangler fil{'er' if len(missing) > 1 else ''}: {', '.join(missing)}")
            return
        for lbl, p in (("A", path_a), ("B", path_b)):
            if not Path(p).is_file():
                QMessageBox.warning(self, "Compare", f"Fil {lbl} finnes ikke:\n{p}")
                return
        if Path(path_a).resolve() == Path(path_b).resolve():
            QMessageBox.warning(self, "Compare", "Velg to ulike filer.")

        outdir = self._report_outdir()
        self.btn_run.setEnabled(False)
        self.btn_open_folder.setEnabled(False)
        self.progress.setRange(0, 0)  # busy
        self.status_label.setText("Starter analyse …")

        self._worker = _CompareWorker(path_a, path_b, outdir, parent=self)
        self._worker.progress.connect(self.status_label.setText)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _report_outdir(self) -> Path:
        from config import APP_SETTINGS

        base = APP_SETTINGS.get("output_root") or Path.home() / "Documents" / "HemaFrag"
        return Path(base) / "Comparisons"

    def _on_done(self, html_path) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.btn_run.setEnabled(True)
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
        self.status_label.setText(message)
        QMessageBox.critical(self, "Compare", message)

    def _open_report_dir(self) -> None:
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl

        target = getattr(self, "_last_html", None)
        folder = Path(target).parent if target else self._report_outdir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
