#!/usr/bin/env python3
"""Build a resumable, read-only historical ladder research corpus."""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
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
    ResearchRoots,
    assert_allowed_raw_path,
    stable_json_fingerprint,
)
from core.research.ladder.corrections import (
    discover_adjustments,
    reconcile_manual_evidence,
)
from core.research.ladder.diagnostics import DiagnosticRecord, run_rust_diagnostic
from core.research.ladder.inventory import (
    build_inventory,
    load_canonical_review_cases,
    load_tracking_index,
    reconcile_inventory,
)
from core.research.ladder.partitions import (
    assign_partitions,
    build_gold_records,
    partition_manifest,
)
from core.research.ladder.review_bundle import prepare_development_review_bundle
from core.research.ladder.round_two import prepare_round_two_review


RESEARCH_RUN_SCHEMA = "hemafrag_ladder_research_run_v1"


def _path_key(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).resolve()))


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
        if candidate == protected_resolved:
            raise ValueError(f"Workspace cannot be a protected input root: {candidate}")
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
    roots = roots or _roots_from_manifest(target)
    _assert_workspace(target, roots)
    review_cases = pd.read_csv(target / "review_cases.csv", keep_default_na=False)
    output_path = target / "diagnostics.ndjson"
    existing = _read_ndjson(output_path) if resume else []
    by_source = {
        _path_key(record["source_path"]): record
        for record in existing
        if record.get("source_path")
    }

    pending: dict[str, dict[str, Any]] = {}
    for row in review_cases.to_dict(orient="records"):
        if str(row.get("record_kind") or "review_case") != "review_case":
            continue
        raw_path = str(row.get("resolved_full_path") or "")
        if not raw_path:
            continue
        source = assert_allowed_raw_path(Path(raw_path), roots)
        key = _path_key(source)
        if key in by_source:
            continue
        pending.setdefault(key, {**row, "_source": source})

    def execute(row: dict[str, Any]) -> dict[str, Any]:
        source = row.pop("_source")
        record = diagnostic_runner(
            Path(cli),
            source,
            configured_ladder=str(row.get("ladder") or ""),
            reviewed_label=str(row.get("label") or ""),
            timeout_seconds=timeout_seconds,
        )
        result = record.to_dict()
        result.update(
            {
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

    combined = list(by_source.values()) + completed_rows
    combined.sort(key=lambda row: _path_key(row["source_path"]))
    _write_ndjson(output_path, combined)

    manifest_path = target / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage"] = "diagnosed"
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["diagnostics"] = {
        "cli": str(Path(cli).resolve()),
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


def finalize_stage(workspace: Path, *, seed: int = 20260810) -> dict[str, Any]:
    """Create the initial gold records, review queue, summaries, and manifests."""

    target = Path(workspace).resolve()
    roots = _roots_from_manifest(target)
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

    candidates: list[dict[str, Any]] = []
    for correction in corrections.to_dict(orient="records"):
        if not _bool(correction.get("gold_eligible")):
            continue
        source_path = str(correction["source_path"])
        raw = inventory_by_path.get(_path_key(source_path))
        if raw is None:
            continue
        diagnostic = diagnostic_by_path.get(_path_key(source_path), {})
        truth_source = (
            "manual_v2" if correction.get("schema_kind") == "v2" else "manual_legacy"
        )
        content_hash = str(raw["content_sha256"])
        ladder = str(correction.get("ladder") or "")
        candidates.append(
            {
                "record_id": f"{content_hash}:{ladder}",
                "path": source_path,
                "physical_run_key": str(raw["physical_run_key"]),
                "content_sha256": content_hash,
                "ladder": ladder,
                "failure_family": str(diagnostic.get("outcome") or "manual_corrected"),
                "truth_source": truth_source,
                "expected_scan_indices": [
                    int(round(float(value)))
                    for value in _parse_json_list(correction.get("selected_times"))
                ],
                "gold_eligible": True,
                "sidecar_path": str(correction.get("sidecar_path") or ""),
            }
        )

    gold = build_gold_records(candidates)
    assigned = assign_partitions(gold, seed=seed)
    gold_records = assigned.to_dict(orient="records") if not assigned.empty else []
    _write_json(
        target / "gold_records.json",
        {"record_count": len(gold_records), "seed": seed, "records": gold_records},
    )
    for partition, filename in (
        ("development", "development_manifest.json"),
        ("locked_validation", "locked_validation_manifest.json"),
        ("release", "release_manifest.json"),
    ):
        _write_json(target / filename, partition_manifest(assigned, partition))

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
        excluded_backup_root=raw_roots[0].parent / "backup",
    )
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
    roots = _roots_from_manifest(workspace)
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
    refresh.set_defaults(
        handler=lambda args: print(
            json.dumps(
                refresh_inventory_stage(
                    _roots_from_manifest(args.workspace.resolve()),
                    args.workspace,
                )["counts"],
                indent=2,
            )
        )
    )

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

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
