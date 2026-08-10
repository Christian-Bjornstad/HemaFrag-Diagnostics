"""Normalize historical manual ladder corrections without modifying them."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .contracts import MANUAL_CORRECTION_SCHEMA_VERSION, ResearchRoots, assert_allowed_raw_path


LADDER_STEP_COUNTS = {"LIZ": 16, "ROX": 21}


@dataclass(frozen=True)
class ManualCorrectionRecord:
    sidecar_path: Path
    source_path: Path
    schema_kind: str
    schema_version: str
    source_sha256: str
    declared_source_sha256: str
    ladder: str
    channel: str
    assay: str
    selected_steps: tuple[int, ...]
    selected_times: tuple[float, ...]
    expected_bp: tuple[float, ...]
    expected_step_count: int | None
    complete: bool
    monotonic: bool
    hash_matches: bool | None
    save_verified: bool | None
    operator: str
    reviewed_at_utc: str
    gold_eligible: bool
    issue_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["sidecar_path"] = str(self.sidecar_path)
        value["source_path"] = str(self.source_path)
        value["selected_steps"] = list(self.selected_steps)
        value["selected_times"] = list(self.selected_times)
        value["expected_bp"] = list(self.expected_bp)
        value["issue_codes"] = list(self.issue_codes)
        return value


@dataclass(frozen=True)
class ManualEvidenceResult:
    evidence: pd.DataFrame
    issues: pd.DataFrame
    summary: dict[str, Any]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_ladder(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("LIZ"):
        return "LIZ"
    if text.startswith("ROX"):
        return "ROX"
    return text


def _integer_keys(mapping: Any) -> tuple[int, ...]:
    if not isinstance(mapping, dict):
        return ()
    return tuple(sorted(int(key) for key in mapping))


def parse_adjustment_sidecar(
    sidecar_path: Path,
    matching_fsa: Path,
    *,
    expected_ladder: str | None = None,
    expected_step_count: int | None = None,
) -> ManualCorrectionRecord:
    """Parse one legacy or v2 sidecar into a provenance-rich record."""

    sidecar = Path(sidecar_path).resolve()
    source = Path(matching_fsa).resolve()
    payload = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Adjustment payload must be a JSON object: {sidecar}")

    schema_value = str(payload.get("schema_version") or "")
    is_v2 = schema_value == "hemafrag_ladder_adjustment_v2"
    schema_kind = "v2" if is_v2 else "legacy"
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    source_meta = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}

    selected_steps = _integer_keys(payload.get("mapping"))
    mapping_times = payload.get("mapping_times")
    mapping_times = mapping_times if isinstance(mapping_times, dict) else {}
    selected_times = tuple(
        float(mapping_times[str(step)])
        for step in selected_steps
        if str(step) in mapping_times
    )
    selected_peaks = payload.get("selected_peaks")
    selected_peaks = selected_peaks if isinstance(selected_peaks, list) else []
    expected_by_step = {
        int(peak["step_index"]): float(peak["expected_bp"])
        for peak in selected_peaks
        if isinstance(peak, dict)
        and "step_index" in peak
        and "expected_bp" in peak
    }
    expected_bp = tuple(
        expected_by_step[step] for step in selected_steps if step in expected_by_step
    )

    source_hash = _sha256_file(source)
    declared_hash = str(source_meta.get("sha256") or "")
    hash_matches = (declared_hash == source_hash) if is_v2 else None
    ladder = (
        _normalize_ladder(analysis.get("ladder"))
        if is_v2
        else _normalize_ladder(expected_ladder)
    )
    channel = str(analysis.get("size_standard_channel") or "") if is_v2 else ""
    assay = str(analysis.get("assay") or "") if is_v2 else ""
    standard_count = LADDER_STEP_COUNTS.get(ladder)
    configured_count = standard_count if is_v2 else expected_step_count
    complete = bool(
        configured_count
        and selected_steps == tuple(range(configured_count))
        and len(selected_times) == configured_count
    )
    monotonic = len(selected_times) == len(selected_steps) and all(
        later > earlier for earlier, later in zip(selected_times, selected_times[1:])
    )
    save_verified = bool(validation.get("save_verified")) if is_v2 else None

    issues: list[str] = []
    if len(selected_times) != len(selected_steps):
        issues.append("mapping_time_missing")
    if not monotonic:
        issues.append("non_monotonic_times")
    if not complete:
        issues.append("partial_mapping")
    if is_v2:
        if not declared_hash:
            issues.append("source_hash_missing")
        elif not hash_matches:
            issues.append("source_hash_mismatch")
        if ladder not in LADDER_STEP_COUNTS:
            issues.append("unknown_ladder")
        if not save_verified:
            issues.append("save_not_verified")
    else:
        if not expected_ladder or expected_step_count is None:
            issues.append("legacy_configuration_missing")
        elif standard_count != expected_step_count:
            issues.append("legacy_configuration_conflict")

    gold_eligible = not issues
    return ManualCorrectionRecord(
        sidecar_path=sidecar,
        source_path=source,
        schema_kind=schema_kind,
        schema_version=schema_value or "legacy_unversioned",
        source_sha256=source_hash,
        declared_source_sha256=declared_hash,
        ladder=ladder,
        channel=channel,
        assay=assay,
        selected_steps=selected_steps,
        selected_times=selected_times,
        expected_bp=expected_bp,
        expected_step_count=configured_count,
        complete=complete,
        monotonic=monotonic,
        hash_matches=hash_matches,
        save_verified=save_verified,
        operator=str(review.get("operator") or ""),
        reviewed_at_utc=str(review.get("saved_at_utc") or ""),
        gold_eligible=gold_eligible,
        issue_codes=tuple(issues),
    )


def _find_matching_fsa(sidecar: Path) -> Path | None:
    suffix = ".ladder_adj.json"
    source_name = sidecar.name[: -len(suffix)] + ".fsa"
    for candidate in sidecar.parent.iterdir():
        if candidate.is_file() and candidate.name.casefold() == source_name.casefold():
            return candidate
    return None


def _configuration_lookup(inventory: Any) -> dict[str, tuple[str, int | None]]:
    if inventory is None or not hasattr(inventory, "tracking"):
        return {}
    tracking = inventory.tracking
    if tracking.empty or "IdentityKey" not in tracking.columns:
        return {}
    lookup: dict[str, tuple[str, int | None]] = {}
    for row in tracking.to_dict(orient="records"):
        identity = str(row.get("IdentityKey") or "")
        if not identity:
            continue
        raw_count = row.get("LadderExpectedStepCount")
        count = None if pd.isna(raw_count) else int(raw_count)
        lookup[identity] = (str(row.get("Ladder") or ""), count)
    return lookup


def discover_adjustments(
    roots: ResearchRoots, inventory: Any | None = None
) -> list[ManualCorrectionRecord]:
    """Discover real sidecars in allowed raw roots, excluding AppleDouble files."""

    configuration = _configuration_lookup(inventory)
    records: list[ManualCorrectionRecord] = []
    for raw_root in roots.raw_roots:
        if not raw_root.exists():
            continue
        for sidecar in sorted(
            raw_root.rglob("*.ladder_adj.json"), key=lambda path: str(path).casefold()
        ):
            if sidecar.name.startswith("._"):
                continue
            safe_sidecar = assert_allowed_raw_path(sidecar, roots)
            source = _find_matching_fsa(safe_sidecar)
            if source is None:
                continue
            safe_source = assert_allowed_raw_path(source, roots)
            identity = f"{safe_source.parent.name}::{safe_source.name}"
            ladder, expected_count = configuration.get(identity, ("", None))
            records.append(
                parse_adjustment_sidecar(
                    safe_sidecar,
                    safe_source,
                    expected_ladder=ladder or None,
                    expected_step_count=expected_count,
                )
            )
    return records


def _path_key(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).resolve()))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def reconcile_manual_evidence(
    records: Iterable[ManualCorrectionRecord],
    review_cases: pd.DataFrame,
    tracking: pd.DataFrame,
) -> ManualEvidenceResult:
    """Reconcile sidecars with archived labels and workbook consumption evidence."""

    sidecars = list(records)
    source_keys = {_path_key(record.source_path) for record in sidecars}
    identity_keys = {
        f"{record.source_path.parent.name}::{record.source_path.name}" for record in sidecars
    }
    evidence: list[dict[str, Any]] = [
        {
            "evidence_kind": "sidecar",
            "record_key": str(record.source_path),
            "sidecar_path": str(record.sidecar_path),
            "gold_eligible": record.gold_eligible,
        }
        for record in sidecars
    ]
    issues: list[dict[str, str]] = []

    if not review_cases.empty:
        for row in review_cases.to_dict(orient="records"):
            if str(row.get("label") or "").strip().casefold() != "manual_adjusted":
                continue
            resolved = str(row.get("resolved_full_path") or row.get("full_path") or "")
            evidence.append(
                {
                    "evidence_kind": "annotation",
                    "record_key": resolved,
                    "sidecar_path": str(row.get("adjustment_path") or ""),
                    "gold_eligible": False,
                }
            )
            if not resolved or _path_key(resolved) not in source_keys:
                issues.append(
                    {
                        "issue_code": "annotation_sidecar_missing",
                        "record_key": resolved,
                        "detail": "Manual-adjusted annotation has no surviving imported sidecar.",
                    }
                )

    if not tracking.empty and "ManualAdjustmentUsed" in tracking.columns:
        for row in tracking.to_dict(orient="records"):
            if not _truthy(row.get("ManualAdjustmentUsed")):
                continue
            identity = str(row.get("IdentityKey") or "")
            evidence.append(
                {
                    "evidence_kind": "workbook",
                    "record_key": identity,
                    "sidecar_path": "",
                    "gold_eligible": False,
                }
            )
            if identity not in identity_keys:
                issues.append(
                    {
                        "issue_code": "workbook_manual_without_sidecar",
                        "record_key": identity,
                        "detail": "Workbook records manual use but no imported sidecar matches the identity.",
                    }
                )

    evidence_frame = pd.DataFrame.from_records(
        evidence,
        columns=("evidence_kind", "record_key", "sidecar_path", "gold_eligible"),
    )
    issues_frame = pd.DataFrame.from_records(
        issues, columns=("issue_code", "record_key", "detail")
    )
    summary = {
        "schema_version": MANUAL_CORRECTION_SCHEMA_VERSION,
        "sidecar_record_count": len(sidecars),
        "gold_eligible_sidecar_count": sum(record.gold_eligible for record in sidecars),
        "evidence_count": len(evidence_frame),
        "issue_count": len(issues_frame),
    }
    return ManualEvidenceResult(evidence_frame, issues_frame, summary)
