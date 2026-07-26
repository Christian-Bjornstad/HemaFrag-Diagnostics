"""Labeling session model — load tracking Excel, iterate samples, write
labels back. Used by the in-app Labeling tab so the chemist can view
plots and assign clonality labels without leaving the GUI.

The chemist's daily loop:
1. Open tracking Excel (the one the batch produces)
2. For each sample row: see the FSA plot → press a number key → label
3. Save back to Excel

Label set mirrors ``ANNOTATION_CLASSES_ORDER`` from ml_training — same
Norwegian labels, same order, so ML training and labeling speak the
same vocabulary.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook

logger = logging.getLogger(__name__)

# Re-export the canonical label order so the GUI and the trainer never
# drift. These are Norwegian — the chemist's working language.
from core.analyses.clonality.ml_training import ANNOTATION_CLASSES_ORDER
from core.analyses.clonality.ml_data_contract import (
    CHEMIST_LABEL_COLUMN,
    load_tracking_run_table,
)

# Keyboard shortcut map — number key → label string.
# Mirrors the order in ANNOTATION_CLASSES_ORDER.
LABEL_KEYS: dict[str, str] = {
    "1": "monoklonal",
    "2": "polyklonal",
    "3": "bi_oligoklonal",
    "4": "irregulaer",
    "5": "pseudoklonal",
    "6": "intet_pcr_produkt_darlig_dna",
    "7": "qc_teknisk_fail",
    "8": "usikker_review",
}

# Reverse lookup: label → shortcut key.
LABEL_TO_KEY: dict[str, str] = {v: k for k, v in LABEL_KEYS.items()}

# Keep the chemist annotation separate from the rule-based suggestion.
LABEL_COLUMN = CHEMIST_LABEL_COLUMN


@dataclass
class LabelingSample:
    """One row from the tracking Excel, ready for labeling."""
    index: int  # row position in the original DataFrame
    dit: str
    assay: str
    well: str
    file_name: str
    source_run_dir: str
    current_label: str = ""
    identity_key: str = ""
    sample_kind: str = ""
    group: str = ""
    tracking_sheet: str = ""
    tracking_row_number: int = 0

    @property
    def is_labeled(self) -> bool:
        return bool(self.current_label and self.current_label.strip())


@dataclass
class LabelingSession:
    """In-memory model: load Excel → iterate → label → save back.

    Does NOT touch the GUI — this is pure data. The tab widget wraps it.
    """
    excel_path: str
    include_controls: bool = False
    include_size_ladders: bool = False
    samples: list[LabelingSample] = field(default_factory=list)
    _df: pd.DataFrame | None = None
    _dirty: bool = False
    _primary_sheet: str = ""
    _available_sheets: tuple[str, ...] = field(default_factory=tuple)

    def load(self) -> None:
        """Load tracked injections from current or legacy workbook sheets."""
        table = load_tracking_run_table(
            self.excel_path,
            include_controls=self.include_controls,
        )
        df = table.frame
        if not self.include_size_ladders and "Assay" in df.columns:
            assay = df["Assay"].fillna("").astype(str).str.strip().str.upper()
            df = df.loc[assay.ne("SL")].reset_index(drop=True)
        self._primary_sheet = table.primary_sheet
        self._available_sheets = table.available_sheets
        if LABEL_COLUMN in df.columns:
            df[LABEL_COLUMN] = df[LABEL_COLUMN].where(pd.notna(df[LABEL_COLUMN]), "").astype(object)
        else:
            df[LABEL_COLUMN] = ""
        self._df = df

        self.samples = []
        for idx, row in df.iterrows():
            def _str(col):
                v = row.get(col, "")
                return str(v) if pd.notna(v) else ""
            sample = LabelingSample(
                index=int(idx) if pd.notna(idx) else len(self.samples),
                dit=_str("DIT"),
                assay=_str("Assay"),
                well=_str("Well"),
                file_name=_str("File"),
                source_run_dir=_str("SourceRunDir"),
                current_label=_str(LABEL_COLUMN),
                identity_key=_str("IdentityKey"),
                sample_kind=_str("SampleKind"),
                group=_str("Group"),
                tracking_sheet=_str("_TrackingSheet"),
                tracking_row_number=int(row.get("_TrackingRowNumber", idx + 2) or idx + 2),
            )
            self.samples.append(sample)

        logger.info("Loaded %d samples from %s", len(self.samples), self.excel_path)

    @property
    def total_count(self) -> int:
        return len(self.samples)

    @property
    def labeled_count(self) -> int:
        return sum(1 for s in self.samples if s.is_labeled)

    @property
    def unlabeled_count(self) -> int:
        return self.total_count - self.labeled_count

    def label_sample(self, sample_index: int, label: str) -> None:
        """Set the label on sample at ``sample_index`` (0-based in ``self.samples``)."""
        if not (0 <= sample_index < len(self.samples)):
            raise IndexError(f"sample_index {sample_index} out of range (0-{len(self.samples) - 1})")
        if label and label not in ANNOTATION_CLASSES_ORDER:
            raise ValueError(
                f"Unknown label '{label}'. Valid: {list(ANNOTATION_CLASSES_ORDER)}"
            )
        sample = self.samples[sample_index]
        sample.current_label = label
        self._dirty = True

    def clear_label(self, sample_index: int) -> None:
        """Remove the label from a sample."""
        self.label_sample(sample_index, "")

    def save_to_excel(self) -> int:
        """Write current labels back to the Excel. Returns number of labels written."""
        if self._df is None:
            raise RuntimeError("No Excel loaded — call load() first")

        if LABEL_COLUMN not in self._df.columns:
            self._df[LABEL_COLUMN] = ""
        self._df[LABEL_COLUMN] = self._df[LABEL_COLUMN].where(
            pd.notna(self._df[LABEL_COLUMN]), ""
        ).astype(object)

        changed: list[LabelingSample] = []
        for sample in self.samples:
            if 0 <= sample.index < len(self._df):
                old_raw = self._df.at[self._df.index[sample.index], LABEL_COLUMN]
                old_val = str(old_raw) if pd.notna(old_raw) else ""
                new_val = sample.current_label
                if old_val != new_val:
                    self._df.at[self._df.index[sample.index], LABEL_COLUMN] = new_val
                    changed.append(sample)

        if changed:
            self._write_changed_labels(changed)

        self._dirty = False
        logger.info("Wrote %d labels to %s", len(changed), self.excel_path)
        return len(changed)

    def _write_changed_labels(self, changed: list[LabelingSample]) -> None:
        """Update label cells in-place so workbook formatting is preserved."""
        wb = load_workbook(self.excel_path)
        try:
            target_names = {sample.tracking_sheet for sample in changed if sample.tracking_sheet}
            target_names.add(self._primary_sheet)
            if self._primary_sheet == "Runs":
                target_names.update({"Patient_Runs", "Control_Runs"})

            for sheet_name in sorted(target_names):
                if not sheet_name or sheet_name not in wb.sheetnames:
                    continue
                ws = wb[sheet_name]
                headers = {
                    str(cell.value or "").strip(): cell.column
                    for cell in ws[1]
                    if str(cell.value or "").strip()
                }
                label_col = headers.get(LABEL_COLUMN)
                if label_col is None:
                    label_col = ws.max_column + 1
                    ws.cell(1, label_col, LABEL_COLUMN)
                identity_col = headers.get("IdentityKey")

                identity_rows: dict[str, list[int]] = {}
                if identity_col is not None:
                    for row_number in range(2, ws.max_row + 1):
                        identity = str(ws.cell(row_number, identity_col).value or "").strip()
                        if identity:
                            identity_rows.setdefault(identity, []).append(row_number)

                for sample in changed:
                    row_numbers = identity_rows.get(sample.identity_key, []) if sample.identity_key else []
                    if not row_numbers and sheet_name == sample.tracking_sheet and sample.tracking_row_number >= 2:
                        row_numbers = [sample.tracking_row_number]
                    for row_number in row_numbers:
                        ws.cell(row_number, label_col, sample.current_label)
            wb.save(self.excel_path)
        finally:
            wb.close()

    def filter_unlabeled(self) -> list[int]:
        """Return the indices (into ``self.samples``) of unlabeled samples."""
        return [i for i, s in enumerate(self.samples) if not s.is_labeled]

    def fsa_path_for(self, sample_index: int, fsa_root: str) -> Path | None:
        """Resolve the FSA file path for a sample, given the FSA root dir."""
        if not (0 <= sample_index < len(self.samples)):
            return None
        sample = self.samples[sample_index]
        if not sample.file_name:
            return None
        root = Path(fsa_root)
        if sample.source_run_dir:
            # source_run_dir is typically a folder name like "2025_01_15_FR1_..."
            candidate = root / sample.source_run_dir / sample.file_name
            if candidate.exists():
                return candidate
        # Try without source_run_dir (flat structure)
        candidate2 = root / sample.file_name
        if candidate2.exists():
            return candidate2
        return None
