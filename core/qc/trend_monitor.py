"""Advisory run-level QC trends with explicit baseline selection."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd
from scipy import signal


QC_TREND_SCHEMA = "hemafrag_qc_trend_monitor_v1"
DEFAULT_MIN_BASELINE_RUNS = 20
DEFAULT_EWMA_LAMBDA = 0.20
DEFAULT_SIGMA_LIMIT = 3.0

_PASS_STATUSES = {"ok", "manual_adjustment"}
_REVIEW_TOKENS = ("review", "partial", "incomplete")
_METRICS = (
    "PassRate",
    "ReviewRate",
    "FailRate",
    "MeanLadderR2",
    "MeanLinearMeanResidualBp",
    "MeanLinearMaxResidualBp",
    "MeanAnchorIntensity",
    "PullUpRate",
    "SaturationRate",
)


def _max_true_run(mask: np.ndarray) -> int:
    if not np.any(mask):
        return 0
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return int(np.max(edges[1::2] - edges[::2]))


def build_entry_qc_trend_evidence(entry: dict[str, Any]) -> dict[str, Any]:
    """Collect cheap, non-diagnostic trend candidates from an analyzed FSA."""
    fsa = entry.get("fsa")
    if fsa is None:
        return {
            "LadderMedianAnchorIntensity": None,
            "PullUpCandidate": None,
            "SaturationCandidate": None,
        }
    ladder_trace = np.asarray(
        getattr(fsa, "size_standard", []),
        dtype=float,
    )
    anchor_scans = np.rint(
        np.asarray(getattr(fsa, "best_size_standard", []), dtype=float)
    ).astype(int)
    valid_scans = anchor_scans[
        (anchor_scans >= 0) & (anchor_scans < ladder_trace.size)
    ]
    median_anchor = (
        float(np.median(ladder_trace[valid_scans]))
        if valid_scans.size
        else None
    )

    raw = getattr(fsa, "fsa", {})
    channels: dict[str, np.ndarray] = {}
    for channel in ("DATA1", "DATA2", "DATA3", "DATA4"):
        values = np.asarray(
            getattr(raw, "get", lambda *_args: [])(channel, []),
            dtype=float,
        )
        if values.size >= 3 and np.all(np.isfinite(values)):
            channels[channel] = values
    saturation = False
    peaks_by_channel: dict[str, np.ndarray] = {}
    heights_by_channel: dict[str, np.ndarray] = {}
    for channel, trace in channels.items():
        maximum = float(np.max(trace))
        at_limit = trace >= 30000.0
        flat_max = np.isclose(
            trace,
            maximum,
            rtol=0.0,
            atol=max(1.0, abs(maximum) * 1e-6),
        )
        saturation = saturation or bool(
            maximum >= 30000.0
            and (_max_true_run(flat_max) >= 2 or int(np.sum(at_limit)) >= 2)
        )
        median = float(np.median(trace))
        noise = float(1.4826 * np.median(np.abs(trace - median)))
        floor = max(50.0, 6.0 * noise)
        peaks, properties = signal.find_peaks(
            trace,
            height=median + floor,
            prominence=floor,
            distance=2,
        )
        peaks_by_channel[channel] = peaks
        heights_by_channel[channel] = np.asarray(
            properties.get("peak_heights", np.zeros(peaks.size)),
            dtype=float,
        )

    pull_up = False
    names = sorted(peaks_by_channel)
    for source in names:
        if pull_up:
            break
        for target in names:
            if source == target:
                continue
            for source_scan, source_height in zip(
                peaks_by_channel[source],
                heights_by_channel[source],
            ):
                aligned = np.flatnonzero(
                    np.abs(peaks_by_channel[target] - source_scan) <= 2
                )
                if aligned.size and np.any(
                    source_height >= 4.0 * heights_by_channel[target][aligned]
                ):
                    pull_up = True
                    break
            if pull_up:
                break
    return {
        "LadderMedianAnchorIntensity": median_anchor,
        "PullUpCandidate": pull_up if channels else None,
        "SaturationCandidate": saturation if channels else None,
    }


def _text_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype="object")
    return frame[column].fillna("").astype(str).str.strip()


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _boolean_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    values = _text_series(frame, column).str.lower()
    return values.map(
        {
            "true": 1.0,
            "1": 1.0,
            "yes": 1.0,
            "y": 1.0,
            "false": 0.0,
            "0": 0.0,
            "no": 0.0,
            "n": 0.0,
        }
    )


def _run_keys(frame: pd.DataFrame) -> pd.Series:
    source = _text_series(frame, "SourceRunDir")
    code = _text_series(frame, "RunCode")
    date = _text_series(frame, "RunDate")
    identity = _text_series(frame, "IdentityKey")
    output = source.where(source.ne(""), code)
    output = output.where(output.ne(""), date)
    return output.where(output.ne(""), identity)


def _status_class(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in _PASS_STATUSES:
        return "pass"
    if any(token in status for token in _REVIEW_TOKENS):
        return "review"
    return "fail"


def build_run_summary(runs: pd.DataFrame) -> pd.DataFrame:
    """Aggregate tracking rows into assay/ladder/run monitoring rows."""
    columns = [
        "SchemaVersion",
        "RunKey",
        "RunDate",
        "Assay",
        "Ladder",
        "Files",
        "PassCount",
        "ReviewCount",
        "FailCount",
        "PassRate",
        "ReviewRate",
        "FailRate",
        "MeanLadderR2",
        "MeanLinearMeanResidualBp",
        "MeanLinearMaxResidualBp",
        "MeanAnchorIntensity",
        "PullUpRate",
        "SaturationRate",
    ]
    if runs.empty:
        return pd.DataFrame(columns=columns)

    work = runs.copy()
    work["_RunKey"] = _run_keys(work)
    work["_RunDate"] = _text_series(work, "RunDate")
    work["_Assay"] = _text_series(work, "Assay").replace("", "Unknown")
    work["_Ladder"] = _text_series(work, "Ladder").replace("", "Unknown")
    work["_StatusClass"] = _text_series(work, "LadderQC").map(_status_class)
    work["_LadderR2"] = _numeric_series(work, "LadderR2")
    work["_LinearMean"] = _numeric_series(
        work,
        "LadderLinearMeanResidualBp",
    )
    work["_LinearMax"] = _numeric_series(
        work,
        "LadderLinearMaxResidualBp",
    )
    work["_AnchorIntensity"] = _numeric_series(
        work,
        "LadderMedianAnchorIntensity",
    )
    work["_PullUp"] = _boolean_series(work, "PullUpCandidate")
    work["_Saturation"] = _boolean_series(work, "SaturationCandidate")
    work = work[work["_RunKey"].ne("")]

    rows: list[dict[str, Any]] = []
    grouping = work.groupby(
        ["_RunKey", "_RunDate", "_Assay", "_Ladder"],
        dropna=False,
        sort=True,
    )
    for (run_key, run_date, assay, ladder), group in grouping:
        count = int(len(group))
        status_counts = group["_StatusClass"].value_counts()
        pass_count = int(status_counts.get("pass", 0))
        review_count = int(status_counts.get("review", 0))
        fail_count = int(status_counts.get("fail", 0))
        rows.append(
            {
                "SchemaVersion": QC_TREND_SCHEMA,
                "RunKey": run_key,
                "RunDate": run_date,
                "Assay": assay,
                "Ladder": ladder,
                "Files": count,
                "PassCount": pass_count,
                "ReviewCount": review_count,
                "FailCount": fail_count,
                "PassRate": pass_count / count,
                "ReviewRate": review_count / count,
                "FailRate": fail_count / count,
                "MeanLadderR2": group["_LadderR2"].mean(),
                "MeanLinearMeanResidualBp": group["_LinearMean"].mean(),
                "MeanLinearMaxResidualBp": group["_LinearMax"].mean(),
                "MeanAnchorIntensity": group["_AnchorIntensity"].mean(),
                "PullUpRate": group["_PullUp"].mean(),
                "SaturationRate": group["_Saturation"].mean(),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["RunDate", "RunKey", "Assay", "Ladder"],
        kind="stable",
        ignore_index=True,
    )


def _finite_values(frame: pd.DataFrame, metric: str) -> pd.Series:
    values = pd.to_numeric(frame[metric], errors="coerce")
    return values[np.isfinite(values)]


def build_control_signals(
    run_summary: pd.DataFrame,
    *,
    baseline_run_keys: Iterable[str] = (),
    min_baseline_runs: int = DEFAULT_MIN_BASELINE_RUNS,
    ewma_lambda: float = DEFAULT_EWMA_LAMBDA,
    sigma_limit: float = DEFAULT_SIGMA_LIMIT,
) -> pd.DataFrame:
    """Build advisory Shewhart/EWMA evidence without changing thresholds."""
    baseline_keys = {
        str(value).strip()
        for value in baseline_run_keys
        if str(value).strip()
    }
    columns = [
        "SchemaVersion",
        "Assay",
        "Ladder",
        "Metric",
        "Status",
        "AdvisoryOnly",
        "BaselineRunCount",
        "BaselineMean",
        "BaselineStdDev",
        "ShewhartLCL",
        "ShewhartUCL",
        "LatestRunKey",
        "LatestValue",
        "LatestEWMA",
        "EWMALCL",
        "EWMAUCL",
        "ShewhartAlert",
        "EWMAAlert",
    ]
    if run_summary.empty:
        return pd.DataFrame(columns=columns)

    lambda_value = float(ewma_lambda)
    if not 0.0 < lambda_value <= 1.0:
        raise ValueError("ewma_lambda must be in (0, 1].")
    min_runs = max(2, int(min_baseline_runs))
    sigma_multiplier = max(0.1, float(sigma_limit))
    rows: list[dict[str, Any]] = []

    for (assay, ladder), group in run_summary.groupby(
        ["Assay", "Ladder"],
        sort=True,
    ):
        ordered = group.sort_values(
            ["RunDate", "RunKey"],
            kind="stable",
        )
        selected = ordered[ordered["RunKey"].astype(str).isin(baseline_keys)]
        for metric in _METRICS:
            values = _finite_values(ordered, metric)
            baseline_values = _finite_values(selected, metric)
            baseline_count = int(selected.loc[baseline_values.index, "RunKey"].nunique())
            status = "active_advisory"
            if not baseline_keys:
                status = "baseline_not_selected"
            elif baseline_count < min_runs:
                status = "insufficient_baseline"

            mean = float(baseline_values.mean()) if baseline_count else np.nan
            std = (
                float(baseline_values.std(ddof=1))
                if baseline_count >= 2
                else np.nan
            )
            if status == "active_advisory" and (
                not np.isfinite(std) or std <= 0.0
            ):
                status = "insufficient_variation"

            latest_run_key = ""
            latest_value = np.nan
            latest_ewma = np.nan
            shewhart_lcl = np.nan
            shewhart_ucl = np.nan
            ewma_lcl = np.nan
            ewma_ucl = np.nan
            shewhart_alert = False
            ewma_alert = False
            if not values.empty:
                latest_index = values.index[-1]
                latest_run_key = str(ordered.loc[latest_index, "RunKey"])
                latest_value = float(values.iloc[-1])
            if status == "active_advisory" and not values.empty:
                shewhart_lcl = mean - sigma_multiplier * std
                shewhart_ucl = mean + sigma_multiplier * std
                if metric.endswith("Rate"):
                    shewhart_lcl = max(0.0, shewhart_lcl)
                    shewhart_ucl = min(1.0, shewhart_ucl)
                z = mean
                for value in values:
                    z = lambda_value * float(value) + (1.0 - lambda_value) * z
                latest_ewma = z
                count = len(values)
                ewma_sigma = std * np.sqrt(
                    (lambda_value / (2.0 - lambda_value))
                    * (1.0 - (1.0 - lambda_value) ** (2 * count))
                )
                ewma_lcl = mean - sigma_multiplier * ewma_sigma
                ewma_ucl = mean + sigma_multiplier * ewma_sigma
                if metric.endswith("Rate"):
                    ewma_lcl = max(0.0, ewma_lcl)
                    ewma_ucl = min(1.0, ewma_ucl)
                shewhart_alert = not (
                    shewhart_lcl <= latest_value <= shewhart_ucl
                )
                ewma_alert = not (ewma_lcl <= latest_ewma <= ewma_ucl)

            rows.append(
                {
                    "SchemaVersion": QC_TREND_SCHEMA,
                    "Assay": assay,
                    "Ladder": ladder,
                    "Metric": metric,
                    "Status": status,
                    "AdvisoryOnly": True,
                    "BaselineRunCount": baseline_count,
                    "BaselineMean": mean,
                    "BaselineStdDev": std,
                    "ShewhartLCL": shewhart_lcl,
                    "ShewhartUCL": shewhart_ucl,
                    "LatestRunKey": latest_run_key,
                    "LatestValue": latest_value,
                    "LatestEWMA": latest_ewma,
                    "EWMALCL": ewma_lcl,
                    "EWMAUCL": ewma_ucl,
                    "ShewhartAlert": shewhart_alert,
                    "EWMAAlert": ewma_alert,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def selected_baseline_run_keys(config: pd.DataFrame | None) -> set[str]:
    """Read explicit TRUE selections from the workbook baseline sheet."""
    if config is None or config.empty or "RunKey" not in config.columns:
        return set()
    include = _boolean_series(
        config,
        "IncludeInBaseline",
    ).fillna(0.0).astype(bool)
    return {
        str(value).strip()
        for value in config.loc[include, "RunKey"]
        if str(value).strip()
    }


__all__ = [
    "DEFAULT_EWMA_LAMBDA",
    "DEFAULT_MIN_BASELINE_RUNS",
    "DEFAULT_SIGMA_LIMIT",
    "QC_TREND_SCHEMA",
    "build_control_signals",
    "build_entry_qc_trend_evidence",
    "build_run_summary",
    "selected_baseline_run_keys",
]
