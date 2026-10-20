"""Conservative sizing for manually assigned, incomplete ladders."""
from __future__ import annotations

import numpy as np
import pandas as pd


class _BoundedLinearSizingModel:
    """Match observed anchors exactly, without extrapolating missing end steps.

    ``predict`` follows the fitted ladder model interface used by QC and plots.
    Values outside the observed interval deliberately have no assigned size.
    """

    def __init__(self, times: np.ndarray, sizes: np.ndarray):
        self.times = times.copy()
        self.sizes = sizes.copy()

    def predict(self, scans: np.ndarray) -> np.ndarray:
        return np.interp(
            np.asarray(scans, dtype=float).reshape(-1),
            self.times,
            self.sizes,
            left=np.nan,
            right=np.nan,
        )


def fit_partial_manual_ladder(fsa):
    """Build a strictly increasing sample domain only between observed anchors.

    An unconstrained regression spline can turn backwards with missing anchors,
    including inside the mapped interval. Piecewise linear interpolation cannot
    overshoot ordered anchors, and does not invent observations for missing
    ladder steps. Keep full precision so slow sizing slopes do not round into
    plateaus; display layers can still round values when presenting them.
    """
    times = np.asarray(fsa.best_size_standard, dtype=float)
    sizes = np.asarray(fsa.ladder_steps, dtype=float)
    if (
        times.ndim != 1
        or sizes.ndim != 1
        or times.size < 3
        or times.size != sizes.size
        or not np.isfinite(times).all()
        or not np.isfinite(sizes).all()
        or np.any(np.diff(times) <= 0)
        or np.any(np.diff(sizes) <= 0)
    ):
        raise ValueError("Partial manual sizing needs at least three strictly increasing paired anchors.")

    sample = np.asarray(fsa.sample_data, dtype=float)
    first_scan = max(0, int(np.ceil(times[0])))
    last_scan = min(sample.size - 1, int(np.floor(times[-1])))
    if last_scan <= first_scan:
        raise ValueError("Partial manual ladder anchors do not cover a usable sample interval.")
    scans = np.arange(first_scan, last_scan + 1, dtype=int)
    model = _BoundedLinearSizingModel(times, sizes)
    frame = pd.DataFrame(
        {"time": scans, "peaks": sample[scans], "basepairs": model.predict(scans)}
    )
    fsa.ladder_model = model
    fsa.sample_data_with_basepairs = frame
    fsa.fitted_to_model = True
    fsa.manual_ladder_sizing_method = "bounded_linear"
    fsa.manual_ladder_sizing_time_range = [float(times[0]), float(times[-1])]
    fsa.manual_ladder_sizing_bp_range = [float(sizes[0]), float(sizes[-1])]
    return fsa
