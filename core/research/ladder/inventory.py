"""Read-only inventory and reconciliation for historical ladder data."""

from __future__ import annotations

import csv
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

import pandas as pd

from .contracts import INVENTORY_SCHEMA_VERSION, ResearchRoots, assert_allowed_raw_path


RAW_COLUMNS = (
    "raw_path",
    "raw_root",
    "year",
    "physical_run_key",
    "logical_run_dir",
    "relative_path",
    "file",
    "content_sha256",
    "size_bytes",
)


@dataclass(frozen=True)
class InventoryResult:
    files: pd.DataFrame
    reconciliation: pd.DataFrame
    review_cases: pd.DataFrame
    tracking: pd.DataFrame
    summary: dict[str, Any]


def _normal_path_key(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).resolve()))


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_archived_path(archived_path: str | Path, roots: ResearchRoots) -> Path:
    """Map an archived drive path to one of the explicit current raw roots."""

    text = str(archived_path).strip()
    if not text:
        raise ValueError("Archived raw path is empty")

    windows_path = PureWindowsPath(text)
    parts = windows_path.parts
    excluded_name = roots.excluded_backup_root.name.casefold()
    if any(part.casefold() == excluded_name for part in parts):
        raise ValueError(f"Archived path references the excluded backup root: {text}")

    direct = Path(text)
    if direct.exists():
        return assert_allowed_raw_path(direct, roots)

    folded_parts = [part.casefold() for part in parts]
    for raw_root in roots.raw_roots:
        root_name = raw_root.name.casefold()
        if root_name not in folded_parts:
            continue
        root_index = folded_parts.index(root_name)
        candidate = raw_root.joinpath(*parts[root_index + 1 :])
        return assert_allowed_raw_path(candidate, roots)

    raise ValueError(f"Archived path cannot be mapped to an allowed raw root: {text}")


def discover_raw_runs(roots: ResearchRoots) -> pd.DataFrame:
    """Inventory FSA files beneath direct top-level physical run directories."""

    records: list[dict[str, Any]] = []
    for raw_root in roots.raw_roots:
        root = raw_root.resolve()
        if not root.exists():
            continue
        year = raw_root.name[:4]
        for physical_dir in sorted(
            (entry for entry in root.iterdir() if entry.is_dir()),
            key=lambda entry: entry.name.casefold(),
        ):
            physical_key = f"{raw_root.name}/{physical_dir.name}"
            for candidate in sorted(
                (
                    entry
                    for entry in physical_dir.rglob("*")
                    if entry.is_file() and entry.suffix.casefold() == ".fsa"
                ),
                key=lambda entry: str(entry).casefold(),
            ):
                path = assert_allowed_raw_path(candidate, roots)
                relative = path.relative_to(root)
                records.append(
                    {
                        "raw_path": str(path),
                        "raw_root": str(root),
                        "year": year,
                        "physical_run_key": physical_key,
                        "logical_run_dir": path.parent.name,
                        "relative_path": str(relative),
                        "file": path.name,
                        "content_sha256": _sha256_file(path),
                        "size_bytes": path.stat().st_size,
                    }
                )
    return pd.DataFrame.from_records(records, columns=RAW_COLUMNS)


def _canonical_review_paths(archive_root: Path) -> list[Path]:
    if not archive_root.exists():
        return []
    return sorted(
        (
            path
            for path in archive_root.rglob("ladder_review_cases.csv")
            if path.parent.name.casefold() == "ladder_review_gate"
            and path.parent.parent.name.casefold() == "reports_backfill"
        ),
        key=lambda path: str(path).casefold(),
    )


def load_canonical_review_cases(
    archive_root: Path, roots: ResearchRoots
) -> pd.DataFrame:
    """Load only run-level reports_backfill ladder-review case bundles."""

    records: list[dict[str, Any]] = []
    for path in _canonical_review_paths(Path(archive_root)):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                row = dict(source)
                row["review_bundle_path"] = str(path.parent)
                row["review_cases_path"] = str(path)
                try:
                    resolved = resolve_archived_path(row.get("full_path", ""), roots)
                except ValueError as exc:
                    row["resolved_full_path"] = ""
                    row["path_resolution_issue"] = str(exc)
                else:
                    row["resolved_full_path"] = str(resolved)
                    row["path_resolution_issue"] = ""
                records.append(row)
    return pd.DataFrame.from_records(records)


def load_tracking_index(roots: ResearchRoots) -> pd.DataFrame:
    """Load the Runs sheets from the three annual overview workbooks."""

    frames: list[pd.DataFrame] = []
    for raw_root in roots.raw_roots:
        year = raw_root.name[:4]
        workbook = (
            roots.archive_root
            / year
            / f"track-clonality-{year}-overview.xlsx"
        )
        if not workbook.exists():
            continue
        frame = pd.read_excel(workbook, sheet_name="Runs", engine="openpyxl")
        frame = frame.copy()
        frame["tracking_year"] = year
        frame["tracking_workbook_path"] = str(workbook.resolve())
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def _issue(
    issue_code: str, record_key: str, detail: str, *, source: str
) -> dict[str, str]:
    return {
        "issue_code": issue_code,
        "record_key": record_key,
        "source": source,
        "detail": detail,
    }


def build_inventory(roots: ResearchRoots) -> InventoryResult:
    """Build a lossless raw/tracking/review reconciliation in memory."""

    raw = discover_raw_runs(roots)
    tracking = load_tracking_index(roots)
    reviews = load_canonical_review_cases(roots.archive_root, roots)
    files = raw.copy()
    issues: list[dict[str, str]] = []

    if not files.empty:
        files["identity_candidate"] = (
            files["logical_run_dir"].astype(str) + "::" + files["file"].astype(str)
        )
    else:
        files["identity_candidate"] = pd.Series(dtype="object")

    tracking_by_identity: dict[str, dict[str, Any]] = {}
    if not tracking.empty and "IdentityKey" in tracking.columns:
        for row in tracking.to_dict(orient="records"):
            identity = str(row.get("IdentityKey") or "")
            if identity:
                tracking_by_identity[identity] = row

    matched_tracking: set[str] = set()
    tracking_matches: list[str] = []
    for row in files.to_dict(orient="records"):
        identity = str(row["identity_candidate"])
        if identity in tracking_by_identity:
            matched_tracking.add(identity)
            tracking_matches.append(identity)
        else:
            tracking_matches.append("")
            issues.append(
                _issue(
                    "raw_only",
                    str(row["raw_path"]),
                    "Raw FSA has no exact annual Runs identity match.",
                    source="raw",
                )
            )
        relative_parent = Path(str(row["relative_path"])).parent
        if len(relative_parent.parts) > 1:
            issues.append(
                _issue(
                    "nested_logical_run",
                    str(row["raw_path"]),
                    f"Logical run {row['logical_run_dir']} is nested beneath physical run {row['physical_run_key']}.",
                    source="raw",
                )
            )
    files["tracking_identity_key"] = tracking_matches

    for identity in sorted(set(tracking_by_identity) - matched_tracking):
        issues.append(
            _issue(
                "tracking_only",
                identity,
                "Annual Runs entry has no exact raw FSA identity match.",
                source="tracking",
            )
        )

    raw_path_keys = {
        _normal_path_key(path): str(path) for path in files.get("raw_path", [])
    }
    for row in reviews.to_dict(orient="records"):
        resolved = str(row.get("resolved_full_path") or "")
        if not resolved or _normal_path_key(resolved) not in raw_path_keys:
            issues.append(
                _issue(
                    "archive_only",
                    str(row.get("full_path") or row.get("file") or ""),
                    str(row.get("path_resolution_issue") or "Canonical review case has no raw FSA match."),
                    source="archive",
                )
            )

    if not files.empty:
        duplicate_groups = files.groupby("content_sha256", dropna=False)
        for content_hash, group in duplicate_groups:
            if len(group) < 2:
                continue
            for raw_path in group["raw_path"]:
                issues.append(
                    _issue(
                        "duplicate_content",
                        str(raw_path),
                        f"SHA-256 {content_hash} occurs in {len(group)} raw files.",
                        source="raw",
                    )
                )

    reconciliation = pd.DataFrame.from_records(
        issues, columns=("issue_code", "record_key", "source", "detail")
    )
    summary = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "raw_file_count": int(len(files)),
        "physical_run_count": int(files["physical_run_key"].nunique())
        if not files.empty
        else 0,
        "tracking_entry_count": int(len(tracking)),
        "canonical_review_case_count": int(len(reviews)),
        "reconciliation_issue_count": int(len(reconciliation)),
    }
    return InventoryResult(
        files=files,
        reconciliation=reconciliation,
        review_cases=reviews,
        tracking=tracking,
        summary=summary,
    )
