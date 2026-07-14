"""FLT3 / NPM1 analysis configuration."""
from __future__ import annotations

ASSAY_CONFIG = {
    "FLT3-ITD": {
        "dye": "ROX",
        "trace_channels": ["DATA1", "DATA2"],
        "peak_channels": ["DATA1", "DATA2"],
        "bp_min": 50.0,
        "bp_max": 1000.0,
        "wt_bp": 330.0,
        "itd_min_bp": 335.0,
        "peak_height_min": 20.0,
        "peak_prominence_min": 10.0,
        "peak_distance": 8,
        "positive_ratio": 0.02,
        "control_wt_min_area": 10000.0,
    },
    "FLT3-D835": {
        "dye": "ROX",
        "trace_channels": ["DATA3"],
        "peak_channels": ["DATA3"],
        "bp_min": 50.0,
        "bp_max": 250.0,
        "wt_bp": 80.0,
        "mut_bp": 129.0,
        "wt_range": (76.0, 83.5),
        "mut_ranges": [(121.0, 130.5)],
        "peak_height_min": 50.0,
        "peak_distance": 8,
        "positive_ratio": 0.05,
        "control_wt_min_area": 1000.0,
    },
    "NPM1": {
        "dye": "ROX",
        "trace_channels": ["DATA3"],
        "peak_channels": ["DATA3"],
        "bp_min": 50.0,
        "bp_max": 1000.0,
        "wt_bp": 300.0,
        "mut_bp": 304.0,
        "positive_ratio": 0.01,
    },
}

ROX_LADDER = "GS500ROX"
BP_CORRECTION_OFFSETS = {
    "FLT3-ITD": 0.0,
    "FLT3-D835": 0.0,
    "NPM1": 0.0,
}

ASSAY_DISPLAY_ORDER = ["FLT3-ITD", "FLT3-D835", "NPM1"]
NONSPECIFIC_PEAKS = {}
REFERENCE_SHADE_COLOR = "#ded7a6"
ASSAY_REFERENCE_RANGES = {
    "FLT3-ITD": [(300.0, 1000.0)],
    "FLT3-D835": [(50.0, 250.0)],
    "NPM1": [(299.0, 301.0), (303.0, 305.0)],
}
ASSAY_REFERENCE_LABEL = {
    "FLT3-ITD": "Analysevindu: 300-1000 bp. Villtype forventet rundt 330 bp, mutert >335 bp.",
    "FLT3-D835": "Analysevindu: 50-250 bp. Villtype: 80 bp, Mutert >129 bp.",
    "NPM1": "Villtype: 299/300-301 bp, Mutert: 303-305 bp",
}

# Plot-only x-axis window (bp). Overrides the detector's bp_min/bp_max
# for the report plot's *initial* axis range so the chemist sees the
# relevant hybridisation zone first. Plotly's native zoom/pan lets
# the chemist widen the view interactively (auto-reset on
# double-click). Lifted out of `_create_plotly_figure` so each assay's
# window is explicit at the config layer.
FLT3_PLOT_BP_WINDOWS: dict[str, tuple[float, float]] = {
    "NPM1": (290.0, 330.0),
}

# Half-width (bp) applied to NPM1 peak-area integration when the
# detector is on the local-sideband baseline. Default 1.0 bp (matches
# GeneMapper "tight" Gaussian). App-tunable via
# `analyses.flt3.peak_window.npm1_half_width_bp`.
FLT3_NPM1_DEFAULT_HALF_WIDTH_BP: float = 1.0


def get_flt3_plot_window(
    assay: str,
    *,
    settings: "dict | None" = None,
) -> tuple[float, float] | None:
    """Return (xmin, xmax) override for the report plot's x-axis range.

    Pure-Python accessor: optional ``settings`` (Dict, defaults to
    ``APP_SETTINGS``) honours per-analysis overrides seeded in
    `analyses.flt3.peak_window.npm1_x_min` / `npm1_x_max`. Returns
    ``None`` when the assay has no registered window so the figure
    builder falls through to its existing detector-driven bp_min/bp_max.
    """
    if assay not in FLT3_PLOT_BP_WINDOWS:
        return None
    default_xmin, default_xmax = FLT3_PLOT_BP_WINDOWS[assay]
    if settings is None:
        try:
            from config import APP_SETTINGS  # type: ignore
            settings = APP_SETTINGS
        except Exception:
            return (default_xmin, default_xmax)
    profile = (settings or {}).get("analyses", {}).get("flt3", {}).get("peak_window", {}) or {}
    xmin = float(profile.get("npm1_x_min", default_xmin))
    xmax = float(profile.get("npm1_x_max", default_xmax))
    if xmax - xmin < 1.0:
        # sanity: keep the window at least 1 bp wide so a malformed
        # settings save does not collapse the plot
        return (default_xmin, default_xmax)
    return (xmin, xmax)


def get_flt3_npm1_half_width_bp(
    *,
    settings: "dict | None" = None,
) -> float:
    """Return the NPM1 peak-area half-width in bp.

    Defaults to ``FLT3_NPM1_DEFAULT_HALF_WIDTH_BP``. App-tunable via
    ``analyses.flt3.peak_window.npm1_half_width_bp``; clamp to the
    sane range [0.3, 5.0] so a malformed save does not flatten the
    integration or balloon it back to the GeneMapper-unmatched
    5-bp fallthrough.
    """
    default = FLT3_NPM1_DEFAULT_HALF_WIDTH_BP
    if settings is None:
        try:
            from config import APP_SETTINGS  # type: ignore
            settings = APP_SETTINGS
        except Exception:
            return default
    profile = (settings or {}).get("analyses", {}).get("flt3", {}).get("peak_window", {}) or {}
    try:
        value = float(profile.get("npm1_half_width_bp", default))
    except (TypeError, ValueError):
        return default
    return float(max(0.3, min(5.0, value)))


def get_flt3_peak_window_settings(
    *,
    settings: "dict | None" = None,
) -> dict[str, float]:
    """Bundle accessor for both values; used by the GUI to read-from/save-to one place."""
    if settings is None:
        try:
            from config import APP_SETTINGS  # type: ignore
            settings = APP_SETTINGS
        except Exception:
            settings = None
    profile: dict[str, float] = ({} if settings is None else (settings.get("analyses", {}).get("flt3", {}).get("peak_window", {}) or {}))
    try:
        half = float(profile.get("npm1_half_width_bp", FLT3_NPM1_DEFAULT_HALF_WIDTH_BP))
    except (TypeError, ValueError):
        half = FLT3_NPM1_DEFAULT_HALF_WIDTH_BP
    half = float(max(0.3, min(5.0, half)))
    default_xmin, default_xmax = FLT3_PLOT_BP_WINDOWS.get("NPM1", (290.0, 330.0))
    try:
        xmin = float(profile.get("npm1_x_min", default_xmin))
        xmax = float(profile.get("npm1_x_max", default_xmax))
    except (TypeError, ValueError):
        xmin, xmax = default_xmin, default_xmax
    if xmax - xmin < 1.0:
        xmin, xmax = default_xmin, default_xmax
    return {
        "npm1_half_width_bp": half,
        "npm1_x_min": xmin,
        "npm1_x_max": xmax,
    }


# Injection time preference (seconds)
PREFERRED_INJECTION_TIME = {
    "FLT3-D835": 3,
    "TKD_digested": 3,
    "undiluted": 3,
    "ratio_quant": 1,
    "10x_diluted": 1,
    "25x_diluted": 1,
    "FLT3-ITD": 1,
    "NPM1": 3,
}
