"""Background worker for the Compare tab.

Analyzes the selected FSA files through the normal single-file pipeline
and builds a multi-file comparison HTML report. Files whose ladder fit
needs manual review are collected and reported through the
``ladder_review_needed`` signal together with a review-bundle path so the
GUI can hand off to Ladder Studio (same gate as Batch Run).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


class CompareWorker(QThread):
    """Analyze N files and build the group comparison report off-thread."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(object)          # Path to generated HTML
    failed = pyqtSignal(str)
    ladder_review_needed = pyqtSignal(dict)   # {bundle_dir, count, file_names, entries}

    def __init__(self, paths: list[Path], outdir: Path, parent=None) -> None:
        super().__init__(parent)
        self._paths = list(paths)
        self._outdir = Path(outdir)

    # ------------------------------------------------------------------ run
    def run(self) -> None:  # noqa: D102 - QThread override
        try:
            entries: list[dict] = []
            review_entries: list[dict] = []

            for idx, raw in enumerate(self._paths, start=1):
                name = Path(raw).name
                self.progress.emit(f"Analyserer fil {idx}/{len(self._paths)}: {name} …")
                result = self._analyze_one(Path(raw))
                if result is None:
                    self.failed.emit(
                        f"Kunne ikke analysere fil {idx}/{len(self._paths)} ({name}). "
                        "Sjekk at det er en gyldig FSA-fil for aktiv analyse."
                    )
                    return
                if isinstance(result.get("analysis_status"), str) and result[
                    "analysis_status"
                ] == "ladder_review_only":
                    review_entries.append(result)
                    continue
                entries.append(result)

            if not entries:
                payload = self._build_review_payload(review_entries)
                if payload is not None:
                    self.ladder_review_needed.emit(payload)
                    return
                self.failed.emit(
                    "Ingen av filene kunne analyseres. Sjekk at det er gyldige "
                    "FSA-filer for aktiv analyse."
                )
                return

            assays = sorted({str(e.get("assay") or "") for e in entries})
            if len(assays) > 1:
                self.failed.emit(
                    "Filene tilhører forskjellige analyser ("
                    + ", ".join(assays)
                    + ") og kan ikke sammenlignes i én rapport."
                )
                return

            from core.html_reports.comparison import build_group_comparison_html_report

            self.progress.emit(f"Bygger sammenligningsrapport ({len(entries)} filer) …")
            html_path = build_group_comparison_html_report(entries, self._outdir)
            self.finished_ok.emit(html_path)

            # Report built fine, but some files still need ladder review —
            # surface it after success so nothing gets silently lost.
            if review_entries:
                payload = self._build_review_payload(review_entries)
                if payload is not None:
                    self.ladder_review_needed.emit(payload)

        except Exception as ex:  # pragma: no cover - defensive UI guard
            self.failed.emit(f"{type(ex).__name__}: {ex}")

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _analyze_one(path: Path) -> dict | None:
        from core.analyses.clonality.pipeline import _analyze_single_file

        try:
            return _analyze_single_file(path)
        except Exception:
            return None

    def _build_review_payload(self, review_entries: list[dict]) -> dict | None:
        """Write a review bundle (like Batch Run) and shape the GUI payload."""
        if not review_entries:
            return None

        try:
            from core.analyses.clonality.ladder_review_gate import (
                write_ladder_review_gate,
            )

            bundle_root = self._outdir / "ladder_review_bundles" / "compare"
            bundle_root.mkdir(parents=True, exist_ok=True)
            gate = write_ladder_review_gate(review_entries, bundle_root, source="compare")
            cases_path = gate.get("cases_path")
            bundle_dir = str(Path(str(cases_path)).parent) if cases_path else str(bundle_root)
        except Exception:
            # Gate artifact failed; still let the user open Ladder Studio with
            # the in-memory entries so nothing blocks on infrastructure.
            bundle_dir = ""

        names = [
            str(e.get("file_name") or getattr(e.get("fsa"), "file_name", "?"))
            for e in review_entries
        ]
        return {
            "bundle_dir": bundle_dir or None,
            "count": len(review_entries),
            "file_names": names,
            "entries": review_entries,
        }
