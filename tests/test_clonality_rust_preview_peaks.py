from types import SimpleNamespace

import numpy as np

from core.analyses.clonality.pipeline import _build_peaks_from_rust_clonality_preview
from core.analyses.clonality.pipeline import (
    _build_rust_tracking_marker_candidates,
    _build_tracking_marker_results,
    _compare_rust_tracking_marker_candidates,
)


def test_build_peaks_from_rust_clonality_preview_uses_matching_assay():
    fsa = SimpleNamespace(
        ladder_steps=np.array([200.0]),
        best_size_standard=np.array([12.0]),
        size_standard=np.array([0.0] * 20),
        rust_clonality_preview={
            "ranked_assays": [
                {
                    "assay_name": "FR1",
                    "matched_by_filename": True,
                    "matched_groups": [
                        {
                            "group_id": 7,
                            "dominant_peak_basepair": 142.35,
                            "dominant_peak_intensity": 3100.0,
                            "dominant_peak_area": 6200.0,
                            "dominant_ratio_vs_second": 2.4,
                            "clonal_candidate": True,
                        }
                    ],
                }
            ]
        }
    )

    peaks = _build_peaks_from_rust_clonality_preview(fsa, "FR1", "DATA1")

    assert list(peaks) == ["DATA1"]
    row = peaks["DATA1"].iloc[0]
    assert row["basepairs"] == 142.35
    assert row["peaks"] == 3100.0
    assert row["area"] == 6200.0
    assert row["keep"] is np.True_ or row["keep"] is True
    assert row["rust_preview"] is np.True_ or row["rust_preview"] is True
    assert row["rust_group_id"] == 7


def test_build_peaks_from_rust_clonality_preview_ignores_invalid_groups():
    fsa = SimpleNamespace(
        rust_clonality_preview={
            "ranked_assays": [
                {
                    "assay_name": "FR1",
                    "matched_groups": [
                        {"dominant_peak_basepair": "bad", "dominant_peak_intensity": 1000.0},
                    ],
                }
            ]
        }
    )

    assert _build_peaks_from_rust_clonality_preview(fsa, "FR1", "DATA1") == {}


def test_build_peaks_from_rust_clonality_preview_prefers_channel_peaks():
    fsa = SimpleNamespace(
        rust_clonality_preview={
            "ranked_assays": [
                {
                    "assay_name": "IGK",
                    "channels": ["DATA1", "DATA2"],
                    "assay_bp_min": 100.0,
                    "assay_bp_max": 320.0,
                    "matched_by_filename": True,
                    "matched_groups": [
                        {
                            "group_id": 7,
                            "dominant_peak_basepair": 279.0,
                            "dominant_peak_intensity": 3100.0,
                        }
                    ],
                }
            ],
            "channel_peak_previews": {
                "DATA1": [
                    {"basepair": 279.2, "intensity": 5000.0, "area": 12000.0},
                    {"basepair": 450.0, "intensity": 9999.0, "area": 1.0},
                ],
                "DATA2": [
                    {"basepair": 150.1, "intensity": 4200.0, "area": 9000.0},
                ],
                "DATA3": [
                    {"basepair": 151.0, "intensity": 9900.0, "area": 9900.0},
                ],
            },
        }
    )

    peaks = _build_peaks_from_rust_clonality_preview(fsa, "IGK", "DATA1")

    assert set(peaks) == {"DATA1", "DATA2"}
    assert list(peaks["DATA1"]["basepairs"]) == [279.2]
    assert peaks["DATA1"].iloc[0]["area"] == 12000.0
    assert list(peaks["DATA2"]["basepairs"]) == [150.1]


def test_rust_tracking_marker_candidates_can_be_compared_to_python_results():
    fsa = SimpleNamespace(
        ladder_steps=np.array([200.0]),
        best_size_standard=np.array([12.0]),
        size_standard=np.array([0.0] * 20),
        rust_clonality_preview={
            "channel_peak_previews": {
                "DATA1": [{"basepair": 279.2, "intensity": 5000.0, "area": 12000.0}],
                "DATA2": [{"basepair": 150.1, "intensity": 4200.0, "area": 9000.0}],
            }
        }
    )
    markers = [
        {"name": "IGK_PK_DATA1_279", "kind": "sample", "expected_bp": 279.0, "channel": "DATA1", "window_bp": 2.0},
        {"name": "LIZ_Ladder_200", "kind": "ladder", "expected_bp": 200.0, "channel": "DATA105", "window_bp": 2.0},
    ]

    rust_results, rust_stats = _build_rust_tracking_marker_candidates(
        fsa,
        markers,
        primary_peak_channel="DATA1",
        sample_fallback_window_bp=5.0,
    )
    comparison = _compare_rust_tracking_marker_candidates(
        {"IGK_PK_DATA1_279": {"ok": True, "found_bp": 279.1}},
        rust_results,
    )

    assert rust_stats["sample_markers"] == 1
    assert rust_stats["sample_hits"] == 1
    assert rust_stats["ladder_markers"] == 1
    assert rust_stats["ladder_hits"] == 1
    assert rust_stats["hits"] == 2
    assert rust_results["IGK_PK_DATA1_279"]["ok"] is True
    assert rust_results["IGK_PK_DATA1_279"]["area"] == 12000.0
    assert rust_results["LIZ_Ladder_200"]["ok"] is True
    assert rust_results["LIZ_Ladder_200"]["search_mode"] == "rust_ladder_anchor"
    assert comparison["matches"] == 1
    assert comparison["mismatches"] == 0


def test_tracking_marker_results_use_rust_with_python_fallback(monkeypatch):
    monkeypatch.delenv("HEMAFRAG_DISABLE_RUST_TRACKING_MARKERS", raising=False)
    fsa = SimpleNamespace(
        ladder_steps=np.array([200.0]),
        best_size_standard=np.array([12.0]),
        size_standard=np.array([0.0] * 20),
        rust_clonality_preview={
            "channel_peak_previews": {
                "DATA1": [{"basepair": 279.2, "intensity": 5000.0, "area": 12000.0}],
            }
        }
    )
    markers = [
        {"name": "IGK_PK_DATA1_279", "kind": "sample", "expected_bp": 279.0, "channel": "DATA1", "window_bp": 2.0},
        {"name": "SL_600", "kind": "sample", "expected_bp": 600.0, "channel": "DATA1", "window_bp": 40.0},
        {"name": "LIZ_Ladder_200", "kind": "ladder", "expected_bp": 200.0, "channel": "DATA105", "window_bp": 2.0},
    ]
    python_calls = []

    def fake_python_eval(**kwargs):
        python_calls.append(kwargs["name"])
        return {"selected": {"ok": True, "found_bp": kwargs["target_bp"], "height": 1.0, "area": 2.0}}

    results, rust_candidates, stats = _build_tracking_marker_results(
        fsa=fsa,
        markers=markers,
        primary_peak_channel="DATA1",
        sample_fallback_window_bp=5.0,
        evaluate_peak_near_bp_with_fallback=fake_python_eval,
    )

    assert results["IGK_PK_DATA1_279"]["source"] == "rust_channel_preview"
    assert results["SL_600"]["source"] == "python"
    assert results["LIZ_Ladder_200"]["source"] == "rust_ladder_anchor"
    assert python_calls == ["SL_600"]
    assert rust_candidates["IGK_PK_DATA1_279"]["ok"] is True
    assert rust_candidates["LIZ_Ladder_200"]["ok"] is True
    assert stats["rust_used"] == 2
    assert stats["python_fallback"] == 1
