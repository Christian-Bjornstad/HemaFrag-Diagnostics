from __future__ import annotations

import pandas as pd

from core.qc.trend_monitor import (
    build_control_signals,
    build_entry_qc_trend_evidence,
    build_run_summary,
    selected_baseline_run_keys,
)
from types import SimpleNamespace
import numpy as np


def _runs(count: int = 24) -> pd.DataFrame:
    rows = []
    for index in range(count):
        rows.append(
            {
                "IdentityKey": f"id-{index}",
                "SourceRunDir": f"run-{index:02d}",
                "RunDate": f"2026-07-{index + 1:02d}",
                "Assay": "FR1",
                "Ladder": "LIZ500_250",
                "LadderQC": "ok",
                "LadderR2": 0.9995 - index * 0.000001,
                "LadderLinearMeanResidualBp": 0.4 + index * 0.001,
                "LadderLinearMaxResidualBp": 1.0 + index * 0.002,
                "LadderMedianAnchorIntensity": 1200 + index,
                "PullUpCandidate": False,
                "SaturationCandidate": False,
            }
        )
    return pd.DataFrame(rows)


def test_run_summary_tracks_rates_residuals_and_optional_artifacts():
    frame = _runs(2)
    frame.loc[1, "LadderQC"] = "review_required"
    frame.loc[1, "PullUpCandidate"] = True

    summary = build_run_summary(frame)

    assert len(summary) == 2
    assert summary["Files"].tolist() == [1, 1]
    assert summary["PassRate"].tolist() == [1.0, 0.0]
    assert summary["ReviewRate"].tolist() == [0.0, 1.0]
    assert summary["PullUpRate"].tolist() == [0.0, 1.0]


def test_control_signals_fail_closed_without_explicit_baseline():
    summary = build_run_summary(_runs())

    signals = build_control_signals(summary)

    assert set(signals["Status"]) == {"baseline_not_selected"}
    assert not signals["ShewhartAlert"].any()
    assert not signals["EWMAAlert"].any()
    assert signals["AdvisoryOnly"].all()


def test_control_signals_activate_only_with_twenty_selected_runs():
    summary = build_run_summary(_runs())
    baseline = summary["RunKey"].tolist()[:20]

    signals = build_control_signals(
        summary,
        baseline_run_keys=baseline,
        min_baseline_runs=20,
    )

    ladder_r2 = signals.loc[signals["Metric"] == "MeanLadderR2"].iloc[0]
    assert ladder_r2["Status"] == "active_advisory"
    assert ladder_r2["BaselineRunCount"] == 20
    assert pd.notna(ladder_r2["LatestEWMA"])
    assert bool(ladder_r2["AdvisoryOnly"]) is True


def test_baseline_config_requires_explicit_true_value():
    config = pd.DataFrame(
        {
            "RunKey": ["run-1", "run-2", "run-3"],
            "IncludeInBaseline": [True, False, "yes"],
        }
    )

    assert selected_baseline_run_keys(config) == {"run-1", "run-3"}


def test_entry_trend_evidence_detects_anchor_intensity_and_candidates():
    source = np.zeros(100)
    target = np.zeros(100)
    source[20] = 4000
    target[20] = 500
    target[60:62] = 31000
    fsa = SimpleNamespace(
        size_standard=source,
        best_size_standard=np.array([20.0]),
        fsa={"DATA1": source, "DATA2": target},
    )

    evidence = build_entry_qc_trend_evidence({"fsa": fsa})

    assert evidence["LadderMedianAnchorIntensity"] == 4000.0
    assert evidence["PullUpCandidate"] is True
    assert evidence["SaturationCandidate"] is True
