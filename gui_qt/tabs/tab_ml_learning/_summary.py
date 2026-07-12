"""MlLearning pure helpers (no Qt).

Phase A (Plan 13).
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

# DIT pattern: 2 digits + 'OUM' + 5 digits (e.g. 24OUM20364)
_DIT_RE = re.compile(r"(\d{2}OUM\d{5})")


def extract_dit(parts: Sequence[str | Path]) -> str:
    """Pull the DIT out of any one of ``parts`` (first match wins).

    Mirrors the prior `extract_dit_from_name` helper but is purely string-based
    so headless tests don't drag in Qt.
    """
    for raw in parts:
        text = str(raw or "")
        match = _DIT_RE.search(text)
        if match:
            return match.group(1)
    return ""


def infer_assay(file_path: Path, fallback: str = "") -> str:
    """Infer the assay name from an FSA file name.

    Used when the xlsx is unavailable or the file came from a run folder
    directly. Mirrors `core.analyses.clonality.classification` heuristics,
    trimmed to the substring markers.
    """
    text = str(file_path.name or "")
    if not text:
        return fallback
    # Underscore or hyphen separated tokens; assay marker is the FIRST
    # token after the DIT prefix in the canonical naming scheme.
    stem = text.rsplit(".", 1)[0]
    tokens = re.split(r"[_\-]+", stem)
    known = {
        "FR1", "FR2", "FR3", "IKZF1", "Ktr-albumin",
        "IGK", "IGK-degenerate", "KDE",
        "DHJH_D", "DHJH_E",
        "TCRbA", "TCRbB", "TCRbC",
        "TCRgA", "TCRgB",
        "SL",
    }
    for token in tokens:
        if token in known:
            return token
    # PK/RK/NK prefix (controls) carry no assay - rely on caller fallback.
    return fallback


_ASSAY_FALLBACK_BUCKET = "UNKNOWN"


def group_by_assay(
    files: Iterable[Path],
    *,
    assay_order: Sequence[str],
) -> dict[str, list[Path]]:
    """Group FSA files by inferred assay; ordered per ``assay_order``.

    The returned dict's insertion order matches ``assay_order`` with an
    ``"UNKNOWN"`` trailing bucket for files where the assay could not be
    inferred (kept last so chemists don't accidentally scan it first).
    """
    by_assay: dict[str, list[Path]] = {
        assay: [] for assay in assay_order
    }
    by_assay[_ASSAY_FALLBACK_BUCKET] = []

    for path in files:
        assay = infer_assay(path)
        if assay and assay in by_assay:
            by_assay[assay].append(path)
        else:
            by_assay[_ASSAY_FALLBACK_BUCKET].append(path)

    # Stable sort inside each group by file name
    return {
        assay: sorted(group, key=lambda p: str(p).lower())
        for assay, group in by_assay.items()
    }


def summarize_run(
    files: Sequence[Path],
    *,
    assay_order: Sequence[str],
) -> dict[str, Any]:
    """Return counts so the UI can render a tiny summary strip.

    Returns:
        {
            "total": int,
            "by_assay": {assay: int, ...},
            "dit_distinct": int,
            "control_count": int,
            "patient_count": int,
        }
    """
    grouped = group_by_assay(files, assay_order=assay_order)
    by_assay = {assay: len(group) for assay, group in grouped.items()}
    dits = {extract_dit([p.name, p.parent.name]) for p in files}
    dits.discard("")
    control_count = 0
    patient_count = 0
    for path in files:
        stem = path.name.upper()
        if stem.startswith(("NK_", "PK_", "RK_")):
            control_count += 1
        else:
            patient_count += 1
    return {
        "total": len(files),
        "by_assay": by_assay,
        "dit_distinct": len(dits),
        "control_count": control_count,
        "patient_count": patient_count,
    }


def entry_payload(
    *,
    ordinal: int,
    raw_path: Path,
    features: dict[str, Any] | None,
    interpretation: dict[str, Any] | None,
    peaks_by_channel: dict[str, Any] | None,
    image_path: Path | None,
    feature_axes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pack a single file's per-analysis state into a JSONL-ready dict.

    Shape is intentionally flat + primitive (no FsaFile objects); the panel
    reads this dict via xhr and Plotly reconstructs the graphs.
    """
    peaks = peaks_by_channel or {}
    return {
        "ordinal": int(ordinal),
        "file": raw_path.name,
        "raw_path": str(raw_path),
        "assay": (features or {}).get("assay") or "",
        "sample_kind": (features or {}).get("sample_kind") or "",
        "control": (features or {}).get("control") or "",
        "dit": extract_dit([raw_path.name, raw_path.parent.name]),
        "primary_peak_channel": (features or {}).get("primary_peak_channel") or "",
        "ladder_qc_status": (features or {}).get("ladder_qc_status") or "",
        "ladder_fit_strategy": (features or {}).get("ladder_fit_strategy") or "",
        "peak_count": (features or {}).get("peak_count") or 0,
        "raw_peak_count": (features or {}).get("raw_peak_count") or 0,
        "peak_count_in_interpretation_range":
            (features or {}).get("peak_count_in_interpretation_range") or 0,
        "dominant_peak_basepairs":
            float((features or {}).get("dominant_peak_basepairs") or 0.0),
        "dominant_peak_height":
            float((features or {}).get("dominant_peak_height") or 0.0),
        "interpretation_range_min_bp":
            float((features or {}).get("interpretation_range_min_bp") or 0.0),
        "interpretation_range_max_bp":
            float((features or {}).get("interpretation_range_max_bp") or 0.0),
        "suggestion": (interpretation or {}).get("ClonalitySuggestion") or "",
        "confidence": (interpretation or {}).get("ClonalityConfidence") or 0.0,
        "review_needed": bool((interpretation or {}).get("ClonalityReviewNeeded")),
        "evidence": (interpretation or {}).get("ClonalityEvidence") or "",
        "peaks_by_channel": {
            ch: {
                "basepairs": list(getattr(df, "get", df.get)("basepairs", []) or []),
                "peaks": list(getattr(df, "get", df.get)("peaks", []) or []),
            }
            if hasattr(df, "get") or isinstance(df, dict)
            else {}
            for ch, df in peaks.items()
        },
        "feature_axes": feature_axes or {},
        "image": str(image_path) if image_path else "",
        "annotation_schema_version": 1,
    }


__all__ = [
    "extract_dit",
    "infer_assay",
    "group_by_assay",
    "summarize_run",
    "entry_payload",
]
