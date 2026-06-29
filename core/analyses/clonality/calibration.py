"""core/analyses/clonality/calibration.py

Plan 11 / Phase 4 — per-assay ML second-opinion with Platt-scaled
predict-with-rejection. Off by default.

Public surface (re-exported via __all__):
    CalibratedMLPrediction                  # result dataclass
    load_calibrated_pipeline                # load estimator + metadata
    predict_with_rejection                  # apply to per-entry features
    attach_ml_suggestion_if_enabled         # entry-level wrapper
    is_load_failed                          # sentinel value

Schema:
  ANNOTATION_CLASSES_ORDER is re-imported from core.analyses.clonality.ml_training
  so both modules share the same canonical label order.

Triggering conditions (independently enforce), per entry:
  1. ladder_qc_status not in {"ok", "manual_adjustment", ""}
     -> force to usikker_review (no ML inference)
  2. control_flag in {"kontroll_avvik", "kontaminasjon_mistenkt"}
     -> force to usikker_review
  3. any of {intet_pcr_produkt_darlig_dna, qc_teknisk_fail}
     appearing as rule-derived fields
     -> force to usikker_review
  4. ML argmax in {monoklonal, polyklonal, bi_oligoklonal} AND
     ML probability >= per_assay_accept_threshold[assay]
     -> accept; output ClonalityMLSuggestion / ClonalityMLConfidence
  5. Else
     -> route to usikker_review (display only)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from config import APP_SETTINGS

from core.analyses.clonality.ml_training import (
    ANNOTATION_CLASSES_ORDER,
    deserialize_model,
)


# Sentinel: load_calibrated_pipeline returns this when model absent.
class _LoadFailed:
    """Sentinel wrapped around a model-not-found reason string."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason)

    def __repr__(self) -> str:
        return "LoadFailed(reason=%r)" % (self.reason,)


def is_load_failed(value: Any) -> bool:
    """True when load_calibrated_pipeline() returned a sentinel."""
    return isinstance(value, _LoadFailed)


# Triple returned by predict_with_rejection() per row.
@dataclass
class CalibratedMLPrediction:
    label: str                          # best ML label
    confidence: float                   # best ML probability (calibrated)
    accepted: bool                      # did the per-assay threshold approve?
    reason: str = ""                    # if not accepted, why? e.g. "ladder_qc!=ok"
    artifact_path: str = ""            # path of the joblib that produced this

    def to_dict(self) -> dict[str, Any]:
        return {
            "ClonalityMLSuggestion": self.label,
            "ClonalityMLConfidence": float(round(self.confidence, 3)),
            "ClonalityMLReviewNeeded": bool(not self.accepted),
            "ClonalityMLModelVersion": "calibration_platt_v1",
            "ClonalityMLEvidence": self.reason,
            "ClonalityMLArtifact": self.artifact_path,
        }


_FORCED_REVIEW_REASON = {
    "ladder_qc": "ladder_qc_status did not pass (forbidden to auto-apply ML)",
    "control_flag": "control_flag triggered manual review",
    "qc_or_dna_fail": "rule-derived qc_teknisk_fail / intet_pcr_produkt_darlig_dna",
}


_LADDER_QC_ACCEPTED = {"", "ok", "manual_adjustment"}


_FORCE_REVIEW_CONTROL_FLAGS = {"kontroll_avvik", "kontaminasjon_mistenkt"}


_RULE_FORCE_REVIEW_LABELS = {"qc_teknisk_fail", "intet_pcr_produkt_darlig_dna"}


_ACCEPTED_LABELS = {"monoklonal", "polyklonal", "bi_oligoklonal"}


def per_assay_threshold(assay: str, settings: dict[str, Any] | None = None) -> float:
    """Read THRESHOLD[assay] from APP_SETTINGS, fall back to _default.

    Schema:
      analyses.clonality.interpretation.thresholds:
        FR1: 0.85, TCRG-A: 0.75, _default: 0.85, ...
    """
    settings = settings if settings is not None else APP_SETTINGS
    cfg = settings.get("analyses", {}).get("clonality", {})
    inter = cfg.get("interpretation", {}) if isinstance(cfg, dict) else {}
    thresholds = inter.get("thresholds", {}) if isinstance(inter, dict) else {}
    if isinstance(thresholds, dict):
        if assay in thresholds:
            return float(thresholds[assay])
        if "_default" in thresholds:
            return float(thresholds["_default"])
    return 0.85


def load_calibrated_pipeline(
    *,
    assay: str,
    output_dir: Path | str | None = None,
    classifier_kind: str = "random_forest",
) -> tuple[Any, dict[str, Any]] | _LoadFailed:
    """Load a saved estimator + metadata by assay.

    Returns either (estimator, metadata_dict) or a LoadFailed sentinel
    carrying the failure reason (file missing, schema mismatch, etc).
    Use is_load_failed() to branch.
    """
    out_dir = Path(output_dir) if output_dir is not None else (
        Path.cwd() / "ObsidianVault" / "Clonality_ML_Log" / "models"
    )
    joblib_path = out_dir / assay / f"{classifier_kind}.joblib"
    metadata_path = out_dir / assay / "metadata.json"
    if not joblib_path.exists():
        return _LoadFailed(
            "no joblib artifact at expected path: %s" % str(joblib_path)
        )
    if not metadata_path.exists():
        return _LoadFailed(
            "no metadata at expected path: %s" % str(metadata_path)
        )
    try:
        estimator, metadata = deserialize_model(
            joblib_path=joblib_path,
            metadata_path=metadata_path,
        )
    except Exception as exc:
        return _LoadFailed(
            "deserialize_model raised %s: %s" % (type(exc).__name__, exc)
        )
    expected_schema = "ml_training_pipeline_v1"
    actual_schema = metadata.get("schema_version")
    if actual_schema != expected_schema:
        return _LoadFailed(
            "schema mismatch: expected %s got %s" % (expected_schema, actual_schema)
        )
    if metadata.get("assay") != assay:
        return _LoadFailed(
            "metadata says assay=%r; caller asked %r" % (
                metadata.get("assay"), assay,
            )
        )
    return estimator, metadata


def _forced_review_reasons(entry: Mapping[str, Any]) -> list[str]:
    """Return a list of forced-review reasons that apply to this entry.

    Primary reasons covered:
      - ladder_qc_status invalid for ML inference (always)
      - control_flag override (contamination / avvik)
      - Already-rule-forced values that should never be ML-overruled:
          qc_teknisk_fail, intet_pcr_produkt_darlig_dna, usikker_review
    """
    reasons = []
    ladder_qc = str(entry.get("ladder_qc_status") or "")
    ladder_review = bool(entry.get("ladder_review_required"))
    if ladder_review or ladder_qc not in _LADDER_QC_ACCEPTED:
        reasons.append(_FORCED_REVIEW_REASON["ladder_qc"])

    control_flag = str(entry.get("control_flag") or "")
    if control_flag in _FORCE_REVIEW_CONTROL_FLAGS:
        reasons.append(_FORCED_REVIEW_REASON["control_flag"])

    rule_label = str(entry.get("ClonalitySuggestion") or "")
    if rule_label in _RULE_FORCE_REVIEW_LABELS or rule_label == "usikker_review":
        reasons.append(_FORCED_REVIEW_REASON["qc_or_dna_fail"])
    return reasons


def predict_with_rejection(
    estimator: Any,
    feature_row: Mapping[str, Any],
    *,
    assay: str,
    tau: float | None = None,
    artifact_path: str = "",
) -> CalibratedMLPrediction:
    """Predict one entry, with explicit per-entry forced-review override.

    Args:
      estimator: fitted classifier with predict_proba() method.
      feature_row: a Mapping where each value is coercible to a float
        via features_from_entry's output shape.
      assay: assay name, used to look up tau override if not provided.

    Returns:
      CalibratedMLPrediction with label, confidence, accepted, reason.
    """
    tau = float(tau if tau is not None else per_assay_threshold(assay))

    import numpy as np
    import pandas as pd
    if not isinstance(feature_row, Mapping):
        feature_row = dict(feature_row)
    row = pd.Series({k: float(v) if v is not None else float("nan")
                      for k, v in feature_row.items()}).to_frame().T
    try:
        proba = estimator.predict_proba(row.to_numpy())
    except Exception:
        return CalibratedMLPrediction(
            label="usikker_review",
            confidence=0.0,
            accepted=False,
            reason="predict_proba raised inside estimator",
            artifact_path=artifact_path,
        )

    classes = list(getattr(estimator, "classes_", []))
    if proba.size == 0 or not classes:
        return CalibratedMLPrediction(
            label="usikker_review",
            confidence=0.0,
            accepted=False,
            reason="estimator produced no probabilities",
            artifact_path=artifact_path,
        )
    arr = np.asarray(proba)
    best_idx = int(np.argmax(arr[0]))
    best_label = str(classes[best_idx])
    best_conf = float(arr[0, best_idx])

    if best_label not in _ACCEPTED_LABELS:
        return CalibratedMLPrediction(
            label=best_label,
            confidence=best_conf,
            accepted=False,
            reason=(
                "label is not in ML trust list (%s); route to review"
                % ", ".join(sorted(_ACCEPTED_LABELS))
            ),
            artifact_path=artifact_path,
        )
    if best_conf < tau:
        return CalibratedMLPrediction(
            label=best_label,
            confidence=best_conf,
            accepted=False,
            reason="prob %.3f < tau %.3f for assay %s" % (best_conf, tau, assay),
            artifact_path=artifact_path,
        )
    return CalibratedMLPrediction(
        label=best_label,
        confidence=best_conf,
        accepted=True,
        reason="accepted (prob %.3f >= tau %.3f)" % (best_conf, tau),
        artifact_path=artifact_path,
    )


def attach_ml_suggestion_if_enabled(
    entry: dict[str, Any],
    *,
    artifact_dir: Path | str | None = None,
    classifier_kind: str = "random_forest",
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mutate `entry` in place adding ML columns when interpretation.enabled.

    Stages applied in order:
      1. Forced-review override: ladder_qc / control_flag / rule-forced
         values -> set ClonalityMLSuggestion='usikker_review', confidence=0.
      2. If interpretation.enabled AND model present: predict + apply per-
         assay tau. If accepted, fields are written; if not accepted,
         fields are still written but ClonalityMLReviewNeeded=True.
      3. If interpretation.disabled OR model absent: leave entry untouched
         (only after step 1 forced-review override when applicable).

    Columns added when the ML path runs:
      ClonalityMLSuggestion
      ClonalityMLConfidence
      ClonalityMLReviewNeeded
      ClonalityMLEvidence
      ClonalityMLModelVersion
      ClonalityMLArtifact (only when predict was attempted)
    """
    settings = settings if settings is not None else APP_SETTINGS
    enabled = bool(
        settings.get("analyses", {}).get("clonality", {}).get(
            "interpretation", {}
        ).get("enabled", False)
    )

    forced = _forced_review_reasons(entry)
    if forced:
        ml_pred = CalibratedMLPrediction(
            label=str(entry.get("ClonalitySuggestion") or "usikker_review"),
            confidence=0.0,
            accepted=False,
            reason="forced-review override: %s" % " AND ".join(sorted(set(forced))),
            artifact_path="",
        )
        for key, val in ml_pred.to_dict().items():
            entry[key] = val
        return entry

    if not enabled:
        return entry

    assay = str(entry.get("assay") or "")
    if not assay:
        return entry

    loaded = load_calibrated_pipeline(
        assay=assay,
        output_dir=artifact_dir,
        classifier_kind=classifier_kind,
    )
    if is_load_failed(loaded):
        for col in (
            "ClonalityMLSuggestion",
            "ClonalityMLConfidence",
            "ClonalityMLReviewNeeded",
            "ClonalityMLEvidence",
            "ClonalityMLModelVersion",
            "ClonalityMLArtifact",
        ):
            entry[col] = ""
        return entry

    estimator, metadata = loaded
    tau = float(metadata.get("accept_threshold_tau") or per_assay_threshold(assay))
    features = entry.get("features") or {}
    if not features:
        from core.analyses.clonality.interpretation import features_from_entry
        features = features_from_entry(entry)
    if isinstance(features, Mapping):
        feature_row = features
    else:
        feature_row = features

    artifact_path = ""
    out_dir = Path(artifact_dir) if artifact_dir is not None else (
        Path.cwd() / "ObsidianVault" / "Clonality_ML_Log" / "models"
    )
    joblib_path = out_dir / assay / f"{classifier_kind}.joblib"
    if joblib_path.exists():
        artifact_path = str(joblib_path)

    pred = predict_with_rejection(
        estimator,
        feature_row,
        assay=assay,
        tau=tau,
        artifact_path=artifact_path,
    )
    for key, val in pred.to_dict().items():
        entry[key] = val
    return entry


__all__ = [
    "CalibratedMLPrediction",
    "load_calibrated_pipeline",
    "predict_with_rejection",
    "attach_ml_suggestion_if_enabled",
    "is_load_failed",
    "per_assay_threshold",
]
