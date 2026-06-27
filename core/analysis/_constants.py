"""
HemaFrag — analysis constants.

Auto-curated from the previous monolithic `core/analysis.py` during the
2026-06-27 `code-cleanup` Phase 2. Re-exported by `core/analysis/__init__.py`
unchanged so all downstream `from core.analysis import CONST` keep working.
"""
from __future__ import annotations

import numpy as np


# --------------------------------------------------------------
# Analysis Constants (extracted magic numbers)
# --------------------------------------------------------------
LADDER_MAX_ITERATIONS = 15
BASELINE_BIN_SIZE = 200
BASELINE_QUANTILE = 0.10
PEAK_MIN_HEIGHT = 800.0
YMAX_PADDING_FACTOR = 1.15
MIN_R2_QUALITY = 0.998  # Post-fit quality gate
LADDER_CANDIDATE_COUNT = 5
HIGH_END_RESCUE_R2 = 0.9999
LOW_INTENSITY_RATIO_FLOOR = 0.55
MEDIAN_INTENSITY_TARGET_RATIO = 0.80
EARLY_PEAK_INTENSITY_WEIGHT = 1.2
GLOBAL_PEAK_INTENSITY_WEIGHT = 0.45
SEVERE_WEAK_PEAK_PENALTY = 0.30
DESCENDING_RECOVERY_R2_FLOOR = 0.9985
DESCENDING_RECOVERY_MAX_ABS_ERROR = 3.0
DESCENDING_RECOVERY_MEAN_ABS_ERROR = 1.6
ASCENDING_RECOVERY_R2_FLOOR = 0.9985
ASCENDING_RECOVERY_MAX_ABS_ERROR = 3.0
ASCENDING_RECOVERY_MEAN_ABS_ERROR = 1.6
ASCENDING_RECOVERY_MIN_INTENSITY = 300.0
GENERAL_COMPLETION_R2_FLOOR = 0.9985
GENERAL_COMPLETION_MAX_ABS_ERROR = 3.0
GENERAL_COMPLETION_MEAN_ABS_ERROR = 1.8
GENERAL_COMPLETION_MIN_INTENSITY = 300.0
CORE_COMPLETION_MIN_ASSIGNED = 12
GS500_FAMILY_STEPS = np.array(
    [35.0, 50.0, 75.0, 100.0, 139.0, 150.0, 160.0, 200.0, 250.0, 300.0, 340.0, 350.0, 400.0, 450.0, 490.0, 500.0],
    dtype=float,
)


def _abi_data_channels(fsa_path: Path) -> set[str]:
    try:
        tags = SeqIO.read(str(fsa_path), "abi").annotations.get("abif_raw", {})
    except Exception:
        return set()
    return {str(key) for key in tags.keys() if str(key).startswith("DATA")}


def _preferred_size_standard_channel_for_file(fsa_path: Path, ladder_name: str) -> str:
    channels = _abi_data_channels(fsa_path)
    ladder_upper = str(ladder_name or "").upper()

    if "LIZ" in ladder_upper:
        if "DATA105" in channels:
            return "DATA105"
        if "DATA5" in channels:
            return "DATA5"
        return "DATA105"

    if "DATA4" in channels:
        return "DATA4"
    if "DATA105" in channels:
        return "DATA105"
    return "DATA4"
ROX400HD_FAMILY_STEPS = np.array(
    [50.0, 60.0, 90.0, 100.0, 120.0, 150.0, 160.0, 180.0, 190.0, 200.0, 220.0, 240.0, 260.0, 280.0, 290.0, 300.0, 320.0, 340.0, 360.0, 380.0, 400.0],
    dtype=float,
)
GS500_LOCAL_REFINEMENT_TRIGGER_MAX_ABS_ERROR = 1.25
GS500_LOCAL_REFINEMENT_TRIGGER_MEAN_ABS_ERROR = 0.70
GS500_LOCAL_REFINEMENT_STEP_RESIDUAL = 0.85
GS500_LOCAL_REFINEMENT_EARLY_STEP_RESIDUAL = 0.55
GS500_LOCAL_REFINEMENT_MAX_STEPS = 5
GS500_LOCAL_REFINEMENT_MAX_OPTIONS_PER_STEP = 4
GS500_LOCAL_REFINEMENT_MAX_TRIALS = 256
GS500_LOCAL_REFINEMENT_MIN_SCORE_GAIN = 0.12
GS500_LOCAL_REFINEMENT_MIN_MAX_ERROR_GAIN = 0.20
GS500_LOCAL_REFINEMENT_MAX_R2_DROP = 0.0008
GS500_TRACE_OPTION_MIN_DISTANCE = 18
GS500_TRACE_OPTION_MIN_HEIGHT = 120.0
GS500_EDGE_TRACE_OPTION_MIN_HEIGHT = 55.0
GS500_TRACE_OPTION_REL_HEIGHT = 0.18
GS500_EDGE_TRACE_OPTION_REL_HEIGHT = 0.08
GS500_ANCHOR_BLOCK_MAX_RESIDUAL = 1.5
GS500_BLOCK_REFINEMENT_MARGIN = 120.0
GS500_BLOCK_REFINEMENT_MIN_DISTANCE = 10
GS500_BLOCK_REFINEMENT_MIN_HEIGHT = 80.0
GS500_EDGE_BLOCK_REFINEMENT_MARGIN = 180.0

# --- Deep Search (Super-Search) Fallback ---
DEEP_SEARCH_TIMEOUT = 300.0  # 5 minutes
DEEP_SEARCH_PEAK_CAP = 80
DEEP_SEARCH_TRIGGER_CURVATURE = 0.5
DEEP_SEARCH_TRIGGER_MAX_ERROR = 5.0
DEEP_SEARCH_BEAM_WIDTH = 500
STRICT_LADDER_SIGNAL_RULES = {
    "LIZ500": {
        "height_floor": 100.0,
        "prominence_floor": 25.0,
        "distance": 15,
    },
    "ROX400HD": {
        "height_floor": 100.0,
        "prominence_floor": 25.0,
        "distance": 15,
    },
    "GS500ROX": {
        "height_floor": 100.0,
        "prominence_floor": 25.0,
        "distance": 15,
    },
}

GS500_EDGE_BLOCK_REFINEMENT_MIN_HEIGHT = 45.0
GS500_BLOCK_REFINEMENT_MAX_CANDIDATES = 10
GS500_ANCHOR_BLOCKS: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3),
    (1, 2, 3),
    (4, 5, 6, 7),
    (12, 13, 14, 15),
    (13, 14, 15),
)
ROX400HD_LOCAL_REFINEMENT_TRIGGER_MAX_ABS_ERROR = 0.95
ROX400HD_LOCAL_REFINEMENT_TRIGGER_MEAN_ABS_ERROR = 0.45
ROX400HD_LOCAL_REFINEMENT_STEP_RESIDUAL = 0.75
ROX400HD_LOCAL_REFINEMENT_EARLY_STEP_RESIDUAL = 0.55
ROX400HD_LOCAL_REFINEMENT_MAX_STEPS = 4
ROX400HD_LOCAL_REFINEMENT_MAX_OPTIONS_PER_STEP = 4
ROX400HD_LOCAL_REFINEMENT_MAX_TRIALS = 256
ROX400HD_LOCAL_REFINEMENT_MIN_SCORE_GAIN = 0.10
ROX400HD_LOCAL_REFINEMENT_MIN_MAX_ERROR_GAIN = 0.20
ROX400HD_LOCAL_REFINEMENT_MAX_R2_DROP = 0.0008

LADDER_FIT_PROFILE_CLONALITY_LIZ500 = "clonality_liz500"
LADDER_FIT_PROFILE_CLONALITY_ROX400HD = "clonality_rox400hd"
LADDER_FIT_PROFILE_FLT3_GS500ROX = "flt3_gs500rox"

LADDER_FIT_AUTO_ACCEPT_RULES: dict[str, dict[str, float]] = {
    LADDER_FIT_PROFILE_CLONALITY_LIZ500: {
        "r2_floor": 0.9985,
        "mean_abs_error_bp": 1.8,
        "max_abs_error_bp": 3.0,
        "linear_trend_max_abs_error_bp": 30.0,
        "max_curvature": 0.9,
    },
    LADDER_FIT_PROFILE_CLONALITY_ROX400HD: {
        "r2_floor": 0.9980,
        "mean_abs_error_bp": 1.8,
        "max_abs_error_bp": 3.0,
        "linear_trend_max_abs_error_bp": 30.0,
        "max_curvature": 0.9,
    },
    LADDER_FIT_PROFILE_FLT3_GS500ROX: {
        "r2_floor": 0.9985,
        "mean_abs_error_bp": 3.0,
        "max_abs_error_bp": 6.0,
        "linear_trend_max_abs_error_bp": 6.0,
        "max_curvature": 0.5,
    },
}

LADDER_FIT_GS500_REFINEMENT_RULES: dict[str, dict[str, Any]] = {
    LADDER_FIT_PROFILE_CLONALITY_LIZ500: {
        "trigger_max_abs_error": GS500_LOCAL_REFINEMENT_TRIGGER_MAX_ABS_ERROR,
        "trigger_mean_abs_error": GS500_LOCAL_REFINEMENT_TRIGGER_MEAN_ABS_ERROR,
        "step_residual": GS500_LOCAL_REFINEMENT_STEP_RESIDUAL,
        "early_step_residual": GS500_LOCAL_REFINEMENT_EARLY_STEP_RESIDUAL,
        "max_steps": GS500_LOCAL_REFINEMENT_MAX_STEPS,
        "max_options_per_step": GS500_LOCAL_REFINEMENT_MAX_OPTIONS_PER_STEP,
        "max_trials": GS500_LOCAL_REFINEMENT_MAX_TRIALS,
        "min_score_gain": GS500_LOCAL_REFINEMENT_MIN_SCORE_GAIN,
        "min_max_error_gain": GS500_LOCAL_REFINEMENT_MIN_MAX_ERROR_GAIN,
        "max_r2_drop": GS500_LOCAL_REFINEMENT_MAX_R2_DROP,
        "trace_option_min_distance": GS500_TRACE_OPTION_MIN_DISTANCE,
        "trace_option_min_height": GS500_TRACE_OPTION_MIN_HEIGHT,
        "edge_trace_option_min_height": GS500_EDGE_TRACE_OPTION_MIN_HEIGHT,
        "trace_option_rel_height": GS500_TRACE_OPTION_REL_HEIGHT,
        "edge_trace_option_rel_height": GS500_EDGE_TRACE_OPTION_REL_HEIGHT,
        "anchor_block_max_residual": GS500_ANCHOR_BLOCK_MAX_RESIDUAL,
        "block_refinement_margin": GS500_BLOCK_REFINEMENT_MARGIN,
        "block_refinement_min_distance": GS500_BLOCK_REFINEMENT_MIN_DISTANCE,
        "block_refinement_min_height": GS500_BLOCK_REFINEMENT_MIN_HEIGHT,
        "edge_block_refinement_margin": GS500_EDGE_BLOCK_REFINEMENT_MARGIN,
        "edge_block_refinement_min_height": GS500_EDGE_BLOCK_REFINEMENT_MIN_HEIGHT,
        "block_refinement_max_candidates": GS500_BLOCK_REFINEMENT_MAX_CANDIDATES,
        "anchor_blocks": GS500_ANCHOR_BLOCKS,
    },
    LADDER_FIT_PROFILE_FLT3_GS500ROX: {
        "trigger_max_abs_error": GS500_LOCAL_REFINEMENT_TRIGGER_MAX_ABS_ERROR,
        "trigger_mean_abs_error": GS500_LOCAL_REFINEMENT_TRIGGER_MEAN_ABS_ERROR,
        "step_residual": GS500_LOCAL_REFINEMENT_STEP_RESIDUAL,
        "early_step_residual": GS500_LOCAL_REFINEMENT_EARLY_STEP_RESIDUAL,
        "max_steps": GS500_LOCAL_REFINEMENT_MAX_STEPS,
        "max_options_per_step": GS500_LOCAL_REFINEMENT_MAX_OPTIONS_PER_STEP,
        "max_trials": GS500_LOCAL_REFINEMENT_MAX_TRIALS,
        "min_score_gain": GS500_LOCAL_REFINEMENT_MIN_SCORE_GAIN,
        "min_max_error_gain": GS500_LOCAL_REFINEMENT_MIN_MAX_ERROR_GAIN,
        "max_r2_drop": GS500_LOCAL_REFINEMENT_MAX_R2_DROP,
        "trace_option_min_distance": GS500_TRACE_OPTION_MIN_DISTANCE,
        "trace_option_min_height": GS500_TRACE_OPTION_MIN_HEIGHT,
        "edge_trace_option_min_height": GS500_EDGE_TRACE_OPTION_MIN_HEIGHT,
        "trace_option_rel_height": GS500_TRACE_OPTION_REL_HEIGHT,
        "edge_trace_option_rel_height": GS500_EDGE_TRACE_OPTION_REL_HEIGHT,
        "anchor_block_max_residual": GS500_ANCHOR_BLOCK_MAX_RESIDUAL,
        "block_refinement_margin": GS500_BLOCK_REFINEMENT_MARGIN,
        "block_refinement_min_distance": GS500_BLOCK_REFINEMENT_MIN_DISTANCE,
        "block_refinement_min_height": GS500_BLOCK_REFINEMENT_MIN_HEIGHT,
        "edge_block_refinement_margin": GS500_EDGE_BLOCK_REFINEMENT_MARGIN,
        "edge_block_refinement_min_height": GS500_EDGE_BLOCK_REFINEMENT_MIN_HEIGHT,
        "block_refinement_max_candidates": GS500_BLOCK_REFINEMENT_MAX_CANDIDATES,
        "anchor_blocks": GS500_ANCHOR_BLOCKS,
    },
}

LADDER_FIT_ROX400HD_REFINEMENT_RULES: dict[str, dict[str, float]] = {
    LADDER_FIT_PROFILE_CLONALITY_ROX400HD: {
        "trigger_max_abs_error": ROX400HD_LOCAL_REFINEMENT_TRIGGER_MAX_ABS_ERROR,
        "trigger_mean_abs_error": ROX400HD_LOCAL_REFINEMENT_TRIGGER_MEAN_ABS_ERROR,
        "step_residual": ROX400HD_LOCAL_REFINEMENT_STEP_RESIDUAL,
        "early_step_residual": ROX400HD_LOCAL_REFINEMENT_EARLY_STEP_RESIDUAL,
        "max_steps": ROX400HD_LOCAL_REFINEMENT_MAX_STEPS,
        "max_options_per_step": ROX400HD_LOCAL_REFINEMENT_MAX_OPTIONS_PER_STEP,
        "max_trials": ROX400HD_LOCAL_REFINEMENT_MAX_TRIALS,
        "min_score_gain": ROX400HD_LOCAL_REFINEMENT_MIN_SCORE_GAIN,
        "min_max_error_gain": ROX400HD_LOCAL_REFINEMENT_MIN_MAX_ERROR_GAIN,
        "max_r2_drop": ROX400HD_LOCAL_REFINEMENT_MAX_R2_DROP,
    },
}
