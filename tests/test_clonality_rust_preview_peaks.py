from types import SimpleNamespace

import numpy as np

from core.analyses.clonality.pipeline import _build_peaks_from_rust_clonality_preview


def test_build_peaks_from_rust_clonality_preview_uses_matching_assay():
    fsa = SimpleNamespace(
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
