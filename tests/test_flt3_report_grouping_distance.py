from types import SimpleNamespace

import pandas as pd
import numpy as np
import pytest

from core.analyses.flt3.classification import detect_analysis_type
from core.analyses.flt3.distance import calculate_bp_distance_metrics
from core.html_reports._legacy import _build_flt3_summary_table, _flt3_report_blocks


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("26OUM00001_ITD_10.fsa", "10x_diluted"),
        ("26OUM00001_10_ITD.fsa", "10x_diluted"),
        ("26OUM00001_ITD_10x.fsa", "10x_diluted"),
        ("26OUM00001_ITD_x10.fsa", "10x_diluted"),
        ("26OUM00001_ITD_1-10.fsa", "10x_diluted"),
        ("26OUM00001_ITD_1_10.fsa", "10x_diluted"),
        ("26OUM00001_ITD_25.fsa", "25x_diluted"),
        ("26OUM00001_25_ITD.fsa", "25x_diluted"),
        ("26OUM00001_ITD_1-25.fsa", "25x_diluted"),
        ("26OUM00001_ITD_ratio_10x.fsa", "ratio_quant"),
        ("26OUM00001_ITD_2026-10-01.fsa", "standard"),
    ],
)
def test_detect_analysis_type_handles_dilution_aliases_without_date_false_positives(name, expected):
    assert detect_analysis_type(name) == expected


def _group_entry(name: str, analysis_type: str) -> dict:
    return {
        "fsa": SimpleNamespace(file_name=name),
        "analysis_type": analysis_type,
        "well_id": "A01",
        "assay": "FLT3-ITD",
    }


def test_flt3_report_blocks_keep_itd_dilutions_in_separate_ordered_groups():
    assays = {
        "FLT3-ITD": [
            _group_entry("ratio.fsa", "ratio_quant"),
            _group_entry("itd_a.fsa", "standard"),
            _group_entry("itd_b.fsa", "undiluted"),
            _group_entry("itd_10.fsa", "10x_diluted"),
            _group_entry("itd_25.fsa", "25x_diluted"),
        ],
        "FLT3-D835": [{"assay": "FLT3-D835"}],
        "NPM1": [{"assay": "NPM1"}],
    }

    blocks = _flt3_report_blocks(assays)

    assert [title for _assay, title, _entries in blocks] == [
        "FLT3-ITD-ratio",
        "FLT3-D835",
        "FLT3-ITD",
        "FLT3-ITD - fortynnet 1:10",
        "FLT3-ITD - fortynnet 1:25",
        "NPM1",
    ]
    assert [entry["fsa"].file_name for entry in blocks[2][2]] == ["itd_a.fsa", "itd_b.fsa"]


def test_bp_distance_uses_channel_specific_wt_and_codon_frame():
    metrics = calculate_bp_distance_metrics(
        [329.1, 330.0],
        [338.2, 338.1],
        wt_channels=["DATA1", "DATA2"],
        mutant_channels=["DATA1", "DATA2"],
    )

    assert metrics[0]["delta_bp"] == pytest.approx(9.1)
    assert metrics[0]["rounded_delta_bp"] == 9
    assert metrics[0]["codon_distance"] == 3
    assert metrics[0]["divisible_by_3"] is True
    assert metrics[1]["delta_bp"] == pytest.approx(8.1)
    assert metrics[1]["rounded_delta_bp"] == 8
    assert metrics[1]["frame_remainder"] == 2
    assert metrics[1]["divisible_by_3"] is False


def test_flt3_summary_shows_distance_and_live_update_target():
    peaks = pd.DataFrame(
        [
            {
                "peak_id": "wt-blue",
                "label": "WT",
                "basepairs": 329.1,
                "peaks": 5000.0,
                "area": 10000.0,
                "area_DATA1": 10000.0,
                "area_DATA2": 0.0,
            },
            {
                "peak_id": "mut-blue",
                "label": "ITD",
                "basepairs": 338.2,
                "peaks": 1000.0,
                "area": 2000.0,
                "area_DATA1": 2000.0,
                "area_DATA2": 0.0,
            },
        ]
    )
    entry = {
        "assay": "FLT3-ITD",
        "ratio": 0.2,
        "ratio_mode": "manual",
        "ratio_numerator_area": 2000.0,
        "ratio_denominator_area": 10000.0,
        "primary_peak_channel": "DATA1",
        "peaks_by_channel": {"DATA1": peaks},
        "selected_wt_peak_id": "wt-blue",
        "selected_mutant_peak_ids": ["mut-blue"],
        "selected_wt_bp": 329.1,
        "selected_wt_bps": [329.1],
        "selected_mutant_bps": [338.2],
        "selected_wt_channel": "DATA1",
        "selected_wt_channels": ["DATA1"],
        "selected_mutant_channels": ["DATA1"],
        "_report_plot_id": "peakplot_test",
    }

    html = _build_flt3_summary_table(entry)

    assert "Δbp / kodoner" in html
    assert "+9.1 bp" in html
    assert "3 kodoner" in html
    assert "delbar" not in html
    assert "≈" not in html
    assert "id='peakplot_test_flt3_bp_distance_summary'" in html


def test_distance_does_not_infer_selection_from_automatic_peak_labels():
    from core.html_reports._legacy import _flt3_bp_distance_metrics

    peaks = pd.DataFrame([
        {"label": "WT", "basepairs": 330, "peaks": 5000, "area": 10000},
        {"label": "ITD", "basepairs": 339, "peaks": 1000, "area": 2000},
    ])
    assert _flt3_bp_distance_metrics({}, peaks) == []


def test_non_codon_distance_shows_only_basepairs():
    from core.html_reports._legacy import _format_flt3_bp_distance_html

    assert _format_flt3_bp_distance_html(calculate_bp_distance_metrics([330], [338])) == "+8.0 bp"


def test_static_distance_ignores_inferred_wt_in_resolved_selection():
    from core.html_reports._legacy import _flt3_bp_distance_metrics

    entry = {
        "manual_ratio_selection": {"enabled": True, "wt": {"peak_id": None}, "mutants": [{"peak_id": "mut"}]},
        "selected_wt_bps": [330], "selected_mutant_bps": [339],
    }
    assert _flt3_bp_distance_metrics(entry) == []


def test_static_distance_accepts_array_channels_without_cross_channel_pairing():
    from core.html_reports._legacy import _flt3_bp_distance_metrics

    entry = {
        "selected_wt_bps": np.array([330., 340.]),
        "selected_mutant_bps": np.array([339., 349., 359.]),
        "selected_wt_channels": np.array(["DATA1", "DATA2"]),
        "selected_mutant_channels": np.array(["DATA1", "DATA2", "DATA3"]),
    }
    metrics = _flt3_bp_distance_metrics(entry)
    assert [(metric["channel"], metric["delta_bp"]) for metric in metrics] == [
        ("DATA1", 9.), ("DATA2", 9.),
    ]
