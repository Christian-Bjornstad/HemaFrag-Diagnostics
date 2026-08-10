"""Deterministic selection for the mixed round-two ladder review cohort."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_ROUND_TWO_SEED = 20260810
FIT_REJECTED_WITH_USABLE_SIGNAL = "fit_rejected_with_usable_signal"
GROUP_REQUIREMENTS = (
    ("suspicious", "LIZ", 6),
    ("suspicious", "ROX", 6),
    ("control", "LIZ", 3),
    ("control", "ROX", 3),
)


@dataclass(frozen=True)
class RoundTwoSelection:
    cases: tuple[dict[str, Any], ...]
    seed: int


def _path_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normcase(str(Path(text).resolve()))


def _normalized_hash(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalized_ladder(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("LIZ"):
        return "LIZ"
    if text.startswith("ROX"):
        return "ROX"
    return text


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)


def _reason_signature(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                value = [text]
        else:
            value = [part for part in text.replace(";", ",").split(",") if part]
    if not isinstance(value, (list, tuple, set)):
        value = []
    reasons = sorted(
        {str(reason).strip().casefold() for reason in value if str(reason).strip()}
    )
    return "|".join(reasons) or "none"


def _tie_break(seed: int, group: str, ladder: str, content_hash: str) -> str:
    payload = f"{seed}|{group}|{ladder}|{content_hash}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _inventory_by_path(
    inventory_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    rows = sorted(inventory_rows, key=_canonical)
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        path = next(
            (
                row.get(column)
                for column in ("resolved_full_path", "raw_path", "source_path", "path")
                if row.get(column)
            ),
            "",
        )
        key = _path_key(path)
        if key:
            result.setdefault(key, row)
    return result


def _candidate_cases(
    diagnostics: Iterable[Mapping[str, Any]],
    inventory_rows: Iterable[Mapping[str, Any]],
    manual_content_hashes: set[str],
    excluded_hashes: set[str],
) -> list[dict[str, Any]]:
    inventory = _inventory_by_path(inventory_rows)
    manual_hashes = {_normalized_hash(value) for value in manual_content_hashes}
    excluded = {_normalized_hash(value) for value in excluded_hashes}
    candidates: list[dict[str, Any]] = []

    for diagnostic in sorted(diagnostics, key=_canonical):
        source_path = str(diagnostic.get("source_path") or "")
        inventory_row = inventory.get(_path_key(source_path))
        if inventory_row is None:
            continue
        content_hash = _normalized_hash(inventory_row.get("content_sha256"))
        physical_run = str(inventory_row.get("physical_run_key") or "").strip()
        ladder = _normalized_ladder(
            diagnostic.get("configured_ladder")
            or diagnostic.get("detected_ladder")
            or inventory_row.get("ladder")
        )
        if (
            not content_hash
            or content_hash in excluded
            or not physical_run
            or ladder not in {"LIZ", "ROX"}
        ):
            continue

        outcome = str(diagnostic.get("outcome") or "").strip().casefold()
        if outcome == FIT_REJECTED_WITH_USABLE_SIGNAL:
            group = "suspicious"
            selection_reason = FIT_REJECTED_WITH_USABLE_SIGNAL
        elif _truthy(diagnostic.get("accepted")) and not _truthy(
            diagnostic.get("review_required")
        ):
            if content_hash in manual_hashes:
                continue
            group = "control"
            selection_reason = "accepted_without_review_or_manual_correction"
        else:
            continue

        path = str(inventory_row.get("raw_path") or source_path)
        candidates.append(
            {
                "path": path,
                "source_path": source_path,
                "file": str(inventory_row.get("file") or Path(path).name),
                "content_sha256": content_hash,
                "physical_run_key": physical_run,
                "year": str(inventory_row.get("year") or "").strip(),
                "assay": str(
                    diagnostic.get("assay") or inventory_row.get("assay") or ""
                ).strip(),
                "ladder": ladder,
                "cohort_group": group,
                "outcome": outcome,
                "reason_signature": _reason_signature(
                    diagnostic.get("reason_codes")
                    or diagnostic.get("archive_reason_codes")
                ),
                "selection_reason": selection_reason,
                "preview_scan_indices": list(
                    diagnostic.get("preview_scan_indices") or []
                ),
            }
        )
    return candidates


def select_round_two_cohort(
    diagnostics: Iterable[Mapping[str, Any]],
    inventory_rows: Iterable[Mapping[str, Any]],
    manual_content_hashes: set[str],
    excluded_hashes: set[str],
    *,
    seed: int = DEFAULT_ROUND_TWO_SEED,
) -> RoundTwoSelection:
    """Select the balanced cohort without depending on input iteration order."""

    candidates = _candidate_cases(
        diagnostics, inventory_rows, manual_content_hashes, excluded_hashes
    )
    selected: list[dict[str, Any]] = []
    used_hashes: set[str] = set()
    used_runs: set[str] = set()
    year_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    assay_counts: Counter[str] = Counter()

    for group, ladder, required_count in GROUP_REQUIREMENTS:
        pool = [
            candidate
            for candidate in candidates
            if candidate["cohort_group"] == group and candidate["ladder"] == ladder
        ]
        for _ in range(required_count):
            available = [
                candidate
                for candidate in pool
                if candidate["content_sha256"] not in used_hashes
                and candidate["physical_run_key"] not in used_runs
            ]
            if not available:
                raise ValueError(
                    f"Insufficient unique candidates for {group} {ladder}: "
                    f"required {required_count}"
                )
            choice = min(
                available,
                key=lambda candidate: (
                    year_counts[candidate["year"]],
                    reason_counts[candidate["reason_signature"]],
                    assay_counts[candidate["assay"]],
                    _tie_break(
                        int(seed), group, ladder, candidate["content_sha256"]
                    ),
                    _canonical(candidate),
                ),
            )
            selected.append(choice)
            used_hashes.add(choice["content_sha256"])
            used_runs.add(choice["physical_run_key"])
            year_counts[choice["year"]] += 1
            reason_counts[choice["reason_signature"]] += 1
            assay_counts[choice["assay"]] += 1

    if len({case["year"] for case in selected}) < 2:
        raise ValueError("Round-two cohort must cover at least two years")
    return RoundTwoSelection(cases=tuple(selected), seed=int(seed))


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size <= 1:
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_round_two_inputs(
    workspace: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], set[str]]:
    """Load selector inputs from an existing ladder research workspace."""

    root = Path(workspace).resolve()
    diagnostics: list[dict[str, Any]] = []
    for line in (root / "diagnostics.ndjson").read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("Each diagnostics.ndjson record must be an object")
            diagnostics.append(value)

    inventory_rows = _read_csv(root / "inventory.csv")
    corrections = _read_csv(root / "manual_corrections.csv")
    manual_hashes = {
        content_hash
        for row in corrections
        if (content_hash := _normalized_hash(row.get("source_sha256")))
    }

    manifest = json.loads(
        (root / "development_manifest.json").read_text(encoding="utf-8")
    )
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list):
        raise ValueError("development_manifest.json must contain a files list")
    excluded_hashes = {
        content_hash
        for row in files
        if isinstance(row, dict)
        and (content_hash := _normalized_hash(row.get("content_sha256")))
    }
    if len(excluded_hashes) != 3:
        raise ValueError(
            "development_manifest.json must contain exactly three round-one hashes"
        )
    return diagnostics, inventory_rows, manual_hashes, excluded_hashes
