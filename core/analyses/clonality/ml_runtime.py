"""core/analyses/clonality/ml_runtime.py

Attach ML predictions to entries during clonality runs. Mirrors the
shape of ``attach_interpretation_if_enabled`` and is invoked from the
clonality pipeline in step 4 / 6 of the run loop.

This module is intentionally separate from ``interpretation.py`` so a
failed ML call never breaks the rule-based interpretation; ML output
is read-only on top.

Public surface (see ``__all__``):
    attach_ml_prediction_if_enabled(entry)
    MLCOLUMNS
    is_ml_enabled
    ml_model_dir_for_settings
    reset_model_store_cache
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

from config import APP_SETTINGS

from core.analyses.clonality.interpretation_units import (
    CHANNEL_ML_COLUMNS,
    CHANNEL_ML_METRICS,
    channel_local_numeric_features,
    channel_ml_column,
    interpretation_units_for_assay,
)
from core.analyses.clonality.ml_model import ClonalityModelStore


_log = logging.getLogger(__name__)


__all__ = [
    "MLCOLUMNS",
    "attach_ml_prediction_if_enabled",
    "is_ml_enabled",
    "ml_model_dir_for_settings",
    "reset_model_store_cache",
]


MLCOLUMNS = (
    "ClonalityMLSuggestion",
    "ClonalityMLConfidence",
    "ClonalityMLThreshold",
    "ClonalityMLReviewNeeded",
    "ClonalityMLEvidence",
    "ClonalityMLModelVersion",
)


_store: ClonalityModelStore | None = None
_store_path: Path | None = None


def is_ml_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Return True iff the in-app ML settings point at an enabled model dir."""
    dir_path = ml_model_dir_for_settings(settings)
    if dir_path is None or not dir_path.exists() or not dir_path.is_dir():
        return False
    return ClonalityModelStore(model_dir=dir_path).has_eligible_models()


def ml_model_dir_for_settings(
    settings: dict[str, Any] | None = None,
) -> Path | None:
    """Resolve the configured model directory from APP_SETTINGS.

    Order of precedence:
        ``analyses.clonality.interpretation.model_path``
    (single key, semantics changed in this revision: directory of
    ``<assay>/<classifier>-<hash>.joblib`` artifacts, not a single file).

    ``None`` when the key is missing or empty. ``Path`` regardless of
    whether the dir exists — ``is_ml_enabled`` is the existence check.
    """
    settings = settings if settings is not None else APP_SETTINGS
    try:
        profile = settings.get("analyses", {}).get("clonality", {}) or {}
    except (AttributeError, TypeError):
        return None
    interpretation = profile.get("interpretation", {}) or {}
    if not isinstance(interpretation, Mapping):
        return None
    if not bool(interpretation.get("enabled", False)):
        return None
    raw = interpretation.get("model_path", "")
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return Path(s).expanduser()


def _get_store(settings: dict[str, Any] | None = None) -> ClonalityModelStore | None:
    """Lazy-singleton: build the ``ClonalityModelStore`` once per process,
    rebuild only when the configured path changes between calls (e.g. when
    the chemist opens a different parent folder).
    """
    global _store, _store_path
    raw = ml_model_dir_for_settings(settings)
    if raw is None:
        return None
    if _store is not None and _store_path == raw:
        return _store
    _store = ClonalityModelStore(model_dir=raw)
    _store_path = raw
    return _store


def reset_model_store_cache() -> None:
    """Drop the cached ``ClonalityModelStore``. Tests + settings changes."""
    global _store, _store_path
    _store = None
    _store_path = None


def _quality_review_reasons(
    entry: dict[str, Any],
    features: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if bool(
        entry.get("ladder_review_required")
        or features.get("ladder_review_required")
    ):
        reasons.append("ladder_qc")
    ladder_status = str(
        entry.get("ladder_qc_status")
        or features.get("ladder_qc_status")
        or ""
    ).strip().lower()
    if ladder_status and ladder_status not in {
        "ok",
        "pass",
        "passed",
        "good",
        "valid",
        "manual_adjustment",
    }:
        reasons.append("ladder_qc")
    if bool(entry.get("ClonalityReviewNeeded", False)):
        reasons.append("rule_review")
    rule_label = str(entry.get("ClonalitySuggestion") or "").strip()
    if rule_label in {"usikker_review", "qc_teknisk_fail", "intet_pcr_produkt_darlig_dna", "intet_pcr_produkt"}:
        reasons.append("rule_quality")
    return list(dict.fromkeys(reasons))


def attach_ml_prediction_if_enabled(entry: dict[str, Any]) -> dict[str, Any]:
    """Attach ML columns to ``entry`` if a model dir is configured.

    Mirrors the rule-based attachment in ``core.analyses.clonality.interp
    retation.interpret_entry``. Always returns ``entry`` (never raises);
    any exception inside the prediction step is logged at WARNING and
    ``entry`` is left un-mutated from an ML standpoint (the rule fields
    remain intact).

    Idempotent: calling twice does not stack results; the second call's
    columns overwrite the first.
    """
    store = _get_store()
    if store is None:
        return entry
    try:
        return _do_attach(entry, store)
    except Exception as exc:  # noqa: BLE001 - defensive
        _log.warning("[clonality-ml] attach failed: %s", exc)
        return entry


def _do_attach(entry: dict[str, Any], store: ClonalityModelStore) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return entry
    features = entry.get("features")
    if not isinstance(features, dict):
        features = {}
    assay = str(entry.get("assay") or "").strip()
    # Only patient/sample entries get ML attached; controls/sl ruled out.
    sample_kind = str(
        entry.get("sample_kind")
        or entry.get("SampleKind")
        or features.get("sample_kind")
        or ""
    )
    if not assay or sample_kind.lower() == "control" or assay.upper() == "SL":
        # Still stamp empty columns so the tracking workbook is uniform.
        for col in MLCOLUMNS:
            entry.setdefault(col, "")
        for col in CHANNEL_ML_COLUMNS:
            entry.setdefault(col, "")
        return entry

    _attach_channel_predictions(entry, store, assay, features)

    required_columns = store.required_feature_columns(assay)
    required_context_columns = [
        column for column in required_columns if str(column).startswith("cohort_")
    ]
    if required_context_columns and not all(
        _feature_is_present(features, column)
        for column in required_context_columns
    ):
        for column in MLCOLUMNS:
            entry[column] = ""
        entry["ClonalityMLReviewNeeded"] = True
        entry["ClonalityMLEvidence"] = "cohort_context_unavailable"
        return entry
    required_raw_columns = [
        column for column in required_columns if str(column).startswith("trace_")
    ]
    if required_raw_columns and not all(
        _feature_is_present(features, column) for column in required_raw_columns
    ):
        # The rule layer intentionally caches scalar-only features. Recompute
        # the full real-FSA contract only when an eligible model needs it.
        from core.analyses.clonality.interpretation import features_from_entry

        features = {**features_from_entry(entry), **features}
    available_channels = features.get("trace_available_channel_count")
    if available_channels is not None:
        try:
            trace_unavailable = float(available_channels) <= 0
        except (TypeError, ValueError):
            trace_unavailable = True
        if trace_unavailable:
            for column in MLCOLUMNS:
                entry.setdefault(column, "")
            entry["ClonalityMLReviewNeeded"] = True
            entry["ClonalityMLEvidence"] = "trace_features_unavailable"
            return entry

    result = store.predict(assay, features)
    if result is None:
        for col in MLCOLUMNS:
            entry.setdefault(col, "")
        return entry

    label = str(result["label"])
    confidence = float(result["confidence"])
    threshold = float(result.get("threshold_tau") or 0.0)
    reasons = _quality_review_reasons(entry, features)
    if bool(result["review_needed"]):
        reasons.append("low_confidence")
    if label in {
        "monoklonal_pa_poly",
        "oligoklonal",
        "irregulaer",
        "lite_pcr_produkt",
        "intet_pcr_produkt",
        "qc_teknisk_fail",
        "usikker_review",
    }:
        reasons.append("rare_label_prediction")
    rule_label = str(entry.get("ClonalitySuggestion") or "").strip()
    if rule_label and label and rule_label != label and rule_label != "usikker_review":
        reasons.append("rule_ml_disagreement")
    reasons = list(dict.fromkeys(reasons))

    entry["ClonalityMLSuggestion"] = label
    entry["ClonalityMLConfidence"] = round(confidence, 3)
    entry["ClonalityMLThreshold"] = round(threshold, 3)
    entry["ClonalityMLReviewNeeded"] = bool(reasons)
    entry["ClonalityMLEvidence"] = ";".join(reasons) if reasons else "rule_ml_agree"
    entry["ClonalityMLModelVersion"] = str(result.get("model_version") or "")
    return entry


def _attach_channel_predictions(
    entry: dict[str, Any],
    store: ClonalityModelStore,
    assay: str,
    features: Mapping[str, Any],
) -> None:
    if not hasattr(store, "is_enabled"):
        return
    units = interpretation_units_for_assay(assay)
    eligible_units = [
        unit
        for unit in units
        if store.is_enabled(unit.unit_id)
    ]
    if not eligible_units:
        return

    full_features: Mapping[str, Any] = features
    if any(
        any(
            str(column).startswith("trace_")
            for column in store.required_feature_columns(unit.unit_id)
        )
        for unit in eligible_units
    ):
        from core.analyses.clonality.interpretation import features_from_entry

        full_features = {**features_from_entry(entry), **dict(features)}

    channel_results: list[dict[str, Any]] = []
    for unit in eligible_units:
        local_features = channel_local_numeric_features(
            full_features,
            unit.channel,
        )
        result = store.predict(unit.unit_id, local_features)
        if result is None:
            continue
        label = str(result["label"])
        confidence = float(result["confidence"])
        threshold = float(result.get("threshold_tau") or 0.0)
        reasons = _quality_review_reasons(entry, local_features)
        if bool(result["review_needed"]):
            reasons.append("low_confidence")
        if label in {
            "monoklonal_pa_poly",
            "oligoklonal",
            "irregulaer",
            "lite_pcr_produkt",
            "intet_pcr_produkt",
            "qc_teknisk_fail",
            "usikker_review",
        }:
            reasons.append("rare_label_prediction")
        reasons = list(dict.fromkeys(reasons))
        payload = {
            "interpretation_unit": unit.unit_id,
            "channel": unit.channel,
            "target_name": unit.target_name,
            "label": label,
            "confidence": round(confidence, 3),
            "threshold": round(threshold, 3),
            "review_needed": bool(reasons),
            "evidence": (
                ";".join(reasons)
                if reasons
                else "channel_model_accepted"
            ),
            "model_version": str(result.get("model_version") or ""),
        }
        channel_results.append(payload)
        values = {
            "Suggestion": payload["label"],
            "Confidence": payload["confidence"],
            "Threshold": payload["threshold"],
            "ReviewNeeded": payload["review_needed"],
            "Evidence": payload["evidence"],
            "ModelVersion": payload["model_version"],
        }
        for metric in CHANNEL_ML_METRICS:
            entry[channel_ml_column(metric, unit.channel)] = values[metric]

    if channel_results:
        entry["ClonalityMLChannelResults"] = channel_results


def _feature_is_present(features: Mapping[str, Any], column: str) -> bool:
    if column in features:
        return True
    if "." not in column:
        return False
    parent, child = column.rsplit(".", 1)
    nested = features.get(parent)
    return isinstance(nested, Mapping) and child in nested
