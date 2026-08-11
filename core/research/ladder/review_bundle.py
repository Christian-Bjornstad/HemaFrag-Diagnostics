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
from typing import Any, Callable, Iterable, Mapping, Sequence

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
BLIND_REVIEW_CASE_FIELDS = (
    "full_path",
    "file",
    "source_run_dir",
    "assay",
    "ladder",
    "primary_reason",
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


def _blind_review_row(
    record: Mapping[str, Any], published_copy: Path, source: Path, case_id: str
) -> dict[str, Any]:
    return {
        "full_path": str(published_copy),
        "file": source.name,
        "source_run_dir": case_id,
        "assay": str(record.get("assay") or ""),
        "ladder": str(record.get("ladder") or ""),
        "primary_reason": "blind_review",
        "label": "",
        "label_note": "",
        "reviewed_at_utc": "",
        "adjustment_path": "",
    }


def _development_review_row(
    record: Mapping[str, Any], published_copy: Path, source: Path, case_id: str
) -> dict[str, Any]:
    return {
        "full_path": str(published_copy),
        "file": source.name,
        "source_run_dir": case_id,
        "assay": "clonality",
        "ladder": str(record.get("ladder") or ""),
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
        "suggested_action": (
            "Review current anchors without consulting historical corrections."
        ),
        "label": "",
        "label_note": "",
        "reviewed_at_utc": "",
        "adjustment_path": "",
    }


def _prepare_review_bundle(
    records: Iterable[Mapping[str, Any]],
    bundle_dir: Path,
    roots: ResearchRoots,
    *,
    bundle_name: str,
    public_case_fields: Sequence[str],
    review_case_fields: Sequence[str],
    review_row_factory: Callable[
        [Mapping[str, Any], Path, Path, str], dict[str, Any]
    ],
    summary_fields: Mapping[str, Any] | None = None,
    readme_body: str | None = None,
) -> ReviewBundleResult:
    destination = _assert_output_path(Path(bundle_dir), roots)
    if destination.exists() and (
        not destination.is_dir() or any(destination.iterdir())
    ):
        raise FileExistsError(
            f"Refusing to overwrite non-empty review bundle: {destination}"
        )

    record_list = [dict(record) for record in records]
    public_fields = tuple(dict.fromkeys(str(field) for field in public_case_fields))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent)
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    case_map: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    try:
        for ordinal, record in enumerate(record_list, 1):
            source = assert_allowed_raw_path(
                Path(str(record.get("path") or "")), roots
            )
            if not source.is_file():
                raise FileNotFoundError(f"Review FSA is missing: {source}")
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
            public_case = {
                "case_id": case_id,
                "copied_path": str(published_copy),
            }
            public_case.update(
                {field: record.get(field, "") for field in public_fields}
            )
            case_map.append(public_case)
            review_rows.append(
                review_row_factory(record, published_copy, source, case_id)
            )

        with (staging / "ladder_review_cases.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=review_case_fields)
            writer.writeheader()
            writer.writerows(review_rows)

        adjustment_database = destination / "ladder_adjustments.sqlite3"
        summary = {
            "schema_version": REVIEW_BUNDLE_SCHEMA_VERSION,
            "generated_at_utc": generated_at,
            "case_count": len(review_rows),
            "review_status": "unresolved",
            "adjustment_database": str(adjustment_database),
            "historical_sidecars_included": False,
            **dict(summary_fields or {}),
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
        if readme_body is None:
            readme_text = (
                f"# {bundle_name}\n\n"
                "This bundle contains copied patient-clonality FSA files and no historical "
                "ladder sidecars. Review the current fit using only the displayed evidence.\n\n"
                "For each case, use `reviewed_no_change` when the displayed anchors are "
                "correct, save corrected anchors and use `manual_adjusted`, or use the "
                "registered missing-ladder exclusion when no usable ladder signal exists.\n\n"
                "Launch with a bundle-local adjustment store:\n\n"
                f"`HEMAFRAG_LADDER_ADJUSTMENT_DB={adjustment_database}`\n"
            )
        else:
            readme_text = (
                f"# {bundle_name}\n\n"
                f"{readme_body}\n\n"
                "For each case, use `reviewed_no_change` when the displayed anchors are "
                "correct, or save corrected anchors and use `manual_adjusted`.\n\n"
                "Launch with a bundle-local adjustment store so historical hash-matched "
                "records cannot be loaded:\n\n"
                f"`HEMAFRAG_LADDER_ADJUSTMENT_DB={adjustment_database}`\n"
            )
        (staging / "README.md").write_text(readme_text, encoding="utf-8")

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


def prepare_blind_review_bundle(
    records: Iterable[Mapping[str, Any]],
    bundle_dir: Path,
    roots: ResearchRoots,
    *,
    bundle_name: str,
    public_case_fields: Sequence[str],
) -> ReviewBundleResult:
    """Create a minimal app-facing blind bundle with an atomic publisher."""

    return _prepare_review_bundle(
        records,
        bundle_dir,
        roots,
        bundle_name=bundle_name,
        public_case_fields=public_case_fields,
        review_case_fields=BLIND_REVIEW_CASE_FIELDS,
        review_row_factory=_blind_review_row,
    )


def prepare_development_review_bundle(
    manifest_path: Path,
    bundle_dir: Path,
    roots: ResearchRoots,
) -> ReviewBundleResult:
    """Create and atomically publish a validated blind review bundle."""

    manifest_path = Path(manifest_path).resolve()
    records = _load_manifest(manifest_path)
    public_records = [
        {
            **record,
            "original_path": str(Path(str(record.get("path") or "")).resolve()),
            "partition": "development",
            "historical_truth_source": str(record.get("truth_source") or ""),
            "baseline_outcome": str(record.get("failure_family") or ""),
        }
        for record in records
    ]
    return _prepare_review_bundle(
        public_records,
        bundle_dir,
        roots,
        bundle_name="Blind Ladder Development Review",
        public_case_fields=(
            "original_path",
            "content_sha256",
            "partition",
            "physical_run_key",
            "ladder",
            "historical_truth_source",
            "baseline_outcome",
        ),
        review_case_fields=REVIEW_CASE_FIELDS,
        review_row_factory=_development_review_row,
        summary_fields={"partition": "development"},
        readme_body=(
            "This bundle contains copied patient-clonality FSA files and no historical "
            "ladder sidecars. Review the current fit without consulting the original files."
        ),
    )


__all__ = [
    "ReviewBundleResult",
    "prepare_blind_review_bundle",
    "prepare_development_review_bundle",
]
