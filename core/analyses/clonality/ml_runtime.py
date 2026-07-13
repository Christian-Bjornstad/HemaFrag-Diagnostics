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
    "ClonalityMLReviewNeeded",
    "ClonalityMLModelVersion",
)


_store: ClonalityModelStore | None = None
_store_path: Path | None = None


def is_ml_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Return True iff the in-app ML settings point at an enabled model dir."""
    dir_path = ml_model_dir_for_settings(settings)
    return bool(dir_path is not None and dir_path.exists() and dir_path.is_dir())


def ml_model_dir_for_settings(
    settings: dict[str, Any] | None = None,
) -> Path | None:
    """Resolve the configured model directory from APP_SETTINGS.

    Order of precedence:
        ``analyses.clonality.interpretation.model_path``
    (single key, semantics changed in this revision: directory of
    ``<assay>/<classifier>.joblib`` not a single file).

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


def _coerce_review(entry: dict[str, Any]) -> bool:
    rule_review = bool(entry.get("ClonalityReviewNeeded", False))
    rule_label = str(entry.get("ClonalitySuggestion") or "").strip()
    if rule_label in {"usikker_review", "qc_teknisk_fail", "intet_pcr_produkt_darlig_dna"}:
        return True
    return rule_review


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
    # Pull features — either precomputed by the rule layer or freshly
    # derived from the entry. Both paths produce the same dict shape.
    features = entry.get("features")
    if not isinstance(features, dict):
        # Lazy import avoids sklearn import unless ML is actually on.
        from core.analyses.clonality.interpretation import features_from_entry
        features = features_from_entry(entry)
    assay = str(entry.get("assay") or "").strip()
    # Only patient/sample entries get ML attached; controls/sl ruled out.
    sample_kind = str(entry.get("sample_kind") or entry.get("SampleKind") or "")
    if not assay or sample_kind.lower() == "control":
        # Still stamp empty columns so the tracking workbook is uniform.
        for col in MLCOLUMNS:
            entry.setdefault(col, "")
        return entry

    result = store.predict(assay, features)
    if result is None:
        for col in MLCOLUMNS:
            entry.setdefault(col, "")
        return entry

    label = str(result["label"])
    confidence = float(result["confidence"])
    ml_review = bool(result["review_needed"])
    review = _coerce_review(entry) or ml_review
    # Disagreement ⇒ forced review (chemist should glance at it)
    rule_label = str(entry.get("ClonalitySuggestion") or "").strip()
    if rule_label and label and rule_label != label and rule_label != "usikker_review":
        review = True

    entry["ClonalityMLSuggestion"] = label
    entry["ClonalityMLConfidence"] = round(confidence, 3)
    entry["ClonalityMLReviewNeeded"] = bool(review)
    entry["ClonalityMLModelVersion"] = str(result.get("model_version") or "")
    return entry
