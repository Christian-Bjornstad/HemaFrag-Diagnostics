from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from core.labeling.labeling_plot import build_labeling_plot_data


def _entry():
    time = np.arange(8)
    return {
        "assay": "IGK",
        "bp_min": 90.0,
        "bp_max": 330.0,
        "trace_channels": ["DATA1", "DATA2"],
        "ladder_qc_status": "ok",
        "fsa": SimpleNamespace(
            sample_data_with_basepairs=pd.DataFrame(
                {
                    "time": time,
                    "basepairs": [80.0, 90.0, 120.0, 150.0, 200.0, 250.0, 330.0, 340.0],
                }
            ),
            fsa={
                "DATA1": np.arange(8, dtype=float) * 10.0,
                "DATA2": np.arange(8, dtype=float) * 20.0,
            },
        ),
        "peaks_by_channel": {
            "DATA1": pd.DataFrame(
                {
                    "basepairs": [120.0, 250.0, 340.0],
                    "peaks": [20.0, 50.0, 70.0],
                    "keep": [True, False, True],
                }
            )
        },
    }


def test_build_labeling_plot_data_uses_calibrated_bp_axis_and_assay_window():
    result = build_labeling_plot_data(_entry())

    assert result.assay == "IGK"
    assert result.bp_min == 100.0
    assert result.bp_max == 340.0
    assert result.interpretation_ranges == ((120.0, 160.0), (190.0, 300.0))
    assert result.nonspecific_peaks == (217.0,)
    assert [trace.channel for trace in result.traces] == ["DATA1", "DATA2"]
    np.testing.assert_array_equal(
        result.traces[0].basepairs,
        [120.0, 150.0, 200.0, 250.0, 330.0, 340.0],
    )
    np.testing.assert_array_equal(
        result.traces[0].rfu,
        [20.0, 30.0, 40.0, 50.0, 60.0, 70.0],
    )


def test_build_labeling_plot_data_filters_out_of_window_peaks_and_preserves_keep():
    result = build_labeling_plot_data(_entry())

    assert [(peak.basepair, peak.kept) for peak in result.peaks] == [
        (120.0, True),
        (250.0, False),
        (340.0, True),
    ]
    assert result.ladder_qc_status == "ok"


def test_build_labeling_plot_data_rejects_missing_calibration():
    entry = _entry()
    entry["fsa"].sample_data_with_basepairs = None

    with pytest.raises(ValueError, match="base-pair calibration"):
        build_labeling_plot_data(entry)
