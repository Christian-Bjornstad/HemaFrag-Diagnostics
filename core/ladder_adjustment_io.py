"""Lightweight ladder-adjustment persistence API.

Extracted from ``core/analysis/_legacy`` so GUI modules (tab_ladder,
ladder review flows) can persist manual ladder mappings WITHOUT pulling
the heavy scientific stack (scipy / sklearn / Bio) into application
startup. This module deliberately imports nothing heavier than the
standard library plus ``core.ladder_adjustment_store``.

Public API (moved verbatim from core.analysis):
- ``save_ladder_adjustment(fsa, adjustment, ...) -> Path``
- ``load_ladder_adjustment(fsa) -> dict | None``
plus the schema constants and normalization helpers that back them.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps import light
    from fraggler.fraggler import FsaFile

LADDER_ADJUSTMENT_SCHEMA_V3 = "hemafrag_ladder_adjustment_v3"
LADDER_ADJUSTMENT_SCHEMA_V2 = "hemafrag_ladder_adjustment_v2"
LADDER_ADJUSTMENT_SCHEMA_LEGACY = "legacy"


def _print_green(text: str) -> None:
    # Mirrors fraggler.fraggler.print_green without importing it (the
    # fraggler package itself stays light, but this avoids the coupling).
    print(f"\033[92m[INFO]: {text}\033[0m")


def _print_warning(text: str) -> None:
    print(f"\033[93m\033[4m[WARNING]: {text}\033[0m")


def ladder_adjustment_file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Backwards-compatible private alias (historically lived in core.analysis).
_ladder_adjustment_file_hash = ladder_adjustment_file_hash


def _legacy_marker_id(
    *,
    step_index: int | None,
    scan_x: float,
    source_kind: str,
    candidate_index: int | None = None,
) -> str:
    """Return a stable identity for marker records synthesized from old payloads."""
    token = "|".join(
        (
            str(source_kind or "legacy"),
            "" if step_index is None else str(int(step_index)),
            format(float(scan_x), ".17g"),
            "" if candidate_index is None else str(int(candidate_index)),
        )
    )
    return f"legacy-{hashlib.sha256(token.encode('utf-8')).hexdigest()[:20]}"


def _normalize_marker(raw: dict[str, Any], *, ordinal: int) -> dict[str, Any] | None:
    try:
        scan_x = float(raw.get("scan_x", raw.get("requested_x")))
    except (TypeError, ValueError):
        return None
    source_kind = str(raw.get("source_kind") or raw.get("source") or "manual_exact")
    candidate_index_raw = raw.get("candidate_index")
    candidate_index = (
        int(candidate_index_raw) if candidate_index_raw is not None else None
    )
    marker_id = str(raw.get("marker_id") or "").strip()
    if not marker_id:
        marker_id = _legacy_marker_id(
            step_index=None,
            scan_x=scan_x,
            source_kind=source_kind,
            candidate_index=candidate_index if candidate_index is not None else ordinal,
        )
    marker = {
        "marker_id": marker_id,
        "scan_x": scan_x,
        "requested_x": float(raw.get("requested_x", scan_x)),
        "intensity": float(raw.get("intensity", 0.0) or 0.0),
        "source_kind": source_kind,
    }
    if candidate_index is not None:
        marker["candidate_index"] = candidate_index
    return marker


def normalize_ladder_adjustment_payload(adjustment: dict | None) -> dict | None:
    """Normalize legacy/v2/v3 payloads without inventing missing observations."""
    if not adjustment:
        return None

    if not any(
        key in adjustment
        for key in ("mapping", "mapping_times", "manual_candidates", "markers")
    ):
        legacy_mapping: dict[int, int] = {}
        is_legacy_mapping = bool(adjustment)
        for key, value in adjustment.items():
            try:
                legacy_mapping[int(key)] = int(value)
            except (TypeError, ValueError):
                is_legacy_mapping = False
                break
        if is_legacy_mapping:
            adjustment = {
                "schema_version": LADDER_ADJUSTMENT_SCHEMA_LEGACY,
                "mapping": legacy_mapping,
            }

    mapping = {
        int(key): int(value)
        for key, value in dict(adjustment.get("mapping") or {}).items()
    }
    mapping_times = {
        int(key): float(value)
        for key, value in dict(adjustment.get("mapping_times") or {}).items()
    }
    manual_candidates = [
        float(value) for value in list(adjustment.get("manual_candidates") or [])
    ]
    markers = [
        marker
        for ordinal, raw in enumerate(list(adjustment.get("markers") or []))
        if isinstance(raw, dict)
        and (marker := _normalize_marker(raw, ordinal=ordinal)) is not None
    ]
    marker_ids_in_order = [str(marker["marker_id"]) for marker in markers]
    if len(marker_ids_in_order) != len(set(marker_ids_in_order)):
        raise ValueError("Ladder adjustment contains duplicate marker identities.")
    marker_ids = {str(marker["marker_id"]) for marker in markers}
    marker_id_by_step = {
        int(key): str(value)
        for key, value in dict(adjustment.get("marker_id_by_step") or {}).items()
        if str(value)
    }

    selected_peaks = copy.deepcopy(adjustment.get("selected_peaks") or [])
    if not isinstance(selected_peaks, list):
        selected_peaks = []
    selected_by_step = {
        int(item["step_index"]): item
        for item in selected_peaks
        if isinstance(item, dict) and item.get("step_index") is not None
    }
    for step_index in sorted(set(mapping) | set(mapping_times)):
        selected = selected_by_step.get(step_index, {})
        scan_x = mapping_times.get(step_index, selected.get("observed_time"))
        if scan_x is None:
            continue
        marker_id = str(
            marker_id_by_step.get(step_index)
            or selected.get("marker_id")
            or _legacy_marker_id(
                step_index=step_index,
                scan_x=float(scan_x),
                source_kind=str(selected.get("source_kind") or "legacy"),
                candidate_index=mapping.get(step_index),
            )
        )
        marker_id_by_step[step_index] = marker_id
        if marker_id not in marker_ids:
            source_kind = str(selected.get("source_kind") or "legacy")
            marker = {
                "marker_id": marker_id,
                "scan_x": float(scan_x),
                "requested_x": float(selected.get("requested_x", scan_x)),
                "intensity": float(selected.get("intensity", 0.0) or 0.0),
                "source_kind": source_kind,
            }
            if step_index in mapping:
                marker["candidate_index"] = int(mapping[step_index])
            markers.append(marker)
            marker_ids.add(marker_id)

    expected_steps = [
        float(value) for value in list(adjustment.get("expected_ladder_steps") or [])
    ]
    explicit_mapped = adjustment.get("mapped_step_indices")
    mapped_step_indices = sorted(
        {
            int(value)
            for value in (
                explicit_mapped
                if isinstance(explicit_mapped, (list, tuple))
                else []
            )
        }
        | set(mapping)
        | set(mapping_times)
        | set(marker_id_by_step)
    )
    missing_step_indices_raw = adjustment.get("missing_step_indices")
    if isinstance(missing_step_indices_raw, (list, tuple)):
        missing_step_indices = sorted({int(value) for value in missing_step_indices_raw})
    elif expected_steps:
        missing_step_indices = [
            index for index in range(len(expected_steps)) if index not in mapped_step_indices
        ]
    else:
        missing_step_indices = []

    normalized = {
        "schema_version": str(
            adjustment.get("schema_version") or LADDER_ADJUSTMENT_SCHEMA_LEGACY
        ),
        "mapping": mapping,
        "mapping_times": mapping_times,
        "manual_candidates": manual_candidates,
        "markers": markers,
        "marker_id_by_step": marker_id_by_step,
        "expected_ladder_steps": expected_steps,
        "mapped_step_indices": mapped_step_indices,
        "missing_step_indices": missing_step_indices,
        "partial_mapping": bool(
            adjustment.get("partial_mapping") or missing_step_indices
        ),
    }
    for key in ("source", "analysis", "review", "validation"):
        value = adjustment.get(key)
        if isinstance(value, (dict, list)):
            normalized[key] = copy.deepcopy(value)
    if selected_peaks:
        normalized["selected_peaks"] = selected_peaks
    return normalized
def save_ladder_adjustment(
    fsa: "FsaFile",
    adjustment: dict[int, int] | dict,
    *,
    manual_candidates: list[float] | None = None,
    mapping_times: dict[int, float] | None = None,
    operator: str = "",
    comment: str = "",
    before_qc: dict[str, Any] | None = None,
    after_qc: dict[str, Any] | None = None,
    partial_approved: bool = False,
) -> Path:
    """Save and verify a manual ladder mapping in the internal adjustment store.

    ``partial_approved`` must only be set after an operator explicitly confirms
    that a stable fit using fewer than the expected ladder anchors is acceptable.
    """
    source_path = Path(fsa.file).resolve()
    try:
        if manual_candidates is not None or mapping_times is not None:
            payload = {
                "mapping": {int(k): int(v) for k, v in adjustment.items()},
                "mapping_times": {int(k): float(v) for k, v in (mapping_times or {}).items()},
                "manual_candidates": [float(v) for v in (manual_candidates or [])],
            }
        else:
            payload = normalize_ladder_adjustment_payload(adjustment) or {
                "mapping": {},
                "mapping_times": {},
                "manual_candidates": [],
            }
        mapping_payload = normalize_ladder_adjustment_payload(payload)
        if mapping_payload is None or not (
            mapping_payload["mapping"] or mapping_payload["mapping_times"]
        ):
            raise ValueError("Ladder adjustment has no persisted peak mapping.")

        # NB: expected_ladder_steps/ladder_steps kan være numpy-array
        # fra Ladder Studio-preview — aldri bruk `array or []` her.
        expected_steps_raw = getattr(fsa, "expected_ladder_steps", None)
        if expected_steps_raw is None or len(expected_steps_raw) == 0:
            expected_steps_raw = getattr(fsa, "ladder_steps", None)
        if expected_steps_raw is None:
            expected_steps_raw = []
        expected_steps = [
            float(step) for step in list(expected_steps_raw)
        ]
        mapped_step_indices = sorted(
            set(mapping_payload["mapping"]) | set(mapping_payload["mapping_times"])
        )
        missing_step_indices = [
            index
            for index in range(len(expected_steps))
            if index not in mapped_step_indices
        ]
        markers = copy.deepcopy(mapping_payload.get("markers") or [])
        markers_by_id = {
            str(marker["marker_id"]): marker
            for marker in markers
            if isinstance(marker, dict) and marker.get("marker_id")
        }
        marker_id_by_step = {
            int(key): str(value)
            for key, value in dict(
                mapping_payload.get("marker_id_by_step") or {}
            ).items()
        }
        selected_peaks = []
        for step_index in mapped_step_indices:
            candidate_index = mapping_payload["mapping"].get(step_index)
            observed_time = mapping_payload["mapping_times"].get(step_index)
            marker_id = marker_id_by_step.get(step_index)
            marker = markers_by_id.get(marker_id or "")
            if marker is None and observed_time is not None:
                marker_id = _legacy_marker_id(
                    step_index=step_index,
                    scan_x=float(observed_time),
                    source_kind="legacy",
                    candidate_index=candidate_index,
                )
                marker = {
                    "marker_id": marker_id,
                    "scan_x": float(observed_time),
                    "requested_x": float(observed_time),
                    "intensity": 0.0,
                    "source_kind": "legacy",
                }
                if candidate_index is not None:
                    marker["candidate_index"] = int(candidate_index)
                markers.append(marker)
                markers_by_id[marker_id] = marker
            if marker_id:
                marker_id_by_step[step_index] = marker_id
            selected_peaks.append(
                {
                    "step_index": int(step_index),
                    "candidate_index": (
                        int(candidate_index) if candidate_index is not None else None
                    ),
                    "marker_id": marker_id or "",
                    "source_kind": (
                        str(marker.get("source_kind") or "legacy")
                        if marker is not None
                        else "legacy"
                    ),
                    "expected_bp": (
                        float(expected_steps[step_index])
                        if 0 <= step_index < len(expected_steps)
                        else None
                    ),
                    "observed_time": (
                        float(observed_time) if observed_time is not None else None
                    ),
                    "requested_x": (
                        float(marker.get("requested_x", observed_time))
                        if marker is not None and observed_time is not None
                        else observed_time
                    ),
                }
            )
        try:
            from app_meta import APP_VERSION
        except Exception:
            APP_VERSION = "unknown"

        normalized = normalize_ladder_adjustment_payload(
            {
                "schema_version": LADDER_ADJUSTMENT_SCHEMA_V3,
                "source": {
                    "file_name": source_path.name,
                    "sha256": ladder_adjustment_file_hash(source_path),
                },
                "analysis": {
                    "analysis_id": str(getattr(fsa, "analysis_id", "") or ""),
                    "assay": str(
                        getattr(fsa, "assay", "")
                        or getattr(fsa, "assay_name", "")
                        or ""
                    ),
                    "ladder": str(getattr(fsa, "ladder", "") or ""),
                    "size_standard_channel": str(
                        getattr(fsa, "rust_size_standard_channel", "")
                        or getattr(fsa, "size_standard_channel", "")
                        or ""
                    ),
                },
                "mapping": mapping_payload["mapping"],
                "mapping_times": mapping_payload["mapping_times"],
                "manual_candidates": mapping_payload["manual_candidates"],
                "markers": markers,
                "marker_id_by_step": marker_id_by_step,
                "expected_ladder_steps": expected_steps,
                "mapped_step_indices": mapped_step_indices,
                "missing_step_indices": missing_step_indices,
                "partial_mapping": bool(missing_step_indices),
                "selected_peaks": selected_peaks,
                "review": {
                    "operator": str(operator or ""),
                    "comment": str(comment or ""),
                    "saved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "app_version": str(APP_VERSION),
                    "before_qc": copy.deepcopy(before_qc or {}),
                    "after_qc": copy.deepcopy(after_qc or {}),
                    "partial_approved": bool(
                        missing_step_indices and partial_approved
                    ),
                },
                "validation": {
                    "save_verified": True,
                    "uses_observed_anchors_only": True,
                },
            }
        )
        if normalized is None:
            raise ValueError("Ladder adjustment could not be normalized.")
        from core.ladder_adjustment_store import (
            load_ladder_adjustment_record,
            save_ladder_adjustment_record,
        )

        database_path = save_ladder_adjustment_record(
            source_path,
            normalized,
            ladder=str(getattr(fsa, "ladder", "") or ""),
            size_standard_channel=str(
                getattr(fsa, "rust_size_standard_channel", "")
                or getattr(fsa, "size_standard_channel", "")
                or ""
            ),
        )
        verified = load_ladder_adjustment_record(
            source_path,
            ladder=str(getattr(fsa, "ladder", "") or ""),
            size_standard_channel=str(
                getattr(fsa, "rust_size_standard_channel", "")
                or getattr(fsa, "size_standard_channel", "")
                or ""
            ),
        )
        if (
            verified is None
            or normalize_ladder_adjustment_payload(verified.get("payload"))
            != normalized
        ):
            raise OSError("Saved ladder adjustment could not be verified.")
        legacy_path = source_path.with_suffix(".ladder_adj.json")
        legacy_path.unlink(missing_ok=True)
        _print_green("Saved ladder adjustment in the internal adjustment store.")
        return database_path
    except Exception as e:
        _print_warning(f"Could not save ladder adjustment: {e}")
        raise RuntimeError(f"Could not save ladder adjustment: {e}") from e


def load_ladder_adjustment(fsa: "FsaFile") -> dict | None:
    """Load a manual mapping from the internal store or migrate a legacy sidecar."""
    from core.ladder_adjustment_store import (
        is_ladder_adjustment_deactivated,
        load_ladder_adjustment_record,
        save_ladder_adjustment_record,
    )

    source_path = Path(fsa.file).expanduser()
    ladder = str(getattr(fsa, "ladder", "") or "")
    channel = str(
        getattr(fsa, "rust_size_standard_channel", "")
        or getattr(fsa, "size_standard_channel", "")
        or ""
    )
    stored = load_ladder_adjustment_record(
        source_path,
        ladder=ladder,
        size_standard_channel=channel,
    )
    if stored is not None:
        return normalize_ladder_adjustment_payload(stored.get("payload"))
    if is_ladder_adjustment_deactivated(
        source_path, ladder=ladder, size_standard_channel=channel
    ):
        return None

    candidate_files: list[Path] = [Path(fsa.file)]
    try:
        resolved = Path(fsa.file).resolve()
    except Exception:
        resolved = None
    if resolved is not None and resolved not in candidate_files:
        candidate_files.append(resolved)

    for candidate_file in candidate_files:
        adj_path = candidate_file.with_suffix(".ladder_adj.json")
        if not adj_path.exists():
            continue
        try:
            payload = json.loads(
                adj_path.read_text(encoding="utf-8", errors="replace")
            )
            if isinstance(payload, dict):
                normalized = normalize_ladder_adjustment_payload(payload)
                source = normalized.get("source", {}) if normalized else {}
                expected_hash = str(source.get("sha256") or "")
                current_hash = ladder_adjustment_file_hash(candidate_file)
                if expected_hash and current_hash and expected_hash != current_hash:
                    _print_warning(
                        f"Ignoring ladder adjustment {adj_path.name}: source FSA hash does not match."
                    )
                    continue
                analysis = normalized.get("analysis", {}) if normalized else {}
                expected_ladder = str(analysis.get("ladder") or "").strip().upper()
                current_ladder = str(getattr(fsa, "ladder", "") or "").strip().upper()
                if (
                    expected_ladder
                    and current_ladder
                    and expected_ladder != current_ladder
                ):
                    _print_warning(
                        f"Ignoring ladder adjustment {adj_path.name}: ladder identity does not match."
                    )
                    continue
                expected_channel = str(
                    analysis.get("size_standard_channel") or ""
                ).strip().upper()
                current_channel = str(
                    getattr(fsa, "rust_size_standard_channel", "")
                    or getattr(fsa, "size_standard_channel", "")
                    or ""
                ).strip().upper()
                if (
                    expected_channel
                    and current_channel
                    and expected_channel != current_channel
                ):
                    _print_warning(
                        f"Ignoring ladder adjustment {adj_path.name}: size-standard channel does not match."
                    )
                    continue
                save_ladder_adjustment_record(
                    candidate_file,
                    payload,
                    ladder=ladder,
                    size_standard_channel=channel,
                )
                adj_path.unlink(missing_ok=True)
                return normalized
        except Exception as e:
            _print_warning(f"Could not load ladder adjustment {adj_path.name}: {e}")
    return None


def deactivate_ladder_adjustment(fsa: "FsaFile") -> None:
    """Deactivate this source-content, ladder and channel without touching the FSA.

    The legacy sidecar is retained for audit, but the tombstone prevents its
    reimport. Identical source copies intentionally share the content identity.
    """
    from core.ladder_adjustment_store import deactivate_ladder_adjustment_record

    deactivate_ladder_adjustment_record(
        Path(fsa.file),
        ladder=str(getattr(fsa, "ladder", "") or ""),
        size_standard_channel=str(
            getattr(fsa, "rust_size_standard_channel", "")
            or getattr(fsa, "size_standard_channel", "")
            or ""
        ),
    )
