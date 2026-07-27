from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from config import APP_SETTINGS
from core.analyses.clonality.interpretation import (
    ANNOTATION_CLASSES,
    ANNOTATION_SCHEMA_VERSION,
    CONTROL_FLAGS,
    TRACKING_COLUMNS,
    features_from_entry,
    interpret_entry,
    sample_annotation_files,
    sl_quality_from_metrics,
)
from core.analyses.clonality.tracking_excel import update_clonality_tracking_workbook
from scripts.render_clonality_interpretation_annotation_html import build_html
from scripts.train_clonality_interpretation_quick_model import train_quick_model


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

    def test_html_contains_class_buttons_control_flags_and_schema(self) -> None:
        html_text = build_html(
            [
                {
                    "ordinal": 1,
                    "raw_path": "/tmp/PK_FR1__220526_E01_H9TEST.fsa",
                    "file": "PK_FR1__220526_E01_H9TEST.fsa",
                    "assay": "FR1",
                    "ladder": "ROX400HD",
                    "sample_kind": "control",
                    "control": "PK",
                    "run_date": "2026-05-22",
                    "ladder_qc_status": "ok",
                    "peak_count": 1,
                    "dominant_peak_height": 1000,
                    "dominant_to_second_ratio": 4.0,
                    "dominant_height_share": 0.7,
                    "suggestion": "monoklonal",
                    "confidence": 0.8,
                    "review_needed": False,
                    "evidence": "test",
                    "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
                    "image": "",
                }
            ],
            title="Test panel",
        )

        for label in ANNOTATION_CLASSES:
            self.assertIn(f"data-class='{label}'", html_text)
        self.assertNotIn("data-class='uspesifikke_topper'", html_text)
        for flag in CONTROL_FLAGS:
            self.assertIn(f"data-flag='{flag}'", html_text)
        self.assertIn(ANNOTATION_SCHEMA_VERSION, html_text)

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

    def test_html_links_parallel_assays_for_same_patient(self) -> None:
        html_text = build_html(
            [
                {
                    "ordinal": 1,
                    "raw_path": "/tmp/26OUM00001_FR1__220526_A01_H9TEST.fsa",
                    "file": "26OUM00001_FR1__220526_A01_H9TEST.fsa",
                    "patient_id": "26OUM00001",
                    "assay": "FR1",
                    "ladder": "ROX400HD",
                    "sample_kind": "patient",
                    "control": "",
                    "run_date": "2026-05-22",
                    "ladder_qc_status": "ok",
                    "peak_count": 3,
                    "peak_count_in_interpretation_range": 3,
                    "peak_count_outside_interpretation_range": 0,
                    "dominant_peak_basepairs": 310.0,
                    "interpretation_range_min_bp": 250.0,
                    "interpretation_range_max_bp": 390.0,
                    "outside_interpretation_height_share": 0.0,
                    "suggestion": "polyklonal",
                    "confidence": 0.66,
                    "review_needed": True,
                    "evidence": "test",
                    "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
                    "image": "",
                },
                {
                    "ordinal": 2,
                    "raw_path": "/tmp/26OUM00001_FR2__220526_A02_H9TEST.fsa",
                    "file": "26OUM00001_FR2__220526_A02_H9TEST.fsa",
                    "patient_id": "26OUM00001",
                    "assay": "FR2",
                    "ladder": "ROX400HD",
                    "sample_kind": "patient",
                    "control": "",
                    "run_date": "2026-05-22",
                    "ladder_qc_status": "ok",
                    "peak_count": 3,
                    "peak_count_in_interpretation_range": 3,
                    "peak_count_outside_interpretation_range": 0,
                    "dominant_peak_basepairs": 260.0,
                    "interpretation_range_min_bp": 210.0,
                    "interpretation_range_max_bp": 330.0,
                    "outside_interpretation_height_share": 0.0,
                    "suggestion": "polyklonal",
                    "confidence": 0.66,
                    "review_needed": True,
                    "evidence": "test",
                    "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
                    "image": "",
                },
            ],
            title="Test panel",
        )

        self.assertIn("Paralleller", html_text)
        self.assertIn("#case-0002", html_text)

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

        html_text = build_html(
            [
                {
                    "ordinal": 1,
                    "raw_path": "/tmp/26OUM00001_SL__220526_A05_H9TEST01.fsa",
                    "file": "26OUM00001_SL__220526_A05_H9TEST01.fsa",
                    "assay": "SL",
                    "ladder": "ROX400HD",
                    "sample_kind": "patient",
                    "control": "",
                    "run_date": "2026-05-22",
                    "ladder_qc_status": "ok",
                    "peak_count": 5,
                    "dominant_peak_height": 1000,
                    "dominant_to_second_ratio": 1.0,
                    "dominant_height_share": 0.3,
                    "sl_100_percent": 45.0,
                    "sl_200_percent": 20.0,
                    "sl_300_percent": 15.0,
                    "sl_400_percent": 12.0,
                    "sl_600_percent": 8.0,
                    "sl_fragmented_percent": 65.0,
                    "sl_quality_class": "litt_fragmentert",
                    "sl_quality_phrase": "Litt fragmentert - kan redusere sensitivitet.",
                    "suggestion": "polyklonal",
                    "confidence": 0.66,
                    "review_needed": True,
                    "evidence": "sl_fragmented_percent=65.0",
                    "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
                    "image": "",
                }
            ],
            title="Test panel",
        )
        self.assertIn("SL quality", html_text)
        self.assertIn("litt_fragmentert", html_text)
        self.assertIn("fragmented=65.00%", html_text)

    def test_quick_training_writes_model_and_reports_for_small_balanced_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            feature_rows = []
            for idx, label in enumerate(["polyklonal", "polyklonal", "polyklonal", "monoklonal", "monoklonal", "monoklonal"]):
                raw_path = f"/tmp/sample_{idx}.fsa"
                rows.append(
                    {
                        "raw_path": raw_path,
                        "file": f"sample_{idx}.fsa",
                        "assay": "FR1",
                        "ladder": "ROX400HD",
                        "sample_kind": "patient",
                        "control": "",
                        "label": label,
                    }
                )
                feature_rows.append(
                    {
                        "raw_path": raw_path,
                        "assay": "FR1",
                        "ladder": "ROX400HD",
                        "primary_peak_channel": "DATA1",
                        "sample_kind": "patient",
                        "control": "",
                        "control_bucket": "patient",
                        "ladder_qc_status": "ok",
                        "peak_count": 6 if label == "polyklonal" else 1,
                        "dominant_peak_height": 200 if label == "polyklonal" else 1200,
                        "second_peak_height": 180 if label == "polyklonal" else 50,
                        "dominant_to_second_ratio": 1.1 if label == "polyklonal" else 24.0,
                        "dominant_height_share": 0.2 if label == "polyklonal" else 0.8,
                    }
                )
            annotations = root / "annotations.json"
            features = root / "feature_rows.csv"
            annotations.write_text(json.dumps({"rows": rows}), encoding="utf-8")
            pd.DataFrame(feature_rows).to_csv(features, index=False)

            report = train_quick_model(annotations, root / "model_out", feature_path=features)

            self.assertTrue(report["trained"])
            self.assertTrue((root / "model_out" / "model.joblib").exists())
            self.assertTrue((root / "model_out" / "label_report.json").exists())
            self.assertTrue((root / "model_out" / "confusion_matrix.csv").exists())
            self.assertTrue((root / "model_out" / "prediction_preview.csv").exists())

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
