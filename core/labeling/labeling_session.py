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

logger = logging.getLogger(__name__)

# Re-export the canonical label order so the GUI and the trainer never
# drift. These are Norwegian — the chemist's working language.
from core.analyses.clonality.ml_training import ANNOTATION_CLASSES_ORDER

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

# The Excel column that stores the chemist's label.
LABEL_COLUMN = "ClonalitySuggestion"


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

    @property
    def is_labeled(self) -> bool:
        return bool(self.current_label and self.current_label.strip())


@dataclass
class LabelingSession:
    """In-memory model: load Excel → iterate → label → save back.

    Does NOT touch the GUI — this is pure data. The tab widget wraps it.
    """
    excel_path: str
    samples: list[LabelingSample] = field(default_factory=list)
    _df: pd.DataFrame | None = None
    _dirty: bool = False

    def load(self) -> None:
        """Load the Run sheet from the tracking Excel into ``samples``."""
        with pd.ExcelFile(self.excel_path, engine="openpyxl") as xls:
            if "Run" not in xls.sheet_names:
                raise ValueError(
                    f"Excel '{self.excel_path}' has no 'Run' sheet. "
                    f"Sheets found: {xls.sheet_names}"
                )
            df = xls.parse("Run")
        if LABEL_COLUMN in df.columns:
            df[LABEL_COLUMN] = df[LABEL_COLUMN].where(pd.notna(df[LABEL_COLUMN]), "").astype(object)
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

        # Ensure the label column exists
        if LABEL_COLUMN not in self._df.columns:
            self._df[LABEL_COLUMN] = ""
        self._df[LABEL_COLUMN] = self._df[LABEL_COLUMN].where(
            pd.notna(self._df[LABEL_COLUMN]), ""
        ).astype(object)

        written = 0
        for sample in self.samples:
            if 0 <= sample.index < len(self._df):
                old_raw = self._df.at[self._df.index[sample.index], LABEL_COLUMN]
                old_val = str(old_raw) if pd.notna(old_raw) else ""
                new_val = sample.current_label
                if old_val != new_val:
                    self._df.at[self._df.index[sample.index], LABEL_COLUMN] = new_val
                    written += 1

        if written > 0:
            # Determine which columns to write — preserve the widest set
            # of columns the Excel already had.
            from core.analyses.clonality.tracking_excel import (
                RUN_SHEET_COLUMNS,
                RUN_SHEET_COLUMNS_WITH_INTERPRETATION,
            )
            if all(c in self._df.columns for c in RUN_SHEET_COLUMNS_WITH_INTERPRETATION):
                write_cols = RUN_SHEET_COLUMNS_WITH_INTERPRETATION
            elif all(c in self._df.columns for c in RUN_SHEET_COLUMNS):
                write_cols = RUN_SHEET_COLUMNS
            else:
                write_cols = list(self._df.columns)

            with pd.ExcelWriter(self.excel_path, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
                self._df[write_cols].to_excel(writer, sheet_name="Run", index=False, startrow=0)

        self._dirty = False
        logger.info("Wrote %d labels to %s", written, self.excel_path)
        return written

    def filter_unlabeled(self) -> list[int]:
        """Return the indices (into ``self.samples``) of unlabeled samples."""
        return [i for i, s in enumerate(self.samples) if not s.is_labeled]

    def fsa_path_for(self, sample_index: int, fsa_root: str) -> Path | None:
        """Resolve the FSA file path for a sample, given the FSA root dir."""
        if not (0 <= sample_index < len(self.samples)):
            return None
        sample = self.samples[sample_index]
        if not sample.file_name or not sample.source_run_dir:
            return None
        root = Path(fsa_root)
        # source_run_dir is typically a folder name like "2025_01_15_FR1_..."
        candidate = root / sample.source_run_dir / sample.file_name
        if candidate.exists():
            return candidate
        # Try without source_run_dir (flat structure)
        candidate2 = root / sample.file_name
        if candidate2.exists():
            return candidate2
        return None
