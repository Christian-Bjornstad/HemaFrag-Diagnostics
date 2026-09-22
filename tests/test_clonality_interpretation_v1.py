from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from config import APP_SETTINGS
from core.analyses.clonality.interpretation import (
    TRACKING_COLUMNS,
    features_from_entry,
    interpret_entry,
    sample_annotation_files,
    sl_quality_from_metrics,
)
from core.analyses.clonality.tracking_excel import update_clonality_tracking_workbook


def _entry(file_name: str, *, interpretation: bool = False) -> dict:
    entry = {
        "fsa": None,
        "file_name": file_name,
        "assay": "FR1",
        "dit": "26OUM00001",
        "group": "B",
        "ladder": "ROX400HD",
        "ladder_qc_status": "ok",
        "ladder_fit_strategy": "linear",
        "ladder_expected_step_count": 16,
        "ladder_fitted_step_count": 16,
        "ladder_r2": 0.9999,
        "ladder_linear_r2": 0.9999,
        "ladder_linear_mean_residual_bp": 0.2,
        "ladder_linear_max_residual_bp": 0.7,
        "ladder_max_curvature": 0.0,
    }
    if interpretation:
        entry.update(
            {
                "ClonalityInterpretationEnabled": True,
                "ClonalitySuggestion": "polyklonal",
                "ClonalityConfidence": 0.8,
                "ClonalityReviewNeeded": False,
                "ClonalityEvidence": "test",
                "ClonalityModelVersion": "test_rules",
            }
        )
    return entry


class ClonalityInterpretationV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._settings = copy.deepcopy(APP_SETTINGS)

    def tearDown(self) -> None:
        APP_SETTINGS.clear()
        APP_SETTINGS.update(self._settings)

    def test_sampling_includes_patient_pk_rk_and_nk_when_available(self) -> None:
        files = [
            *(Path(f"26OUM{i:05d}_FR1__220526_A01_H9TEST.fsa") for i in range(20)),
            *(Path(f"PK_FR1__220526_E{i:02d}_H9TEST.fsa") for i in range(5)),
            *(Path(f"RK_FR1__220526_F{i:02d}_H9TEST.fsa") for i in range(4)),
            *(Path(f"NK_FR1__220526_G{i:02d}_H9TEST.fsa") for i in range(3)),
        ]

        selected, summary = sample_annotation_files(
            files,
            limit=16,
            quotas={"patient": 8, "pk": 3, "rk": 3, "nk": 2},
        )

        names = {path.name for path in selected}
        self.assertEqual(summary["selected_total"], 16)
        self.assertTrue(any(name.startswith("26OUM") for name in names))
        self.assertTrue(any(name.startswith("PK_") for name in names))
        self.assertTrue(any(name.startswith("RK_") for name in names))
        self.assertTrue(any(name.startswith("NK_") for name in names))

    def test_known_nonspecific_peaks_are_exposed_and_excluded_from_interpretation(self) -> None:
        entry = _entry("26OUM00001_DHJH_D__220526_A01_H9TEST01.fsa")
        entry.update(
            {
                "assay": "DHJH_D",
                "primary_peak_channel": "DATA2",
                "peaks_by_channel": {
                    "DATA2": pd.DataFrame(
                        [
                            {"basepairs": 158.0, "peaks": 3000.0, "area": 9000.0},
                            {"basepairs": 132.0, "peaks": 300.0, "area": 800.0},
                        ]
                    )
                },
            }
        )

        features = features_from_entry(entry)
        interpretation = interpret_entry(entry)

        self.assertEqual(features["raw_peak_count"], 2)
        self.assertEqual(features["peak_count"], 1)
        self.assertEqual(features["peak_count_in_interpretation_range"], 2)
        self.assertEqual(features["peak_count_outside_interpretation_range"], 0)
        self.assertEqual(features["nonspecific_peak_count"], 1)
        self.assertTrue(features["dominant_peak_is_nonspecific"])
        self.assertNotEqual(interpretation["ClonalitySuggestion"], "uspesifikke_topper")
        self.assertIn("known_nonspecific_peaks_excluded", interpretation["ClonalityEvidence"])

    def test_unknown_out_of_reference_peak_is_not_marked_nonspecific(self) -> None:
        entry = _entry("26OUM00001_DHJH_D__220526_A01_H9TEST01.fsa")
        entry.update(
            {
                "assay": "DHJH_D",
                "primary_peak_channel": "DATA2",
                "peaks_by_channel": {
                    "DATA2": pd.DataFrame(
                        [
                            {"basepairs": 530.0, "peaks": 3000.0, "area": 9000.0},
                            {"basepairs": 132.0, "peaks": 300.0, "area": 800.0},
                        ]
                    )
                },
            }
        )

        features = features_from_entry(entry)
        interpretation = interpret_entry(entry)

        self.assertEqual(features["raw_peak_count"], 2)
        self.assertEqual(features["peak_count"], 1)
        self.assertEqual(features["peak_count_in_interpretation_range"], 1)
        self.assertEqual(features["peak_count_outside_interpretation_range"], 1)
        self.assertEqual(features["nonspecific_peak_count"], 0)
        self.assertNotEqual(interpretation["ClonalitySuggestion"], "uspesifikke_topper")

    def test_sl_quality_uses_area_percentages(self) -> None:
        metrics = {
            "targets_bp": [100.0, 200.0, 300.0, 400.0, 600.0],
            "areas": [45.0, 20.0, 15.0, 12.0, 8.0],
            "percents": [45.0, 20.0, 15.0, 12.0, 8.0],
            "total_area": 100000.0,
        }

        quality = sl_quality_from_metrics(metrics)
        self.assertEqual(quality["quality_class"], "litt_fragmentert")
        self.assertEqual(quality["fragmented_percent"], 65.0)

        entry = _entry("26OUM00001_SL__220526_A05_H9TEST01.fsa")
        entry.update({"assay": "SL", "sl_metrics": metrics})
        features = features_from_entry(entry)
        interpretation = interpret_entry(entry)

        self.assertEqual(features["sl_quality_class"], "litt_fragmentert")
        self.assertEqual(features["sl_fragmented_percent"], 65.0)
        self.assertEqual(interpretation["ClonalitySLFragmentedPercent"], 65.0)

    def test_tracking_columns_are_only_added_when_interpretation_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workbook_off = Path(tmp) / "off.xlsx"
            update_clonality_tracking_workbook(
                workbook_off,
                [_entry("26OUM00001_FR1__220526_A01_H9TEST01.fsa")],
                refresh_dashboard=False,
            )
            off_runs = pd.read_excel(workbook_off, sheet_name="Runs", engine="openpyxl")
            for column in TRACKING_COLUMNS:
                self.assertNotIn(column, off_runs.columns)

            APP_SETTINGS.setdefault("analyses", {}).setdefault("clonality", {}).setdefault("interpretation", {})["enabled"] = True
            workbook_on = Path(tmp) / "on.xlsx"
            update_clonality_tracking_workbook(
                workbook_on,
                [_entry("26OUM00001_FR1__220526_A01_H9TEST01.fsa", interpretation=True)],
                refresh_dashboard=False,
            )
            on_runs = pd.read_excel(workbook_on, sheet_name="Runs", engine="openpyxl")
            for column in TRACKING_COLUMNS:
                self.assertIn(column, on_runs.columns)
            self.assertEqual(on_runs.iloc[0]["ClonalitySuggestion"], "polyklonal")


    def test_dhjh_d_zero_peaks_is_polyklonal(self) -> None:
        """Regression: ordinal 11 – DHJH_D 0 peaks should be polyklonal."""
        entry = _entry("25OUM01897_DHJH_D__090426_A05_H9TEST.fsa")
        entry.update({
            "assay": "DHJH_D",
            "primary_peak_channel": "DATA2",
            "peaks_by_channel": {},
        })
        result = interpret_entry(entry)
        self.assertEqual(result["ClonalitySuggestion"], "polyklonal")
        self.assertIn("dhjh_d_polyclonal", result["ClonalityEvidence"])

    def test_dhjh_e_zero_peaks_is_usikker_review(self) -> None:
        """Regression: ordinals 12, 13 – DHJH_E 0 peaks should be usikker_review."""
        entry = _entry("25OUM01897_DHJH_E__090426_A05_H9TEST.fsa")
        entry.update({
            "assay": "DHJH_E",
            "primary_peak_channel": "DATA1",
            "peaks_by_channel": {},
        })
        result = interpret_entry(entry)
        self.assertEqual(result["ClonalitySuggestion"], "usikker_review")
        self.assertIn("dhjh_e_review", result["ClonalityEvidence"])

    def test_igk_eight_peaks_share_044_is_polyklonal(self) -> None:
        """Regression: ordinal 16 – IGK 8 peaks, share ~0.44 should be polyklonal."""
        entry = _entry("25OUM01897_IGK__090426_A05_H9TEST.fsa")
        # Build 8 peaks within IGK reference ranges (120-160 bp and 190-300 bp)
        # dominant has ~44% of total height
        heights = [17767.0, 5183.0, 4000.0, 3500.0, 3200.0, 2800.0, 2500.0, 1353.0]
        bps = [130.0, 140.0, 150.0, 200.0, 220.0, 240.0, 260.0, 280.0]
        peaks_df = pd.DataFrame([
            {"basepairs": bp, "peaks": h, "area": h * 3.0}
            for bp, h in zip(bps, heights)
        ])
        entry.update({
            "assay": "IGK",
            "primary_peak_channel": "DATA1",
            "peaks_by_channel": {"DATA1": peaks_df},
        })
        features = features_from_entry(entry)
        # Verify preconditions
        self.assertGreaterEqual(features["peak_count"], 5)
        self.assertLessEqual(features["dominant_height_share"], 0.48)

        result = interpret_entry(entry)
        self.assertEqual(result["ClonalitySuggestion"], "polyklonal")
        self.assertIn("igk_relaxed", result["ClonalityEvidence"])

    def test_tcrba_zero_peaks_is_polyklonal(self) -> None:
        """Regression: ordinals 4, 5 – TCRbA 0 peaks should be polyklonal."""
        entry = _entry("25OUM01897_TCRbA__090426_A05_H9TEST.fsa")
        entry.update({
            "assay": "TCRbA",
            "primary_peak_channel": "DATA1",
            "peaks_by_channel": {},
        })
        result = interpret_entry(entry)
        self.assertEqual(result["ClonalitySuggestion"], "polyklonal")
        self.assertIn("tcrba_polyclonal", result["ClonalityEvidence"])

    def test_tcrbc_zero_peaks_is_polyklonal(self) -> None:
        """Regression: ordinal 8 – TCRbC 0 peaks should be polyklonal."""
        entry = _entry("25OUM01897_TCRbC__090426_A05_H9TEST.fsa")
        entry.update({
            "assay": "TCRbC",
            "primary_peak_channel": "DATA1",
            "peaks_by_channel": {},
        })
        result = interpret_entry(entry)
        self.assertEqual(result["ClonalitySuggestion"], "polyklonal")
        self.assertIn("tcrbc_polyclonal", result["ClonalityEvidence"])

    def test_fr1_still_uses_default_rules(self) -> None:
        """FR1 with good peaks should still produce monoklonal via default rules."""
        entry = _entry("25OUM01897_FR1__090426_A01_H9TEST.fsa")
        peaks_df = pd.DataFrame([
            {"basepairs": 330.0, "peaks": 5000.0, "area": 15000.0},
            {"basepairs": 340.0, "peaks": 200.0, "area": 600.0},
        ])
        entry.update({
            "assay": "FR1",
            "primary_peak_channel": "DATA1",
            "peaks_by_channel": {"DATA1": peaks_df},
        })
        result = interpret_entry(entry)
        self.assertEqual(result["ClonalitySuggestion"], "monoklonal")

    def test_default_zero_peaks_is_bad_dna_for_unknown_assay(self) -> None:
        """Unknown assay with 0 peaks falls through to default → bad DNA."""
        entry = _entry("25OUM01897_UNKNOWN__090426_A01_H9TEST.fsa")
        entry.update({
            "assay": "UNKNOWN_ASSAY",
            "primary_peak_channel": "DATA1",
            "peaks_by_channel": {},
        })
        result = interpret_entry(entry)
        self.assertEqual(result["ClonalitySuggestion"], "intet_pcr_produkt_darlig_dna")


if __name__ == "__main__":
    unittest.main()
