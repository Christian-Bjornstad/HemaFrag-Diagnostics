from __future__ import annotations

import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from config import APP_SETTINGS
from core.analyses.clonality.config import ASSAY_REFERENCE_RANGES, NONSPECIFIC_PEAKS
from core.qc.qc_markers import (
    control_id_from_filename,
    parse_pcr_date_from_filename,
)
from core.utils import is_control_file, strip_stage_prefix


ANNOTATION_SCHEMA_VERSION = "clonality_interpretation_v1"
INTERPRETATION_RULE_VERSION = "clonality_interpretation_rules_v1"
MODEL_VERSION = "clonality_interpretation_quick_model_v1"

ANNOTATION_CLASSES = [
    "polyklonal",
    "monoklonal",
    "bi_oligoklonal",
    "irregulaer",
    "pseudoklonal",
    "intet_pcr_produkt_darlig_dna",
    "qc_teknisk_fail",
    "usikker_review",
]

CONTROL_FLAGS = [
    "kontroll_ok",
    "kontroll_avvik",
    "kontaminasjon_mistenkt",
    "svakt_signal",
]

TRACKING_COLUMNS = [
    "ClonalityInterpretationEnabled",
    "ClonalitySuggestion",
    "ClonalityConfidence",
    "ClonalityReviewNeeded",
    "ClonalityEvidence",
    "ClonalitySLQualityClass",
    "ClonalitySLFragmentedPercent",
    "ClonalitySLQualityPhrase",
    "ClonalityModelVersion",
]

DEFAULT_SAMPLE_QUOTAS = {
    "patient": 400,
    "pk": 40,
    "rk": 30,
    "nk": 30,
}

NONSPECIFIC_PEAK_WINDOW_BP = 1.5


def interpretation_enabled(settings: dict[str, Any] | None = None) -> bool:
    settings = settings or APP_SETTINGS
    profile = settings.get("analyses", {}).get("clonality", {})
    interpretation = profile.get("interpretation", {})
    if not isinstance(interpretation, dict):
        return False
    return bool(interpretation.get("enabled", False))


def learning_mode_enabled(settings: dict[str, Any] | None = None) -> bool:
    settings = settings or APP_SETTINGS
    profile = settings.get("analyses", {}).get("clonality", {})
    learning = profile.get("learning", {})
    if not isinstance(learning, dict):
        return False
    return bool(learning.get("enabled", False))


def learning_output_dir(settings: dict[str, Any] | None = None) -> str:
    settings = settings or APP_SETTINGS
    profile = settings.get("analyses", {}).get("clonality", {})
    learning = profile.get("learning", {})
    if not isinstance(learning, dict):
        return ""
    return str(learning.get("output_dir", "") or "")


def sample_kind_for_file(path: Path | str) -> tuple[str, str, str]:
    name = strip_stage_prefix(Path(path).name)
    control = control_id_from_filename(name)
    if control in {"PK", "PK1", "PK2"}:
        return "control", control, "pk"
    if control == "RK":
        return "control", control, "rk"
    if control == "NK":
        return "control", control, "nk"
    if is_control_file(name):
        return "control", control if control != "UNKNOWN" else "", "control_other"
    return "patient", "", "patient"


def sample_annotation_files(
    files: Sequence[Path],
    *,
    limit: int = 500,
    quotas: dict[str, int] | None = None,
) -> tuple[list[Path], dict[str, Any]]:
    quotas = dict(quotas or DEFAULT_SAMPLE_QUOTAS)
    limit = max(0, int(limit or 0))
    buckets: dict[str, list[Path]] = {"patient": [], "pk": [], "rk": [], "nk": [], "control_other": []}
    for path in sorted({Path(p).expanduser() for p in files}):
        _sample_kind, _control, bucket = sample_kind_for_file(path)
        buckets.setdefault(bucket, []).append(path)

    selected: list[Path] = []
    selected_by_bucket: Counter[str] = Counter()
    for bucket in ("patient", "pk", "rk", "nk"):
        take = min(len(buckets.get(bucket, [])), int(quotas.get(bucket, 0)), max(0, limit - len(selected)))
        selected.extend(buckets.get(bucket, [])[:take])
        selected_by_bucket[bucket] += take

    remaining_slots = max(0, limit - len(selected))
    if remaining_slots:
        already = set(selected)
        leftovers: list[Path] = []
        for bucket in ("patient", "pk", "rk", "nk", "control_other"):
            leftovers.extend([p for p in buckets.get(bucket, []) if p not in already])
        for path in sorted(leftovers)[:remaining_slots]:
            selected.extend([path])
            selected_by_bucket[sample_kind_for_file(path)[2]] += 1

    summary = {
        "limit": limit,
        "requested_quotas": quotas,
        "candidate_counts": {key: len(value) for key, value in sorted(buckets.items())},
        "selected_counts": dict(selected_by_bucket),
        "selected_total": len(selected),
    }
    return selected, summary



def per_channel_trace_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """Per-`DATA*`-channel raw-trace summary.

    Returns a flat dict where the keys are dotted (`peak_count_per_channel.<DATA1>`)
    plus four aggregate fields (`peak_variance_per_channel`, `mad_per_channel`,
    `dome_peak_count_per_channel`, `dome_height_ratio_per_channel`).
    Designed so the ML can decide `intet_pcr_produkt_darlig_dna` vs
    `qc_teknisk_fail` from the per-channel shape alone.

    Safe to call on entries with missing `peaks_by_channel`: returns
    dict of length 0 with no exception.
    """
    pb = entry.get("peaks_by_channel")
    if not isinstance(pb, dict):
        pb = {}

    out: dict[str, Any] = {
        "peak_count_per_channel": {},
        "peak_variance_per_channel": {},
        "mad_per_channel": {},
        "dome_peak_count_per_channel": {},
        "dome_height_ratio_per_channel": {},
    }
    if not pb:
        return out

    channel_names = sorted(str(k) for k in pb.keys())
    for channel in channel_names:
        frame = pb[channel]
        if not hasattr(frame, "empty"):
            continue
        if frame.empty or "peaks" not in frame.columns:
            heights = np.array([], dtype=float)
        else:
            heights = pd.to_numeric(frame["peaks"], errors="coerce").fillna(0.0).to_numpy()
        heights = heights[heights > 0]
        if heights.size == 0:
            out["peak_count_per_channel"][channel] = 0
            out["peak_variance_per_channel"][channel] = 0.0
            out["mad_per_channel"][channel] = 0.0
            out["dome_peak_count_per_channel"][channel] = 0
            out["dome_height_ratio_per_channel"][channel] = 0.0
            continue
        max_h = float(np.nanmax(heights))
        n = int(heights.size)
        peak_count = int(n)
        peak_var = float(np.nanvar(heights)) if n > 1 else 0.0
        median_h = float(np.nanmedian(heights))
        mad = float(np.nanmedian(np.abs(heights - median_h))) if n > 0 else 0.0
        dome_threshold = 0.6 * max_h
        dome_count = int(np.sum(heights >= dome_threshold))
        mean_height = float(np.nanmean(heights)) if n > 0 else 0.0
        dome_ratio = float(max_h / mean_height) if mean_height > 0 else 0.0

        out["peak_count_per_channel"][channel] = peak_count
        out["peak_variance_per_channel"][channel] = peak_var
        out["mad_per_channel"][channel] = mad
        out["dome_peak_count_per_channel"][channel] = dome_count
        out["dome_height_ratio_per_channel"][channel] = dome_ratio
    return out


def reference_window_features(entry: dict[str, Any]) -> dict[str, Any]:
    """Three reference-window position features for the dominant peak.

    Reads ASSAY_REFERENCE_RANGES via assay_interpretation_range() and computes:
      - dom_distance_to_ref_window_center_bp: signed bp distance from dominant
        peak to range midpoint; positive = upstream of center.
      - ref_window_coverage_fraction: dominant-peak width (estimated as 3 bp)
        divided by full window width — cheap proxy.
      - in_reference_window: True iff dominant basepair lies within window.
    """
    assay = str(entry.get("assay") or "")
    range_text = ""
    rng_min: float = float("nan")
    rng_max: float = float("nan")
    try:
        rng = assay_interpretation_range(assay)  # may raise ValueError
        if isinstance(rng, tuple) and len(rng) == 2:
            rng_min, rng_max = float(rng[0]), float(rng[1])
            range_text = f"{int(rng_min)}-{int(rng_max)}"
    except (KeyError, ValueError, TypeError):
        pass

    dom_bp_raw = entry.get("dominant_peak_basepairs")
    try:
        dom_bp = float(dom_bp_raw) if dom_bp_raw is not None else float("nan")
    except (TypeError, ValueError):
        dom_bp = float("nan")

    if (
        dom_bp != dom_bp  # NaN check
        or rng_min != rng_min
        or rng_max != rng_max
    ):
        return {
            "dom_distance_to_ref_window_center_bp": float("nan"),
            "ref_window_coverage_fraction": 0.0,
            "in_reference_window": False,
            "interpretation_window_for_assay": range_text,
        }
    center = (rng_min + rng_max) / 2.0
    distance = dom_bp - center
    width = max(rng_max - rng_min, 1e-9)
    in_window = bool(rng_min <= dom_bp <= rng_max)
    coverage = 3.0 / width
    return {
        "dom_distance_to_ref_window_center_bp": float(distance),
        "ref_window_coverage_fraction": float(coverage) if in_window else 0.0,
        "in_reference_window": in_window,
        "interpretation_window_for_assay": range_text,
    }


def compute_patient_panel_features(
    entry: dict[str, Any],
    all_patient_entries: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Per-patient replicate concordance (T-2.3).

    Given the entry plus an iterable of all sibling entries sharing the same
    DIT, count distinct assays run and the fraction of the canonical
    clonality panel that's been completed for this patient.

    The canonical panel is intentionally explicit (FR1, FR2, FR3, IGK,
    KDE, TCRG-A, TCRG-B, DHJH_D, DHJH_E) — chemist owns the list.
    Today's call site is the pipeline orchestrator in Phase 6; this is
    a stand-in callable that returns safe defaults when the orchestrator
    has not yet plumbed the patient-entry iterator.
    """
    canonical: tuple[str, ...] = (
        "FR1", "FR2", "FR3", "IGK", "KDE", "TCRGA", "TCRGB", "DHJHD", "DHJHE",
    )

    if not all_patient_entries:
        return {
            "patient_assays_run_count": 0,
            "assay_panel_completeness_pct": 0.0,
            "patient_entry_count": 0,
        }

    def _canon(name: Any) -> str | None:
        s = str(name or "").strip().upper()
        # Strip whitespace + separators that may or may not exist in the source.
        s = s.replace(" ", "").replace("-", "").replace("_", "")
        return s or None

    seen = {_canon(e.get("assay")) for e in all_patient_entries}
    seen.discard(None)
    distinct_count = sum(1 for c in canonical if c in seen)
    complete = distinct_count / len(canonical) if canonical else 0.0
    return {
        "patient_assays_run_count": int(distinct_count),
        "assay_panel_completeness_pct": float(complete),
        "patient_entry_count": len(list(all_patient_entries)),
    }



def features_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    file_name = str(entry.get("file_name") or getattr(entry.get("fsa"), "file_name", "") or "")
    sample_kind, control, control_bucket = sample_kind_for_file(file_name)
    peaks = _combined_peak_frame(entry)
    peak_context = peak_context_for_assay(str(entry.get("assay") or ""), peaks)
    interpretation_peaks = peak_context["interpretation_peaks"]
    heights = _numeric_list(interpretation_peaks.get("peaks", [])) if not interpretation_peaks.empty else []
    areas = (
        _numeric_list(interpretation_peaks.get("area", []))
        if not interpretation_peaks.empty and "area" in interpretation_peaks.columns
        else []
    )
    heights_desc = sorted(heights, reverse=True)
    areas_desc = sorted(areas, reverse=True)

    dominant_height = heights_desc[0] if heights_desc else 0.0
    second_height = heights_desc[1] if len(heights_desc) > 1 else 0.0
    total_height = float(np.nansum(heights)) if heights else 0.0
    total_area = float(np.nansum(areas)) if areas else 0.0
    dominant_area = areas_desc[0] if areas_desc else 0.0
    tracking_stats = entry.get("rust_tracking_marker_stats") or {}
    if not isinstance(tracking_stats, dict):
        tracking_stats = {}
    sl_quality = sl_quality_from_metrics(entry.get("sl_metrics") or {})

    return {
        "file": file_name,
        "raw_path": str(entry.get("original_file_path") or getattr(entry.get("fsa"), "file", "") or ""),
        "assay": str(entry.get("assay") or ""),
        "ladder": str(entry.get("ladder") or ""),
        "primary_peak_channel": str(entry.get("primary_peak_channel") or ""),
        "sample_kind": sample_kind,
        "control": control,
        "control_bucket": control_bucket,
        "run_date": parse_pcr_date_from_filename(file_name) or "",
        "ladder_qc_status": str(entry.get("ladder_qc_status") or ""),
        "ladder_review_required": bool(entry.get("ladder_review_required", False)),
        "ladder_r2": _finite_or_zero(entry.get("ladder_r2")),
        "ladder_linear_r2": _finite_or_zero(entry.get("ladder_linear_r2")),
        "ladder_linear_mean_residual_bp": _finite_or_zero(entry.get("ladder_linear_mean_residual_bp")),
        "ladder_linear_max_residual_bp": _finite_or_zero(entry.get("ladder_linear_max_residual_bp")),
        "raw_peak_count": peak_context["raw_peak_count"],
        "peak_count": int(len(heights)),
        "peak_count_in_interpretation_range": peak_context["in_range_count"],
        "peak_count_outside_interpretation_range": peak_context["out_of_range_count"],
        "nonspecific_peak_count": peak_context["nonspecific_count"],
        "nonspecific_peak_basepairs": peak_context["nonspecific_basepairs"],
        "nonspecific_height_share": peak_context["nonspecific_height_share"],
        "dominant_peak_basepairs": peak_context["dominant_peak_basepairs"],
        "dominant_peak_in_interpretation_range": peak_context["dominant_peak_in_range"],
        "dominant_peak_is_nonspecific": peak_context["dominant_peak_is_nonspecific"],
        "outside_interpretation_height_share": peak_context["outside_height_share"],
        "interpretation_range_min_bp": peak_context["range_min_bp"],
        "interpretation_range_max_bp": peak_context["range_max_bp"],
        "interpretation_ranges_bp": peak_context["ranges_text"],
        "dominant_peak_height": float(dominant_height),
        "second_peak_height": float(second_height),
        "dominant_to_second_ratio": float(dominant_height / second_height) if second_height > 0 else float(dominant_height),
        "dominant_height_share": float(dominant_height / total_height) if total_height > 0 else 0.0,
        "total_peak_height": total_height,
        "dominant_peak_area": float(dominant_area),
        "total_peak_area": total_area,
        "dominant_area_share": float(dominant_area / total_area) if total_area > 0 else 0.0,
        "rust_preview_top_score": _finite_or_zero(entry.get("rust_preview_top_score")),
        "rust_preview_top_clonal_groups": int(entry.get("rust_preview_top_clonal_groups", 0) or 0),
        "rust_preview_top_dominant_ratio": _finite_or_zero(entry.get("rust_preview_top_dominant_ratio")),
        "tracking_marker_count": int(tracking_stats.get("markers", 0) or tracking_stats.get("sample_markers", 0) or 0),
        "tracking_marker_hits": int(tracking_stats.get("hits", 0) or 0),
        "tracking_marker_misses": int(tracking_stats.get("misses", 0) or 0),
        "sl_total_area": sl_quality.get("total_area", 0.0),
        "sl_100_percent": sl_quality.get("p100", 0.0),
        "sl_200_percent": sl_quality.get("p200", 0.0),
        "sl_300_percent": sl_quality.get("p300", 0.0),
        "sl_400_percent": sl_quality.get("p400", 0.0),
        "sl_600_percent": sl_quality.get("p600", 0.0),
        "sl_fragmented_percent": sl_quality.get("fragmented_percent", 0.0),
        "sl_quality_class": sl_quality.get("quality_class", ""),
        "sl_quality_phrase": sl_quality.get("quality_phrase", ""),
        "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
        **per_channel_trace_summary(entry),
        **reference_window_features(entry),
        **compute_patient_panel_features(entry),
    }


def interpret_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Interpret a single FSA entry.

    For patient samples the interpretation is dispatched to an assay-specific
    helper so that thresholds and zero-peak semantics can be tuned per assay.
    Ladder QC failures, SL quality classification, and control logic are
    handled before dispatching and remain assay-agnostic.
    """
    features = features_from_entry(entry)
    suggestion = "usikker_review"
    confidence = 0.35
    review_needed = True
    evidence: list[str] = []

    ladder_qc = str(features["ladder_qc_status"]).lower()
    if features["ladder_review_required"] or ladder_qc not in {"", "ok", "manual_adjustment"}:
        suggestion = "qc_teknisk_fail"
        confidence = 0.82
        evidence.append(f"ladder_qc={features['ladder_qc_status'] or 'unknown'}")
    elif (
        str(features["assay"]).upper() == "SL"
        and features["sample_kind"] != "control"
        and str(features.get("sl_quality_class") or "")
    ):
        suggestion, confidence, review_needed, sl_evidence = _sl_interpretation_from_features(features)
        evidence.extend(sl_evidence)
    elif features["sample_kind"] == "control":
        suggestion = _control_suggestion(features)
        confidence = 0.7 if suggestion != "qc_teknisk_fail" else 0.82
        evidence.append(f"control={features['control'] or 'unknown'}")
    else:
        # --- Patient sample: dispatch to assay-specific helper ---
        assay_key = _assay_key(str(features.get("assay") or ""))
        handler = _ASSAY_DISPATCH.get(assay_key, _interpret_default)
        suggestion, confidence, review_needed, assay_evidence = handler(features)
        evidence.extend(assay_evidence)

    if confidence >= 0.7 and suggestion not in {"pseudoklonal", "irregulaer", "usikker_review"}:
        review_needed = bool(features["sample_kind"] == "control" and suggestion == "qc_teknisk_fail")

    return {
        "ClonalityInterpretationEnabled": True,
        "ClonalitySuggestion": suggestion,
        "ClonalityConfidence": round(float(confidence), 3),
        "ClonalityReviewNeeded": bool(review_needed),
        "ClonalityEvidence": "; ".join(evidence),
        "ClonalitySLQualityClass": features.get("sl_quality_class", ""),
        "ClonalitySLFragmentedPercent": (
            round(float(features.get("sl_fragmented_percent", 0.0) or 0.0), 1)
            if str(features.get("assay") or "").upper() == "SL"
            else ""
        ),
        "ClonalitySLQualityPhrase": features.get("sl_quality_phrase", ""),
        "ClonalityModelVersion": INTERPRETATION_RULE_VERSION,
        "features": features,
    }


def attach_interpretation_if_enabled(entry: dict[str, Any]) -> dict[str, Any]:
    if not interpretation_enabled():
        return entry
    result = interpret_entry(entry)
    entry["clonality_interpretation"] = result
    for column in TRACKING_COLUMNS:
        entry[column] = result.get(column, "")
    return entry


def annotation_export_rows_to_frame(payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        rows = []
    return pd.DataFrame([row for row in rows if isinstance(row, dict)])


def write_annotation_csv_from_json(json_path: Path, csv_path: Path) -> Path:
    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    df = annotation_export_rows_to_frame(payload)
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)
    return csv_path


def write_learning_annotation_seed(
    entries: Sequence[dict[str, Any]],
    out_dir: Path,
    *,
    annotator: str = "",
    source: str = "app_run",
) -> dict[str, str]:
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    exported_at = utc_now_iso()
    stamp = exported_at.replace(":", "").replace("-", "")[:15]
    rows = []
    for ordinal, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        features = features_from_entry(entry)
        interpretation = entry.get("clonality_interpretation") if isinstance(entry.get("clonality_interpretation"), dict) else {}
        rows.append(
            {
                "ordinal": ordinal,
                "raw_path": features.get("raw_path", ""),
                "file": features.get("file", ""),
                "assay": features.get("assay", ""),
                "ladder": features.get("ladder", ""),
                "sample_kind": features.get("sample_kind", ""),
                "control": features.get("control", ""),
                "run_date": features.get("run_date", ""),
                "primary_peak_channel": features.get("primary_peak_channel", ""),
                "ladder_qc_status": features.get("ladder_qc_status", ""),
                "raw_peak_count": features.get("raw_peak_count", 0),
                "peak_count": features.get("peak_count", 0),
                "peak_count_in_interpretation_range": features.get("peak_count_in_interpretation_range", 0),
                "peak_count_outside_interpretation_range": features.get("peak_count_outside_interpretation_range", 0),
                "nonspecific_peak_count": features.get("nonspecific_peak_count", 0),
                "nonspecific_peak_basepairs": features.get("nonspecific_peak_basepairs", ""),
                "dominant_peak_basepairs": features.get("dominant_peak_basepairs", 0.0),
                "dominant_peak_height": features.get("dominant_peak_height", 0.0),
                "dominant_to_second_ratio": features.get("dominant_to_second_ratio", 0.0),
                "dominant_height_share": features.get("dominant_height_share", 0.0),
                "sl_fragmented_percent": features.get("sl_fragmented_percent", 0.0),
                "sl_quality_class": features.get("sl_quality_class", ""),
                "suggestion": interpretation.get("ClonalitySuggestion", ""),
                "confidence": interpretation.get("ClonalityConfidence", ""),
                "review_needed": interpretation.get("ClonalityReviewNeeded", ""),
                "evidence": interpretation.get("ClonalityEvidence", ""),
                "label": "",
                "control_flags": [],
                "note": "",
                "source": source,
                "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
                "annotator": annotator,
                "exported_at": exported_at,
            }
        )
    payload = {
        "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
        "exported_at": exported_at,
        "annotator": annotator,
        "source": source,
        "rows": rows,
    }
    json_path = out_dir / f"clonality_learning_annotations_{stamp}.json"
    csv_path = out_dir / f"clonality_learning_annotations_{stamp}.csv"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_rows_csv(rows, csv_path)
    return {"json": str(json_path), "csv": str(csv_path), "rows": str(len(rows))}


def write_rows_csv(rows: Iterable[dict[str, Any]], path: Path) -> Path:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sl_quality_from_metrics(sl_metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize SL DNA quality from 100/200/300/400/600 bp area percentages."""
    if not isinstance(sl_metrics, dict) or not sl_metrics:
        return _sl_quality_result("", "", 0.0, [0.0] * 5, 0.0)

    raw_percents = sl_metrics.get("percents") or []
    percents = [_finite_or_zero(raw_percents[idx]) if idx < len(raw_percents) else 0.0 for idx in range(5)]
    p100, p200, p300, p400, p600 = percents
    total_area = _finite_or_zero(sl_metrics.get("total_area"))
    fragmented_percent = min(100.0, max(0.0, p100 + p200))
    sum_100_300 = p100 + p200 + p300

    if total_area < 1e4:
        return _sl_quality_result(
            "uegnet_lavt_signal",
            "Materialet er uegnet (svært lite signal).",
            fragmented_percent,
            percents,
            total_area,
        )
    if p100 < 5:
        return _sl_quality_result(
            "uegnet_svak_100bp",
            "Materialet er uegnet (svært svak 100 bp-peak).",
            fragmented_percent,
            percents,
            total_area,
        )
    if p100 >= 85 and p200 <= 15 and p300 <= 5:
        return _sl_quality_result("svært_fragmentert", "Svært fragmentert materiale.", fragmented_percent, percents, total_area)
    if p100 >= 60 and fragmented_percent >= 80 and p300 <= 15:
        return _sl_quality_result(
            "mer_enn_50_prosent_fragmentert",
            "Mer enn 50 % fragmentert - redusert sensitivitet.",
            fragmented_percent,
            percents,
            total_area,
        )
    if p100 >= 45 and sum_100_300 >= 70:
        return _sl_quality_result(
            "litt_fragmentert",
            "Litt fragmentert - kan redusere sensitivitet.",
            fragmented_percent,
            percents,
            total_area,
        )
    if p100 <= 50 and fragmented_percent <= 70 and p300 >= 10 and p400 >= 5:
        return _sl_quality_result("bra_kvalitet", "Bra kvalitet.", fragmented_percent, percents, total_area)
    return _sl_quality_result(
        "uvanlig_fordeling_review",
        "Uvanlig fordeling - vurder manuelt.",
        fragmented_percent,
        percents,
        total_area,
    )


def assay_interpretation_ranges(assay: str) -> list[tuple[float, float]]:
    return list(ASSAY_REFERENCE_RANGES.get(_assay_name(assay), []))


def assay_interpretation_range(assay: str) -> tuple[float, float] | None:
    ranges = assay_interpretation_ranges(assay)
    if not ranges:
        return None
    return min(start for start, _end in ranges), max(end for _start, end in ranges)


def peak_context_for_assay(assay: str, peaks: pd.DataFrame) -> dict[str, Any]:
    assay_name = _assay_name(assay)
    ranges = assay_interpretation_ranges(assay_name)
    bp_range = assay_interpretation_range(assay_name)
    empty_peaks = pd.DataFrame()
    if bp_range is None or peaks.empty or "basepairs" not in peaks.columns:
        return {
            "range_min_bp": bp_range[0] if bp_range else 0.0,
            "range_max_bp": bp_range[1] if bp_range else 0.0,
            "ranges_text": _ranges_text(ranges),
            "raw_peak_count": 0,
            "in_range_count": 0,
            "out_of_range_count": 0,
            "nonspecific_count": 0,
            "nonspecific_basepairs": "",
            "nonspecific_height_share": 0.0,
            "dominant_peak_basepairs": 0.0,
            "dominant_peak_in_range": False,
            "dominant_peak_is_nonspecific": False,
            "outside_height_share": 0.0,
            "interpretation_peaks": empty_peaks,
        }

    frame = peaks.copy()
    frame["basepairs"] = pd.to_numeric(frame["basepairs"], errors="coerce")
    frame["peaks"] = pd.to_numeric(frame.get("peaks", 0.0), errors="coerce").fillna(0.0)
    frame = frame[np.isfinite(frame["basepairs"]) & (frame["peaks"] > 0)].copy()
    if frame.empty:
        return {
            "range_min_bp": bp_range[0],
            "range_max_bp": bp_range[1],
            "ranges_text": _ranges_text(ranges),
            "raw_peak_count": 0,
            "in_range_count": 0,
            "out_of_range_count": 0,
            "nonspecific_count": 0,
            "nonspecific_basepairs": "",
            "nonspecific_height_share": 0.0,
            "dominant_peak_basepairs": 0.0,
            "dominant_peak_in_range": False,
            "dominant_peak_is_nonspecific": False,
            "outside_height_share": 0.0,
            "interpretation_peaks": empty_peaks,
        }

    in_range = _in_any_range(frame["basepairs"], ranges)
    nonspecific = _known_nonspecific_mask(assay_name, frame["basepairs"])
    interpretable = frame[in_range & ~nonspecific].copy()
    dominant = frame.sort_values("peaks", ascending=False).iloc[0]
    total_height = float(frame["peaks"].sum())
    outside_height = float(frame.loc[~in_range, "peaks"].sum())
    nonspecific_height = float(frame.loc[nonspecific, "peaks"].sum())
    dominant_bp = float(dominant["basepairs"])
    dominant_is_nonspecific = bool(_known_nonspecific_mask(assay_name, pd.Series([dominant_bp])).iloc[0])
    lo, hi = bp_range
    return {
        "range_min_bp": float(lo),
        "range_max_bp": float(hi),
        "ranges_text": _ranges_text(ranges),
        "raw_peak_count": int(len(frame)),
        "in_range_count": int(in_range.sum()),
        "out_of_range_count": int((~in_range).sum()),
        "nonspecific_count": int(nonspecific.sum()),
        "nonspecific_basepairs": ";".join(f"{value:.1f}" for value in frame.loc[nonspecific, "basepairs"].tolist()),
        "nonspecific_height_share": float(nonspecific_height / total_height) if total_height > 0 else 0.0,
        "dominant_peak_basepairs": dominant_bp,
        "dominant_peak_in_range": bool(_in_any_range(pd.Series([dominant_bp]), ranges).iloc[0]),
        "dominant_peak_is_nonspecific": dominant_is_nonspecific,
        "outside_height_share": float(outside_height / total_height) if total_height > 0 else 0.0,
        "interpretation_peaks": interpretable,
    }


def _sl_quality_result(
    quality_class: str,
    quality_phrase: str,
    fragmented_percent: float,
    percents: list[float],
    total_area: float,
) -> dict[str, Any]:
    return {
        "quality_class": quality_class,
        "quality_phrase": quality_phrase,
        "fragmented_percent": float(fragmented_percent),
        "p100": float(percents[0]) if len(percents) > 0 else 0.0,
        "p200": float(percents[1]) if len(percents) > 1 else 0.0,
        "p300": float(percents[2]) if len(percents) > 2 else 0.0,
        "p400": float(percents[3]) if len(percents) > 3 else 0.0,
        "p600": float(percents[4]) if len(percents) > 4 else 0.0,
        "total_area": float(total_area),
    }


def _sl_interpretation_from_features(features: dict[str, Any]) -> tuple[str, float, bool, list[str]]:
    quality_class = str(features.get("sl_quality_class") or "")
    fragmented = float(features.get("sl_fragmented_percent", 0.0) or 0.0)
    evidence = [f"sl_fragmented_percent={fragmented:.1f}"]
    if quality_class:
        evidence.append(f"sl_quality={quality_class}")

    if quality_class.startswith("uegnet"):
        return "intet_pcr_produkt_darlig_dna", 0.78, False, evidence
    if quality_class in {"svært_fragmentert", "mer_enn_50_prosent_fragmentert"}:
        return "usikker_review", 0.62, True, evidence
    if quality_class in {"litt_fragmentert", "bra_kvalitet"}:
        return "polyklonal", 0.66, True, evidence
    return "usikker_review", 0.5, True, evidence


def _has_unspecific_peak_pattern(features: dict[str, Any]) -> bool:
    assay = _assay_name(str(features.get("assay") or ""))
    if assay in {"SL", ""} or assay not in NONSPECIFIC_PEAKS:
        return False
    nonspecific_count = int(features.get("nonspecific_peak_count", 0) or 0)
    if nonspecific_count == 0:
        return False
    nonspecific_share = float(features.get("nonspecific_height_share", 0.0) or 0.0)
    dominant_nonspecific = bool(features.get("dominant_peak_is_nonspecific", False))
    return dominant_nonspecific or nonspecific_share >= 0.35


# ============================================================
# Assay-specific patient interpretation helpers
# ============================================================
# Each function receives the full *features* dict and returns a tuple:
#   (suggestion: str, confidence: float, review_needed: bool, evidence: list[str])
#
# When a new assay needs custom tuning, add a dedicated function below
# and register it in _ASSAY_DISPATCH. Everything not in the map falls
# through to _interpret_default, which contains the original generic logic.
# ============================================================

_InterpResult = tuple[str, float, bool, list[str]]


def _interpret_default(features: dict[str, Any]) -> _InterpResult:
    """Generic patient interpretation (original rule chain)."""
    if features["peak_count"] == 0 and features["raw_peak_count"] > 0:
        evidence = ["no_interpretable_peaks_inside_reference_range"]
        if _has_unspecific_peak_pattern(features):
            evidence.insert(0, "known_nonspecific_peaks_excluded")
        return "usikker_review", 0.5, True, evidence
    if features["peak_count"] == 0 or features["dominant_peak_height"] < 80:
        return "intet_pcr_produkt_darlig_dna", 0.78, True, ["no_or_very_weak_peaks"]
    evidence_prefix = ["known_nonspecific_peaks_excluded"] if _has_unspecific_peak_pattern(features) else []
    if features["dominant_to_second_ratio"] >= 3.0 and features["dominant_height_share"] >= 0.45:
        return "monoklonal", 0.72, True, evidence_prefix + ["dominant_peak_ratio>=3"]
    if features["peak_count"] >= 2 and features["dominant_height_share"] >= 0.58:
        return "bi_oligoklonal", 0.62, True, evidence_prefix + ["multiple_dominant_peaks"]
    if features["peak_count"] >= 5 and features["dominant_height_share"] < 0.35:
        return "polyklonal", 0.66, True, evidence_prefix + ["distributed_peak_profile"]
    if features["peak_count"] <= 2:
        return "pseudoklonal", 0.46, True, evidence_prefix + ["limited_peak_pattern_needs_replicate_review"]
    return "irregulaer", 0.44, True, evidence_prefix + ["mixed_peak_pattern"]


def _interpret_fr1(features: dict[str, Any]) -> _InterpResult:
    """FR1 (IgH): standard rules, same as default for now."""
    return _interpret_default(features)


def _interpret_fr2(features: dict[str, Any]) -> _InterpResult:
    """FR2 (IgH): standard rules, same as default for now."""
    return _interpret_default(features)


def _interpret_fr3(features: dict[str, Any]) -> _InterpResult:
    """FR3 (IgH): standard rules, same as default for now."""
    return _interpret_default(features)


def _interpret_dhjh_d(features: dict[str, Any]) -> _InterpResult:
    """DHJH mix D: zero-peak patient samples are polyklonal (not bad DNA).

    DHJH_D has a broad reference range (110-290 + 390-420 bp) and many
    non-specific peaks.  Clinical practice shows that zero detectable peaks
    after filtering is common and expected for polyclonal repertoires.
    """
    if features["peak_count"] == 0 or features["dominant_peak_height"] < 80:
        if features["raw_peak_count"] > 0:
            return "polyklonal", 0.62, True, ["zero_interpretation_peaks_dhjh_d_polyclonal"]
        return "polyklonal", 0.55, True, ["no_peaks_dhjh_d_polyclonal"]
    return _interpret_default(features)


def _interpret_dhjh_e(features: dict[str, Any]) -> _InterpResult:
    """DHJH mix E: zero-peak patient samples → usikker_review.

    DHJH_E has a narrow reference range (100-130 bp) and many non-specific
    peaks nearby.  Zero detectable peaks is ambiguous rather than
    definitively poor DNA.
    """
    if features["peak_count"] == 0 or features["dominant_peak_height"] < 80:
        return "usikker_review", 0.55, True, ["zero_peaks_dhjh_e_review"]
    return _interpret_default(features)


def _interpret_igk(features: dict[str, Any]) -> _InterpResult:
    """IGK: relaxed polyklonal threshold for multi-peak profiles.

    When there are ≥5 peaks with dominant_height_share ≤ 0.48 this is a
    polyclonal pattern even if the share is above the generic 0.35 cutoff.
    This captures cases like ordinal 16 (8 peaks, ratio 3.4, share 0.44).
    """
    if features["peak_count"] == 0 or features["dominant_peak_height"] < 80:
        return _interpret_default(features)
    # Relaxed polyklonal: many peaks + moderate share
    if features["peak_count"] >= 5 and features["dominant_height_share"] <= 0.48:
        evidence = ["distributed_peak_profile_igk_relaxed"]
        if _has_unspecific_peak_pattern(features):
            evidence.insert(0, "known_nonspecific_peaks_excluded")
        return "polyklonal", 0.64, True, evidence
    return _interpret_default(features)


def _interpret_kde(features: dict[str, Any]) -> _InterpResult:
    """KDE: standard rules for now."""
    return _interpret_default(features)


def _interpret_tcrb_a(features: dict[str, Any]) -> _InterpResult:
    """TCRβ mix A: zero-peak → polyklonal.

    TCRbA has a narrow reference range (240-285 bp).  The polyclonal
    TCR-beta background often produces no detectable discrete peaks.
    """
    if features["peak_count"] == 0 or features["dominant_peak_height"] < 80:
        if features["raw_peak_count"] > 0:
            return "polyklonal", 0.60, True, ["zero_interpretation_peaks_tcrba_polyclonal"]
        return "polyklonal", 0.52, True, ["no_peaks_tcrba_polyclonal"]
    return _interpret_default(features)


def _interpret_tcrb_b(features: dict[str, Any]) -> _InterpResult:
    """TCRβ mix B: standard rules for now."""
    return _interpret_default(features)


def _interpret_tcrb_c(features: dict[str, Any]) -> _InterpResult:
    """TCRβ mix C: zero-peak → polyklonal.

    TCRbC has split reference ranges (170-210 + 285-325 bp).
    Zero peaks after filtering is common in polyclonal patients.
    """
    if features["peak_count"] == 0 or features["dominant_peak_height"] < 80:
        if features["raw_peak_count"] > 0:
            return "polyklonal", 0.60, True, ["zero_interpretation_peaks_tcrbc_polyclonal"]
        return "polyklonal", 0.52, True, ["no_peaks_tcrbc_polyclonal"]
    return _interpret_default(features)


def _interpret_tcrg_a(features: dict[str, Any]) -> _InterpResult:
    """TCRγ mix A: standard rules for now."""
    return _interpret_default(features)


def _interpret_tcrg_b(features: dict[str, Any]) -> _InterpResult:
    """TCRγ mix B: standard rules for now."""
    return _interpret_default(features)


# --- Dispatch map: _assay_key(assay_name) → handler ---
_ASSAY_DISPATCH: dict[str, Any] = {
    "FR1": _interpret_fr1,
    "FR2": _interpret_fr2,
    "FR3": _interpret_fr3,
    "DHJHD": _interpret_dhjh_d,
    "DHJHE": _interpret_dhjh_e,
    "IGK": _interpret_igk,
    "KDE": _interpret_kde,
    "TCRBA": _interpret_tcrb_a,
    "TCRBB": _interpret_tcrb_b,
    "TCRBC": _interpret_tcrb_c,
    "TCRGA": _interpret_tcrg_a,
    "TCRGB": _interpret_tcrg_b,
}


def _assay_key(assay: str) -> str:
    return str(assay or "").replace("_", "").replace("-", "").upper()


def _assay_name(assay: str) -> str:
    key = _assay_key(assay)
    for name in set(ASSAY_REFERENCE_RANGES) | set(NONSPECIFIC_PEAKS):
        if _assay_key(name) == key:
            return name
    return str(assay or "")


def _in_any_range(values: pd.Series, ranges: Sequence[tuple[float, float]]) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    mask = pd.Series(False, index=numeric.index)
    for lo, hi in ranges:
        mask |= numeric.between(float(lo), float(hi), inclusive="both")
    return mask.fillna(False)


def _known_nonspecific_mask(assay: str, values: pd.Series) -> pd.Series:
    known = NONSPECIFIC_PEAKS.get(_assay_name(assay), [])
    numeric = pd.to_numeric(values, errors="coerce")
    mask = pd.Series(False, index=numeric.index)
    for bp in known:
        mask |= (numeric - float(bp)).abs() <= NONSPECIFIC_PEAK_WINDOW_BP
    return mask.fillna(False)


def _ranges_text(ranges: Sequence[tuple[float, float]]) -> str:
    return "; ".join(f"{float(lo):.0f}-{float(hi):.0f}" for lo, hi in ranges)


def _combined_peak_frame(entry: dict[str, Any]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    peaks_by_channel = entry.get("peaks_by_channel") or {}
    if not isinstance(peaks_by_channel, dict):
        return pd.DataFrame()
    for channel, frame in peaks_by_channel.items():
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        copy = frame.copy()
        copy["channel"] = str(channel)
        frames.append(copy)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if "peaks" in combined.columns:
        combined = combined[pd.to_numeric(combined["peaks"], errors="coerce").fillna(0) > 0]
    return combined


def _numeric_list(values: Iterable[Any]) -> list[float]:
    result: list[float] = []
    for value in values:
        number = _finite_or_zero(value)
        if number > 0:
            result.append(number)
    return result


def _finite_or_zero(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _control_suggestion(features: dict[str, Any]) -> str:
    control = str(features.get("control") or "").upper()
    peak_count = int(features.get("peak_count", 0) or 0)
    dominant = float(features.get("dominant_peak_height", 0.0) or 0.0)
    marker_count = int(features.get("tracking_marker_count", 0) or 0)
    marker_hits = int(features.get("tracking_marker_hits", 0) or 0)
    if control in {"PK", "PK1", "PK2"}:
        if marker_count and marker_hits < marker_count:
            return "qc_teknisk_fail"
        return "monoklonal" if dominant > 0 else "qc_teknisk_fail"
    if control == "NK":
        if peak_count == 0 or dominant < 150:
            return "intet_pcr_produkt_darlig_dna"
        return "pseudoklonal"
    if control == "RK":
        if peak_count >= 3:
            return "polyklonal"
        return "usikker_review"
    return "usikker_review"
