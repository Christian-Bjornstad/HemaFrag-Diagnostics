"""core/analyses/clonality/ml_model.py

Lazy-loading, per-assay wrapper around the joblib pickles that
``ml_training.serialize_model`` writes. Used by the runtime
hook ``attach_ml_prediction_if_enabled`` and by the GUI.

Layout on disk (one folder per assay):
    <model_dir>/
        FR1/
            random_forest.joblib
            metadata.json
        TCRG-A/
            random_forest.joblib
            metadata.json
        ...

Public surface (see __all__):
    ClonalityModelStore
    flatten_features_for_inference
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd

from core.analyses.clonality.ml_training import deserialize_model


__all__ = [
    "ClonalityModelStore",
    "DEFAULT_CLASSIFIER_KIND",
    "flatten_features_for_inference",
]


# Order preference when selecting which joblib under an assay folder
# to load first. RF is the canonical Phase-5 model; qda_calibrated is
# the fallback. Anything else is ignored.
DEFAULT_CLASSIFIER_KIND = "random_forest"
_CLASSIFIER_PREFERENCE = ("random_forest", "qda_calibrated")


# Keys inside features dicts (from features_from_entry) that carry nested
# per-channel frames; we expand these into flat columns named
# ``<prefix>_<upper(channel)>``.
_NESTED_FIELD_EXPANSION: tuple[tuple[str, str], ...] = (
    ("peak_count_per_channel", "trace_peak_count"),
    ("peak_variance_per_channel", "trace_peak_variance"),
    ("mad_per_channel", "trace_mad"),
    ("dome_peak_count_per_channel", "trace_dome_peak_count"),
    ("dome_height_ratio_per_channel", "trace_dome_height_ratio"),
)


@dataclass
class _AssayArtifact:
    """One assay's preloaded joblib + metadata pair."""
    estimator: Any
    metadata: dict[str, Any]


@dataclass
class ClonalityModelStore:
    """Lazily load and cache per-assay ML models.

    Pass ``model_dir=None`` to disable. Empty (non-model) dirs are
    tolerated; unknown assays gracefully return ``None`` from
    ``predict``.

    No sklearn import is required to construct the store; we only
    invoke sklearn inside ``predict`` once an assay is requested.
    """
    model_dir: Path | None = None
    _cache: dict[str, _AssayArtifact] = field(default_factory=dict)
    _available: set[str] = field(default_factory=set)
    _discovered: bool = False

    def __post_init__(self) -> None:
        # Eagerly discover at construction so ``is_enabled`` does not
        # need to read the disk on every call. Cheap: one stat per dir.
        if self.model_dir is not None:
            self._discover()

    def is_enabled(self, assay: str) -> bool:
        if self.model_dir is None:
            return False
        if not assay:
            return False
        return _normalise_assay(assay) in self._available

    def predict(
        self,
        assay: str,
        features: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Predict a single (assay, features) tuple.

        Returns ``None`` when ML is disabled or unknown for ``assay``.
        Otherwise returns::

            {
                "label":          "monoklonal" | ... ,
                "confidence":     0.0 .. 1.0,
                "review_needed":  bool,
                "model_version":  <metadata.schema_version>,
                "threshold_tau":  float,
                "all_scores":     {label: prob, ...} (best-effort; absent if
                                  the estimator has no predict_proba),
            }
        """
        if self.model_dir is None or not assay:
            return None
        norm = _normalise_assay(assay)
        if norm not in self._available:
            return None
        artifact = self._cache.get(norm)
        if artifact is None:
            artifact = self._load_assay(norm)
        if artifact is None:
            return None
        if features is None:
            return None

        feature_columns = list(artifact.metadata.get("feature_columns") or ())
        if not feature_columns:
            return None

        X = flatten_features_for_inference(
            dict(features), columns=feature_columns,
        )
        if X.empty:
            return None
        try:
            proba = artifact.estimator.predict_proba(_estimator_input(artifact.estimator, X))
        except Exception:  # noqa: BLE001 - defensive: any sklearn quirk
            return None

        classes_attr = getattr(artifact.estimator, "classes_", None)
        if classes_attr is None:
            return None
        classes = [str(c) for c in np.asarray(classes_attr).tolist()]
        if proba.shape[0] != 1 or not classes:
            return None

        row = np.asarray(proba[0])
        best_idx = int(np.argmax(row))
        label = classes[best_idx]
        confidence = float(row[best_idx])

        # Multi-class absolute confidence check (calibrated RF gives
        # well-scaled probs; we use max prob).
        tau = float(artifact.metadata.get("accept_threshold_tau") or 0.80)
        review_needed = bool(confidence < tau)

        all_scores = {str(classes[i]): float(row[i]) for i in range(len(classes))}
        return {
            "label": label,
            "confidence": confidence,
            "review_needed": review_needed,
            "model_version": str(artifact.metadata.get("schema_version") or ""),
            "threshold_tau": tau,
            "all_scores": all_scores,
        }

    # ---- internals ------------------------------------------------------

    def _discover(self) -> None:
        if self.model_dir is None:
            return
        root = Path(self.model_dir)
        self._available = set()
        if not root.exists() or not root.is_dir():
            return
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            meta = child / "metadata.json"
            if not meta.exists():
                continue
            # Check that at least one preferred classifier exists.
            if any((child / f"{kind}.joblib").exists() for kind in _CLASSIFIER_PREFERENCE):
                # Register common spellings plus the separator-free key used
                # by runtime assay classifiers (TCRG-A vs TCRGA).
                self._available.add(child.name)
                self._available.add(child.name.upper())
                self._available.add(_assay_key(child.name))
        self._discovered = True

    def _load_assay(self, norm_assay: str) -> _AssayArtifact | None:
        if self.model_dir is None:
            return None
        # We may have registered an uppercase variant; resolve back to
        # the actual on-disk folder name.
        candidates = _resolve_assay_path(self.model_dir, norm_assay)
        if not candidates:
            return None
        assay_dir = candidates[0]
        meta_path = assay_dir / "metadata.json"
        if not meta_path.exists():
            return None
        # Try preferred classifiers in order.
        joblib_path: Path | None = None
        for kind in _CLASSIFIER_PREFERENCE:
            candidate = assay_dir / f"{kind}.joblib"
            if candidate.exists():
                joblib_path = candidate
                break
        if joblib_path is None:
            # Fall back to any *.joblib under the dir.
            joblibs = sorted(assay_dir.glob("*.joblib"))
            if not joblibs:
                return None
            joblib_path = joblibs[0]
        try:
            estimator, metadata = deserialize_model(
                joblib_path=joblib_path, metadata_path=meta_path,
            )
        except Exception:  # noqa: BLE001 - load tolerance
            return None
        artifact = _AssayArtifact(estimator=estimator, metadata=metadata)
        self._cache[norm_assay] = artifact
        return artifact


def _normalise_assay(assay: str | None) -> str:
    """Normalise assay key for folder lookup.

    Mirrors the canonical form used by the trainer, which is just
    the original spelling (the metadata.json carries ``assay``+``feature_columns``).
    Falls back to a stable strip/upper form for case-folded queries.
    """
    if not assay:
        return ""
    s = str(assay).strip()
    if not s:
        return ""
    # The trained pipeline saves the assay using the exact form passed in
    # (e.g. "FR1", "TCRG-A"), while runtime classifiers sometimes emit a
    # compact form ("TCRGA"). Use the compact key for cache/discovery and let
    # _resolve_assay_path map back to the on-disk spelling.
    return _assay_key(s)


def _assay_key(assay: str | None) -> str:
    return str(assay or "").strip().replace(" ", "").replace("-", "").replace("_", "").upper()


def _resolve_assay_path(model_dir: Path, raw_assay: str) -> list[Path]:
    """Return the candidate assay folder names under model_dir."""
    s = str(raw_assay).strip()
    candidates = []
    for c in (s, s.upper(), s.replace("-", "_"), s.replace("_", "-")):
        if c and (model_dir / c).is_dir():
            candidates.append(model_dir / c)
    raw_key = _assay_key(s)
    for child in sorted(Path(model_dir).iterdir()):
        if child.is_dir() and _assay_key(child.name) == raw_key and child not in candidates:
            candidates.append(child)
    return candidates


def _estimator_input(estimator: Any, X: pd.DataFrame) -> pd.DataFrame | np.ndarray:
    """Return X in the shape least likely to trigger sklearn feature warnings."""
    feature_names = getattr(estimator, "feature_names_in_", None)
    if feature_names is None:
        return X.values
    names = [str(name) for name in np.asarray(feature_names).tolist()]
    if all(name in X.columns for name in names):
        return X[names]
    return X


def flatten_features_for_inference(
    features: Mapping[str, Any],
    *,
    columns: Sequence[str],
) -> pd.DataFrame:
    """Project a runtime ``features_from_entry`` dict into the column
    layout expected by the loaded estimator.

    - Numeric, float-ish, and bool scalars fill 0.0 on column miss.
    - Nested per-``DATA*`` dicts (``peak_count_per_channel.DATA1``)
      expand to columns named with the chosen prefix.
    - Anything not in ``columns`` is ignored.
    - Missing values are filled with 0.0; non-finite values too. The
      loaded estimator (with its own sklearn imputer, if any) is the
      authoritative normaliser — this helper just guarantees shape.
    """
    if not columns:
        return pd.DataFrame()
    flat: dict[str, Any] = {}

    # First pass: numeric scalars / strings / lists
    for key, value in features.items():
        if key in columns:
            flat[key] = value

    # Second pass: nested per-channel fields
    for raw_key, prefix in _NESTED_FIELD_EXPANSION:
        nested = features.get(raw_key)
        if not isinstance(nested, dict):
            continue
        for channel, sub_value in nested.items():
            channel_key = str(channel).upper()
            for col in (
                f"{prefix}_{channel_key}",
                f"{raw_key}.{channel_key}",
            ):
                if col in columns:
                    flat[col] = sub_value

    # Third pass: ensure every required column is present with at least NaN
    for col in columns:
        flat.setdefault(col, np.nan)

    df = pd.DataFrame([{col: flat.get(col, np.nan) for col in columns}],
                      columns=list(columns))
    # Coerce to numeric (non-numeric -> NaN); the imputer in the loaded
    # scikit-learn pipeline is expected to handle NaN when present.
    for col in df.columns:
        series = df[col]
        if series.dtype == object or series.dtype.name == "category":
            df[col] = pd.to_numeric(series, errors="coerce")
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return df
