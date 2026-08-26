"""Tests for IGHV recognition: assay-name variants, Norwegian control
names ("Positiv_kontroll"/"Negativ_kontroll"), and IGHV QC markers
(PK window + 300 bp ROX ladder for both mixes).
"""

from __future__ import annotations

import pytest

from core.analyses.clonality.classification import detect_assay
from core.qc.qc_markers import control_id_from_filename, markers_for_entry
from core.qc.qc_rules import QCRules
from core.utils import is_control_file


class TestDetectAssayIghvVariants:
    @pytest.mark.parametrize(
        "name",
        [
            "IGHV_Mix1_PAT0123.fsa",
            "IGHV_M1_PAT0123.fsa",
            "IGHVM1_20260826.fsa",
            "ighv mix 1 - run.fsa",
            "20260826_IGHV-Mix1_A01.fsa",
        ],
    )
    def test_mix1_variants(self, name):
        assert detect_assay(name) == "IGHV Mix 1"

    @pytest.mark.parametrize(
        "name",
        [
            "IGHV_Mix2_PAT0123.fsa",
            "IGHV_M2_sample.fsa",
            "IGHVM2_x.fsa",
            "ighv mix 2 - run.fsa",
        ],
    )
    def test_mix2_variants(self, name):
        assert detect_assay(name) == "IGHV Mix 2"

    @pytest.mark.parametrize(
        "name",
        ["FR1_a.fsa", "FR3_b.fsa", "TCRgA_c.fsa", "IKZF1_d.fsa", "DHJH_D_e.fsa", "random.fsa"],
    )
    def test_no_false_ighv(self, name):
        assert not str(detect_assay(name)).startswith("IGHV")


class TestNorwegianControlNames:
    @pytest.mark.parametrize(
        "name",
        [
            "Positiv_kontroll_IGHV_Mix1_120126_A01_C991475U.fsa",
            "Positiv Kontroll IGHVM1.fsa",
            "positiv-kontroll_x.fsa",
            "PositivKontroll_a.fsa",
        ],
    )
    def test_positiv_kontroll_maps_to_pk(self, name):
        assert control_id_from_filename(name) == "PK"
        assert is_control_file(name)

    @pytest.mark.parametrize(
        "name",
        [
            "Negativ_kontroll_IGHV_Mix1.fsa",
            "negativ kontroll y.fsa",
            "NegativKontroll_z.fsa",
        ],
    )
    def test_negativ_kontroll_maps_to_nk(self, name):
        assert control_id_from_filename(name) == "NK"
        assert is_control_file(name)

    @pytest.mark.parametrize(
        "name,want",
        [
            ("PK1_TCRgA_120126_E05_H9C0U3SI.fsa", "PK1"),
            ("PK2_x.fsa", "PK2"),
            ("NK_FR1_run.fsa", "NK"),
            ("RK_t.fsa", "RK"),
            ("DIT_a.fsa", "DIT"),
            ("NTC_b.fsa", "NTC"),
            ("IVS-0000_c.fsa", "IVS-0000"),
            ("PAT0123_IGHV_Mix1.fsa", "UNKNOWN"),
            ("FR1_sample.fsa", "UNKNOWN"),
        ],
    )
    def test_legacy_names_unchanged(self, name, want):
        assert control_id_from_filename(name) == want


class TestIghvQcMarkers:
    RULES = QCRules()

    def _entry(self, filename: str, assay: str) -> dict:
        fsa = type("F", (), {"file_name": filename})()
        return {"fsa": fsa, "file_name": filename, "assay": assay, "ladder": "ROX"}

    def test_positiv_kontroll_mix1_gets_markers(self):
        entry = self._entry("Positiv_kontroll_IGHV_Mix1_120126_A01.fsa", "IGHV Mix 1")
        markers = markers_for_entry(entry, self.RULES)
        names = [m["name"] for m in markers]
        assert any("Ladder_300" in n for n in names)
        pk = [m for m in markers if m["kind"] == "sample"]
        assert len(pk) == 1
        assert pk[0]["channel"] == "DATA1"
        assert 535.0 <= pk[0]["expected_bp"] <= 550.0

    def test_positiv_kontroll_mix2_gets_markers(self):
        entry = self._entry("Positiv_kontroll_IGHVM2_run.fsa", "IGHV Mix 2")
        markers = markers_for_entry(entry, self.RULES)
        pk = [m for m in markers if m["kind"] == "sample"]
        assert len(pk) == 1
        assert pk[0]["channel"] == "DATA1"
        assert 356.0 <= pk[0]["expected_bp"] <= 359.0
        assert any(m["kind"] == "ladder" and m["expected_bp"] == 300.0 for m in markers)

    def test_negativ_kontroll_and_samples_get_no_markers(self):
        assert markers_for_entry(
            self._entry("Negativ_kontroll_IGHVM1.fsa", "IGHV Mix 1"), self.RULES
        ) == []
        assert markers_for_entry(
            self._entry("PAT0123_IGHV_Mix1.fsa", "IGHV Mix 1"), self.RULES
        ) == []
