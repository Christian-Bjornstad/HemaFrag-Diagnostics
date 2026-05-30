"""
HemaFrag Diagnostics — Main Pipeline.

``run_pipeline`` processes all .fsa files in a directory, classifies them,
fits ladders, detects peaks, builds DIT reports, and orchestrates the full
analysis flow.
"""
from __future__ import annotations

import os
import re
import sys
import __main__
import threading
import time
from pathlib import Path
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

from fraggler.fraggler import print_green, print_warning

from config import resolve_analysis_excel_output_path
from core.analyses.clonality.config import (
    ASSAY_CONFIG,
    LIZ_LADDER,
    ROX_LADDER,
    SL_TARGET_FRAGMENTS_BP,
    SL_WINDOW_BP,
)
from core.analyses.clonality.classification import classify_fsa
from core.analyses.clonality.tracking_excel import (
    CLONALITY_TRACKING_FILENAME,
    resolve_original_input_path,
    resolve_source_run_dir,
    update_clonality_tracking_workbook,
)
from core.analysis import (
    LADDER_FIT_PROFILE_CLONALITY_LIZ500,
    LADDER_FIT_PROFILE_CLONALITY_ROX400HD,
    analyse_fsa_liz,
    analyse_fsa_rox,
    auto_detect_sl_peaks,
    compute_ladder_qc_metrics,
    compute_sl_area_metrics,
)
from core.plotting_plotly import (
    compute_group_ymax_for_entries,
    build_interactive_assay_batch_plot_html,
)
from core.plotting_mpl import compute_zoom_ymax
from core.html_reports import (
    extract_dit_from_name,
)
from core.engine_flags import strict_rust_ladder_enabled
from core.analyses.shared_pipeline import (
    finalize_pipeline_run,
    normalize_pipeline_paths,
    scan_fsa_files,
)
from core.utils import strip_stage_prefix


def _scan_files(fsa_dir: Path, mode: str = "all") -> list[Path]:
    """Scans for .fsa files, filtering out water files and optionally non-controls."""
    fsa_files = scan_fsa_files(fsa_dir, mode=mode)
    if fsa_files:
        print_green(f"Fant {len(fsa_files)} .fsa-filer: {[p.name for p in fsa_files]}")
    return fsa_files


def _progress_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _emit_progress(
    progress_callback,
    *,
    phase: str,
    file_name: str = "",
    files_done: int = 0,
    files_total: int = 0,
    note: str = "",
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        {
            "folder_name": "",
            "job_name": "",
            "phase": phase,
            "file_name": file_name,
            "files_done": int(files_done),
            "files_total": int(files_total),
            "jobs_done": 0,
            "jobs_total": 0,
            "heartbeat_at": _progress_timestamp(),
            "note": note,
        }
    )


def _should_use_multiprocessing() -> bool:
    if strict_rust_ladder_enabled():
        return False
    try:
        from config import APP_SETTINGS

        if APP_SETTINGS.get("engine", {}).get("use_rust", False):
            allow_pool = os.environ.get("HEMAFRAG_CLONALITY_ALLOW_PYTHON_POOL_WITH_RUST", "").strip().lower()
            if allow_pool not in {"1", "true", "yes", "on"} and _rust_worker_batch_mode_available():
                return False
    except Exception:
        pass
    disabled = os.environ.get("FRAGGLER_DISABLE_MULTIPROCESSING", "").strip().lower()
    if disabled in {"1", "true", "yes", "on"}:
        return False
    if getattr(sys, "frozen", False):
        return False
    main_file = getattr(__main__, "__file__", "")
    if not main_file or str(main_file).startswith("<"):
        return False
    if not Path(main_file).exists():
        return False
    return True


def _rust_worker_batch_mode_available() -> bool:
    try:
        from core.rust_bridge import _persistent_rust_worker_supported, _resolve_cli_bin

        cli_bin = _resolve_cli_bin()
        return bool(_persistent_rust_worker_supported() and cli_bin is not None and cli_bin.exists())
    except Exception:
        return False


def _build_peaks_from_rust_clonality_preview(fsa, assay: str, primary_peak_channel: str) -> dict[str, pd.DataFrame]:
    preview = getattr(fsa, "rust_clonality_preview", None)
    if not isinstance(preview, dict):
        return {}

    ranked_assays = preview.get("ranked_assays") or []
    if not isinstance(ranked_assays, list):
        return {}

    assay_key = str(assay or "").strip().lower()
    selected = None
    for candidate in ranked_assays:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("assay_name") or "").strip().lower() == assay_key:
            selected = candidate
            break
    if selected is None:
        for candidate in ranked_assays:
            if isinstance(candidate, dict) and candidate.get("matched_by_filename"):
                selected = candidate
                break
    if selected is None and ranked_assays and isinstance(ranked_assays[0], dict):
        selected = ranked_assays[0]
    if not isinstance(selected, dict):
        return {}

    channel_peak_previews = preview.get("channel_peak_previews")
    channel_rows: dict[str, list[dict]] = {}
    if isinstance(channel_peak_previews, dict):
        selected_channels = selected.get("channels")
        allowed_channels = {str(channel) for channel in selected_channels} if isinstance(selected_channels, list) else set()
        assay_min = selected.get("assay_bp_min")
        assay_max = selected.get("assay_bp_max")
        try:
            assay_min_f = float(assay_min) if assay_min is not None else np.nan
            assay_max_f = float(assay_max) if assay_max is not None else np.nan
        except (TypeError, ValueError):
            assay_min_f = np.nan
            assay_max_f = np.nan
        for channel, peaks in channel_peak_previews.items():
            channel_name = str(channel)
            if allowed_channels and channel_name not in allowed_channels:
                continue
            if not isinstance(peaks, list):
                continue
            for index, peak in enumerate(peaks):
                if not isinstance(peak, dict):
                    continue
                try:
                    bp_f = float(peak.get("basepair"))
                    height_f = float(peak.get("intensity"))
                except (TypeError, ValueError):
                    continue
                if not np.isfinite(bp_f) or not np.isfinite(height_f):
                    continue
                if np.isfinite(assay_min_f) and bp_f < assay_min_f:
                    continue
                if np.isfinite(assay_max_f) and bp_f > assay_max_f:
                    continue
                channel_rows.setdefault(channel_name, []).append(
                    {
                        "basepairs": bp_f,
                        "peaks": height_f,
                        "area": float(peak.get("area")) if peak.get("area") is not None else np.nan,
                        "keep": True,
                        "rust_preview": True,
                        "rust_group_id": index + 1,
                        "rust_dominant_ratio": np.nan,
                    }
                )
    if channel_rows:
        return {
            channel: pd.DataFrame(rows)
            .sort_values(["basepairs", "peaks"], ascending=[True, False])
            .reset_index(drop=True)
            for channel, rows in channel_rows.items()
            if rows
        }

    rows = []
    for group in selected.get("matched_groups") or []:
        if not isinstance(group, dict):
            continue
        bp = group.get("dominant_peak_basepair")
        height = group.get("dominant_peak_intensity")
        area = group.get("dominant_peak_area")
        try:
            bp_f = float(bp)
            height_f = float(height)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(bp_f) or not np.isfinite(height_f):
            continue
        rows.append(
            {
                "basepairs": bp_f,
                "peaks": height_f,
                "area": float(area) if area is not None else np.nan,
                "keep": bool(group.get("clonal_candidate", True)),
                "rust_preview": True,
                "rust_group_id": int(group.get("group_id", 0) or 0),
                "rust_dominant_ratio": float(group.get("dominant_ratio_vs_second"))
                if group.get("dominant_ratio_vs_second") is not None
                else np.nan,
            }
        )

    if not rows:
        return {}
    df = (
        pd.DataFrame(rows)
        .sort_values(["basepairs", "peaks"], ascending=[True, False])
        .reset_index(drop=True)
    )
    return {primary_peak_channel: df}


def _select_rust_marker_candidate(
    preview: dict,
    *,
    channel: str,
    target_bp: float,
    window_bp: float,
) -> dict:
    channel_previews = preview.get("channel_peak_previews")
    if not isinstance(channel_previews, dict):
        return {"ok": False, "reason": "rust_channel_peak_previews_missing"}
    peaks = channel_previews.get(str(channel))
    if not isinstance(peaks, list):
        return {"ok": False, "reason": "rust_marker_channel_missing"}

    candidates = []
    for peak in peaks:
        if not isinstance(peak, dict):
            continue
        try:
            found_bp = float(peak.get("basepair"))
            height = float(peak.get("intensity"))
        except (TypeError, ValueError):
            continue
        if not np.isfinite(found_bp) or not np.isfinite(height):
            continue
        delta = found_bp - float(target_bp)
        if abs(delta) <= float(window_bp):
            candidates.append(
                {
                    "ok": True,
                    "found_bp": found_bp,
                    "height": height,
                    "area": float(peak.get("area")) if peak.get("area") is not None else np.nan,
                    "delta_bp": delta,
                    "search_mode": "rust_channel_preview",
                    "search_window_bp": float(window_bp),
                    "reason": "",
                }
            )

    if not candidates:
        return {
            "ok": False,
            "reason": "rust_marker_peak_not_found",
            "search_mode": "rust_channel_preview",
            "search_window_bp": float(window_bp),
        }
    return min(candidates, key=lambda candidate: (abs(float(candidate["delta_bp"])), -float(candidate["height"])))


def _build_rust_tracking_marker_candidates(
    fsa,
    markers: list[dict],
    *,
    primary_peak_channel: str,
    sample_fallback_window_bp: float,
) -> tuple[dict[str, dict], dict[str, int]]:
    preview = getattr(fsa, "rust_clonality_preview", None)
    stats = {
        "sample_markers": 0,
        "sample_hits": 0,
        "sample_misses": 0,
        "ladder_markers": 0,
        "ladder_hits": 0,
        "ladder_misses": 0,
        "hits": 0,
        "misses": 0,
    }

    results: dict[str, dict] = {}
    for marker in markers:
        marker_kind = marker.get("kind")
        if marker_kind == "ladder":
            stats["ladder_markers"] += 1
            result = _select_rust_ladder_marker_candidate(
                fsa,
                target_bp=float(marker["expected_bp"]),
                window_bp=float(marker["window_bp"]),
            )
            results[str(marker["name"])] = result
            if result.get("ok"):
                stats["ladder_hits"] += 1
                stats["hits"] += 1
            else:
                stats["ladder_misses"] += 1
                stats["misses"] += 1
            continue
        if marker_kind != "sample":
            continue
        if not isinstance(preview, dict):
            result = {"ok": False, "reason": "rust_clonality_preview_missing"}
            results[str(marker["name"])] = result
            stats["sample_markers"] += 1
            stats["sample_misses"] += 1
            stats["misses"] += 1
            continue
        stats["sample_markers"] += 1
        channel = primary_peak_channel if marker.get("channel") == "primary" else str(marker.get("channel"))
        window_bp = max(float(marker.get("window_bp", 0.0) or 0.0), float(sample_fallback_window_bp))
        result = _select_rust_marker_candidate(
            preview,
            channel=channel,
            target_bp=float(marker["expected_bp"]),
            window_bp=window_bp,
        )
        results[str(marker["name"])] = result
        if result.get("ok"):
            stats["sample_hits"] += 1
            stats["hits"] += 1
        else:
            stats["sample_misses"] += 1
            stats["misses"] += 1
    return results, stats


def _select_rust_ladder_marker_candidate(
    fsa,
    *,
    target_bp: float,
    window_bp: float,
) -> dict:
    ladder_steps = np.asarray(getattr(fsa, "ladder_steps", []), dtype=float)
    peak_times = np.asarray(getattr(fsa, "best_size_standard", []), dtype=float)
    if ladder_steps.size == 0 or peak_times.size == 0 or ladder_steps.size != peak_times.size:
        return {"ok": False, "reason": "rust_ladder_anchor_map_missing"}

    matches = np.where(np.isclose(ladder_steps, float(target_bp), atol=1e-6))[0]
    if not matches.size:
        return {"ok": False, "reason": "rust_ladder_anchor_not_found"}

    match_index = int(matches[0])
    datapoint = float(peak_times[match_index])
    size_standard = np.asarray(getattr(fsa, "size_standard", []), dtype=float)
    peak_idx = int(round(datapoint))
    height = np.nan
    area = np.nan
    if 0 <= peak_idx < size_standard.size:
        height = float(size_standard[peak_idx])
        lo = max(0, peak_idx - 3)
        hi = min(size_standard.size, peak_idx + 4)
        area = float(np.nansum(size_standard[lo:hi]))

    return {
        "ok": True,
        "found_bp": float(target_bp),
        "height": height,
        "area": area,
        "delta_bp": 0.0,
        "search_mode": "rust_ladder_anchor",
        "search_window_bp": float(window_bp),
        "reason": "",
    }


def _compare_rust_tracking_marker_candidates(
    python_results: dict[str, dict],
    rust_results: dict[str, dict],
    *,
    tolerance_bp: float = 0.75,
) -> dict[str, int]:
    stats = {"compared": 0, "matches": 0, "mismatches": 0, "python_only": 0, "rust_only": 0}
    for name, rust_result in rust_results.items():
        python_result = python_results.get(name)
        if not python_result:
            stats["rust_only"] += 1
            continue
        python_ok = bool(python_result.get("ok", False))
        rust_ok = bool(rust_result.get("ok", False))
        if python_ok and rust_ok:
            stats["compared"] += 1
            try:
                delta = abs(float(python_result["found_bp"]) - float(rust_result["found_bp"]))
            except (TypeError, ValueError):
                stats["mismatches"] += 1
                continue
            if delta <= float(tolerance_bp):
                stats["matches"] += 1
            else:
                stats["mismatches"] += 1
        elif python_ok:
            stats["python_only"] += 1
        elif rust_ok:
            stats["rust_only"] += 1
    return stats


def _rust_tracking_markers_enabled() -> bool:
    disabled = os.environ.get("HEMAFRAG_DISABLE_RUST_TRACKING_MARKERS", "").strip().lower()
    return disabled not in {"1", "true", "yes", "on"}


def _python_tracking_marker_result(
    *,
    fsa,
    marker: dict,
    channel: str,
    evaluate_peak_near_bp_with_fallback,
) -> dict:
    res = evaluate_peak_near_bp_with_fallback(
        fsa=fsa,
        channel=channel,
        target_bp=float(marker["expected_bp"]),
        window_bp=float(marker["window_bp"]),
        baseline_correct=True,
        name=marker.get("name"),
    )
    selected = dict(res["selected"])
    selected.setdefault("source", "python")
    return selected


def _build_tracking_marker_results(
    *,
    fsa,
    markers: list[dict],
    primary_peak_channel: str,
    sample_fallback_window_bp: float,
    evaluate_peak_near_bp_with_fallback,
) -> tuple[dict[str, dict], dict[str, dict], dict[str, int]]:
    rust_candidates, rust_stats = _build_rust_tracking_marker_candidates(
        fsa,
        markers,
        primary_peak_channel=primary_peak_channel,
        sample_fallback_window_bp=sample_fallback_window_bp,
    )
    stats = {
        "markers": 0,
        "rust_used": 0,
        "python_fallback": 0,
        "rust_sample_candidates": int(rust_stats.get("sample_markers", 0)),
        "rust_sample_hits": int(rust_stats.get("sample_hits", 0)),
        "rust_sample_misses": int(rust_stats.get("sample_misses", 0)),
        "rust_ladder_candidates": int(rust_stats.get("ladder_markers", 0)),
        "rust_ladder_hits": int(rust_stats.get("ladder_hits", 0)),
        "rust_ladder_misses": int(rust_stats.get("ladder_misses", 0)),
    }
    use_rust = _rust_tracking_markers_enabled()
    results: dict[str, dict] = {}

    for marker in markers:
        stats["markers"] += 1
        name = str(marker["name"])
        channel = primary_peak_channel if marker.get("channel") == "primary" else str(marker.get("channel"))
        rust_result = rust_candidates.get(name)
        if use_rust and marker.get("kind") in {"sample", "ladder"} and rust_result and rust_result.get("ok"):
            selected = dict(rust_result)
            selected["source"] = (
                "rust_ladder_anchor" if marker.get("kind") == "ladder" else "rust_channel_preview"
            )
            results[name] = selected
            stats["rust_used"] += 1
            continue

        results[name] = _python_tracking_marker_result(
            fsa=fsa,
            marker=marker,
            channel=channel,
            evaluate_peak_near_bp_with_fallback=evaluate_peak_near_bp_with_fallback,
        )
        stats["python_fallback"] += 1

    return results, rust_candidates, stats


def _analyze_single_file(fsa_path: Path) -> dict | None:
    """Analyze a single FSA file. Returns an entry dict or None if skipped.

    This is a top-level function (not a closure) so it can be pickled
    for multiprocessing.
    """
    classified = classify_fsa(fsa_path)
    if classified is None:
        return None

    (
        assay,
        group,
        ladder,
        trace_channels,
        peak_channels,
        primary_peak_channel,
        bp_min,
        bp_max,
    ) = classified

    sample_channel = trace_channels[0]

    try:
        if ladder == "LIZ":
            fsa = analyse_fsa_liz(
                fsa_path,
                sample_channel,
                ladder_name=LIZ_LADDER,
                ladder_fit_profile=LADDER_FIT_PROFILE_CLONALITY_LIZ500,
            )
        else:
            fsa = analyse_fsa_rox(
                fsa_path,
                sample_channel,
                ladder_name=ROX_LADDER,
                ladder_fit_profile=LADDER_FIT_PROFILE_CLONALITY_ROX400HD,
            )
    except Exception as ex:
        print_warning(f"[ANALYZE] Skipping unreadable file {fsa_path.name}: {ex}")
        return None

    if fsa is None:
        return None

    peaks_by_channel: dict[str, pd.DataFrame | None] = {}
    if assay == "SL":
        try:
            peaks_by_channel = auto_detect_sl_peaks(
                fsa,
                peak_channels=peak_channels,
                targets_bp=SL_TARGET_FRAGMENTS_BP,
                window_bp=SL_WINDOW_BP,
                min_height=800.0,
            )
        except Exception as ex:
            print_warning(f"[SL] Klarte ikke autovalg av SL-peaks for {fsa.file_name}: {ex}")
            peaks_by_channel = {ch: pd.DataFrame(columns=["basepairs", "peaks", "keep"]) for ch in peak_channels}
    else:
        for ch in peak_channels:
            peaks_by_channel[ch] = pd.DataFrame(columns=["basepairs", "peaks", "keep"])
        rust_peaks = _build_peaks_from_rust_clonality_preview(fsa, assay, primary_peak_channel)
        if rust_peaks:
            peaks_by_channel.update(rust_peaks)

    ymax = compute_zoom_ymax(fsa, bp_min, bp_max, trace_channels, assay_name=assay)

    # Ladder QC
    expected_ladder_steps = list(
        map(float, getattr(fsa, "expected_ladder_steps", getattr(fsa, "ladder_steps", [])))
    )
    fitted_ladder_steps = list(map(float, getattr(fsa, "ladder_steps", [])))
    ladder_fit_strategy = str(getattr(fsa, "ladder_fit_strategy", "auto_full"))
    ladder_missing_expected_steps = list(
        map(float, getattr(fsa, "ladder_missing_expected_steps", []))
    )
    ladder_fit_note = str(
        getattr(
            fsa,
            "ladder_fit_note",
            "All expected ladder steps were fitted." if not ladder_missing_expected_steps else "Manual ladder review recommended.",
        )
    )
    ladder_review_required = bool(
        getattr(fsa, "ladder_review_required", bool(ladder_missing_expected_steps))
    )
    ladder_qc_status = str(getattr(fsa, "ladder_qc_status", "ok") or "ok")
    ladder_r2, n_ladder_steps, n_size_standard_peaks = np.nan, np.nan, np.nan
    ladder_mean_residual_bp, ladder_max_residual_bp, ladder_max_curvature = np.nan, np.nan, np.nan
    ladder_linear_r2, ladder_quadratic_r2 = np.nan, np.nan
    ladder_linear_mean_residual_bp, ladder_linear_max_residual_bp = np.nan, np.nan
    ladder_quadratic_mean_residual_bp, ladder_quadratic_max_residual_bp = np.nan, np.nan
    try:
        metrics = compute_ladder_qc_metrics(fsa)
        ladder_r2 = metrics["r2"]
        n_ladder_steps = metrics["n_ladder_steps"]
        n_size_standard_peaks = metrics["n_size_standard_peaks"]
        ladder_mean_residual_bp = metrics["mean_abs_error_bp"]
        ladder_max_residual_bp = metrics["max_abs_error_bp"]
        ladder_linear_r2 = metrics["linear_trend_r2"]
        ladder_quadratic_r2 = metrics["quadratic_trend_r2"]
        ladder_linear_mean_residual_bp = metrics["linear_trend_mean_abs_error_bp"]
        ladder_linear_max_residual_bp = metrics["linear_trend_max_abs_error_bp"]
        ladder_quadratic_mean_residual_bp = metrics["quadratic_trend_mean_abs_error_bp"]
        ladder_quadratic_max_residual_bp = metrics["quadratic_trend_max_abs_error_bp"]
        ladder_max_curvature = metrics["max_curvature"]
        if ladder_fit_strategy == "manual_adjustment":
            ladder_qc_status = "manual_adjustment"
        elif bool(getattr(fsa, "ladder_missing_signal", False)):
            ladder_qc_status = "missing_ladder"
        elif ladder_review_required:
            ladder_qc_status = "review_required"
    except Exception as ex:
        print_warning(f"[LADDER_QC] Klarte ikke beregne QC for {fsa.file_name}: {ex}")
        ladder_qc_status = "ladder_qc_failed"

    # SL-area
    sl_metrics = None
    if assay == "SL":
        try:
            sl_metrics = compute_sl_area_metrics(
                fsa,
                trace_channel=primary_peak_channel,
                targets_bp=SL_TARGET_FRAGMENTS_BP,
                window_bp=SL_WINDOW_BP,
            )
        except Exception as ex:
            print_warning(f"[SL] Klarte ikke beregne SL-area for {fsa.file_name}: {ex}")

    # Pre-calculate tracking peaks to avoid re-detection later (saves time + allows dropping raw FSA)
    from core.qc.qc_rules import QCRules
    from core.qc.qc_markers import markers_for_entry, evaluate_peak_near_bp_with_fallback
    
    rules = QCRules() # Default rules for tracking
    markers = markers_for_entry({"fsa": fsa, "assay": assay, "ladder": ladder}, rules)
    tracking_marker_results, rust_tracking_marker_candidates, rust_tracking_marker_stats = _build_tracking_marker_results(
        fsa=fsa,
        markers=markers,
        primary_peak_channel=primary_peak_channel,
        sample_fallback_window_bp=float(getattr(rules, "sample_peak_window_bp_fallback", 0.0) or 0.0),
        evaluate_peak_near_bp_with_fallback=evaluate_peak_near_bp_with_fallback,
    )
    rust_tracking_marker_comparison = _compare_rust_tracking_marker_candidates(
        tracking_marker_results,
        rust_tracking_marker_candidates,
    )

    rust_clonality_preview = getattr(fsa, "rust_clonality_preview", None)
    top_rust_assay = {}
    if isinstance(rust_clonality_preview, dict):
        ranked_assays = rust_clonality_preview.get("ranked_assays") or []
        if isinstance(ranked_assays, list) and ranked_assays:
            first = ranked_assays[0]
            if isinstance(first, dict):
                top_rust_assay = first

    return {
        "fsa": fsa,
        "file_name": fsa.file_name,
        "original_file_path": str(resolve_original_input_path(getattr(fsa, "file", None)) or getattr(fsa, "file", "") or ""),
        "source_run_dir": resolve_source_run_dir({"fsa": fsa}),
        "peaks_by_channel": peaks_by_channel,
        "tracking_marker_results": tracking_marker_results,
        "rust_tracking_marker_candidates": rust_tracking_marker_candidates,
        "rust_tracking_marker_stats": rust_tracking_marker_stats,
        "rust_tracking_marker_comparison": rust_tracking_marker_comparison,
        "trace_channels": trace_channels,
        "primary_peak_channel": primary_peak_channel,
        "ymax": ymax,
        "assay": assay,
        "group": group,
        "ladder": ladder,
        "bp_min": bp_min,
        "bp_max": bp_max,
        "dit": extract_dit_from_name(fsa.file_name),
        "ladder_qc_status": ladder_qc_status,
        "ladder_r2": ladder_r2,
        "ladder_mean_residual_bp": ladder_mean_residual_bp,
        "ladder_max_residual_bp": ladder_max_residual_bp,
        "ladder_linear_r2": ladder_linear_r2,
        "ladder_quadratic_r2": ladder_quadratic_r2,
        "ladder_linear_mean_residual_bp": ladder_linear_mean_residual_bp,
        "ladder_linear_max_residual_bp": ladder_linear_max_residual_bp,
        "ladder_quadratic_mean_residual_bp": ladder_quadratic_mean_residual_bp,
        "ladder_quadratic_max_residual_bp": ladder_quadratic_max_residual_bp,
        "ladder_max_curvature": ladder_max_curvature,
        "n_ladder_steps": n_ladder_steps,
        "n_size_standard_peaks": n_size_standard_peaks,
        "ladder_fit_strategy": ladder_fit_strategy,
        "ladder_missing_expected_steps": ladder_missing_expected_steps,
        "ladder_fit_note": ladder_fit_note,
        "ladder_review_required": ladder_review_required,
        "ladder_review_reason": str(getattr(fsa, "rust_review_primary_reason", "") or ""),
        "ladder_review_reason_codes": list(getattr(fsa, "rust_review_reason_codes", []) or []),
        "ladder_review_summary": str(getattr(fsa, "rust_review_summary", "") or ""),
        "ladder_expected_step_count": len(expected_ladder_steps),
        "ladder_fitted_step_count": len(fitted_ladder_steps),
        "rust_preview_top_assay": str(top_rust_assay.get("assay_name") or ""),
        "rust_preview_top_score": float(top_rust_assay.get("score", np.nan))
        if top_rust_assay.get("score") is not None
        else np.nan,
        "rust_preview_top_clonal_groups": int(top_rust_assay.get("clonal_group_count", 0) or 0),
        "rust_preview_top_dominant_ratio": float(top_rust_assay.get("best_dominant_ratio", np.nan))
        if top_rust_assay.get("best_dominant_ratio") is not None
        else np.nan,
        "sl_metrics": sl_metrics,
    }


def _run_analyze_single_file_child(fsa_path: Path, queue) -> None:
    previous_worker_setting = os.environ.get("HEMAFRAG_DISABLE_PERSISTENT_RUST_WORKER")
    os.environ["HEMAFRAG_DISABLE_PERSISTENT_RUST_WORKER"] = "1"
    try:
        from core.rust_bridge import reset_rust_engine_stats, rust_engine_stats_snapshot

        reset_rust_engine_stats()
        result = _analyze_single_file(fsa_path)
        if isinstance(result, dict):
            result["_rust_engine_stats_delta"] = rust_engine_stats_snapshot()
        queue.put(("ok", result))
    except BaseException as exc:
        queue.put(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        if previous_worker_setting is None:
            os.environ.pop("HEMAFRAG_DISABLE_PERSISTENT_RUST_WORKER", None)
        else:
            os.environ["HEMAFRAG_DISABLE_PERSISTENT_RUST_WORKER"] = previous_worker_setting


def _clonality_file_timeout_seconds() -> int:
    env_value = os.environ.get("HEMAFRAG_CLONALITY_FILE_TIMEOUT_SECONDS", "").strip()
    if env_value:
        try:
            return max(0, int(float(env_value)))
        except ValueError:
            pass

    try:
        from config import APP_SETTINGS

        value = (
            APP_SETTINGS.get("analyses", {})
            .get("clonality", {})
            .get("pipeline", {})
            .get("file_timeout_seconds", 0)
        )
        return max(0, int(float(value or 0)))
    except Exception:
        return 0


def _can_use_isolated_file_timeout() -> bool:
    if os.name != "posix":
        return False
    if getattr(sys, "frozen", False):
        return False
    if threading.current_thread() is not threading.main_thread():
        return False
    return True


def _analyze_single_file_with_timeout(fsa_path: Path, timeout_seconds: int) -> tuple[dict | None, str]:
    if timeout_seconds <= 0 or not _can_use_isolated_file_timeout():
        return _analyze_single_file(fsa_path), ""

    import multiprocessing as mp
    import queue as queue_mod

    ctx = mp.get_context("fork")
    result_queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_run_analyze_single_file_child, args=(fsa_path, result_queue))
    proc.start()

    try:
        status, payload = result_queue.get(timeout=timeout_seconds)
    except queue_mod.Empty:
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
        return None, f"timeout_after_{timeout_seconds}s"

    proc.join(5)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
        return None, "child_did_not_exit_after_result"

    if proc.exitcode and proc.exitcode != 0:
        return None, f"child_exit_{proc.exitcode}"

    if status == "ok":
        if isinstance(payload, dict):
            rust_stats_delta = payload.pop("_rust_engine_stats_delta", None)
            if isinstance(rust_stats_delta, dict):
                try:
                    from core.rust_bridge import merge_rust_engine_stats

                    merge_rust_engine_stats(rust_stats_delta)
                except Exception:
                    pass
        return payload, ""
    return None, str(payload or "child_error")


def _format_rust_tracking_summary(entries: list[dict]) -> str:
    totals: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for entry in entries:
        for key, value in (entry.get("rust_tracking_marker_stats") or {}).items():
            try:
                totals[key] = int(totals.get(key, 0)) + int(value or 0)
            except Exception:
                continue
        for result in (entry.get("tracking_marker_results") or {}).values():
            source = str(result.get("source") or "unknown")
            source_counts[source] = int(source_counts.get(source, 0)) + 1

    if not totals and not source_counts:
        return "not available"
    return (
        "markers={markers} rust_used={rust_used} python_fallback={python_fallback} "
        "sample={rust_sample_hits}/{rust_sample_candidates} "
        "ladder={rust_ladder_hits}/{rust_ladder_candidates} "
        "sources={sources}"
    ).format(
        markers=int(totals.get("markers", 0)),
        rust_used=int(totals.get("rust_used", 0)),
        python_fallback=int(totals.get("python_fallback", 0)),
        rust_sample_hits=int(totals.get("rust_sample_hits", 0)),
        rust_sample_candidates=int(totals.get("rust_sample_candidates", 0)),
        rust_ladder_hits=int(totals.get("rust_ladder_hits", 0)),
        rust_ladder_candidates=int(totals.get("rust_ladder_candidates", 0)),
        sources=", ".join(f"{key}:{source_counts[key]}" for key in sorted(source_counts)) or "-",
    )


def _analyze_files(
    fsa_files: list[Path],
    *,
    progress_callback=None,
) -> tuple[list[dict], int]:
    """Performs analysis (ladder fitting, peak detection) on a list of FSA files.

    Uses multiprocessing to analyze files in parallel across available CPU cores.
    """
    total_files = len(fsa_files)
    use_multiprocessing = (
        progress_callback is None
        and _should_use_multiprocessing()
        and total_files >= 2
    )

    if not use_multiprocessing:
        from config import APP_SETTINGS

        if APP_SETTINGS.get("engine", {}).get("use_rust", False) and fsa_files:
            try:
                from core.rust_bridge import prime_rust_worker_results, reset_rust_engine_stats

                reset_rust_engine_stats()
                primed = prime_rust_worker_results(fsa_files, "clonality")
                if primed:
                    print_green(f"[RUST] Primed {primed} clonality files through persistent worker.")
            except Exception as ex:
                print_warning(f"[RUST] Failed to prewarm clonality worker cache ({ex}).")

        results = []
        file_timeout_seconds = _clonality_file_timeout_seconds()
        for index, path in enumerate(fsa_files, start=1):
            _emit_progress(
                progress_callback,
                phase="analyze",
                file_name=path.name,
                files_done=index - 1,
                files_total=total_files,
                note="file_started",
            )

            stop_event = threading.Event()
            file_started = time.monotonic()

            def _heartbeat() -> None:
                elapsed = 0
                while not stop_event.wait(30.0):
                    elapsed = int(time.monotonic() - file_started)
                    print_warning(
                        f"[ANALYZE] Slow file: {path.name} still running after {elapsed}s "
                        f"({index}/{total_files})."
                    )
                    _emit_progress(
                        progress_callback,
                        phase="analyze",
                        file_name=path.name,
                        files_done=index - 1,
                        files_total=total_files,
                        note="slow_file" if elapsed >= 30 else "heartbeat",
                    )

            heartbeat_thread = threading.Thread(target=_heartbeat, daemon=True)
            heartbeat_thread.start()
            try:
                result, skip_reason = _analyze_single_file_with_timeout(path, file_timeout_seconds)
                if skip_reason:
                    print_warning(f"[ANALYZE] Skipping {path.name}: {skip_reason}.")
                    _emit_progress(
                        progress_callback,
                        phase="analyze",
                        file_name=path.name,
                        files_done=index - 1,
                        files_total=total_files,
                        note=skip_reason,
                    )
                if isinstance(result, dict):
                    rust_stats_delta = result.pop("_rust_engine_stats_delta", None)
                    if isinstance(rust_stats_delta, dict):
                        try:
                            from core.rust_bridge import merge_rust_engine_stats

                            merge_rust_engine_stats(rust_stats_delta)
                        except Exception:
                            pass
                results.append(result)
            finally:
                stop_event.set()
                heartbeat_thread.join(timeout=0.1)

            _emit_progress(
                progress_callback,
                phase="analyze",
                file_name=path.name,
                files_done=index,
                files_total=total_files,
                note="file_complete",
            )
    else:
        from multiprocessing import Pool, cpu_count

        n_workers = max(1, cpu_count() - 1)

        try:
            with Pool(n_workers) as pool:
                results = pool.map(_analyze_single_file, fsa_files)
        except Exception as ex:
            # Fallback to sequential if multiprocessing fails (e.g. frozen app)
            print_warning(f"[PARALLEL] Multiprocessing failed ({ex}), falling back to sequential.")
            results = [_analyze_single_file(p) for p in fsa_files]

    entries = [r for r in results if r is not None]
    skipped = len(fsa_files) - len(entries)

    try:
        from core.rust_bridge import format_rust_engine_stats

        print_green(f"[RUST] Engine usage: {format_rust_engine_stats()}")
    except Exception:
        pass
    print_green(f"[RUST] Tracking markers: {_format_rust_tracking_summary(entries)}")

    print_green(f"[MASTER] Totalt {len(entries)} filer analysert. {skipped} skippet.")
    return entries, skipped


def run_pipeline(
    fsa_dir: Path,
    base_outdir: Path | None = None,
    assay_folder_name: str | None = None,
    return_entries: bool = False,
    make_dit_reports: bool = True,
    mode: str = "all",
    tracking_excel_path: Path | None = None,
    update_tracking_workbook: bool = True,
    progress_callback=None,
) -> list[dict] | None:

    """
    Kjør full HemaFrag-pipeline på alle .fsa-filer i fsa_dir.
    """
    fsa_dir, assay_dir = normalize_pipeline_paths(fsa_dir, base_outdir, assay_folder_name)

    # 1) Scan
    fsa_files = _scan_files(fsa_dir, mode)
    if not fsa_files:
        return [] if return_entries else None

    # 2) Analyze
    entries, _ = _analyze_files(fsa_files, progress_callback=progress_callback)
    if not entries:
        print_warning("Ingen gyldige entries etter analyse – avslutter.")
        return [] if return_entries else None

    if update_tracking_workbook:
        resolved_tracking_excel_path = tracking_excel_path or resolve_analysis_excel_output_path(
            "clonality",
            assay_dir,
            CLONALITY_TRACKING_FILENAME,
        )
        update_clonality_tracking_workbook(resolved_tracking_excel_path, entries)

    return finalize_pipeline_run(
        entries,
        assay_dir,
        return_entries=return_entries,
        make_dit_reports=make_dit_reports,
        mode=mode,
    )
