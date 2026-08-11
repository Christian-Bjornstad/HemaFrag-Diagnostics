"""Deterministic selection for the mixed round-two ladder review cohort."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.analyses.clonality.ladder_review_labels import (
    is_review_fitting_eligible,
    is_review_ml_eligible,
    is_review_resolved,
)
from core.ladder_adjustment_store import load_ladder_adjustment_record
from core.research.ladder.contracts import (
    ResearchRoots,
    assert_canonical_production_roots,
    assert_canonical_production_workspace,
)
from core.research.ladder.review_bundle import prepare_blind_review_bundle


DEFAULT_ROUND_TWO_SEED = 20260810
FIT_REJECTED_WITH_USABLE_SIGNAL = "fit_rejected_with_usable_signal"
BLIND_ORDER_DOMAIN = "round-two-public-order-v1"
GROUP_REQUIREMENTS = (
    ("suspicious", "LIZ", 6),
    ("suspicious", "ROX", 6),
    ("control", "LIZ", 3),
    ("control", "ROX", 3),
)
ROUND_TWO_CASE_COUNT = sum(required for _group, _ladder, required in GROUP_REQUIREMENTS)
ROUND_TWO_EXPECTED_STEP_COUNTS = {"LIZ": 16, "ROX": 21}
MIN_DIVERSITY = 2
ROUND_TWO_BUNDLE_NAME = "Blind Ladder Round-Two Review"
ROUND_TWO_PUBLIC_CASE_FIELDS = (
    "content_sha256",
    "physical_run_key",
    "year",
    "assay",
    "ladder",
)
ROUND_TWO_LADDER_ALIASES = {
    "LIZ": ("LIZ", "LIZ500_250"),
    "ROX": ("ROX", "ROX400HD"),
}


@dataclass(frozen=True)
class RoundTwoSelection:
    cases: tuple[dict[str, Any], ...]
    seed: int


@dataclass(frozen=True)
class RoundTwoReviewResult:
    bundle_dir: Path
    case_count: int
    adjustment_database: Path
    withheld_manifest: Path


@dataclass(frozen=True)
class RoundTwoOutcomeResult:
    outcomes_path: Path
    comparison_path: Path
    total_count: int
    excluded_count: int
    fitting_evaluation_count: int
    ml_eligible_count: int


def classify_controller_supplied_round_two_migration(
    selection_cases: Iterable[Mapping[str, Any]],
    supplied_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize controller-provided legacy evidence without reading source paths.

    Every row is joined exclusively by content SHA-256. Migrated evidence always
    requires a fresh review and is never directly eligible for gold data.
    """

    selected = [dict(case) for case in selection_cases]
    selected_hashes = [_normalized_hash(case.get("content_sha256")) for case in selected]
    if any(not _is_sha256(value) for value in selected_hashes) or len(
        set(selected_hashes)
    ) != len(selected_hashes):
        raise ValueError("Selection cases require unique SHA-256 content hashes")

    supplied_by_hash: dict[str, Mapping[str, Any]] = {}
    for row in supplied_rows:
        content_hash = _normalized_hash(row.get("content_sha256"))
        if not _is_sha256(content_hash) or content_hash in supplied_by_hash:
            raise ValueError(
                "Controller-supplied rows require unique SHA-256 content hashes"
            )
        supplied_by_hash[content_hash] = row
    if set(supplied_by_hash) != set(selected_hashes):
        raise ValueError(
            "Controller-supplied hashes must exactly match the selected case hashes"
        )

    result: list[dict[str, Any]] = []
    for case, content_hash in zip(selected, selected_hashes):
        supplied = supplied_by_hash[content_hash]
        label = str(supplied.get("label") or "").strip().casefold()
        if label in {"manual_adjusted", "reviewed_no_change"}:
            classification = "resolved_decision_evidence"
        elif not label:
            classification = "excluded_error_evidence"
        else:
            raise ValueError(
                f"Unsupported controller-supplied review label for {content_hash}: {label}"
            )
        result.append(
            {
                "case_id": str(case.get("case_id") or ""),
                "content_sha256": content_hash,
                "label": label,
                "label_note": str(supplied.get("label_note") or ""),
                "source_reviewed_at_utc": str(
                    supplied.get("reviewed_at_utc") or ""
                ),
                "evidence_classification": classification,
                "requires_re_review": True,
                "gold_eligible": False,
            }
        )
    return result


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


def _normalized_run_key(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").casefold()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        sample_kind = str(
            inventory_row.get("sample_kind")
            or inventory_row.get("SampleKind")
            or ""
        ).strip().casefold()
        if sample_kind != "patient":
            continue
        content_hash = _normalized_hash(inventory_row.get("content_sha256"))
        diagnostic_hash = _normalized_hash(diagnostic.get("source_sha256"))
        if diagnostic_hash != content_hash:
            raise ValueError(
                "Round-two diagnostic/inventory SHA-256 mismatch for "
                f"{source_path}"
            )
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
                "sample_kind": sample_kind,
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


def _diversity_values(
    cases: Iterable[Mapping[str, Any]],
) -> tuple[set[str], set[str], set[str], set[str]]:
    case_list = list(cases)
    years = {str(case["year"]) for case in case_list if str(case["year"]).strip()}
    control_years = {
        str(case["year"])
        for case in case_list
        if case["cohort_group"] == "control" and str(case["year"]).strip()
    }
    reasons = {
        str(case["reason_signature"])
        for case in case_list
        if case["cohort_group"] == "suspicious"
        and str(case["reason_signature"]).strip()
        and case["reason_signature"] != "none"
    }
    assays = {str(case["assay"]) for case in case_list if str(case["assay"]).strip()}
    return years, control_years, reasons, assays


def _diversity_failures(cases: Iterable[Mapping[str, Any]]) -> list[str]:
    values = _diversity_values(cases)
    names = ("year", "control year", "reason", "assay")
    return [
        name for name, dimension in zip(names, values) if len(dimension) < MIN_DIVERSITY
    ]


def _joint_selection(
    candidates: list[dict[str, Any]],
    *,
    seed: int,
    require_diversity: bool,
) -> tuple[dict[str, Any], ...] | None:
    pools = [
        sorted(
            (
                candidate
                for candidate in candidates
                if candidate["cohort_group"] == group
                and candidate["ladder"] == ladder
            ),
            key=_canonical,
        )
        for group, ladder, _required_count in GROUP_REQUIREMENTS
    ]
    selected: list[dict[str, Any]] = []
    used_hashes: set[str] = set()
    used_runs: set[str] = set()
    year_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    assay_counts: Counter[str] = Counter()

    def available_from(
        pool: list[dict[str, Any]], start: int = 0
    ) -> list[tuple[int, dict[str, Any]]]:
        return [
            (index, candidate)
            for index, candidate in enumerate(pool[start:], start)
            if candidate["content_sha256"] not in used_hashes
            and _normalized_run_key(candidate["physical_run_key"]) not in used_runs
        ]

    def diversity_remains_possible(
        group_index: int,
        start: int,
        picked_in_group: int,
    ) -> bool:
        possible = list(selected)
        for index in range(group_index, len(GROUP_REQUIREMENTS)):
            required = GROUP_REQUIREMENTS[index][2]
            remaining_slots = (
                required - picked_in_group if index == group_index else required
            )
            if remaining_slots <= 0:
                continue
            pool_start = start if index == group_index else 0
            possible.extend(
                candidate
                for _, candidate in available_from(pools[index], pool_start)
            )
        return not _diversity_failures(possible)

    def search(
        group_index: int,
        start: int = 0,
        picked_in_group: int = 0,
    ) -> tuple[dict[str, Any], ...] | None:
        if group_index == len(GROUP_REQUIREMENTS):
            if require_diversity and _diversity_failures(selected):
                return None
            return tuple(selected)

        group, ladder, required_count = GROUP_REQUIREMENTS[group_index]
        if picked_in_group == required_count:
            return search(group_index + 1)

        available = available_from(pools[group_index], start)
        if len(available) < required_count - picked_in_group:
            return None
        for later_index in range(group_index + 1, len(GROUP_REQUIREMENTS)):
            later_required = GROUP_REQUIREMENTS[later_index][2]
            if len(available_from(pools[later_index])) < later_required:
                return None
        if require_diversity and not diversity_remains_possible(
            group_index, start, picked_in_group
        ):
            return None

        ordered = sorted(
            available,
            key=lambda item: (
                not bool(item[1]["year"]),
                year_counts[item[1]["year"]],
                group == "suspicious" and item[1]["reason_signature"] == "none",
                reason_counts[item[1]["reason_signature"]],
                not bool(item[1]["assay"]),
                assay_counts[item[1]["assay"]],
                _tie_break(seed, group, ladder, item[1]["content_sha256"]),
                _canonical(item[1]),
            ),
        )
        for candidate_index, choice in ordered:
            selected.append(choice)
            used_hashes.add(choice["content_sha256"])
            normalized_run = _normalized_run_key(choice["physical_run_key"])
            used_runs.add(normalized_run)
            year_counts[choice["year"]] += 1
            reason_counts[choice["reason_signature"]] += 1
            assay_counts[choice["assay"]] += 1

            result = search(group_index, candidate_index + 1, picked_in_group + 1)
            if result is not None:
                return result

            selected.pop()
            used_hashes.remove(choice["content_sha256"])
            used_runs.remove(normalized_run)
            year_counts[choice["year"]] -= 1
            reason_counts[choice["reason_signature"]] -= 1
            assay_counts[choice["assay"]] -= 1
        return None

    return search(0)


def _blind_order_cases(
    cases: Iterable[dict[str, Any]], *, seed: int
) -> tuple[dict[str, Any], ...]:
    """Apply a domain-separated order that is independent of cohort quotas."""

    def order_key(case: Mapping[str, Any]) -> tuple[str, str]:
        content_hash = _normalized_hash(case.get("content_sha256"))
        payload = f"{BLIND_ORDER_DOMAIN}|{int(seed)}|{content_hash}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest(), content_hash

    return tuple(sorted(cases, key=order_key))


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
    numeric_seed = int(seed)
    quota_selection = _joint_selection(
        candidates, seed=numeric_seed, require_diversity=False
    )
    if quota_selection is None:
        for group, ladder, required_count in GROUP_REQUIREMENTS:
            group_count = sum(
                candidate["cohort_group"] == group and candidate["ladder"] == ladder
                for candidate in candidates
            )
            if group_count < required_count:
                raise ValueError(
                    f"Insufficient unique candidates for {group} {ladder}: "
                    f"required {required_count}"
                )
        raise ValueError(
            "Insufficient globally disjoint candidates for round-two quotas"
        )

    if not _diversity_failures(quota_selection):
        selected = quota_selection
    else:
        selected = _joint_selection(
            candidates, seed=numeric_seed, require_diversity=True
        )
        if selected is None:
            failures = _diversity_failures(candidates)
            detail = ", ".join(failures or ("joint year/reason/assay",))
            raise ValueError(
                f"Diversity requirements cannot be satisfied: {detail}"
            )
    return RoundTwoSelection(
        cases=_blind_order_cases(selected, seed=numeric_seed),
        seed=numeric_seed,
    )


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


def _research_roots_from_workspace(workspace: Path) -> ResearchRoots:
    manifest = json.loads(
        (workspace / "run_manifest.json").read_text(encoding="utf-8")
    )
    values = manifest.get("roots") if isinstance(manifest, dict) else None
    if not isinstance(values, dict):
        raise ValueError("run_manifest.json must contain research roots")
    roots = ResearchRoots(
        raw_roots=tuple(Path(value) for value in values.get("raw_roots", ())),
        archive_root=Path(str(values.get("archive_root") or "")),
        output_root=Path(str(values.get("output_root") or "")),
        excluded_backup_root=Path(str(values.get("excluded_backup_root") or "")),
    )
    if not roots.raw_roots:
        raise ValueError("run_manifest.json must contain at least one raw root")
    try:
        workspace.relative_to(roots.output_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"Workspace must be below the research output root: {roots.output_root.resolve()}"
        ) from exc
    return roots


def _roots_key(roots: ResearchRoots) -> tuple[tuple[str, ...], str, str, str]:
    return (
        tuple(_path_key(path) for path in roots.raw_roots),
        _path_key(roots.archive_root),
        _path_key(roots.output_root),
        _path_key(roots.excluded_backup_root),
    )


def _round_two_roots(
    workspace: Path, roots: ResearchRoots | None
) -> ResearchRoots:
    manifest_roots = _research_roots_from_workspace(workspace)
    if roots is None:
        assert_canonical_production_workspace(workspace)
        return assert_canonical_production_roots(manifest_roots)
    if _roots_key(roots) != _roots_key(manifest_roots):
        raise ValueError("Injected research roots must exactly match run_manifest.json")
    return roots


def _write_withheld_manifest_temporary(path: Path, payload: Mapping[str, Any]) -> Path:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(
                payload,
                handle,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        return temporary
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def prepare_round_two_review(
    workspace: Path,
    *,
    seed: int = DEFAULT_ROUND_TWO_SEED,
    roots: ResearchRoots | None = None,
) -> RoundTwoReviewResult:
    """Select and publish a blind round-two bundle plus a withheld allocation."""

    target = Path(workspace).resolve()
    roots = _round_two_roots(target, roots)
    bundle_dir = target / "round_2_review_bundle"
    withheld_path = target / "round_2_selection_withheld.json"
    if withheld_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing withheld manifest: {withheld_path}"
        )
    if bundle_dir.exists() and (
        not bundle_dir.is_dir() or any(bundle_dir.iterdir())
    ):
        raise FileExistsError(
            f"Refusing to overwrite non-empty review bundle: {bundle_dir}"
        )

    diagnostics, inventory, manual_hashes, excluded_hashes = load_round_two_inputs(
        target
    )
    selection = select_round_two_cohort(
        diagnostics,
        inventory,
        manual_hashes,
        excluded_hashes,
        seed=seed,
    )
    withheld_cases = []
    for ordinal, case in enumerate(selection.cases, 1):
        case_id = f"{ordinal:03d}"
        source_name = Path(str(case.get("path") or "")).name
        withheld_cases.append(
            {
                **case,
                "case_id": case_id,
                "copied_path": str(bundle_dir / "files" / case_id / source_name),
            }
        )
    withheld_payload = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": selection.seed,
        "case_count": len(withheld_cases),
        "bundle_dir": str(bundle_dir),
        "cases": withheld_cases,
    }
    temporary_manifest = _write_withheld_manifest_temporary(
        withheld_path, withheld_payload
    )
    published_bundle = False
    try:
        bundle_result = prepare_blind_review_bundle(
            selection.cases,
            bundle_dir,
            roots,
            bundle_name=ROUND_TWO_BUNDLE_NAME,
            public_case_fields=ROUND_TWO_PUBLIC_CASE_FIELDS,
        )
        published_bundle = True
        if withheld_path.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing withheld manifest: {withheld_path}"
            )
        os.replace(temporary_manifest, withheld_path)
    except Exception:
        temporary_manifest.unlink(missing_ok=True)
        if published_bundle:
            shutil.rmtree(bundle_dir, ignore_errors=True)
        raise

    return RoundTwoReviewResult(
        bundle_dir=bundle_result.bundle_dir,
        case_count=bundle_result.case_count,
        adjustment_database=bundle_result.adjustment_database,
        withheld_manifest=withheld_path,
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _scan_indices(value: Any, *, context: str) -> list[float]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    result: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{context} contains a non-numeric scan index") from exc
        if not math.isfinite(number):
            raise ValueError(f"{context} contains a non-finite scan index")
        result.append(number)
    return result


def _verified_manual_scan_indices(
    source_path: Path,
    *,
    ladder: str,
    database_path: Path,
    case_id: str,
) -> list[float]:
    ladder_family = _normalized_ladder(ladder)
    aliases = ROUND_TWO_LADDER_ALIASES.get(ladder_family)
    if aliases is None:
        raise ValueError(
            f"Manual case {case_id} has unsupported ladder identity: {ladder}"
        )
    expected_count = ROUND_TWO_EXPECTED_STEP_COUNTS[ladder_family]
    requested_identity = str(ladder or "").strip().upper()
    ordered_aliases = tuple(
        dict.fromkeys(
            (requested_identity, *aliases)
            if requested_identity in aliases
            else aliases
        )
    )
    for alias in ordered_aliases:
        record = load_ladder_adjustment_record(
            source_path,
            ladder=alias,
            database_path=database_path,
            allow_unscoped_ladder=False,
        )
        payload = record.get("payload") if isinstance(record, dict) else None
        validation = payload.get("validation") if isinstance(payload, dict) else None
        selected_peaks = (
            payload.get("selected_peaks") if isinstance(payload, dict) else None
        )
        if (
            not isinstance(validation, dict)
            or validation.get("save_verified") is not True
            or not isinstance(selected_peaks, list)
            or not selected_peaks
        ):
            continue

        indexed: list[tuple[int, float]] = []
        for peak in selected_peaks:
            if not isinstance(peak, dict):
                raise ValueError(
                    f"Manual case {case_id} must contain a full contiguous "
                    f"{expected_count}-step selected_peaks mapping"
                )
            try:
                raw_step_index = peak["step_index"]
                step_index = int(raw_step_index)
                observed_time = float(peak["observed_time"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(
                    f"Manual case {case_id} must contain a full contiguous "
                    f"{expected_count}-step selected_peaks mapping"
                ) from None
            try:
                integral_step = float(raw_step_index) == float(step_index)
            except (TypeError, ValueError):
                integral_step = False
            if not integral_step or step_index < 0 or not math.isfinite(observed_time):
                raise ValueError(
                    f"Manual case {case_id} must contain a full contiguous "
                    f"{expected_count}-step selected_peaks mapping"
                )
            indexed.append((step_index, observed_time))

        indexed.sort()
        step_indices = [step_index for step_index, _value in indexed]
        if step_indices != list(range(expected_count)):
            raise ValueError(
                f"Manual case {case_id} must contain a full contiguous "
                f"{expected_count}-step selected_peaks mapping"
            )
        scan_indices = [value for _step_index, value in indexed]
        if any(
            left >= right
            for left, right in zip(scan_indices, scan_indices[1:])
        ):
            raise ValueError(
                f"Manual case {case_id} selected_peaks scans must be strictly increasing"
            )
        return scan_indices

    raise ValueError(
        f"Manual case {case_id} has no verified selected_peaks in the bundle database "
        f"for ladder aliases {', '.join(ordered_aliases)}"
    )


def _anchor_deltas(
    rust_scan_indices: list[float], review_scan_indices: list[float]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for anchor_index in range(max(len(rust_scan_indices), len(review_scan_indices))):
        rust_value = (
            rust_scan_indices[anchor_index]
            if anchor_index < len(rust_scan_indices)
            else None
        )
        review_value = (
            review_scan_indices[anchor_index]
            if anchor_index < len(review_scan_indices)
            else None
        )
        result.append(
            {
                "anchor_index": anchor_index,
                "rust_scan_index": rust_value,
                "review_scan_index": review_value,
                "delta_scan": (
                    review_value - rust_value
                    if rust_value is not None and review_value is not None
                    else None
                ),
            }
        )
    return result


def _counter(values: Iterable[Any]) -> dict[str, int]:
    counts = Counter(str(value or "") for value in values)
    return dict(sorted(counts.items()))


def _repeated_error_patterns(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        if (
            case["cohort_group"] == "suspicious"
            and case["label"] == "manual_adjusted"
        ):
            grouped.setdefault(case["failure_signature"], []).append(case)

    result: list[dict[str, Any]] = []
    for signature, pattern_cases in sorted(grouped.items()):
        if len(pattern_cases) < 2:
            continue
        deltas = [
            abs(float(anchor["delta_scan"]))
            for case in pattern_cases
            for anchor in case["anchor_deltas"]
            if anchor["delta_scan"] is not None
        ]
        result.append(
            {
                "failure_signature": signature,
                "case_count": len(pattern_cases),
                "case_ids": [case["case_id"] for case in pattern_cases],
                "maximum_absolute_delta_scan": max(deltas, default=0.0),
            }
        )
    return result


def _markdown_cell(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )


def _markdown_count_table(title: str, counts: Mapping[str, int]) -> list[str]:
    lines = [f"## {title}", "", "| Value | Count |", "|---|---:|"]
    lines.extend(
        f"| {_markdown_cell(value) or '(blank)'} | {count} |"
        for value, count in counts.items()
    )
    lines.append("")
    return lines


def _render_round_two_comparison(payload: Mapping[str, Any]) -> str:
    counts = payload["counts"]
    lines = [
        "# Round-Two Ladder Review Comparison",
        "",
        f"Generated: {payload['generated_at_utc']}",
        "",
        "## Denominators",
        "",
        f"- Audit total: {payload['total_count']}",
        f"- Missing-ladder exclusions: {payload['excluded_count']}",
        f"- Fitting evaluation: {payload['fitting_evaluation_count']}",
        f"- ML eligible: {payload['ml_eligible_count']}",
        "",
    ]
    for title, key in (
        ("Review outcome", "by_label"),
        ("Ladder", "by_ladder"),
        ("Year", "by_year"),
        ("Assay", "by_assay"),
        ("Failure signature", "by_failure_signature"),
        ("Blind cohort group", "by_cohort_group"),
    ):
        lines.extend(_markdown_count_table(title, counts[key]))

    lines.extend(
        [
            "## Case comparison",
            "",
            "| Case | Label | Ladder | Year | Assay | Blind cohort group | Failure signature | Rust scans | Review scans | Review - Rust |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for case in payload["cases"]:
        delta_values = [item["delta_scan"] for item in case["anchor_deltas"]]
        escaped_case = {
            key: _markdown_cell(case[key])
            for key in (
                "case_id",
                "label",
                "ladder",
                "year",
                "assay",
                "cohort_group",
                "failure_signature",
            )
        }
        lines.append(
            "| {case_id} | {label} | {ladder} | {year} | {assay} | "
            "{cohort_group} | {failure_signature} | {rust} | {review} | {delta} |".format(
                **escaped_case,
                rust=json.dumps(case["rust_preview_scan_indices"]),
                review=json.dumps(case["review_scan_indices"]),
                delta=json.dumps(delta_values),
            )
        )
    lines.extend(["", "## Repeated error patterns", ""])
    patterns = payload["repeated_error_patterns"]
    if patterns:
        for pattern in patterns:
            lines.append(
                "- {failure_signature}: {case_count} manually corrected suspicious "
                "cases; maximum absolute scan delta {maximum_absolute_delta_scan}.".format(
                    **{
                        **pattern,
                        "failure_signature": _markdown_cell(
                            pattern["failure_signature"]
                        ),
                    }
                )
            )
    else:
        lines.append("- No repeated manually corrected suspicious pattern met the shortlist threshold.")
    lines.append("")
    return "\n".join(lines)


def _write_temporary_text(path: Path, text: str) -> Path:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        return temporary
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _reserve_sibling_path(path: Path, *, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=suffix,
        delete=False,
    ) as handle:
        reserved = Path(handle.name)
    reserved.unlink()
    return reserved


def _publish_output_pair(replacements: tuple[tuple[Path, Path], ...]) -> None:
    backups: dict[Path, Path | None] = {}
    published: list[Path] = []
    try:
        for _temporary, target in replacements:
            backup = (
                _reserve_sibling_path(target, suffix=".rollback")
                if target.exists()
                else None
            )
            if backup is not None:
                os.replace(target, backup)
            backups[target] = backup

        for temporary, target in replacements:
            os.replace(temporary, target)
            published.append(target)
    except Exception:
        for target in published:
            target.unlink(missing_ok=True)
        try:
            for _temporary, target in reversed(replacements):
                backup = backups.get(target)
                if backup is not None and backup.exists():
                    os.replace(backup, target)
        except Exception as rollback_error:
            raise RuntimeError(
                "Round-two output publication and rollback both failed"
            ) from rollback_error
        raise
    else:
        for backup in backups.values():
            if backup is not None:
                backup.unlink(missing_ok=True)
    finally:
        for temporary, _target in replacements:
            temporary.unlink(missing_ok=True)


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _validate_round_two_manifest_cases(
    cases: list[dict[str, Any]],
) -> None:
    if len(cases) != ROUND_TWO_CASE_COUNT:
        raise ValueError(
            f"Round-two finalization requires exactly {ROUND_TWO_CASE_COUNT} cases"
        )
    expected_ids = [f"{index:03d}" for index in range(1, ROUND_TWO_CASE_COUNT + 1)]
    case_ids = [str(case.get("case_id") or "").strip() for case in cases]
    if case_ids != expected_ids:
        raise ValueError("Round-two case IDs must be the contiguous sequence 001-018")

    quota_counts = Counter(
        (
            str(case.get("cohort_group") or "").strip().casefold(),
            _normalized_ladder(case.get("ladder")),
        )
        for case in cases
    )
    expected_quotas = Counter(
        {(group, ladder): count for group, ladder, count in GROUP_REQUIREMENTS}
    )
    if quota_counts != expected_quotas:
        raise ValueError(
            "Round-two withheld cohort does not satisfy the required quota counts"
        )

    content_hashes = [
        _normalized_hash(case.get("content_sha256")) for case in cases
    ]
    if not all(_is_sha256(value) for value in content_hashes) or len(
        set(content_hashes)
    ) != ROUND_TWO_CASE_COUNT:
        raise ValueError("Round-two cases require unique valid content SHA-256 hashes")
    physical_runs = [
        _normalized_run_key(case.get("physical_run_key")) for case in cases
    ]
    if not all(physical_runs) or len(set(physical_runs)) != ROUND_TWO_CASE_COUNT:
        raise ValueError("Round-two cases require unique nonblank physical runs")
    copied_paths = [_path_key(case.get("copied_path")) for case in cases]
    if not all(copied_paths) or len(set(copied_paths)) != ROUND_TWO_CASE_COUNT:
        raise ValueError("Round-two cases require unique nonblank copied paths")


def finalize_round_two_review(
    workspace: Path, *, roots: ResearchRoots | None = None
) -> RoundTwoOutcomeResult:
    """Finalize a fully resolved blind review using only bundle-local evidence."""

    target = Path(workspace).resolve()
    _round_two_roots(target, roots)
    bundle_dir = target / "round_2_review_bundle"
    cases_path = bundle_dir / "ladder_review_cases.csv"
    withheld_path = target / "round_2_selection_withheld.json"
    adjustment_database = bundle_dir / "ladder_adjustments.sqlite3"
    review_rows = _read_csv(cases_path)
    withheld = _load_json_object(withheld_path)
    withheld_cases_raw = withheld.get("cases")
    if not isinstance(withheld_cases_raw, list) or not all(
        isinstance(case, dict) for case in withheld_cases_raw
    ):
        raise ValueError("Round-two withheld manifest must contain a cases list")
    withheld_cases = [dict(case) for case in withheld_cases_raw]
    expected_count = int(withheld.get("case_count") or 0)
    if expected_count != ROUND_TWO_CASE_COUNT:
        raise ValueError(
            f"Round-two finalization requires exactly {ROUND_TWO_CASE_COUNT} cases"
        )
    _validate_round_two_manifest_cases(withheld_cases)
    if len(review_rows) != expected_count or len(withheld_cases) != expected_count:
        raise ValueError("Round-two CSV and withheld manifest case counts do not match")

    rows_by_id = {str(row.get("source_run_dir") or "").strip(): row for row in review_rows}
    cases_by_id = {str(case.get("case_id") or "").strip(): case for case in withheld_cases}
    if (
        "" in rows_by_id
        or "" in cases_by_id
        or len(rows_by_id) != len(review_rows)
        or len(cases_by_id) != len(withheld_cases)
        or rows_by_id.keys() != cases_by_id.keys()
    ):
        raise ValueError("Round-two CSV rows do not match the withheld manifest cases")

    unresolved = [
        case_id
        for case_id, row in sorted(rows_by_id.items())
        if not is_review_resolved(row.get("label"))
    ]
    if unresolved:
        raise ValueError(
            f"Round-two review has {len(unresolved)} unresolved rows: {', '.join(unresolved)}"
        )

    outcome_cases: list[dict[str, Any]] = []
    bundle_files_root = (bundle_dir / "files").resolve()
    for case_id in sorted(rows_by_id):
        row = rows_by_id[case_id]
        withheld_case = cases_by_id[case_id]
        source_path = Path(str(row.get("full_path") or ""))
        if _path_key(source_path) != _path_key(withheld_case.get("copied_path")):
            raise ValueError(f"Round-two case {case_id} copied path does not match")
        copied_path = source_path.resolve()
        try:
            copied_relative = copied_path.relative_to(bundle_files_root)
        except ValueError as exc:
            raise ValueError(
                f"Round-two case {case_id} copied file must be contained in the bundle files directory"
            ) from exc
        if not copied_relative.parts or copied_relative.parts[0] != case_id:
            raise ValueError(
                f"Round-two case {case_id} copied file must be contained in its case directory"
            )
        if not copied_path.is_file():
            raise ValueError(f"Round-two case {case_id} copied file does not exist")
        expected_hash = _normalized_hash(withheld_case.get("content_sha256"))
        if _sha256_file(copied_path) != expected_hash:
            raise ValueError(
                f"Round-two case {case_id} copied file SHA-256 does not match selection"
            )
        if str(row.get("file") or "").strip() != copied_path.name or str(
            withheld_case.get("file") or ""
        ).strip() != copied_path.name:
            raise ValueError(f"Round-two case {case_id} copied file identity does not match")
        if _normalized_ladder(row.get("ladder")) != _normalized_ladder(
            withheld_case.get("ladder")
        ):
            raise ValueError(f"Round-two case {case_id} ladder identity does not match")
        if str(row.get("assay") or "").strip() != str(
            withheld_case.get("assay") or ""
        ).strip():
            raise ValueError(f"Round-two case {case_id} assay identity does not match")
        label = str(row.get("label") or "").strip().casefold()
        reviewed_at_utc = str(row.get("reviewed_at_utc") or "").strip()
        if (
            not reviewed_at_utc
            and label != "excluded_missing_ladder_signal"
        ):
            raise ValueError(
                f"Round-two case {case_id} requires a review timestamp"
            )
        stored_adjustment = load_ladder_adjustment_record(
            copied_path,
            database_path=adjustment_database,
        )
        has_adjustment = stored_adjustment is not None or copied_path.with_suffix(
            ".ladder_adj.json"
        ).exists()
        adjustment_path = str(row.get("adjustment_path") or "").strip()
        rust_scans = _scan_indices(
            withheld_case.get("preview_scan_indices"),
            context=f"Round-two case {case_id} Rust preview",
        )
        if label == "manual_adjusted":
            review_scans = _verified_manual_scan_indices(
                source_path,
                ladder=str(row.get("ladder") or ""),
                database_path=adjustment_database,
                case_id=case_id,
            )
        elif label == "reviewed_no_change":
            if adjustment_path or has_adjustment:
                raise ValueError(
                    f"Round-two reviewed_no_change case {case_id} has contradictory adjustment evidence"
                )
            review_scans = list(rust_scans)
        elif label == "excluded_missing_ladder_signal":
            if (
                not str(row.get("label_note") or "").strip()
                or not reviewed_at_utc
            ):
                raise ValueError(
                    f"Round-two excluded case {case_id} requires a note and review timestamp"
                )
            if adjustment_path or has_adjustment:
                raise ValueError(
                    f"Round-two excluded case {case_id} has contradictory adjustment evidence"
                )
            review_scans = []
        else:  # The centralized policy currently makes this unreachable.
            raise ValueError(f"Unsupported resolved label for round-two case {case_id}")

        outcome_cases.append(
            {
                "case_id": case_id,
                "content_sha256": str(withheld_case.get("content_sha256") or ""),
                "physical_run_key": str(withheld_case.get("physical_run_key") or ""),
                "year": str(withheld_case.get("year") or ""),
                "assay": str(withheld_case.get("assay") or row.get("assay") or ""),
                "ladder": str(withheld_case.get("ladder") or row.get("ladder") or ""),
                "cohort_group": str(withheld_case.get("cohort_group") or ""),
                "failure_signature": str(withheld_case.get("reason_signature") or "none"),
                "selection_reason": str(withheld_case.get("selection_reason") or ""),
                "label": label,
                "label_note": str(row.get("label_note") or ""),
                "reviewed_at_utc": reviewed_at_utc,
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

    total_count = len(outcome_cases)
    excluded_count = sum(
        case["label"] == "excluded_missing_ladder_signal" for case in outcome_cases
    )
    fitting_evaluation_count = sum(
        bool(case["fitting_evaluation_eligible"]) for case in outcome_cases
    )
    ml_eligible_count = sum(bool(case["ml_eligible"]) for case in outcome_cases)
    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": "1.0",
        "generated_at_utc": generated_at,
        "total_count": total_count,
        "excluded_count": excluded_count,
        "fitting_evaluation_count": fitting_evaluation_count,
        "ml_eligible_count": ml_eligible_count,
        "counts": {
            "by_label": _counter(case["label"] for case in outcome_cases),
            "by_ladder": _counter(case["ladder"] for case in outcome_cases),
            "by_year": _counter(case["year"] for case in outcome_cases),
            "by_assay": _counter(case["assay"] for case in outcome_cases),
            "by_failure_signature": _counter(
                case["failure_signature"] for case in outcome_cases
            ),
            "by_cohort_group": _counter(
                case["cohort_group"] for case in outcome_cases
            ),
        },
        "repeated_error_patterns": _repeated_error_patterns(outcome_cases),
        "cases": outcome_cases,
    }
    outcomes_path = target / "round_2_review_outcomes.json"
    comparison_path = target / "round_2_review_comparison.md"
    outcomes_temporary = _write_temporary_text(
        outcomes_path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    comparison_temporary: Path | None = None
    try:
        comparison_temporary = _write_temporary_text(
            comparison_path, _render_round_two_comparison(payload)
        )
        _publish_output_pair(
            (
                (outcomes_temporary, outcomes_path),
                (comparison_temporary, comparison_path),
            )
        )
    except Exception:
        outcomes_temporary.unlink(missing_ok=True)
        if comparison_temporary is not None:
            comparison_temporary.unlink(missing_ok=True)
        raise

    return RoundTwoOutcomeResult(
        outcomes_path=outcomes_path,
        comparison_path=comparison_path,
        total_count=total_count,
        excluded_count=excluded_count,
        fitting_evaluation_count=fitting_evaluation_count,
        ml_eligible_count=ml_eligible_count,
    )
