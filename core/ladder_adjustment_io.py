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


def normalize_ladder_adjustment_payload(adjustment: dict | None) -> dict | None:
    """Normalizes legacy and enriched ladder adjustment payloads."""
    if not adjustment:
        return None

    if "mapping" in adjustment or "mapping_times" in adjustment or "manual_candidates" in adjustment:
        mapping_raw = adjustment.get("mapping", {})
        mapping_times_raw = adjustment.get("mapping_times", {})
        manual_candidates_raw = adjustment.get("manual_candidates", [])
        normalized = {
            "mapping": {int(k): int(v) for k, v in mapping_raw.items()},
            "mapping_times": {int(k): float(v) for k, v in mapping_times_raw.items()},
            "manual_candidates": [float(v) for v in manual_candidates_raw],
        }
        if adjustment.get("schema_version"):
            normalized["schema_version"] = str(adjustment["schema_version"])
        else:
            normalized["schema_version"] = LADDER_ADJUSTMENT_SCHEMA_LEGACY
        for key in ("source", "analysis", "selected_peaks", "review", "validation"):
            value = adjustment.get(key)
            if isinstance(value, (dict, list)):
                normalized[key] = copy.deepcopy(value)
        return normalized

    return {
        "schema_version": LADDER_ADJUSTMENT_SCHEMA_LEGACY,
        "mapping": {int(k): int(v) for k, v in adjustment.items()},
        "mapping_times": {},
        "manual_candidates": [],
    }


# Backwards-compatible private alias (historically lived in core.analysis).
_normalize_ladder_adjustment_payload = normalize_ladder_adjustment_payload


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
) -> Path:
    """Save and verify a manual ladder mapping in the internal adjustment store."""
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
        selected_peaks = []
        for step_index, candidate_index in sorted(mapping_payload["mapping"].items()):
            observed_time = mapping_payload["mapping_times"].get(step_index)
            selected_peaks.append(
                {
                    "step_index": int(step_index),
                    "candidate_index": int(candidate_index),
                    "expected_bp": (
                        float(expected_steps[step_index])
                        if 0 <= step_index < len(expected_steps)
                        else None
                    ),
                    "observed_time": (
                        float(observed_time) if observed_time is not None else None
                    ),
                }
            )
        try:
            from app_meta import APP_VERSION
        except Exception:
            APP_VERSION = "unknown"

        normalized = {
            "schema_version": LADDER_ADJUSTMENT_SCHEMA_V2,
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
            "selected_peaks": selected_peaks,
            "review": {
                "operator": str(operator or ""),
                "comment": str(comment or ""),
                "saved_at_utc": datetime.now(timezone.utc).isoformat(),
                "app_version": str(APP_VERSION),
                "before_qc": copy.deepcopy(before_qc or {}),
                "after_qc": copy.deepcopy(after_qc or {}),
            },
            "validation": {
                "save_verified": True,
            },
        }
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
