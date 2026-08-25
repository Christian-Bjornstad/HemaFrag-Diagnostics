"""Lightweight baseline utilities.

Extracted verbatim from ``core/analysis/_legacy`` so plotting, QC and HTML
report modules can compute baselines WITHOUT importing scipy / sklearn at
application startup. Depends only on numpy plus fraggler's ``baseline_arPLS``
(the fraggler package itself is verified light — it pulls no scientific
stack at import time).
"""
from __future__ import annotations

import numpy as np

try:  # pragma: no cover - environment dependent
    from fraggler.fraggler import baseline_arPLS
except Exception:  # pragma: no cover - degrade to rolling fallback
    baseline_arPLS = None

BASELINE_BIN_SIZE = 200
BASELINE_QUANTILE = 0.10


def _rolling_quantile_baseline(
    trace: np.ndarray,
    bin_size: int = BASELINE_BIN_SIZE,
    quantile: float = BASELINE_QUANTILE,
) -> np.ndarray:
    """Low-envelope baseline estimated from per-bin quantiles.

    Same semantics as the original Python-loop implementation:
    bins of size ``bin_size`` cover the trace, the last bin may be
    shorter, and the per-bin output is linearly interpolated back to
    the original index range.
    """
    values = np.asarray(trace, dtype=float)
    n = values.size
    if n == 0:
        return np.zeros_like(values, dtype=float)
    if bin_size < 20:
        bin_size = 20

    full_bins = n // bin_size
    rem = n % bin_size

    with np.errstate(all="ignore"):
        if full_bins == 0:
            # n < bin_size: a single short bin.
            centres = np.array([0.5 * (n - 1)], dtype=float)
            q_vals = np.array([float(np.quantile(values, quantile))],
                              dtype=float)
        elif rem == 0:
            # Perfect fit: every bin has exactly `bin_size` items.
            bins = values.reshape((full_bins, bin_size))
            centres = (np.arange(full_bins, dtype=float) * bin_size
                       + 0.5 * (bin_size - 1.0))
            q_vals = np.quantile(bins, quantile, axis=1)
        else:
            # `full_bins` complete bins + one short trailing bin.
            head = values[: full_bins * bin_size].reshape((full_bins, bin_size))
            tail = values[full_bins * bin_size:]
            centres = np.empty(full_bins + 1, dtype=float)
            centres[:full_bins] = (
                np.arange(full_bins, dtype=float) * bin_size
                + 0.5 * (bin_size - 1.0)
            )
            centres[full_bins] = 0.5 * (full_bins * bin_size + n - 1)
            head_q = np.quantile(head, quantile, axis=1)
            tail_q = float(np.quantile(tail, quantile))
            q_vals = np.empty(full_bins + 1, dtype=float)
            q_vals[:full_bins] = head_q
            q_vals[full_bins] = tail_q

    idx = np.arange(n, dtype=float)
    if q_vals.size == 1:
        return np.full_like(idx, q_vals[0], dtype=float)

    return np.interp(
        idx,
        centres,
        q_vals,
        left=q_vals[0],
        right=q_vals[-1],
    )


def _compute_robust_arpls_baseline(
    trace: np.ndarray,
    lam: float = 100.0,
    ratio: float = 0.99,
) -> np.ndarray:
    """
    Robust baseline for high-dynamic-range traces.
    Caps extreme spikes before arPLS and constrains the output against a
    rolling low-envelope to avoid baseline "mountains" under tall peaks.
    """
    values = np.asarray(trace, dtype=float)
    if values.size == 0:
        return np.zeros_like(values, dtype=float)

    try:
        if baseline_arPLS is None:
            raise RuntimeError("fraggler.baseline_arPLS unavailable")
        baseline = np.asarray(baseline_arPLS(values, ratio=ratio, lam=lam), dtype=float)
    except Exception:
        baseline = _rolling_quantile_baseline(values, bin_size=BASELINE_BIN_SIZE, quantile=BASELINE_QUANTILE)

    envelope = _rolling_quantile_baseline(values, bin_size=BASELINE_BIN_SIZE, quantile=BASELINE_QUANTILE)
    residual = values - envelope
    residual_scale = float(np.std(residual)) if residual.size else 0.0
    positive_excess = np.maximum(baseline - envelope, 0.0)
    mountain_score = float(np.quantile(positive_excess, 0.95)) if positive_excess.size else 0.0

    upper_guard = max(10.0, 0.10 * residual_scale)
    lower_guard = max(25.0, 2.5 * upper_guard)
    if mountain_score <= upper_guard:
        constrained = baseline
    else:
        constrained = np.clip(baseline, envelope - lower_guard, envelope + upper_guard)
    constrained = np.where(np.isfinite(constrained), constrained, envelope)
    return constrained


def estimate_running_baseline(
    trace: np.ndarray,
    bin_size: int = BASELINE_BIN_SIZE,
    quantile: float = BASELINE_QUANTILE,
    use_arpls: bool = True,
    lam: float = 100.0,
) -> np.ndarray:
    """Robust rullende baseline med arPLS som default."""
    n = trace.size
    if n == 0:
        return np.zeros_like(trace, dtype=float)

    if use_arpls:
        try:
            baseline = _compute_robust_arpls_baseline(trace, lam=lam, ratio=0.99)
            return baseline
        except Exception:
            pass  # Fallback til den enkle metoden

    if bin_size < 20:
        bin_size = 20

    return _rolling_quantile_baseline(trace, bin_size=bin_size, quantile=quantile)


def baseline_correct_ladder_trace(
    trace: np.ndarray,
    *,
    bin_size: int = BASELINE_BIN_SIZE,
    quantile: float = BASELINE_QUANTILE,
) -> np.ndarray:
    """Return a nonnegative, peak-preserving size-standard trace.

    Ladder peaks are narrow compared with a 200-scan baseline window. A low
    quantile envelope follows offset/drift (including negative baselines)
    without following the ladder peaks themselves. This deliberately
    conservative correction may leave a little residual background, but it
    does not flatten the peaks that the fitter needs.
    """
    values = np.asarray(trace, dtype=float).reshape(-1)
    if values.size == 0:
        return values.copy()

    finite = np.isfinite(values)
    if not np.any(finite):
        return np.zeros_like(values, dtype=float)
    if not np.all(finite):
        indices = np.arange(values.size, dtype=float)
        values = np.interp(indices, indices[finite], values[finite])

    baseline = _rolling_quantile_baseline(
        values,
        bin_size=max(20, int(bin_size)),
        quantile=float(np.clip(quantile, 0.01, 0.35)),
    )
    corrected = np.maximum(values - baseline, 0.0)
    return np.where(np.isfinite(corrected), corrected, 0.0)
