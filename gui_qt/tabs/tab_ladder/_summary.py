"""HemaFrag GUI Qt — pure helpers for `tab_ladder`.

Phase 12.1 — extracted from the previously-monolithic
`gui_qt/tabs/tab_ladder/_legacy.py` so they can be unit-tested
without spinning up a `QApplication` or constructing a `TabLadder`.

Pure functions only; no Qt widgets, no instance-state reads/writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config import APP_SETTINGS
from core.analyses.clonality.ladder_review_labels import is_review_resolved


def resolve_cache_key(file_path: Path) -> Path:
    """Resolve a (possibly not-yet-existing) path into a canonical key.

    Falls back to expanduser() if resolve() raises on Windows for
    relative paths. Mirrors the prior inline implementation in
    TabLadder so existing callers and persisted cache entries keep
    matching.
    """
    try:
        return file_path.expanduser().resolve()
    except Exception:
        return file_path.expanduser()


def entry_original_path(entry: dict) -> Path | None:
    """Find the canonical FSA path attached to a clonality batch entry.

    Tries `original_file_path` then `full_path` then falls back to
    the FSA object's `.file` / `.path` / `.file_path` /
    `.filepath`. Returns `None` when nothing resolvable exists so
    the caller can drop the row instead of crashing.
    """
    raw_path = str(
        entry.get("original_file_path") or entry.get("full_path") or ""
    ).strip()
    if not raw_path:
        fsa = entry.get("fsa")
        raw_path = str(
            getattr(fsa, "file", "")
            or getattr(fsa, "path", "")
            or getattr(fsa, "file_path", "")
            or getattr(fsa, "filepath", "")
            or ""
        ).strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser()


def entry_cache_key(entry: dict) -> Path | None:
    """Wrap: `entry_original_path` then through `resolve_cache_key`."""
    original_path = entry_original_path(entry)
    if original_path is None:
        return None
    return resolve_cache_key(original_path)


def manual_adjustment_consumption(
    result: dict,
    file_path: Path,
) -> dict[str, Any]:
    """Summarize whether a saved correction produced a successful entry."""
    target = resolve_cache_key(file_path)
    from core.ladder_adjustment_store import load_ladder_adjustment_record

    adjustment_record = load_ladder_adjustment_record(file_path)
    adjustment_present = adjustment_record is not None
    adjustment_hash = str(
        (adjustment_record or {}).get("payload_sha256") or ""
    )
    entries = list(result.get("dit_report_entries") or [])
    if not entries:
        entries = list(result.get("collected_entries") or [])
        entries.extend(result.get("qc_report_entries") or [])

    matching_entry: dict | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry_cache_key(entry) == target:
            matching_entry = entry
            break

    failed = bool(result.get("failed_jobs"))
    gate = result.get("ladder_review_gate") or {}
    review_count = (
        int(gate.get("review_case_count") or 0)
        if isinstance(gate, dict)
        else 0
    )
    if matching_entry is None:
        return {
            "status": (
                "not_consumed"
                if adjustment_present
                else "not_applicable"
            ),
            "consumed": False,
            "adjustment_present": adjustment_present,
            "reason": "No completed analysis entry was returned for this file.",
        }

    provenance = matching_entry.get("analysis_provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    strategy = str(
        provenance.get("ladder_fit_strategy")
        or matching_entry.get("ladder_fit_strategy")
        or ""
    )
    entry_claims_consumed = bool(
        provenance.get("manual_adjustment_consumed")
        or strategy == "manual_adjustment"
    )
    analyzed_adjustment_hash = str(
        provenance.get("manual_adjustment_sha256") or ""
    )
    hash_matches = bool(
        adjustment_hash
        and analyzed_adjustment_hash
        and adjustment_hash == analyzed_adjustment_hash
    )
    successful = (
        adjustment_present
        and entry_claims_consumed
        and hash_matches
        and not failed
        and review_count <= 0
    )
    if successful:
        reason = "Saved correction was consumed by a successful rerun."
    elif entry_claims_consumed and adjustment_present and not hash_matches:
        reason = (
            "The rerun consumed a different correction than the currently "
            "saved adjustment."
        )
    elif not entry_claims_consumed and adjustment_present:
        reason = "The rerun entry did not use the saved manual correction."
    elif not adjustment_present:
        reason = "No saved manual correction was present for this file."
    elif failed:
        reason = "The correction was loaded, but the rerun reported failed jobs."
    else:
        reason = "The correction was loaded, but ladder review is still required."
    return {
        "status": (
            "consumed"
            if successful
            else "not_consumed"
            if adjustment_present
            else "not_applicable"
        ),
        "consumed": successful,
        "adjustment_present": adjustment_present,
        "reason": reason,
        "strategy": strategy,
        "source_sha256": str(provenance.get("source_sha256") or ""),
        "manual_adjustment_sha256": analyzed_adjustment_hash,
        "saved_adjustment_sha256": adjustment_hash,
    }


def format_ladder_confidence_shadow(payload: dict | None) -> str:
    """Format read-only candidate ambiguity evidence for Ladder Studio."""
    if not isinstance(payload, dict):
        return "Unavailable"
    rank = payload.get("runtime_selected_rank")
    margin = payload.get("top1_top2_score_margin")
    stable = payload.get("stable_under_tested_thresholds")
    parts = [f"Selected rank {rank}" if rank is not None else "Selected rank unavailable"]
    if margin is not None:
        parts.append(f"top-2 margin {float(margin):.3f}")
    if stable is True:
        parts.append("threshold stable")
    elif stable is False:
        parts.append("threshold unstable")
    parts.append("shadow only")
    return " · ".join(parts)


def metadata_from_entry(file_path: Path, entry: dict) -> dict:
    """Build the metadata dict passed to the dialog when a row is queued.

    Mirrors the prior TabLadder._metadata_from_entry exactly.
    """
    trace_channels = entry.get("trace_channels") or []
    if not isinstance(trace_channels, list):
        trace_channels = list(trace_channels)
    primary_peak_channel = str(
        entry.get("primary_peak_channel")
        or (trace_channels[0] if trace_channels else "DATA1")
    )
    return {
        "analysis": APP_SETTINGS.get("active_analysis", "clonality"),
        "assay": str(entry.get("assay") or ""),
        "group": str(entry.get("group") or ""),
        "ladder": str(entry.get("ladder") or ""),
        "trace_channels": trace_channels,
        "peak_channels": list(trace_channels),
        "primary_peak_channel": primary_peak_channel,
        "sample_channel": primary_peak_channel,
        "bp_min": float(entry.get("bp_min") or 0.0),
        "bp_max": float(entry.get("bp_max") or 0.0),
        "file_path": file_path,
        "raw": {},
    }


def format_file_item(file_path: Path, case: dict | None) -> str:
    """One-line display string for a file-list row.

    Falls back to the bare filename when `case` is None (the file
    was scanned but isn't a bundle row). Otherwise the row carries
    assay / well / ladder / linear stats / qc to make triage at a
    glance usable without opening the dialog.
    """
    if not case:
        return file_path.name

    parts = [file_path.name]
    assay = str(case.get("assay", "") or "").strip()
    well = str(case.get("well", "") or "").strip()
    ladder = str(case.get("ladder", "") or "").strip()
    if assay:
        parts.append(assay)
    if well:
        parts.append(well)
    if ladder:
        parts.append(ladder)
    linear_max = case.get("linear_max")
    linear_r2 = case.get("linear_r2")
    qc = str(case.get("ladder_qc", "") or "").strip()
    if linear_max not in (None, ""):
        try:
            parts.append(f"max {float(linear_max):.2f}")
        except Exception:
            parts.append(f"max {linear_max}")
    if linear_r2 not in (None, ""):
        try:
            parts.append(f"r2 {float(linear_r2):.5f}")
        except Exception:
            parts.append(f"r2 {linear_r2}")
    if qc:
        parts.append(qc)
    return " · ".join(parts)


# Phase 12.3 — chip-strip state labels + precedence.
CHIP_STATE_LABELS = {
    "reviewed",
    "needs_review",
    "file_unreachable",
    "untouched",
}

# Color contract for the four chip-state precedence. The convention
# matches `core/analyses/clonality/clonality_qc` semantics:
# - reviewed         → green (chemist has cleared the row)
# - needs_review     → amber (bad ladder fit or pending review)
# - file_unreachable → red (path doesn't resolve on disk)
# - untouched        → gray (row loaded but chemist hasn't touched it)
CHIP_STATE_COLORS = {
    "reviewed": "#16a34a",         # green
    "needs_review": "#d97706",     # amber
    "file_unreachable": "#dc2626", # red
    "untouched": "#94a3b8",        # gray
}


def chip_state(row: dict, *, check_filesystem: bool = False) -> str:
    """Return one of: 'reviewed' | 'needs_review' | 'file_unreachable' | 'untouched'.

    The state of a row is the *highest* priority in this order —
    file_unreachable (most actionable for the chemist) wins over
    needs_review, which wins over touched-but-not-saved, which
    wins over untouched.

    The `check_filesystem` kwarg forces a `Path.exists()` check
    rather than relying on the row's `_path_unreachable` tag,
    which is useful when callers don't trust the cached tag.

    Tests pin the precedence contract — see
    `tests/test_tab_ladder_submodules.py::ChipStateHelperTests`.
    """
    # 1. File unreachable — Phase 12.0 tags row["_path_unreachable"].
    if check_filesystem:
        raw_path = str(row.get("full_path", "") or "")
        if raw_path and not Path(raw_path).expanduser().exists():
            return "file_unreachable"
    elif str(row.get("_path_unreachable", "")).lower() == "true":
        return "file_unreachable"

    # 2. Label resolved → reviewed.
    if is_review_resolved(row.get("label")):
        return "reviewed"

    # 3. Open tooltip reasons flag a needs_review row.
    ladder_qc_status = str(row.get("ladder_qc_status", "") or "").strip().lower()
    review_required_raw = str(row.get("ladder_review_required", "") or "").strip().lower()
    review_required = review_required_raw in {"true", "1", "yes"}
    if ladder_qc_status in {"review_required", "missing_ladder", "ladder_qc_failed"} or review_required:
        return "needs_review"

    return "untouched"


def count_chip_states(rows: list[dict], *, check_filesystem: bool = False) -> dict:
    """Tally how many rows fall into each chip-state bucket.

    Returns {reviewed: int, needs_review: int, file_unreachable: int,
    untouched: int}. Used by the chip-strip legend + bundle summary banner.
    """
    counts = {key: 0 for key in CHIP_STATE_LABELS}
    for row in rows or []:
        try:
            state = chip_state(row, check_filesystem=check_filesystem)
        except Exception:
            state = "untouched"
        if state in counts:
            counts[state] += 1
        else:
            counts["untouched"] += 1
    return counts
