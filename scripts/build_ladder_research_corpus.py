#!/usr/bin/env python3
"""Build a resumable, read-only historical ladder research corpus."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from core.research.ladder.contracts import (
    DIAGNOSTIC_SCHEMA_VERSION,
    ResearchRoots,
    assert_allowed_raw_path,
    assert_canonical_production_roots,
    assert_canonical_production_workspace,
    stable_json_fingerprint,
)
from core.research.ladder.corrections import (
    discover_adjustments,
    reconcile_manual_evidence,
)
from core.research.ladder.diagnostics import DiagnosticRecord, run_rust_diagnostic
from core.research.ladder.fit_improvement import (
    assert_validation_unlocked,
    build_approved_fit_gold,
    finalize_fit_improvement_wave,
    freeze_fit_candidate,
    prepare_fit_improvement_experiment,
)
from core.research.ladder.inventory import (
    build_inventory,
    load_canonical_review_cases,
    load_tracking_index,
    reconcile_inventory,
)
from core.research.ladder.partitions import (
    assign_partitions,
    build_gold_records,
    build_provisional_records,
    partition_manifest,
)
from core.research.ladder.review_bundle import prepare_development_review_bundle
from core.research.ladder.round_two import (
    finalize_round_two_review,
    prepare_round_two_review,
)


RESEARCH_RUN_SCHEMA = "hemafrag_ladder_research_run_v1"


def _path_key(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).resolve()))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if pd.isna(value) if not isinstance(value, (list, tuple, dict)) else False:
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(_json_safe(value), indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8")
    temporary.replace(path)


def _assert_workspace(workspace: Path, roots: ResearchRoots) -> Path:
    candidate = workspace.resolve()
    output_root = roots.output_root.resolve()
    try:
        candidate.relative_to(output_root)
    except ValueError as exc:
        raise ValueError(f"Workspace must be below the research output root: {output_root}") from exc
    for protected in (*roots.raw_roots, roots.archive_root, roots.excluded_backup_root):
        protected_resolved = protected.resolve()
        try:
            candidate.relative_to(protected_resolved)
        except ValueError:
            continue
        raise ValueError(
            f"Workspace cannot be a protected input root or descendant: {candidate}"
        )
    return candidate


def _serialize_correction(record) -> dict[str, Any]:
    row = record.to_dict()
    for column in ("selected_steps", "selected_times", "expected_bp", "issue_codes"):
        row[column] = json.dumps(row[column], separators=(",", ":"))
    return row


def _write_inventory_artifacts(target: Path, result, corrections, manual) -> None:
    _write_csv(target / "inventory.csv", result.files)
    _write_json(
        target / "reconciliation.json",
        {
            "summary": result.summary,
            "issues": result.reconciliation.to_dict(orient="records"),
        },
    )
    correction_frame = pd.DataFrame.from_records(
        [_serialize_correction(record) for record in corrections]
    )
    _write_csv(target / "manual_corrections.csv", correction_frame)
    _write_json(
        target / "manual_reconciliation.json",
        {
            "summary": manual.summary,
            "evidence": manual.evidence.to_dict(orient="records"),
            "issues": manual.issues.to_dict(orient="records"),
        },
    )
    _write_csv(target / "review_cases.csv", result.review_cases)


def inventory_stage(roots: ResearchRoots, workspace: Path) -> dict[str, Any]:
    """Inventory raw/archive/workbook inputs and surviving manual corrections."""

    target = _assert_workspace(Path(workspace), roots)
    target.mkdir(parents=True, exist_ok=True)
    result = build_inventory(roots)
    corrections = discover_adjustments(roots, result)
    manual = reconcile_manual_evidence(corrections, result.review_cases, result.tracking)
    _write_inventory_artifacts(target, result, corrections, manual)

    generated = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": RESEARCH_RUN_SCHEMA,
        "generated_at_utc": generated,
        "updated_at_utc": generated,
        "stage": "inventory",
        "roots": {
            "raw_roots": [str(path.resolve()) for path in roots.raw_roots],
            "archive_root": str(roots.archive_root.resolve()),
            "output_root": str(roots.output_root.resolve()),
            "excluded_backup_root": str(roots.excluded_backup_root.resolve()),
        },
        "counts": {**result.summary, **manual.summary},
        "configuration_fingerprint": stable_json_fingerprint(
            {
                "raw_roots": [str(path.resolve()) for path in roots.raw_roots],
                "archive_root": str(roots.archive_root.resolve()),
                "excluded_backup_root": str(roots.excluded_backup_root.resolve()),
            }
        ),
    }
    _write_json(target / "run_manifest.json", manifest)
    return manifest


def refresh_inventory_stage(roots: ResearchRoots, workspace: Path) -> dict[str, Any]:
    """Refresh joins and correction evidence while reusing existing FSA hashes."""

    target = _assert_workspace(Path(workspace), roots)
    raw = pd.read_csv(target / "inventory.csv", keep_default_na=False)
    result = reconcile_inventory(
        raw,
        load_tracking_index(roots),
        load_canonical_review_cases(roots.archive_root, roots),
    )
    corrections = discover_adjustments(roots, result)
    manual = reconcile_manual_evidence(corrections, result.review_cases, result.tracking)
    _write_inventory_artifacts(target, result, corrections, manual)

    manifest_path = target / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage"] = "inventory_refreshed"
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["counts"] = {**result.summary, **manual.summary}
    _write_json(manifest_path, manifest)
    return manifest


def _roots_from_manifest(workspace: Path) -> ResearchRoots:
    manifest = json.loads((workspace / "run_manifest.json").read_text(encoding="utf-8"))
    roots = manifest["roots"]
    return ResearchRoots(
        raw_roots=tuple(Path(value) for value in roots["raw_roots"]),
        archive_root=Path(roots["archive_root"]),
        output_root=Path(roots["output_root"]),
        excluded_backup_root=Path(roots["excluded_backup_root"]),
    )


def _production_roots_from_manifest(workspace: Path) -> ResearchRoots:
    target = assert_canonical_production_workspace(workspace)
    return assert_canonical_production_roots(_roots_from_manifest(target))


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


def _write_ndjson(path: Path, records: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    text = "".join(
        json.dumps(_json_safe(record), sort_keys=True, ensure_ascii=False) + "\n"
        for record in records
    )
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _diagnostic_record_is_reusable(
    record: dict[str, Any], provenance: dict[str, Any]
) -> bool:
    if record.get("schema_version") != DIAGNOSTIC_SCHEMA_VERSION:
        return False
    if record.get("diagnostic_success") is not True:
        return False
    if str(record.get("transport_status") or "") != "ok":
        return False
    return all(record.get(key) == value for key, value in provenance.items())


def diagnose_stage(
    workspace: Path,
    *,
    cli: Path,
    roots: ResearchRoots | None = None,
    max_workers: int = 3,
    timeout_seconds: int = 30,
    resume: bool = True,
    diagnostic_runner: Callable[..., DiagnosticRecord] = run_rust_diagnostic,
) -> dict[str, Any]:
    """Run deterministic Rust diagnostics for every canonical review case."""

    target = Path(workspace).resolve()
    if roots is None:
        roots = _production_roots_from_manifest(target)
    else:
        _assert_workspace(target, roots)
    cli_path = Path(cli).resolve()
    cli_sha256 = _sha256_file(cli_path)
    review_cases = pd.read_csv(target / "review_cases.csv", keep_default_na=False)
    inventory = pd.read_csv(target / "inventory.csv", keep_default_na=False)
    inventory_by_path = {
        _path_key(row.get("raw_path") or row.get("resolved_full_path")): row
        for row in inventory.to_dict(orient="records")
        if row.get("raw_path") or row.get("resolved_full_path")
    }
    output_path = target / "diagnostics.ndjson"
    existing = _read_ndjson(output_path) if resume else []
    by_source = {
        _path_key(record["source_path"]): record
        for record in existing
        if record.get("source_path")
    }

    reusable: dict[str, dict[str, Any]] = {}
    pending: dict[str, dict[str, Any]] = {}
    settings_fingerprints: set[str] = set()
    for row in review_cases.to_dict(orient="records"):
        if str(row.get("record_kind") or "review_case") != "review_case":
            continue
        raw_path = str(row.get("resolved_full_path") or "")
        if not raw_path:
            continue
        source = assert_allowed_raw_path(Path(raw_path), roots)
        key = _path_key(source)
        inventory_row = inventory_by_path.get(key)
        if inventory_row is None:
            raise ValueError(f"Diagnostic source is missing from inventory: {source}")
        source_sha256 = _sha256_file(source)
        inventory_sha256 = str(inventory_row.get("content_sha256") or "").strip().lower()
        if source_sha256 != inventory_sha256:
            raise ValueError(
                f"Diagnostic source SHA-256 does not match inventory: {source}"
            )
        physical_run_key = str(
            inventory_row.get("physical_run_key") or ""
        ).strip()
        if not physical_run_key:
            raise ValueError(
                f"Diagnostic source has no physical_run_key in inventory: {source}"
            )
        settings_fingerprint = stable_json_fingerprint(
            {
                "analysis": "clonality",
                "compact_json": True,
                "configured_ladder": str(row.get("ladder") or ""),
                "deterministic": True,
                "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
                "research_run_schema": RESEARCH_RUN_SCHEMA,
                "reviewed_label": str(row.get("label") or ""),
                "timeout_seconds": int(timeout_seconds),
            }
        )
        settings_fingerprints.add(settings_fingerprint)
        provenance = {
            "source_sha256": source_sha256,
            "physical_run_key": physical_run_key,
            "cli_sha256": cli_sha256,
            "diagnostic_settings_fingerprint": settings_fingerprint,
        }
        prior = by_source.get(key)
        if prior is not None and _diagnostic_record_is_reusable(prior, provenance):
            reusable[key] = prior
            continue
        pending.setdefault(
            key,
            {**row, "_source": source, "_provenance": provenance},
        )

    def execute(row: dict[str, Any]) -> dict[str, Any]:
        source = row.pop("_source")
        provenance = row.pop("_provenance")
        record = diagnostic_runner(
            cli_path,
            source,
            configured_ladder=str(row.get("ladder") or ""),
            reviewed_label=str(row.get("label") or ""),
            timeout_seconds=timeout_seconds,
        )
        result = record.to_dict()
        result.update(provenance)
        result.update(
            {
                "diagnostic_success": record.transport_status == "ok",
                "assay": str(row.get("assay") or ""),
                "source_run_dir": str(row.get("source_run_dir") or ""),
                "archive_primary_reason": str(row.get("primary_reason") or ""),
                "archive_reason_codes": str(row.get("reason_codes") or ""),
            }
        )
        return result

    completed_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as executor:
        futures = [executor.submit(execute, dict(row)) for row in pending.values()]
        for future in as_completed(futures):
            completed_rows.append(future.result())

    combined = list(reusable.values()) + completed_rows
    combined.sort(key=lambda row: _path_key(row["source_path"]))
    _write_ndjson(output_path, combined)

    manifest_path = target / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage"] = "diagnosed"
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["diagnostics"] = {
        "cli": str(cli_path),
        "cli_sha256": cli_sha256,
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "settings_fingerprints": sorted(settings_fingerprints),
        "max_workers": max(1, int(max_workers)),
        "timeout_seconds": int(timeout_seconds),
        "record_count": len(combined),
        "new_record_count": len(completed_rows),
    }
    _write_json(manifest_path, manifest)
    return manifest["diagnostics"]


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(text)
    return list(parsed) if isinstance(parsed, (list, tuple)) else []


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


def _ladder_family(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("LIZ"):
        return "LIZ"
    if text.startswith("ROX"):
        return "ROX"
    return text


def _load_manual_correction_approvals(
    workspace: Path,
) -> dict[tuple[str, str], dict[str, str]]:
    approvals_path = workspace / "manual_correction_approvals.csv"
    if not approvals_path.exists() or approvals_path.stat().st_size <= 1:
        return {}
    approvals = pd.read_csv(approvals_path, keep_default_na=False)
    required = {
        "content_sha256",
        "ladder",
        "review_approved",
        "review_label",
        "reviewed_at_utc",
        "reviewed_by",
    }
    missing = sorted(required - set(approvals.columns))
    if missing:
        raise ValueError(f"Manual correction approvals are missing columns: {missing}")
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in approvals.to_dict(orient="records"):
        if not _bool(row.get("review_approved")):
            continue
        content_hash = str(row.get("content_sha256") or "").strip().lower()
        ladder = _ladder_family(row.get("ladder"))
        review_label = str(row.get("review_label") or "").strip().casefold()
        reviewed_at = str(row.get("reviewed_at_utc") or "").strip()
        reviewed_by = str(row.get("reviewed_by") or "").strip()
        if (
            len(content_hash) != 64
            or any(character not in "0123456789abcdef" for character in content_hash)
            or review_label != "manual_adjusted"
            or ladder not in {"LIZ", "ROX"}
            or not reviewed_at
            or not reviewed_by
        ):
            raise ValueError(
                "Approved manual corrections require a valid content hash, ladder, "
                "manual_adjusted label, reviewer, and timestamp"
            )
        key = (content_hash, ladder)
        if key in result:
            raise ValueError(f"Duplicate manual correction approval: {key}")
        result[key] = {
            "review_label": review_label,
            "reviewed_at_utc": reviewed_at,
            "reviewed_by": reviewed_by,
        }
    return result


def finalize_stage(
    workspace: Path,
    *,
    seed: int = 20260810,
    roots: ResearchRoots | None = None,
) -> dict[str, Any]:
    """Create the initial gold records, review queue, summaries, and manifests."""

    target = Path(workspace).resolve()
    if roots is None:
        roots = _production_roots_from_manifest(target)
    else:
        _assert_workspace(target, roots)
    inventory = pd.read_csv(target / "inventory.csv", keep_default_na=False)
    corrections_path = target / "manual_corrections.csv"
    corrections = (
        pd.read_csv(corrections_path, keep_default_na=False)
        if corrections_path.stat().st_size > 1
        else pd.DataFrame()
    )
    diagnostics = _read_ndjson(target / "diagnostics.ndjson")
    diagnostic_by_path = {
        _path_key(record["source_path"]): record
        for record in diagnostics
        if record.get("source_path")
    }
    inventory_by_path = {
        _path_key(row["raw_path"]): row for row in inventory.to_dict(orient="records")
    }

    approvals = _load_manual_correction_approvals(target)
    candidates: list[dict[str, Any]] = []
    for correction in corrections.to_dict(orient="records"):
        if not _bool(correction.get("provisional_eligible")):
            continue
        analysis_id = str(correction.get("analysis_id") or "").strip().casefold()
        sample_kind = str(correction.get("sample_kind") or "").strip().casefold()
        if analysis_id != "clonality" or sample_kind != "patient":
            continue
        source_path = str(correction["source_path"])
        raw = inventory_by_path.get(_path_key(source_path))
        if raw is None:
            continue
        if str(raw.get("sample_kind") or "").strip().casefold() != "patient":
            continue
        diagnostic = diagnostic_by_path.get(_path_key(source_path), {})
        historical_truth_source = (
            "manual_v2" if correction.get("schema_kind") == "v2" else "manual_legacy"
        )
        content_hash = str(raw["content_sha256"]).strip().lower()
        if str(correction.get("source_sha256") or "").strip().lower() != content_hash:
            raise ValueError(
                f"Provisional correction SHA-256 does not match inventory: {source_path}"
            )
        ladder = _ladder_family(correction.get("ladder"))
        approval = approvals.get((content_hash, ladder))
        review_approved = approval is not None
        candidates.append(
            {
                "record_id": f"{content_hash}:{ladder}",
                "path": source_path,
                "physical_run_key": str(raw["physical_run_key"]),
                "content_sha256": content_hash,
                "ladder": ladder,
                "failure_family": str(diagnostic.get("outcome") or "manual_corrected"),
                "truth_source": (
                    "reviewed_correction"
                    if review_approved
                    else historical_truth_source
                ),
                "historical_truth_source": historical_truth_source,
                "expected_scan_indices": [
                    int(round(float(value)))
                    for value in _parse_json_list(correction.get("selected_times"))
                ],
                "analysis_id": analysis_id,
                "identity_key": str(correction.get("identity_key") or ""),
                "sample_kind": sample_kind,
                "provisional_eligible": True,
                "gold_eligible": review_approved,
                "review_approved": review_approved,
                "review_label": (
                    approval["review_label"] if approval is not None else ""
                ),
                "reviewed_at_utc": (
                    approval["reviewed_at_utc"] if approval is not None else ""
                ),
                "reviewed_by": (
                    approval["reviewed_by"] if approval is not None else ""
                ),
                "sidecar_path": str(correction.get("sidecar_path") or ""),
            }
        )

    provisional = build_provisional_records(candidates)
    provisional_assigned = assign_partitions(provisional, seed=seed)
    gold = build_gold_records(candidates)
    if gold.empty:
        assigned = gold.copy()
        assigned["partition"] = pd.Series(dtype="object")
    else:
        assigned = gold.merge(
            provisional_assigned[["record_id", "partition"]],
            on="record_id",
            how="left",
            validate="one_to_one",
        )
        if assigned["partition"].isna().any():
            raise ValueError(
                "Approved gold evidence is outside the provisional partition scope"
            )
    gold_records = assigned.to_dict(orient="records") if not assigned.empty else []
    _write_json(
        target / "gold_records.json",
        {"record_count": len(gold_records), "seed": seed, "records": gold_records},
    )
    _write_json(
        target / "development_manifest.json",
        partition_manifest(
            provisional_assigned,
            "development",
            require_approval=False,
        ),
    )
    for partition, filename in (
        ("locked_validation", "locked_validation_manifest.json"),
        ("release", "release_manifest.json"),
    ):
        _write_json(
            target / filename,
            partition_manifest(assigned, partition, require_approval=True),
        )

    backed_paths = {_path_key(record["path"]) for record in gold_records}
    review_queue = [
        record
        for record in diagnostics
        if _path_key(record["source_path"]) not in backed_paths
    ]
    _write_csv(target / "review_queue.csv", pd.DataFrame.from_records(review_queue))

    diagnostic_frame = pd.DataFrame.from_records(diagnostics)
    if diagnostic_frame.empty:
        summary = pd.DataFrame(
            columns=("transport_status", "configured_ladder", "outcome", "count")
        )
    else:
        summary = (
            diagnostic_frame.groupby(
                ["transport_status", "configured_ladder", "outcome"],
                dropna=False,
            )
            .size()
            .reset_index(name="count")
        )
    _write_csv(target / "failure_summary.csv", summary)

    manifest_path = target / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage"] = "finalized_for_review"
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["finalize"] = {
        "seed": int(seed),
        "gold_record_count": len(gold_records),
        "provisional_evidence_count": len(provisional),
        "approved_correction_count": sum(
            _bool(record.get("review_approved")) for record in candidates
        ),
        "review_queue_count": len(review_queue),
        "partition_counts": assigned["partition"].value_counts().to_dict()
        if not assigned.empty
        else {},
    }
    _write_json(manifest_path, manifest)
    return manifest["finalize"]


def _inventory_command(args: argparse.Namespace) -> None:
    raw_roots = tuple(Path(value).resolve() for value in args.raw_root)
    roots = ResearchRoots(
        raw_roots=raw_roots,
        archive_root=args.archive_root.resolve(),
        output_root=args.output_root.resolve(),
        excluded_backup_root=ResearchRoots.default().excluded_backup_root,
    )
    assert_canonical_production_roots(roots)
    current = roots.output_root / "current"
    if current.exists():
        raise FileExistsError(
            f"Research workspace already exists: {current}. Use it or move it to a versioned run directory."
        )
    roots.output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=roots.output_root))
    try:
        inventory_stage(roots, staging)
        staging.replace(current)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps({"workspace": str(current), "stage": "inventory"}, indent=2))


def _prepare_review_command(args: argparse.Namespace) -> None:
    workspace = args.workspace.resolve()
    roots = _production_roots_from_manifest(workspace)
    result = prepare_development_review_bundle(
        workspace / "development_manifest.json",
        workspace / "development_review_bundle",
        roots,
    )
    print(
        json.dumps(
            {
                "bundle_dir": str(result.bundle_dir),
                "case_count": result.case_count,
                "adjustment_database": str(result.adjustment_database),
            },
            indent=2,
        )
    )


def _refresh_inventory_command(args: argparse.Namespace) -> None:
    workspace = args.workspace.resolve()
    roots = _production_roots_from_manifest(workspace)
    print(
        json.dumps(
            refresh_inventory_stage(roots, workspace)["counts"],
            indent=2,
        )
    )


def _prepare_round_two_command(args: argparse.Namespace) -> None:
    result = prepare_round_two_review(args.workspace.resolve(), seed=args.seed)
    print(
        json.dumps(
            {
                "bundle_dir": str(result.bundle_dir),
                "case_count": result.case_count,
                "adjustment_database": str(result.adjustment_database),
                "withheld_manifest": str(result.withheld_manifest),
            },
            indent=2,
        )
    )


def _finalize_round_two_command(args: argparse.Namespace) -> None:
    result = finalize_round_two_review(args.workspace.resolve())
    print(
        json.dumps(
            {
                "outcomes_path": str(result.outcomes_path),
                "comparison_path": str(result.comparison_path),
                "total_count": result.total_count,
                "excluded_count": result.excluded_count,
                "fitting_evaluation_count": result.fitting_evaluation_count,
                "ml_eligible_count": result.ml_eligible_count,
            },
            indent=2,
        )
    )


def _prepare_fit_improvement_command(args: argparse.Namespace) -> None:
    result = prepare_fit_improvement_experiment(
        args.workspace.resolve(), seed=args.seed
    )
    print(
        json.dumps(
            {
                "experiment_dir": str(result.experiment_dir),
                "development_bundle": str(result.development.bundle_dir),
                "development_case_count": result.development.case_count,
                "validation_bundle": str(result.validation.bundle_dir),
                "validation_case_count": result.validation.case_count,
            },
            indent=2,
        )
    )


def _finalize_fit_wave_command(args: argparse.Namespace, wave: str) -> None:
    result = finalize_fit_improvement_wave(args.workspace.resolve(), wave)
    print(
        json.dumps(
            {
                "wave": result.wave,
                "outcomes_path": str(result.outcomes_path),
                "comparison_path": str(result.comparison_path),
                "total_count": result.total_count,
                "excluded_count": result.excluded_count,
                "fitting_evaluation_count": result.fitting_evaluation_count,
                "ml_eligible_count": result.ml_eligible_count,
            },
            indent=2,
        )
    )


def _freeze_fit_candidate_command(args: argparse.Namespace) -> None:
    assert_canonical_production_workspace(args.workspace.resolve())
    configuration = json.loads(args.configuration_json)
    if not isinstance(configuration, dict):
        raise ValueError("--configuration-json must decode to a JSON object")
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    result = freeze_fit_candidate(
        args.workspace.resolve(),
        binary=args.cli.resolve(),
        configuration=configuration,
        git_revision=completed.stdout.strip(),
    )
    print(
        json.dumps(
            {
                "manifest_path": str(result.manifest_path),
                "binary_path": str(result.binary_path),
                "binary_sha256": result.binary_sha256,
                "configuration_fingerprint": result.configuration_fingerprint,
                "git_revision": result.git_revision,
            },
            indent=2,
        )
    )


def _export_fit_gold_command(args: argparse.Namespace) -> None:
    workspace = args.workspace.resolve()
    assert_canonical_production_workspace(workspace)
    experiment = workspace / "rust_fit_improvement"
    round_two = json.loads(
        (workspace / "round_2_review_outcomes.json").read_text(encoding="utf-8")
    )
    development = json.loads(
        (experiment / "development_outcomes.json").read_text(encoding="utf-8")
    )
    selected_cases: dict[str, dict[str, Any]] = {}
    for manifest_path in (
        workspace / "round_2_selection_withheld.json",
        experiment / "development_selection_withheld.json",
    ):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for case in manifest.get("cases") or []:
            selected_cases[str(case.get("content_sha256") or "").casefold()] = dict(
                case
            )
    approvals: dict[str, dict[str, Any]] = {}
    approved_runs: set[str] = set()
    omitted_duplicate_runs = 0
    for payload in (round_two, development):
        for outcome in payload.get("cases") or []:
            if not bool(outcome.get("fitting_evaluation_eligible")):
                continue
            content_hash = str(outcome.get("content_sha256") or "").casefold()
            selected = selected_cases.get(content_hash)
            if selected is None:
                raise ValueError("Reviewed fit-gold case is missing its hash-bound selection")
            physical_run = str(outcome.get("physical_run_key") or "")
            run_key = physical_run.strip().casefold()
            if run_key in approved_runs:
                omitted_duplicate_runs += 1
                continue
            approved_runs.add(run_key)
            approvals[content_hash] = {
                "path": str(selected.get("copied_path") or ""),
                "content_sha256": content_hash,
                "physical_run_key": physical_run,
                "identity_key": f"patient:{physical_run}",
                "sample_kind": str(selected.get("sample_kind") or "patient"),
                "reviewed_by": args.reviewed_by,
                "approved_for_fit_gold": True,
            }
    manifest = build_approved_fit_gold(round_two, development, approvals)
    manifest["omitted_duplicate_run_count"] = omitted_duplicate_runs
    output = experiment / "approved_fit_gold_manifest.json"
    _write_json(output, manifest)
    print(
        json.dumps(
            {
                "output": str(output),
                "record_count": manifest["record_count"],
                "omitted_duplicate_run_count": omitted_duplicate_runs,
            },
            indent=2,
        )
    )


def _export_fit_validation_gold_command(args: argparse.Namespace) -> None:
    workspace = args.workspace.resolve()
    assert_canonical_production_workspace(workspace)
    experiment = workspace / "rust_fit_improvement"
    assert_validation_unlocked(workspace)
    validation = json.loads(
        (experiment / "validation_outcomes.json").read_text(encoding="utf-8")
    )
    selection = json.loads(
        (experiment / "validation_selection_withheld.json").read_text(
            encoding="utf-8"
        )
    )
    selected_cases = {
        str(case.get("content_sha256") or "").casefold(): dict(case)
        for case in selection.get("cases") or []
    }
    approvals: dict[str, dict[str, Any]] = {}
    for outcome in validation.get("cases") or []:
        if not bool(outcome.get("fitting_evaluation_eligible")):
            continue
        content_hash = str(outcome.get("content_sha256") or "").casefold()
        selected = selected_cases.get(content_hash)
        if selected is None:
            raise ValueError("Validation fit-gold case is missing its hash-bound selection")
        physical_run = str(outcome.get("physical_run_key") or "")
        approvals[content_hash] = {
            "path": str(selected.get("copied_path") or ""),
            "content_sha256": content_hash,
            "physical_run_key": physical_run,
            "identity_key": f"patient:{physical_run}",
            "sample_kind": str(selected.get("sample_kind") or "patient"),
            "reviewed_by": args.reviewed_by,
            "approved_for_fit_gold": True,
        }
    manifest = build_approved_fit_gold(
        {"cases": []},
        validation,
        approvals,
        development_truth_source="validation_review",
        partition="locked_validation_fit_gold",
    )
    output = experiment / "validation_gold_manifest.json"
    _write_json(output, manifest)
    print(json.dumps({"output": str(output), "record_count": manifest["record_count"]}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    inventory = commands.add_parser("inventory")
    inventory.add_argument("--archive-root", required=True, type=Path)
    inventory.add_argument("--raw-root", required=True, action="append", type=Path)
    inventory.add_argument("--output-root", required=True, type=Path)
    inventory.set_defaults(handler=_inventory_command)

    refresh = commands.add_parser("refresh-inventory")
    refresh.add_argument("--workspace", required=True, type=Path)
    refresh.set_defaults(handler=_refresh_inventory_command)

    diagnose = commands.add_parser("diagnose")
    diagnose.add_argument("--workspace", required=True, type=Path)
    diagnose.add_argument("--cli", required=True, type=Path)
    diagnose.add_argument("--max-workers", type=int, default=3)
    diagnose.add_argument("--timeout-seconds", type=int, default=30)
    diagnose.add_argument("--resume", action="store_true")
    diagnose.set_defaults(
        handler=lambda args: print(
            json.dumps(
                diagnose_stage(
                    args.workspace,
                    cli=args.cli,
                    max_workers=args.max_workers,
                    timeout_seconds=args.timeout_seconds,
                    resume=args.resume,
                ),
                indent=2,
            )
        )
    )

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--workspace", required=True, type=Path)
    finalize.add_argument("--seed", type=int, default=20260810)
    finalize.set_defaults(
        handler=lambda args: print(
            json.dumps(finalize_stage(args.workspace, seed=args.seed), indent=2)
        )
    )

    prepare_review = commands.add_parser("prepare-review")
    prepare_review.add_argument("--workspace", required=True, type=Path)
    prepare_review.set_defaults(handler=_prepare_review_command)

    prepare_round_two = commands.add_parser("prepare-round-two")
    prepare_round_two.add_argument("--workspace", required=True, type=Path)
    prepare_round_two.add_argument("--seed", type=int, default=20260810)
    prepare_round_two.set_defaults(handler=_prepare_round_two_command)

    finalize_round_two = commands.add_parser("finalize-round-two")
    finalize_round_two.add_argument("--workspace", required=True, type=Path)
    finalize_round_two.set_defaults(handler=_finalize_round_two_command)

    prepare_fit = commands.add_parser("prepare-fit-improvement")
    prepare_fit.add_argument("--workspace", required=True, type=Path)
    prepare_fit.add_argument("--seed", type=int, default=20260811)
    prepare_fit.set_defaults(handler=_prepare_fit_improvement_command)

    finalize_fit_development = commands.add_parser("finalize-fit-development")
    finalize_fit_development.add_argument("--workspace", required=True, type=Path)
    finalize_fit_development.set_defaults(
        handler=lambda args: _finalize_fit_wave_command(args, "development")
    )

    freeze_fit = commands.add_parser("freeze-fit-candidate")
    freeze_fit.add_argument("--workspace", required=True, type=Path)
    freeze_fit.add_argument("--cli", required=True, type=Path)
    freeze_fit.add_argument("--configuration-json", default="{}")
    freeze_fit.set_defaults(handler=_freeze_fit_candidate_command)

    export_fit_gold = commands.add_parser("export-fit-gold")
    export_fit_gold.add_argument("--workspace", required=True, type=Path)
    export_fit_gold.add_argument("--reviewed-by", default="chemist")
    export_fit_gold.set_defaults(handler=_export_fit_gold_command)

    export_validation_gold = commands.add_parser("export-fit-validation-gold")
    export_validation_gold.add_argument("--workspace", required=True, type=Path)
    export_validation_gold.add_argument("--reviewed-by", default="chemist")
    export_validation_gold.set_defaults(handler=_export_fit_validation_gold_command)

    finalize_fit_validation = commands.add_parser("finalize-fit-validation")
    finalize_fit_validation.add_argument("--workspace", required=True, type=Path)
    finalize_fit_validation.set_defaults(
        handler=lambda args: _finalize_fit_wave_command(args, "validation")
    )

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
