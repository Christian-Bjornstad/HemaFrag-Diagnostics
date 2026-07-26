from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from core.analyses.clonality.ml_training import PerAssayDataset
from core.analyses.clonality.ml_validation import (
    assess_promotion_gate,
    grouped_oof_validate,
    render_review_panel_html,
)


def _dataset() -> PerAssayDataset:
    rng = np.random.default_rng(123)
    rows = []
    features = []
    labels = []
    dits = []
    for group_index in range(30):
        label = "monoklonal" if group_index % 2 == 0 else "polyklonal"
        for replicate in range(2):
            signal = 1.0 if label == "monoklonal" else 0.0
            features.append(
                {
                    "trace_dominant_area_share_raw_per_channel.DATA1": (
                        signal + float(rng.normal(0, 0.08))
                    ),
                    "trace_peak_count_raw_per_channel.DATA1": (
                        2.0 if label == "monoklonal" else 10.0
                    ),
                }
            )
            labels.append(label)
            dit = f"DIT-{group_index:03d}"
            dits.append(dit)
            rows.append(
                {
                    "IdentityKey": f"{dit}-{replicate}",
                    "DIT": dit,
                    "Assay": "FR1",
                    "RunDate": f"2026-07-{1 + group_index % 3:02d}",
                    "SourceRunKey": f"run-{group_index % 3}",
                    "RuleSuggestion": (
                        label if group_index % 5 else "usikker_review"
                    ),
                    "RuleConfidence": 0.8,
                    "RuleReviewNeeded": group_index % 5 == 0,
                }
            )
    return PerAssayDataset(
        X=pd.DataFrame(features),
        y=pd.Series(labels),
        dit=pd.Series(dits),
        assay="FR1",
        rows=pd.DataFrame(rows),
        rare_class_counts={"monoklonal": 30, "polyklonal": 30},
    )


def _fast_fit(X, y, *, kind, random_state):
    del kind
    return RandomForestClassifier(
        n_estimators=20,
        max_depth=4,
        random_state=random_state,
        n_jobs=1,
    ).fit(X, y)


def test_grouped_oof_validation_predicts_every_row_without_dit_leakage(monkeypatch):
    monkeypatch.setattr(
        "core.analyses.clonality.ml_validation.fit_classifier",
        _fast_fit,
    )
    dataset = _dataset()

    result = grouped_oof_validate(
        dataset,
        classifier_kind="random_forest",
        n_splits=5,
        random_state=44,
        accept_threshold_tau=0.8,
    )

    assert len(result.predictions) == dataset.n_samples
    assert result.predictions["RowIndex"].nunique() == dataset.n_samples
    assert result.predictions.groupby("DIT")["Fold"].nunique().eq(1).all()
    assert result.split_manifest["every_row_oof_once"] is True
    assert result.split_manifest["effective_splits"] == 5
    assert len(result.fold_metrics) == 5
    assert set(result.drift_summary["Dimension"]) == {"SourceRunKey", "RunDate"}


def test_grouped_validation_exports_disagreements_and_review_html(monkeypatch):
    monkeypatch.setattr(
        "core.analyses.clonality.ml_validation.fit_classifier",
        _fast_fit,
    )
    dataset = _dataset()
    dataset.rows.loc[0, "SourceRunKey"] = "<private>"
    dataset.rows.loc[0, "RuleSuggestion"] = "polyklonal"

    result = grouped_oof_validate(
        dataset,
        classifier_kind="random_forest",
        n_splits=3,
        accept_threshold_tau=0.99,
    )
    gate = assess_promotion_gate(
        result,
        min_macro_f1=0.5,
        min_monoklonal_f1=0.5,
        min_monoklonal_precision=0.5,
        min_dit_groups=20,
    )
    panel = render_review_panel_html(result, promotion_gate=gate)

    assert not result.review_cases.empty
    assert result.review_cases["ReviewReason"].str.contains(
        "low_confidence|rule_ml_disagreement"
    ).any()
    assert "<table>" in panel
    assert "&lt;private&gt;" in panel
    assert "<private>" not in panel


def test_promotion_gate_reports_each_failed_requirement(monkeypatch):
    monkeypatch.setattr(
        "core.analyses.clonality.ml_validation.fit_classifier",
        _fast_fit,
    )
    result = grouped_oof_validate(
        _dataset(),
        classifier_kind="random_forest",
        n_splits=3,
    )

    gate = assess_promotion_gate(
        result,
        min_macro_f1=1.01,
        min_monoklonal_f1=1.01,
        min_monoklonal_precision=1.01,
        min_dit_groups=100,
    )

    assert gate.passed is False
    assert len(gate.reasons) >= 4
