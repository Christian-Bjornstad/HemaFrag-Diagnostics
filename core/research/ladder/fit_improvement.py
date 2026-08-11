"""Deterministic patient-only cohorts for Rust ladder fitting improvement."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.research.ladder.contracts import ResearchRoots
from core.research.ladder.review_bundle import (
    ReviewBundleResult,
    prepare_blind_review_bundle,
)
from core.research.ladder.round_two import (
    _anchor_deltas,
    _counter,
    _publish_output_pair,
    _round_two_roots,
    _scan_indices,
    _verified_manual_scan_indices,
    _write_temporary_text,
    load_round_two_inputs,
)
from core.analyses.clonality.ladder_review_labels import (
    is_review_fitting_eligible,
    is_review_ml_eligible,
    is_review_resolved,
)
from core.ladder_adjustment_store import load_ladder_adjustment_record


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
    WaveQuota("validation", "control", "LIZ", 41),
    WaveQuota("validation", "control", "ROX", 9),
    WaveQuota("validation", "suspicious", "LIZ", 5),
    WaveQuota("validation", "suspicious", "ROX", 5),
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


@dataclass(frozen=True)
class FitImprovementExperimentResult:
    experiment_dir: Path
    development: ReviewBundleResult
    validation: ReviewBundleResult
    development_withheld_manifest: Path
    validation_withheld_manifest: Path
    experiment_manifest: Path


@dataclass(frozen=True)
class CandidateFreezeResult:
    manifest_path: Path
    binary_path: Path
    binary_sha256: str
    configuration_fingerprint: str
    git_revision: str


@dataclass(frozen=True)
class FitImprovementOutcomeResult:
    wave: str
    outcomes_path: Path
    comparison_path: Path
    total_count: int
    excluded_count: int
    fitting_evaluation_count: int
    ml_eligible_count: int


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


FIT_IMPROVEMENT_PUBLIC_FIELDS = (
    "content_sha256",
    "physical_run_key",
    "year",
    "assay",
    "ladder",
)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prior_review_hashes(workspace: Path, round_one_hashes: set[str]) -> set[str]:
    withheld_path = workspace / "round_2_selection_withheld.json"
    payload = json.loads(withheld_path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or len(cases) != 18:
        raise ValueError("round_2_selection_withheld.json must contain 18 cases")
    round_two_hashes = {
        _normalized_hash(case.get("content_sha256"))
        for case in cases
        if isinstance(case, dict)
    }
    if len(round_two_hashes) != 18 or any(not value for value in round_two_hashes):
        raise ValueError("Round-two cases require 18 unique content hashes")
    return set(round_one_hashes) | round_two_hashes


def _withheld_cases(
    cases: Iterable[FitImprovementCase], final_bundle: Path
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for case in cases:
        result.append(
            {
                **case.as_record(),
                "copied_path": str(
                    final_bundle / "files" / case.case_id / case.file
                ),
            }
        )
    return result


def prepare_fit_improvement_experiment(
    workspace: Path,
    *,
    seed: int = DEFAULT_FIT_IMPROVEMENT_SEED,
    roots: ResearchRoots | None = None,
) -> FitImprovementExperimentResult:
    """Publish development and locked validation waves as one transaction."""

    target = Path(workspace).resolve()
    resolved_roots = _round_two_roots(target, roots)
    experiment_dir = target / "rust_fit_improvement"
    if experiment_dir.exists():
        raise FileExistsError(
            f"Refusing to overwrite fit-improvement experiment: {experiment_dir}"
        )
    diagnostics, inventory, manual_hashes, round_one_hashes = load_round_two_inputs(
        target
    )
    excluded_hashes = _prior_review_hashes(target, round_one_hashes) | manual_hashes
    selection = select_fit_improvement_waves(
        diagnostics,
        inventory,
        excluded_hashes=excluded_hashes,
        seed=seed,
    )

    staging = Path(
        tempfile.mkdtemp(prefix=".rust_fit_improvement-", dir=target)
    )
    final_development = experiment_dir / "development_40"
    final_validation = experiment_dir / "validation_60"
    development_withheld = experiment_dir / "development_selection_withheld.json"
    validation_withheld = experiment_dir / "validation_selection_withheld.json"
    experiment_manifest = experiment_dir / "experiment_manifest.json"
    generated_at = datetime.now(timezone.utc).isoformat()
    try:
        development_result = prepare_blind_review_bundle(
            [case.as_record() for case in selection.development_cases],
            staging / "development_40",
            resolved_roots,
            bundle_name="Blind Ladder Fit Development Review (40)",
            public_case_fields=FIT_IMPROVEMENT_PUBLIC_FIELDS,
            summary_fields={
                "experiment_wave": "development",
                "experiment_root": str(experiment_dir),
            },
            published_bundle_dir=final_development,
        )
        validation_result = prepare_blind_review_bundle(
            [case.as_record() for case in selection.validation_cases],
            staging / "validation_60",
            resolved_roots,
            bundle_name="Blind Ladder Fit Validation Review (60)",
            public_case_fields=FIT_IMPROVEMENT_PUBLIC_FIELDS,
            summary_fields={
                "experiment_wave": "validation",
                "experiment_root": str(experiment_dir),
                "candidate_freeze_manifest": str(
                    experiment_dir / "candidate_freeze_manifest.json"
                ),
            },
            published_bundle_dir=final_validation,
        )
        _write_json(
            staging / "development_selection_withheld.json",
            {
                "schema_version": "1.0",
                "generated_at_utc": generated_at,
                "seed": int(seed),
                "wave": "development",
                "case_count": 40,
                "bundle_dir": str(final_development),
                "cases": _withheld_cases(
                    selection.development_cases, final_development
                ),
            },
        )
        _write_json(
            staging / "validation_selection_withheld.json",
            {
                "schema_version": "1.0",
                "generated_at_utc": generated_at,
                "seed": int(seed),
                "wave": "validation",
                "case_count": 60,
                "bundle_dir": str(final_validation),
                "cases": _withheld_cases(selection.validation_cases, final_validation),
            },
        )
        _write_json(
            staging / "experiment_manifest.json",
            {
                "schema_version": "1.0",
                "generated_at_utc": generated_at,
                "seed": int(seed),
                "development_case_count": 40,
                "validation_case_count": 60,
                "prior_review_hash_count": len(excluded_hashes),
                "candidate_freeze_manifest": str(
                    experiment_dir / "candidate_freeze_manifest.json"
                ),
                "status": "development_review",
            },
        )
        staging.replace(experiment_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(experiment_dir, ignore_errors=True)
        raise

    return FitImprovementExperimentResult(
        experiment_dir=experiment_dir,
        development=development_result,
        validation=validation_result,
        development_withheld_manifest=development_withheld,
        validation_withheld_manifest=validation_withheld,
        experiment_manifest=experiment_manifest,
    )


def freeze_fit_candidate(
    workspace: Path,
    *,
    binary: Path,
    configuration: Mapping[str, Any],
    git_revision: str,
) -> CandidateFreezeResult:
    """Bind validation to one reviewed-development Rust candidate."""

    experiment = Path(workspace).resolve() / "rust_fit_improvement"
    development_outcomes = experiment / "development_outcomes.json"
    value = json.loads(development_outcomes.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or int(value.get("total_count") or 0) != 40:
        raise ValueError("Candidate freeze requires 40 finalized development cases")
    binary_path = Path(binary).resolve()
    if not binary_path.is_file():
        raise FileNotFoundError(f"Candidate Rust binary does not exist: {binary_path}")
    manifest_path = experiment / "candidate_freeze_manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite candidate freeze: {manifest_path}")
    binary_hash = _sha256_file(binary_path)
    configuration_fingerprint = _stable_digest(
        _canonical(dict(configuration))
    )
    payload = {
        "schema_version": "1.0",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "binary_path": str(binary_path),
        "binary_sha256": binary_hash,
        "configuration": dict(configuration),
        "configuration_fingerprint": configuration_fingerprint,
        "git_revision": str(git_revision).strip(),
        "development_outcomes": str(development_outcomes),
        "development_outcomes_sha256": _sha256_file(development_outcomes),
    }
    temporary = manifest_path.with_name(f".{manifest_path.name}.tmp")
    _write_json(temporary, payload)
    os.replace(temporary, manifest_path)
    return CandidateFreezeResult(
        manifest_path=manifest_path,
        binary_path=binary_path,
        binary_sha256=binary_hash,
        configuration_fingerprint=configuration_fingerprint,
        git_revision=str(git_revision).strip(),
    )


def assert_validation_unlocked(workspace: Path) -> dict[str, Any]:
    """Verify that the exact frozen Rust binary still exists unchanged."""

    manifest_path = (
        Path(workspace).resolve()
        / "rust_fit_improvement"
        / "candidate_freeze_manifest.json"
    )
    if not manifest_path.is_file():
        raise ValueError("Validation requires a frozen candidate manifest")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Candidate freeze manifest must be a JSON object")
    configuration = payload.get("configuration")
    expected_configuration_fingerprint = str(
        payload.get("configuration_fingerprint") or ""
    )
    if not isinstance(configuration, dict) or _stable_digest(
        _canonical(configuration)
    ) != expected_configuration_fingerprint:
        raise ValueError("Frozen candidate configuration fingerprint does not match")
    binary = Path(str(payload.get("binary_path") or ""))
    expected_hash = _normalized_hash(payload.get("binary_sha256"))
    if not binary.is_file() or _sha256_file(binary) != expected_hash:
        raise ValueError("Frozen candidate binary SHA-256 does not match")
    development = Path(str(payload.get("development_outcomes") or ""))
    expected_development_hash = _normalized_hash(
        payload.get("development_outcomes_sha256")
    )
    if (
        not development.is_file()
        or _sha256_file(development) != expected_development_hash
    ):
        raise ValueError("Frozen development outcomes SHA-256 does not match")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _wave_quota_counter(wave: str) -> Counter[tuple[str, str]]:
    quotas = DEVELOPMENT_QUOTAS if wave == "development" else VALIDATION_QUOTAS
    return Counter(
        {(quota.cohort_group, quota.ladder): quota.count for quota in quotas}
    )


def _validate_wave_manifest_cases(
    cases: list[dict[str, Any]], *, wave: str, expected_count: int
) -> None:
    if len(cases) != expected_count:
        raise ValueError(
            f"Fit-improvement {wave} finalization requires exactly {expected_count} cases"
        )
    expected_ids = [f"{index:03d}" for index in range(1, expected_count + 1)]
    if [str(case.get("case_id") or "") for case in cases] != expected_ids:
        raise ValueError(f"Fit-improvement {wave} case IDs must be contiguous")
    if any(str(case.get("sample_kind") or "").casefold() != "patient" for case in cases):
        raise ValueError("Fit-improvement finalization requires patient cases only")
    quotas = Counter(
        (
            str(case.get("cohort_group") or "").casefold(),
            _normalized_ladder(case.get("ladder")),
        )
        for case in cases
    )
    if quotas != _wave_quota_counter(wave):
        raise ValueError(f"Fit-improvement {wave} quotas do not match the lock")
    hashes = [_normalized_hash(case.get("content_sha256")) for case in cases]
    runs = [_normalized_run(case.get("physical_run_key")) for case in cases]
    copied = [_path_key(case.get("copied_path")) for case in cases]
    if any(len(value) != 64 for value in hashes) or len(set(hashes)) != expected_count:
        raise ValueError("Fit-improvement cases require unique valid content hashes")
    if not all(runs) or len(set(runs)) != expected_count:
        raise ValueError("Fit-improvement cases require unique physical runs")
    if not all(copied) or len(set(copied)) != expected_count:
        raise ValueError("Fit-improvement cases require unique copied paths")


def _render_wave_comparison(payload: Mapping[str, Any]) -> str:
    lines = [
        f"# Ladder Fit Improvement — {str(payload['wave']).title()} Review",
        "",
        f"Generated: {payload['generated_at_utc']}",
        "",
        "## Denominators",
        "",
        f"- Audit total: {payload['total_count']}",
        f"- Exclusions: {payload['excluded_count']}",
        f"- Fitting evaluation: {payload['fitting_evaluation_count']}",
        f"- ML eligible: {payload['ml_eligible_count']}",
        "",
        "## Review outcomes",
        "",
        "| Label | Count |",
        "|---|---:|",
    ]
    for label, count in payload["counts"]["by_label"].items():
        escaped_label = str(label).replace("|", "\\|")
        lines.append(f"| {escaped_label} | {count} |")
    lines.append("")
    return "\n".join(lines)


def finalize_fit_improvement_wave(
    workspace: Path,
    wave: str,
    *,
    roots: ResearchRoots | None = None,
) -> FitImprovementOutcomeResult:
    """Finalize one fully resolved wave using only contained, hash-locked evidence."""

    normalized_wave = str(wave).strip().casefold()
    if normalized_wave not in {"development", "validation"}:
        raise ValueError("Fit-improvement wave must be development or validation")
    target = Path(workspace).resolve()
    _round_two_roots(target, roots)
    if normalized_wave == "validation":
        assert_validation_unlocked(target)
    expected_count = 40 if normalized_wave == "development" else 60
    experiment = target / "rust_fit_improvement"
    bundle = experiment / (
        "development_40" if normalized_wave == "development" else "validation_60"
    )
    withheld_path = experiment / f"{normalized_wave}_selection_withheld.json"
    payload = json.loads(withheld_path.read_text(encoding="utf-8"))
    cases_value = payload.get("cases") if isinstance(payload, dict) else None
    if (
        not isinstance(cases_value, list)
        or not all(isinstance(case, dict) for case in cases_value)
        or int(payload.get("case_count") or 0) != expected_count
        or str(payload.get("wave") or "").casefold() != normalized_wave
    ):
        raise ValueError(f"Invalid {normalized_wave} withheld manifest")
    cases = [dict(case) for case in cases_value]
    _validate_wave_manifest_cases(
        cases, wave=normalized_wave, expected_count=expected_count
    )
    rows = _read_csv(bundle / "ladder_review_cases.csv")
    if len(rows) != expected_count:
        raise ValueError(f"Fit-improvement {normalized_wave} CSV count does not match")
    rows_by_id = {str(row.get("source_run_dir") or "").strip(): row for row in rows}
    cases_by_id = {str(case.get("case_id") or "").strip(): case for case in cases}
    if (
        "" in rows_by_id
        or len(rows_by_id) != expected_count
        or rows_by_id.keys() != cases_by_id.keys()
    ):
        raise ValueError("Fit-improvement CSV rows do not match withheld cases")
    unresolved = [
        case_id
        for case_id, row in sorted(rows_by_id.items())
        if not is_review_resolved(row.get("label"))
    ]
    if unresolved:
        raise ValueError(
            f"Fit-improvement {normalized_wave} has {len(unresolved)} unresolved cases"
        )

    files_root = (bundle / "files").resolve()
    adjustment_database = bundle / "ladder_adjustments.sqlite3"
    outcomes: list[dict[str, Any]] = []
    for case_id in sorted(rows_by_id):
        row = rows_by_id[case_id]
        case = cases_by_id[case_id]
        copied_path = Path(str(row.get("full_path") or "")).resolve()
        if _path_key(copied_path) != _path_key(case.get("copied_path")):
            raise ValueError(f"Fit-improvement case {case_id} copied path does not match")
        try:
            relative = copied_path.relative_to(files_root)
        except ValueError as exc:
            raise ValueError(
                f"Fit-improvement case {case_id} is outside the bundle"
            ) from exc
        if not relative.parts or relative.parts[0] != case_id or not copied_path.is_file():
            raise ValueError(f"Fit-improvement case {case_id} copy is missing or misplaced")
        expected_hash = _normalized_hash(case.get("content_sha256"))
        if _sha256_file(copied_path) != expected_hash:
            raise ValueError(f"Fit-improvement case {case_id} SHA-256 does not match")
        if (
            str(row.get("file") or "") != copied_path.name
            or str(case.get("file") or "") != copied_path.name
            or _normalized_ladder(row.get("ladder"))
            != _normalized_ladder(case.get("ladder"))
            or str(row.get("assay") or "") != str(case.get("assay") or "")
        ):
            raise ValueError(f"Fit-improvement case {case_id} identity does not match")

        label = str(row.get("label") or "").strip().casefold()
        reviewed_at = str(row.get("reviewed_at_utc") or "").strip()
        if not reviewed_at:
            raise ValueError(f"Fit-improvement case {case_id} requires a timestamp")
        adjustment_path = str(row.get("adjustment_path") or "").strip()
        stored_adjustment = load_ladder_adjustment_record(
            copied_path, database_path=adjustment_database
        )
        has_adjustment = stored_adjustment is not None or copied_path.with_suffix(
            ".ladder_adj.json"
        ).exists()
        rust_scans = _scan_indices(
            case.get("preview_scan_indices"),
            context=f"Fit-improvement case {case_id} Rust preview",
        )
        if label == "manual_adjusted":
            review_scans = _verified_manual_scan_indices(
                copied_path,
                ladder=str(row.get("ladder") or ""),
                database_path=adjustment_database,
                case_id=case_id,
            )
        elif label == "reviewed_no_change":
            if adjustment_path or has_adjustment:
                raise ValueError(
                    f"Fit-improvement case {case_id} has contradictory adjustment evidence"
                )
            expected_steps = 16 if _normalized_ladder(row.get("ladder")) == "LIZ" else 21
            if len(rust_scans) != expected_steps or any(
                right <= left for left, right in zip(rust_scans, rust_scans[1:])
            ):
                raise ValueError(
                    f"Fit-improvement case {case_id} requires a complete Rust ladder"
                )
            review_scans = list(rust_scans)
        elif label == "excluded_missing_ladder_signal":
            if (
                not str(row.get("label_note") or "").strip()
                or adjustment_path
                or has_adjustment
            ):
                raise ValueError(
                    f"Fit-improvement excluded case {case_id} requires a note and no adjustment"
                )
            review_scans = []
        else:
            raise ValueError(f"Unsupported fit-improvement label for case {case_id}")

        outcomes.append(
            {
                "case_id": case_id,
                "content_sha256": expected_hash,
                "physical_run_key": str(case.get("physical_run_key") or ""),
                "sample_kind": "patient",
                "year": str(case.get("year") or ""),
                "assay": str(case.get("assay") or ""),
                "ladder": _normalized_ladder(case.get("ladder")),
                "cohort_group": str(case.get("cohort_group") or ""),
                "failure_signature": str(case.get("reason_signature") or "none"),
                "search_tier": str(case.get("search_tier") or ""),
                "label": label,
                "label_note": str(row.get("label_note") or ""),
                "reviewed_at_utc": reviewed_at,
                "rust_preview_scan_indices": rust_scans,
                "review_scan_indices": review_scans,
                "anchor_deltas": (
                    []
                    if label == "excluded_missing_ladder_signal"
                    else _anchor_deltas(rust_scans, review_scans)
                ),
                "fitting_evaluation_eligible": is_review_fitting_eligible(label),
                "ml_eligible": is_review_ml_eligible(label),
            }
        )

    excluded_count = sum(
        case["label"] == "excluded_missing_ladder_signal" for case in outcomes
    )
    fitting_count = sum(bool(case["fitting_evaluation_eligible"]) for case in outcomes)
    ml_count = sum(bool(case["ml_eligible"]) for case in outcomes)
    result_payload = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "wave": normalized_wave,
        "total_count": expected_count,
        "excluded_count": excluded_count,
        "fitting_evaluation_count": fitting_count,
        "ml_eligible_count": ml_count,
        "counts": {
            "by_label": _counter(case["label"] for case in outcomes),
            "by_ladder": _counter(case["ladder"] for case in outcomes),
            "by_cohort_group": _counter(case["cohort_group"] for case in outcomes),
        },
        "cases": outcomes,
    }
    outcomes_path = experiment / f"{normalized_wave}_outcomes.json"
    comparison_path = experiment / f"{normalized_wave}_comparison.md"
    outcomes_temp = _write_temporary_text(
        outcomes_path,
        json.dumps(result_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    comparison_temp = _write_temporary_text(
        comparison_path, _render_wave_comparison(result_payload)
    )
    _publish_output_pair(
        ((outcomes_temp, outcomes_path), (comparison_temp, comparison_path))
    )
    return FitImprovementOutcomeResult(
        wave=normalized_wave,
        outcomes_path=outcomes_path,
        comparison_path=comparison_path,
        total_count=expected_count,
        excluded_count=excluded_count,
        fitting_evaluation_count=fitting_count,
        ml_eligible_count=ml_count,
    )


def build_approved_fit_gold(
    round_two_outcomes: Mapping[str, Any],
    development_outcomes: Mapping[str, Any],
    approvals: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build hash- and identity-bound fitting gold from explicit approvals."""

    reviewed_by_hash: dict[str, tuple[str, dict[str, Any]]] = {}
    for source, payload in (
        ("round_two_review", round_two_outcomes),
        ("development_review", development_outcomes),
    ):
        cases = payload.get("cases") if isinstance(payload, Mapping) else None
        if not isinstance(cases, list) or not all(
            isinstance(case, Mapping) for case in cases
        ):
            raise ValueError(f"{source} outcomes must contain a cases list")
        for raw_case in cases:
            case = dict(raw_case)
            content_hash = _normalized_hash(case.get("content_sha256"))
            if len(content_hash) != 64:
                raise ValueError(f"{source} outcome requires a valid SHA-256")
            if content_hash in reviewed_by_hash:
                raise ValueError("Reviewed fitting outcomes contain duplicate content")
            reviewed_by_hash[content_hash] = (source, case)

    records: list[dict[str, Any]] = []
    seen_runs: set[str] = set()
    for approval_key, raw_approval in sorted(approvals.items()):
        approval = dict(raw_approval)
        if not bool(approval.get("approved_for_fit_gold")):
            continue
        content_hash = _normalized_hash(approval_key)
        declared_hash = _normalized_hash(approval.get("content_sha256"))
        if len(content_hash) != 64 or declared_hash != content_hash:
            raise ValueError("Fit-gold approval must be joined by matching SHA-256")
        reviewed = reviewed_by_hash.get(content_hash)
        if reviewed is None:
            raise ValueError("Fit-gold approval has no hash-matched reviewed outcome")
        truth_source, case = reviewed
        label = str(case.get("label") or "").strip().casefold()
        if label not in {"manual_adjusted", "reviewed_no_change"} or not bool(
            case.get("fitting_evaluation_eligible")
        ):
            raise ValueError("Fit-gold approval is not a usable reviewed ladder")

        ladder = _normalized_ladder(case.get("ladder"))
        expected_count = 16 if ladder == "LIZ" else 21 if ladder == "ROX" else 0
        raw_scans = case.get("review_scan_indices")
        if not isinstance(raw_scans, list):
            raise ValueError("Fit-gold review sequence must be a list")
        scans = [int(value) for value in raw_scans]
        if (
            expected_count == 0
            or len(scans) != expected_count
            or any(float(value) != int(value) for value in raw_scans)
            or any(right <= left for left, right in zip(scans, scans[1:]))
        ):
            raise ValueError("Fit-gold approval requires a complete ordered ladder")

        path = Path(str(approval.get("path") or "")).expanduser().resolve()
        if not path.is_file() or _sha256_file(path) != content_hash:
            raise ValueError("Fit-gold source bytes do not match approved SHA-256")
        sample_kind = str(
            approval.get("sample_kind") or case.get("sample_kind") or ""
        ).strip().casefold()
        if sample_kind != "patient":
            raise ValueError("Fit-gold approval requires patient clonality data")
        physical_run = _normalized_run(
            approval.get("physical_run_key") or case.get("physical_run_key")
        )
        case_run = _normalized_run(case.get("physical_run_key"))
        if not physical_run or physical_run != case_run:
            raise ValueError("Fit-gold approval physical run does not match review")
        if physical_run in seen_runs:
            raise ValueError("Fit-gold approvals contain a duplicate physical run")
        seen_runs.add(physical_run)
        identity_key = str(approval.get("identity_key") or "").strip()
        reviewed_by = str(approval.get("reviewed_by") or "").strip()
        reviewed_at = str(case.get("reviewed_at_utc") or "").strip()
        if not identity_key or not reviewed_by or not reviewed_at:
            raise ValueError("Fit-gold approval requires bound identity and review provenance")

        records.append(
            {
                "path": str(path),
                "content_sha256": content_hash,
                "physical_run_key": str(case.get("physical_run_key") or ""),
                "identity_key": identity_key,
                "sample_kind": "patient",
                "analysis_id": "clonality",
                "ladder": ladder,
                "expected_scan_indices": scans,
                "failure_family": str(case.get("failure_signature") or ""),
                "truth_source": truth_source,
                "partition": "development_fit_gold",
                "review_label": label,
                "reviewed_at_utc": reviewed_at,
                "reviewed_by": reviewed_by,
                "review_approved": True,
                "gold_eligible": True,
                "approved_for_fit_gold": True,
            }
        )

    if not records:
        raise ValueError("Fit-gold approvals contain no usable reviewed ladders")
    records.sort(key=lambda record: (record["content_sha256"], record["path"]))
    return {
        "schema_version": "hemafrag_approved_fit_gold_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "records": records,
    }
