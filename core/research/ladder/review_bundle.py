"""Prepare isolated, blind-first Ladder Studio review bundles."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

from core.research.ladder.contracts import ResearchRoots, assert_allowed_raw_path


REVIEW_BUNDLE_SCHEMA_VERSION = "1.0"
REVIEW_CASE_FIELDS = (
    "full_path",
    "file",
    "source_run_dir",
    "assay",
    "ladder",
    "ladder_qc_status",
    "ladder_review_required",
    "primary_reason",
    "reason_codes",
    "review_summary",
    "linear_max",
    "linear_mean",
    "linear_r2",
    "expected_count",
    "fitted_count",
    "fit_strategy",
    "suggested_action",
    "label",
    "label_note",
    "reviewed_at_utc",
    "adjustment_path",
)


@dataclass(frozen=True)
class ReviewBundleResult:
    bundle_dir: Path
    case_count: int
    adjustment_database: Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


def _assert_output_path(bundle_dir: Path, roots: ResearchRoots) -> Path:
    candidate = bundle_dir.resolve()
    try:
        candidate.relative_to(roots.output_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"Review bundle must be below the research output root: {roots.output_root.resolve()}"
        ) from exc
    return candidate


def _load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("partition") != "development":
        raise ValueError("Review bundle requires a development partition manifest.")
    files = payload.get("files")
    if not isinstance(files, list) or int(payload.get("file_count", -1)) != len(files):
        raise ValueError("Development manifest file count is inconsistent.")
    if not files:
        raise ValueError("Development manifest contains no files.")
    return files


def prepare_development_review_bundle(
    manifest_path: Path,
    bundle_dir: Path,
    roots: ResearchRoots,
) -> ReviewBundleResult:
    """Create and atomically publish a validated blind review bundle."""

    manifest_path = Path(manifest_path).resolve()
    destination = _assert_output_path(Path(bundle_dir), roots)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty review bundle: {destination}")

    records = _load_manifest(manifest_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    generated_at = datetime.now(timezone.utc).isoformat()
    case_map: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    try:
        for ordinal, record in enumerate(records, 1):
            source = assert_allowed_raw_path(Path(str(record.get("path") or "")), roots)
            if not source.is_file():
                raise FileNotFoundError(f"Development FSA is missing: {source}")
            expected_hash = str(record.get("content_sha256") or "").strip().lower()
            actual_hash = _sha256_file(source)
            if not expected_hash or actual_hash != expected_hash:
                raise ValueError(
                    f"SHA-256 mismatch for {source}: expected {expected_hash}, got {actual_hash}"
                )

            case_id = f"{ordinal:03d}"
            copied = staging / "files" / case_id / source.name
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copied)
            copied_hash = _sha256_file(copied)
            if copied_hash != expected_hash:
                raise ValueError(
                    f"SHA-256 mismatch after copying {source}: expected {expected_hash}, got {copied_hash}"
                )

            published_copy = destination / copied.relative_to(staging)
            ladder = str(record.get("ladder") or "")
            case_map.append(
                {
                    "case_id": case_id,
                    "copied_path": str(published_copy),
                    "original_path": str(source),
                    "content_sha256": expected_hash,
                    "partition": "development",
                    "physical_run_key": str(record.get("physical_run_key") or ""),
                    "ladder": ladder,
                    "historical_truth_source": str(record.get("truth_source") or ""),
                    "baseline_outcome": str(record.get("failure_family") or ""),
                }
            )
            review_rows.append(
                {
                    "full_path": str(published_copy),
                    "file": source.name,
                    "source_run_dir": case_id,
                    "assay": "clonality",
                    "ladder": ladder,
                    "ladder_qc_status": "review_required",
                    "ladder_review_required": "true",
                    "primary_reason": "blind_development_review",
                    "reason_codes": "research_checkpoint_a",
                    "review_summary": "Independent development-partition ladder review",
                    "linear_max": "",
                    "linear_mean": "",
                    "linear_r2": "",
                    "expected_count": "",
                    "fitted_count": "",
                    "fit_strategy": "",
                    "suggested_action": "Review current anchors without consulting historical corrections.",
                    "label": "",
                    "label_note": "",
                    "reviewed_at_utc": "",
                    "adjustment_path": "",
                }
            )

        with (staging / "ladder_review_cases.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=REVIEW_CASE_FIELDS)
            writer.writeheader()
            writer.writerows(review_rows)

        adjustment_database = destination / "ladder_adjustments.sqlite3"
        summary = {
            "schema_version": REVIEW_BUNDLE_SCHEMA_VERSION,
            "generated_at_utc": generated_at,
            "partition": "development",
            "case_count": len(review_rows),
            "review_status": "unresolved",
            "adjustment_database": str(adjustment_database),
            "historical_sidecars_included": False,
        }
        _write_json(staging / "ladder_review_summary.json", summary)
        _write_json(
            staging / "research_case_map.json",
            {
                "schema_version": REVIEW_BUNDLE_SCHEMA_VERSION,
                "generated_at_utc": generated_at,
                "cases": case_map,
            },
        )
        (staging / "README.md").write_text(
            "# Blind Ladder Development Review\n\n"
            "This bundle contains copied patient-clonality FSA files and no historical "
            "ladder sidecars. Review the current fit without consulting the original files.\n\n"
            "For each case, use `reviewed_no_change` when the displayed anchors are correct, "
            "or save corrected anchors and use `manual_adjusted`.\n\n"
            "Launch with a bundle-local adjustment store so historical hash-matched records "
            "cannot be loaded:\n\n"
            f"`HEMAFRAG_LADDER_ADJUSTMENT_DB={adjustment_database}`\n",
            encoding="utf-8",
        )

        if destination.exists():
            destination.rmdir()
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return ReviewBundleResult(
        bundle_dir=destination,
        case_count=len(review_rows),
        adjustment_database=destination / "ladder_adjustments.sqlite3",
    )


__all__ = ["ReviewBundleResult", "prepare_development_review_bundle"]
