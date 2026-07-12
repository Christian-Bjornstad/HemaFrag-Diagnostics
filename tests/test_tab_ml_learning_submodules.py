"""Plan 13 / Phase A tests for the ML Learning tab sub-package.

Headless under QT_QPA_PLATFORM=offscreen.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from core.analyses.clonality.config import ASSAY_DISPLAY_ORDER
from gui_qt.tabs.tab_ml_learning._summary import (
    entry_payload,
    extract_dit,
    group_by_assay,
    infer_assay,
    summarize_run,
)
from gui_qt.tabs.tab_ml_learning._io import (
    append_jsonl,
    list_fsa_files,
    read_json,
    write_json,
)
from gui_qt.tabs.tab_ml_learning._constants import (
    KEYBOARD_SHORTCUTS,
    LEARNING_SCHEMA_VERSION,
)


# Subset used in helper tests where we don't need every assay bucket.
ASSAY_ORDER = ("FR1", "FR2", "FR3", "TCRbA", "TCRbC", "TCRgA")


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---- Pure helpers -------------------------------------------------------


class TestExtractDit:
    def test_matches_canonical_dit(self):
        assert extract_dit(["24OUM20364_FR1_A_040125_A01_H920FZY9.fsa"]) == "24OUM20364"

    def test_falls_back_to_parent_path(self):
        # FSA filename was renamed; parent dir still carries the DIT
        text = "2025_01_04_TCRb_aw_C990RHO1_24OUM20364_2025-01-06_0371/file.fsa"
        assert extract_dit([text, "file.fsa"]) == "24OUM20364"

    def test_no_match_returns_empty(self):
        assert extract_dit(["abc", "def"]) == ""

    def test_first_match_wins(self):
        assert extract_dit(["24OUM20364_FR1", "25OUM99999_FR1"]) == "24OUM20364"


class TestInferAssay:
    def test_canonical_filename(self):
        file = Path("24OUM20364_FR1_A_040125_A01_H920FZY9.fsa")
        assert infer_assay(file) == "FR1"

    def test_tcrb_c_token(self):
        file = Path("26OUM01234_TCRbC_040125_A01_H9C0U3SG.fsa")
        assert infer_assay(file) == "TCRbC"

    def test_unknown_returns_empty_by_default(self):
        file = Path("foo_bar.fsa")
        assert infer_assay(file) == ""

    def test_unknown_returns_fallback(self):
        file = Path("foo_bar.fsa")
        assert infer_assay(file, fallback="?") == "?"


class TestGroupByAssay:
    def test_buckets_each_assay(self, tmp_path):
        files = [
            tmp_path / "a_FR1_xxx.fsa",
            tmp_path / "b_FR1_yyy.fsa",
            tmp_path / "c_TCRbA_xxx.fsa",
            tmp_path / "d_PK_TCRbA_yyy.fsa",
            tmp_path / "weird_xxx.fsa",
        ]
        for f in files:
            f.write_text("x")
        out = group_by_assay(files, assay_order=ASSAY_ORDER)
        assert set(out["FR1"]) == {files[0], files[1]}
        assert set(out["TCRbA"]) == {files[2], files[3]}
        assert out["UNKNOWN"] == [files[4]]
        for missing in ("FR2", "FR3", "TCRbC", "TCRgA"):
            assert out[missing] == []

    def test_sorts_inside_bucket(self, tmp_path):
        files = [tmp_path / f"{n}_PK_FR1_{c}.fsa" for n, c in [(2, "z"), (1, "a"), (3, "m")]]
        for f in files:
            f.write_text("x")
        out = group_by_assay(files, assay_order=ASSAY_ORDER)
        assert [f.name for f in out["FR1"]] == sorted(f.name for f in files)


class TestSummarizeRun:
    def test_counts_total_and_buckets(self, tmp_path):
        files = []
        for tag, count, prefix in [("FR1", 4, ""), ("TCRbA", 2, "PK"), ("UNKNOWN", 1, "")]:
            for i in range(count):
                files.append(tmp_path / f"{prefix}_{tag}_{i}.fsa")
        for f in files:
            f.write_text("x")
        summary = summarize_run(files, assay_order=ASSAY_ORDER)
        assert summary["total"] == 7
        assert summary["by_assay"]["FR1"] == 4
        assert summary["by_assay"]["TCRbA"] == 2
        assert summary["control_count"] == 2
        assert summary["patient_count"] == 5


class TestEntryPayload:
    def test_makes_flat_dict(self, tmp_path):
        f = tmp_path / "24OUM20364_FR1_A_040125_A01_H920FZY9.fsa"
        f.write_text("x")
        payload = entry_payload(
            ordinal=1,
            raw_path=f,
            features={
                "assay": "FR1",
                "sample_kind": "patient",
                "primary_peak_channel": "DATA1",
                "ladder_qc_status": "ok",
                "peak_count": 3,
                "peak_count_in_interpretation_range": 3,
                "interpretation_range_min_bp": 80.0,
                "interpretation_range_max_bp": 360.0,
                "dominant_peak_basepairs": 312.0,
                "dominant_peak_height": 5000.0,
            },
            interpretation={
                "ClonalitySuggestion": "monoklonal",
                "ClonalityConfidence": 0.92,
                "ClonalityEvidence": "single dominant peak",
            },
            peaks_by_channel={},
            image_path=None,
        )
        assert payload["dit"] == "24OUM20364"
        assert payload["assay"] == "FR1"
        assert payload["suggestion"] == "monoklonal"
        assert payload["annotation_schema_version"] == LEARNING_SCHEMA_VERSION


# ---- IO helpers ---------------------------------------------------------


class TestListFsaFiles:
    def test_returns_sorted_fsa_only(self, tmp_path):
        (tmp_path / "a.fsa").write_text("x")
        (tmp_path / "b.fsa").write_text("x")
        (tmp_path / "c.txt").write_text("x")
        (tmp_path / "d.fsa").write_text("")  # zero-byte - skip
        out = list_fsa_files(tmp_path)
        assert [f.name for f in out] == ["a.fsa", "b.fsa"]

    def test_missing_folder_returns_empty(self, tmp_path):
        assert list_fsa_files(tmp_path / "nope") == []


class TestJsonRoundTrip:
    def test_write_then_read(self, tmp_path):
        path = tmp_path / "x.json"
        write_json(path, {"a": 1, "b": [1, 2, 3]})
        assert read_json(path) == {"a": 1, "b": [1, 2, 3]}

    def test_missing_returns_none(self, tmp_path):
        assert read_json(tmp_path / "x.json") is None

    def test_append_jsonl_increments(self, tmp_path):
        path = tmp_path / "x.jsonl"
        append_jsonl(path, {"i": 0})
        append_jsonl(path, {"i": 1})
        append_jsonl(path, {"i": 2})
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        assert json.loads(lines[2]) == {"i": 2}


# ---- Widget -------------------------------------------------------------


class TestTabWidget:
    def test_constructs_empty(self, qapp):
        from gui_qt.tabs.tab_ml_learning import TabMlLearning

        w = TabMlLearning()
        assert w._root is None
        assert w._table.rowCount() == 0
        assert w._assay_combo.count() == len(ASSAY_DISPLAY_ORDER) + 1  # +all
        assert w._open_panel_btn.isEnabled() is False  # Phase B
        assert w._export_btn.isEnabled() is False  # Phase C

    def test_set_root_populates_table(self, qapp, tmp_path):
        from gui_qt.tabs.tab_ml_learning import TabMlLearning

        (tmp_path / "a_FR1_x.fsa").write_text("x")
        (tmp_path / "b_TCRbA_y.fsa").write_text("x")
        (tmp_path / "c.txt").write_text("x")
        w = TabMlLearning()
        n = w.set_root(tmp_path)
        assert n == 2
        w._refresh_table()
        # QComboBox index 0 = "(all assays)"
        assert w._table.rowCount() == 2

        # Switch to FR1 only
        w.set_assay("FR1")
        assert w._table.rowCount() == 1

        # controls excluded
        (tmp_path / "PK_TCRbA_x.fsa").write_text("x")
        w.set_root(tmp_path)
        assert w._candidate_paths and any(f.name.startswith("PK_") for f in w._candidate_paths)
        # skip controls -> hide PK row
        w._disagreements_only.setChecked(True)
        assert all(
            not w._table.item(r, 2).text().upper().startswith(("NK_", "PK_", "RK_"))
            for r in range(w._table.rowCount())
        )

    def test_selected_paths(self, qapp, tmp_path):
        from gui_qt.tabs.tab_ml_learning import TabMlLearning

        (tmp_path / "a_FR1.fsa").write_text("x")
        (tmp_path / "b_FR1.fsa").write_text("x")
        w = TabMlLearning()
        w.set_root(tmp_path)
        w._refresh_table()
        rows = [w._table.item(r, 0) for r in range(w._table.rowCount())]
        # Toggle only the first row
        rows[0].setCheckState(Qt.CheckState.Checked)
        rows[1].setCheckState(Qt.CheckState.Unchecked)
        sel = w.selected_paths()
        assert len(sel) == 1
        assert sel[0].name == "a_FR1.fsa"


# ---- Constants expose ---------------------------------------------------


def test_constants_surface():
    assert LEARNING_SCHEMA_VERSION == 1
    assert KEYBOARD_SHORTCUTS["m"] == "monoklonal"
    assert "q" in KEYBOARD_SHORTCUTS
