"""Tests for the LabelingSession model — load, label, save round-trip."""
from __future__ import annotations

import openpyxl
import pandas as pd
import pytest

from core.labeling.labeling_session import (
    LABEL_COLUMN,
    LABEL_KEYS,
    LABEL_TO_KEY,
    LabelingSession,
)


def _make_test_excel(tmp_path) -> str:
    """Create a minimal tracking Excel with a Run sheet."""
    path = str(tmp_path / "tracking.xlsx")
    df = pd.DataFrame({
        "DIT": ["26A01", "26A01", "26B02"],
        "Assay": ["FR1", "IGK", "FR1"],
        "Well": ["A01", "A02", "A03"],
        "File": ["sample1.fsa", "sample2.fsa", "sample3.fsa"],
        "SourceRunDir": ["run_2025_01_15", "run_2025_01_15", "run_2025_02_20"],
        "IdentityKey": ["ID1", "ID2", "ID3"],
        "SampleKind": ["patient", "patient", "patient"],
        "Group": ["B", "B", "A"],
        LABEL_COLUMN: ["", "", "monoklonal"],  # 3rd sample already labeled
    })
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Run", index=False)
    return path


def test_load_reads_all_samples(tmp_path):
    path = _make_test_excel(tmp_path)
    session = LabelingSession(excel_path=path)
    session.load()
    assert session.total_count == 3
    assert session.labeled_count == 1  # 3rd sample has monoklonal
    assert session.unlabeled_count == 2


def test_sample_fields_populate_correctly(tmp_path):
    path = _make_test_excel(tmp_path)
    session = LabelingSession(excel_path=path)
    session.load()
    s0 = session.samples[0]
    assert s0.dit == "26A01"
    assert s0.assay == "FR1"
    assert s0.well == "A01"
    assert s0.file_name == "sample1.fsa"
    assert s0.source_run_dir == "run_2025_01_15"
    assert s0.current_label == ""
    assert not s0.is_labeled

    s2 = session.samples[2]
    assert s2.current_label == "monoklonal"
    assert s2.is_labeled


def test_label_sample_sets_label(tmp_path):
    path = _make_test_excel(tmp_path)
    session = LabelingSession(excel_path=path)
    session.load()
    session.label_sample(0, "monoklonal")
    assert session.samples[0].current_label == "monoklonal"
    assert session.samples[0].is_labeled
    assert session.labeled_count == 2


def test_clear_label_removes_label(tmp_path):
    path = _make_test_excel(tmp_path)
    session = LabelingSession(excel_path=path)
    session.load()
    session.clear_label(2)  # had "monoklonal"
    assert session.samples[2].current_label == ""
    assert not session.samples[2].is_labeled
    assert session.labeled_count == 0


def test_unknown_label_raises(tmp_path):
    path = _make_test_excel(tmp_path)
    session = LabelingSession(excel_path=path)
    session.load()
    with pytest.raises(ValueError, match="Unknown label"):
        session.label_sample(0, "banana")


def test_filter_unlabeled_returns_correct_indices(tmp_path):
    path = _make_test_excel(tmp_path)
    session = LabelingSession(excel_path=path)
    session.load()
    unlabeled = session.filter_unlabeled()
    assert unlabeled == [0, 1]  # sample 2 is already labeled


def test_save_round_trip(tmp_path):
    path = _make_test_excel(tmp_path)
    session = LabelingSession(excel_path=path)
    session.load()
    session.label_sample(0, "polyklonal")
    session.label_sample(1, "bi_oligoklonal")
    written = session.save_to_excel()
    assert written == 2

    # Reload and verify
    session2 = LabelingSession(excel_path=path)
    session2.load()
    assert session2.samples[0].current_label == "polyklonal"
    assert session2.samples[1].current_label == "bi_oligoklonal"
    assert session2.samples[2].current_label == "monoklonal"  # preserved
    assert session2.labeled_count == 3


def test_save_only_writes_changed_labels(tmp_path):
    path = _make_test_excel(tmp_path)
    session = LabelingSession(excel_path=path)
    session.load()
    # Don't change anything
    written = session.save_to_excel()
    assert written == 0


def test_label_keys_match_annotation_classes_order():
    from core.analyses.clonality.ml_training import ANNOTATION_CLASSES_ORDER
    assert len(LABEL_KEYS) == len(ANNOTATION_CLASSES_ORDER)
    for key, label in LABEL_KEYS.items():
        assert label in ANNOTATION_CLASSES_ORDER, f"{label} not in ANNOTATION_CLASSES_ORDER"


def test_label_to_key_is_inverse():
    for key, label in LABEL_KEYS.items():
        assert LABEL_TO_KEY[label] == key


def test_missing_run_sheet_raises(tmp_path):
    path = str(tmp_path / "bad.xlsx")
    df = pd.DataFrame({"x": [1, 2]})
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="WrongSheet", index=False)
    session = LabelingSession(excel_path=path)
    with pytest.raises(ValueError, match="no 'Run' sheet"):
        session.load()


def test_fsa_path_resolution(tmp_path):
    """Test FSA path resolution with a mock directory structure."""
    fsa_root = tmp_path / "fsa_data"
    run_dir = fsa_root / "run_2025_01_15"
    run_dir.mkdir(parents=True)
    (run_dir / "sample1.fsa").touch()

    path = _make_test_excel(tmp_path)
    session = LabelingSession(excel_path=path)
    session.load()

    resolved = session.fsa_path_for(0, str(fsa_root))
    assert resolved is not None
    assert resolved.name == "sample1.fsa"
    assert resolved.exists()


def test_fsa_path_returns_none_for_missing_file(tmp_path):
    fsa_root = tmp_path / "fsa_data"
    fsa_root.mkdir()

    path = _make_test_excel(tmp_path)
    session = LabelingSession(excel_path=path)
    session.load()

    resolved = session.fsa_path_for(0, str(fsa_root))
    assert resolved is None
