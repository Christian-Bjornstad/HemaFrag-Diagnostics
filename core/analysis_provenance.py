"""Consistent per-file provenance for reports and tracking exports."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app_meta import APP_VERSION


ANALYSIS_PROVENANCE_SCHEMA = "hemafrag_analysis_provenance_v2"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_path(entry: dict[str, Any], fsa: Any) -> Path | None:
    value = (
        entry.get("original_file_path")
        or getattr(fsa, "file", None)
        or ""
    )
    if not value:
        return None
    return Path(str(value)).expanduser()


def build_analysis_provenance(entry: dict[str, Any]) -> dict[str, object]:
    fsa = entry.get("fsa")
    strategy = str(entry.get("ladder_fit_strategy") or "")
    source = _source_path(entry, fsa)
    artifact = getattr(fsa, "fsa_artifact", None)
    source_hash = str(getattr(artifact, "content_sha256", "") or "")
    if not source_hash and source is not None and source.is_file():
        source_hash = _sha256_file(source)

    adjustment_hash = ""
    adjustment_schema = ""
    adjustment_payload: dict[str, Any] = {}
    if source is not None:
        from core.ladder_adjustment_store import load_ladder_adjustment_record

        record = load_ladder_adjustment_record(
            source,
            ladder=str(entry.get("internal_ladder") or entry.get("ladder") or ""),
            size_standard_channel=str(
                entry.get("size_standard_channel")
                or getattr(fsa, "size_standard_channel", "")
                or ""
            ),
        )
        if record is not None:
            adjustment_hash = str(record.get("payload_sha256") or "")
            payload = record.get("payload")
            if isinstance(payload, dict):
                from core.ladder_adjustment_io import normalize_ladder_adjustment_payload

                adjustment_payload = normalize_ladder_adjustment_payload(payload) or {}
                adjustment_schema = str(
                    adjustment_payload.get("schema_version") or "legacy"
                )

    manual_strategy = strategy in {"manual_adjustment", "manual_partial"}
    if manual_strategy:
        engine = "manual"
    elif getattr(fsa, "rust_detected_ladder", None):
        engine = "rust"
    else:
        engine = "python"
    reason_codes = entry.get("ladder_review_reason_codes") or []
    if not isinstance(reason_codes, (list, tuple)):
        reason_codes = [reason_codes]
    return {
        "schema_version": ANALYSIS_PROVENANCE_SCHEMA,
        "app_version": str(APP_VERSION),
        "source_file": source.name if source is not None else str(entry.get("file_name") or ""),
        "source_sha256": source_hash,
        "ladder": str(entry.get("internal_ladder") or entry.get("ladder") or ""),
        "size_standard_channel": str(
            entry.get("size_standard_channel")
            or getattr(fsa, "size_standard_channel", "")
            or ""
        ),
        "ladder_engine": engine,
        "ladder_fit_strategy": strategy,
        "ladder_search_tier": str(
            entry.get("ladder_search_tier")
            or getattr(fsa, "rust_ladder_fit_tier", "")
            or ""
        ),
        "ladder_qc_status": str(entry.get("ladder_qc_status") or ""),
        "ladder_reason_codes": [
            str(value) for value in reason_codes if str(value)
        ],
        "ladder_selected_baseline_like_anchor_count": int(
            entry.get("ladder_selected_baseline_like_anchor_count")
            or getattr(fsa, "rust_selected_baseline_like_anchor_count", 0)
            or 0
        ),
        "ladder_selected_cleaner_neighbor_count": int(
            entry.get("ladder_selected_cleaner_neighbor_count")
            or getattr(fsa, "rust_selected_cleaner_neighbor_count", 0)
            or 0
        ),
        "ladder_selected_strong_baseline_anchor_count": int(
            entry.get("ladder_selected_strong_baseline_anchor_count")
            or getattr(fsa, "rust_selected_strong_baseline_anchor_count", 0)
            or 0
        ),
        "manual_adjustment_consumed": manual_strategy,
        "manual_adjustment_schema": adjustment_schema,
        "manual_adjustment_sha256": adjustment_hash,
        "manual_adjustment_partial": bool(
            strategy == "manual_partial"
            or adjustment_payload.get("partial_mapping")
        ),
        "manual_adjustment_mapped_step_indices": [
            int(value)
            for value in (
                getattr(fsa, "manual_ladder_mapped_step_indices", None)
                or adjustment_payload.get("mapped_step_indices")
                or []
            )
        ],
        "manual_adjustment_missing_step_indices": [
            int(value)
            for value in (
                getattr(fsa, "manual_ladder_missing_step_indices", None)
                or adjustment_payload.get("missing_step_indices")
                or []
            )
        ],
        "manual_adjustment_marker_ids": sorted(
            str(value)
            for value in dict(
                getattr(fsa, "manual_ladder_marker_id_by_step", None)
                or adjustment_payload.get("marker_id_by_step")
                or {}
            ).values()
            if str(value)
        ),
    }


def attach_analysis_provenance(entry: dict[str, Any]) -> dict[str, Any]:
    entry["analysis_provenance"] = build_analysis_provenance(entry)
    return entry


__all__ = [
    "ANALYSIS_PROVENANCE_SCHEMA",
    "attach_analysis_provenance",
    "build_analysis_provenance",
]
