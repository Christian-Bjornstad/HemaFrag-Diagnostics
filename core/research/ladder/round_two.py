"""Deterministic selection for the mixed round-two ladder review cohort."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.research.ladder.contracts import ResearchRoots
from core.research.ladder.review_bundle import prepare_blind_review_bundle


DEFAULT_ROUND_TWO_SEED = 20260810
FIT_REJECTED_WITH_USABLE_SIGNAL = "fit_rejected_with_usable_signal"
GROUP_REQUIREMENTS = (
    ("suspicious", "LIZ", 6),
    ("suspicious", "ROX", 6),
    ("control", "LIZ", 3),
    ("control", "ROX", 3),
)
MIN_DIVERSITY = 2
ROUND_TWO_BUNDLE_NAME = "Blind Ladder Round-Two Review"
ROUND_TWO_PUBLIC_CASE_FIELDS = (
    "content_sha256",
    "physical_run_key",
    "year",
    "assay",
    "ladder",
)


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


def _diversity_values(
    cases: Iterable[Mapping[str, Any]],
) -> tuple[set[str], set[str], set[str]]:
    case_list = list(cases)
    years = {str(case["year"]) for case in case_list if str(case["year"]).strip()}
    reasons = {
        str(case["reason_signature"])
        for case in case_list
        if case["cohort_group"] == "suspicious"
        and str(case["reason_signature"]).strip()
        and case["reason_signature"] != "none"
    }
    assays = {str(case["assay"]) for case in case_list if str(case["assay"]).strip()}
    return years, reasons, assays


def _diversity_failures(cases: Iterable[Mapping[str, Any]]) -> list[str]:
    values = _diversity_values(cases)
    names = ("year", "reason", "assay")
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
            and candidate["physical_run_key"] not in used_runs
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
            used_runs.add(choice["physical_run_key"])
            year_counts[choice["year"]] += 1
            reason_counts[choice["reason_signature"]] += 1
            assay_counts[choice["assay"]] += 1

            result = search(group_index, candidate_index + 1, picked_in_group + 1)
            if result is not None:
                return result

            selected.pop()
            used_hashes.remove(choice["content_sha256"])
            used_runs.remove(choice["physical_run_key"])
            year_counts[choice["year"]] -= 1
            reason_counts[choice["reason_signature"]] -= 1
            assay_counts[choice["assay"]] -= 1
        return None

    return search(0)


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
    return RoundTwoSelection(cases=selected, seed=numeric_seed)


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
    workspace: Path, *, seed: int = DEFAULT_ROUND_TWO_SEED
) -> RoundTwoReviewResult:
    """Select and publish a blind round-two bundle plus a withheld allocation."""

    target = Path(workspace).resolve()
    roots = _research_roots_from_workspace(target)
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
