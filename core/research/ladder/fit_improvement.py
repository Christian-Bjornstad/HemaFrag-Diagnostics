"""Deterministic patient-only cohorts for Rust ladder fitting improvement."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_FIT_IMPROVEMENT_SEED = 20260811
FIT_REJECTED_WITH_USABLE_SIGNAL = "fit_rejected_with_usable_signal"
SELECTION_DOMAIN = "fit-improvement-v1"
BLIND_ORDER_DOMAIN = "fit-improvement-public-order-v1"


@dataclass(frozen=True)
class WaveQuota:
    wave: str
    cohort_group: str
    ladder: str
    count: int


DEVELOPMENT_QUOTAS = (
    WaveQuota("development", "control", "LIZ", 25),
    WaveQuota("development", "control", "ROX", 8),
    WaveQuota("development", "suspicious", "LIZ", 3),
    WaveQuota("development", "suspicious", "ROX", 4),
)
VALIDATION_QUOTAS = (
    WaveQuota("validation", "control", "LIZ", 40),
    WaveQuota("validation", "control", "ROX", 9),
    WaveQuota("validation", "suspicious", "LIZ", 5),
    WaveQuota("validation", "suspicious", "ROX", 6),
)
ALL_QUOTAS = (*DEVELOPMENT_QUOTAS, *VALIDATION_QUOTAS)


@dataclass(frozen=True)
class FitImprovementCase:
    wave: str
    case_id: str
    path: str
    source_path: str
    file: str
    content_sha256: str
    physical_run_key: str
    sample_kind: str
    year: str
    assay: str
    ladder: str
    cohort_group: str
    outcome: str
    reason_signature: str
    selection_reason: str
    search_tier: str
    preview_scan_indices: tuple[int, ...]

    def as_record(self) -> dict[str, Any]:
        record = dict(self.__dict__)
        record["preview_scan_indices"] = list(self.preview_scan_indices)
        return record


@dataclass(frozen=True)
class FitImprovementSelection:
    cases: tuple[FitImprovementCase, ...]
    seed: int

    @property
    def development_cases(self) -> tuple[FitImprovementCase, ...]:
        return tuple(case for case in self.cases if case.wave == "development")

    @property
    def validation_cases(self) -> tuple[FitImprovementCase, ...]:
        return tuple(case for case in self.cases if case.wave == "validation")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _path_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normcase(str(Path(text).resolve()))


def _normalized_hash(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalized_run(value: Any) -> str:
    return str(value or "").strip().casefold()


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
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


def _reason_signature(value: Any) -> str:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split("|") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        parts = [str(part).strip() for part in value if str(part).strip()]
    else:
        parts = []
    return "|".join(sorted(set(parts))) or "none"


def _stable_digest(*parts: Any) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _inventory_by_path(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
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
    excluded_hashes: set[str],
) -> list[FitImprovementCase]:
    inventory = _inventory_by_path(inventory_rows)
    excluded = {_normalized_hash(value) for value in excluded_hashes}
    candidates: list[FitImprovementCase] = []

    for diagnostic in sorted(diagnostics, key=_canonical):
        source_path = str(diagnostic.get("source_path") or "")
        inventory_row = inventory.get(_path_key(source_path))
        if inventory_row is None:
            continue
        sample_kind = str(inventory_row.get("sample_kind") or "").strip().casefold()
        if sample_kind != "patient":
            continue
        content_hash = _normalized_hash(inventory_row.get("content_sha256"))
        diagnostic_hash = _normalized_hash(diagnostic.get("source_sha256"))
        if diagnostic_hash != content_hash:
            raise ValueError(
                "Fit-improvement diagnostic/inventory SHA-256 mismatch for "
                f"{source_path}"
            )
        physical_run = str(inventory_row.get("physical_run_key") or "").strip()
        year = str(inventory_row.get("year") or "").strip()
        ladder = _normalized_ladder(
            diagnostic.get("configured_ladder")
            or diagnostic.get("detected_ladder")
            or inventory_row.get("ladder")
        )
        if (
            not content_hash
            or content_hash in excluded
            or not physical_run
            or not year
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
            group = "control"
            selection_reason = "accepted_without_review"
        else:
            continue

        path = str(inventory_row.get("raw_path") or source_path)
        candidates.append(
            FitImprovementCase(
                wave="",
                case_id="",
                path=path,
                source_path=source_path,
                file=str(inventory_row.get("file") or Path(path).name),
                content_sha256=content_hash,
                physical_run_key=physical_run,
                sample_kind=sample_kind,
                year=year,
                assay=str(
                    diagnostic.get("assay") or inventory_row.get("assay") or ""
                ).strip(),
                ladder=ladder,
                cohort_group=group,
                outcome=outcome,
                reason_signature=_reason_signature(
                    diagnostic.get("reason_codes")
                    or diagnostic.get("archive_reason_codes")
                ),
                selection_reason=selection_reason,
                search_tier=str(diagnostic.get("search_tier") or "").strip(),
                preview_scan_indices=tuple(
                    int(value) for value in diagnostic.get("preview_scan_indices") or ()
                ),
            )
        )
    return candidates


def _pick_diverse(
    candidates: list[FitImprovementCase],
    count: int,
    *,
    seed: int,
    domain: str,
) -> list[FitImprovementCase]:
    remaining = list(candidates)
    selected: list[FitImprovementCase] = []
    year_counts: Counter[str] = Counter()
    assay_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    tier_counts: Counter[str] = Counter()
    while remaining and len(selected) < count:
        remaining.sort(
            key=lambda case: (
                year_counts[case.year],
                not bool(case.assay),
                assay_counts[case.assay],
                case.reason_signature == "none",
                reason_counts[case.reason_signature],
                not bool(case.search_tier),
                tier_counts[case.search_tier],
                _stable_digest(
                    SELECTION_DOMAIN,
                    seed,
                    domain,
                    case.content_sha256,
                ),
                case.content_sha256,
            )
        )
        choice = remaining.pop(0)
        selected.append(choice)
        year_counts[choice.year] += 1
        assay_counts[choice.assay] += 1
        reason_counts[choice.reason_signature] += 1
        tier_counts[choice.search_tier] += 1
    return selected


def _blind_order(
    cases: Iterable[FitImprovementCase], *, wave: str, seed: int
) -> tuple[FitImprovementCase, ...]:
    ordered = sorted(
        cases,
        key=lambda case: (
            _stable_digest(
                BLIND_ORDER_DOMAIN, seed, wave, case.content_sha256
            ),
            case.content_sha256,
        ),
    )
    return tuple(
        replace(case, wave=wave, case_id=f"{index:03d}")
        for index, case in enumerate(ordered, 1)
    )


def select_fit_improvement_waves(
    diagnostics: Iterable[Mapping[str, Any]],
    inventory_rows: Iterable[Mapping[str, Any]],
    *,
    excluded_hashes: set[str],
    seed: int = DEFAULT_FIT_IMPROVEMENT_SEED,
) -> FitImprovementSelection:
    """Select both waves jointly with global content/run isolation."""

    numeric_seed = int(seed)
    candidates = _candidate_cases(diagnostics, inventory_rows, excluded_hashes)
    required_by_group = Counter()
    for quota in ALL_QUOTAS:
        required_by_group[(quota.cohort_group, quota.ladder)] += quota.count

    for (group, ladder), required in required_by_group.items():
        available = sum(
            case.cohort_group == group and case.ladder == ladder
            for case in candidates
        )
        if available < required:
            raise ValueError(
                f"Insufficient unique candidates for {group} {ladder}: "
                f"required {required}"
            )

    run_groups: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for case in candidates:
        run_groups[_normalized_run(case.physical_run_key)].add(
            (case.cohort_group, case.ladder)
        )

    selected_by_group: dict[tuple[str, str], list[FitImprovementCase]] = {}
    used_hashes: set[str] = set()
    used_runs: set[str] = set()
    group_order = sorted(
        required_by_group,
        key=lambda key: (
            len(
                {
                    _normalized_run(case.physical_run_key)
                    for case in candidates
                    if (case.cohort_group, case.ladder) == key
                }
            ),
            key,
        ),
    )
    for group, ladder in group_order:
        required = required_by_group[(group, ladder)]
        pool = [
            case
            for case in candidates
            if case.cohort_group == group
            and case.ladder == ladder
            and case.content_sha256 not in used_hashes
            and _normalized_run(case.physical_run_key) not in used_runs
        ]
        best_per_run: dict[str, FitImprovementCase] = {}
        for case in sorted(
            pool,
            key=lambda value: (
                len(run_groups[_normalized_run(value.physical_run_key)]) > 1,
                _stable_digest(
                    SELECTION_DOMAIN,
                    numeric_seed,
                    group,
                    ladder,
                    value.content_sha256,
                ),
                value.content_sha256,
            ),
        ):
            best_per_run.setdefault(_normalized_run(case.physical_run_key), case)
        chosen = _pick_diverse(
            list(best_per_run.values()),
            required,
            seed=numeric_seed,
            domain=f"total|{group}|{ladder}",
        )
        if len(chosen) != required:
            raise ValueError(
                "Insufficient globally disjoint candidates for fit-improvement quotas"
            )
        selected_by_group[(group, ladder)] = chosen
        used_hashes.update(case.content_sha256 for case in chosen)
        used_runs.update(_normalized_run(case.physical_run_key) for case in chosen)

    wave_cases: dict[str, list[FitImprovementCase]] = {
        "development": [],
        "validation": [],
    }
    for group, ladder in sorted(required_by_group):
        group_cases = selected_by_group[(group, ladder)]
        development_count = next(
            quota.count
            for quota in DEVELOPMENT_QUOTAS
            if quota.cohort_group == group and quota.ladder == ladder
        )
        development = _pick_diverse(
            group_cases,
            development_count,
            seed=numeric_seed,
            domain=f"development|{group}|{ladder}",
        )
        development_hashes = {case.content_sha256 for case in development}
        validation = [
            case for case in group_cases if case.content_sha256 not in development_hashes
        ]
        wave_cases["development"].extend(development)
        wave_cases["validation"].extend(validation)

    development = _blind_order(
        wave_cases["development"], wave="development", seed=numeric_seed
    )
    validation = _blind_order(
        wave_cases["validation"], wave="validation", seed=numeric_seed
    )
    return FitImprovementSelection(
        cases=(*development, *validation),
        seed=numeric_seed,
    )
