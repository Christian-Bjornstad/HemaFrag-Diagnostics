"""Evidence ranking and leakage-safe ladder gold partitions."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

import pandas as pd

from .contracts import PARTITION_SCHEMA_VERSION, stable_json_fingerprint


TRUTH_RANK = {
    "manual_v2": 50,
    "manual_legacy": 40,
    "reviewed_correction": 30,
    "reviewed_no_change": 25,
    "reviewed_consensus": 20,
}


def _frame(records: Iterable[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(records, pd.DataFrame):
        return records.copy()
    return pd.DataFrame.from_records(list(records))


def _scan_tuple(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(int(round(float(item))) for item in value)


def build_gold_records(
    records: Iterable[dict[str, Any]] | pd.DataFrame,
) -> pd.DataFrame:
    """Resolve duplicate evidence by rank after rejecting mapping conflicts."""

    frame = _frame(records)
    if frame.empty:
        return frame
    required = {"content_sha256", "ladder", "truth_source", "expected_scan_indices"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Gold records are missing required columns: {missing}")
    if "gold_eligible" in frame.columns:
        frame = frame[frame["gold_eligible"].fillna(False).astype(bool)].copy()
    if frame.empty:
        return frame

    selected: list[pd.Series] = []
    for (content_hash, ladder), group in frame.groupby(
        ["content_sha256", "ladder"], sort=True, dropna=False
    ):
        mappings = {_scan_tuple(value) for value in group["expected_scan_indices"]}
        if len(mappings) > 1:
            raise ValueError(
                f"Conflicting gold mappings for content {content_hash!r} and ladder {ladder!r}"
            )
        ranked = group.assign(
            _truth_rank=group["truth_source"].map(TRUTH_RANK).fillna(0).astype(int),
            _stable_id=group.get("record_id", group.index.astype(str)).astype(str),
        ).sort_values(["_truth_rank", "_stable_id"], ascending=[False, True])
        selected.append(ranked.iloc[0].drop(labels=["_truth_rank", "_stable_id"]))
    return pd.DataFrame(selected).reset_index(drop=True)


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _components(frame: pd.DataFrame) -> list[list[int]]:
    union = _UnionFind(len(frame))
    seen: dict[tuple[str, str], int] = {}
    for position, row in enumerate(frame.to_dict(orient="records")):
        for kind, value in (
            ("run", row.get("physical_run_key")),
            ("content", row.get("content_sha256")),
        ):
            key = (kind, str(value or ""))
            if not key[1]:
                continue
            if key in seen:
                union.union(position, seen[key])
            else:
                seen[key] = position
    grouped: dict[int, list[int]] = defaultdict(list)
    for position in range(len(frame)):
        grouped[union.find(position)].append(position)
    return list(grouped.values())


def _component_key(frame: pd.DataFrame, positions: list[int], seed: int) -> str:
    records = frame.iloc[positions]
    identifiers = sorted(
        str(value)
        for value in records.get("record_id", records.index.astype(str)).tolist()
    )
    return stable_json_fingerprint({"seed": int(seed), "records": identifiers})


def assign_partitions(
    records: Iterable[dict[str, Any]] | pd.DataFrame,
    *,
    seed: int,
) -> pd.DataFrame:
    """Assign whole physical-run/content components deterministically."""

    frame = _frame(records).reset_index(drop=True)
    if frame.empty:
        frame["partition"] = pd.Series(dtype="object")
        return frame
    required = {"physical_run_key", "content_sha256", "failure_family"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Partition records are missing required columns: {missing}")

    components = sorted(
        _components(frame), key=lambda positions: _component_key(frame, positions, seed)
    )
    component_families = {
        tuple(component): {
            str(value)
            for value in frame.iloc[component]["failure_family"].dropna().tolist()
            if str(value)
        }
        for component in components
    }
    all_families = sorted(set().union(*component_families.values()))
    development: set[tuple[int, ...]] = set()
    covered: set[str] = set()
    for family in all_families:
        if family in covered:
            continue
        candidate = next(
            (
                tuple(component)
                for component in components
                if family in component_families[tuple(component)]
                and tuple(component) not in development
            ),
            None,
        )
        if candidate is None:
            continue
        development.add(candidate)
        covered.update(component_families[candidate])

    remaining = [
        tuple(component) for component in components if tuple(component) not in development
    ]
    assignments: dict[int, str] = {}
    for component in development:
        for position in component:
            assignments[position] = "development"
    for ordinal, component in enumerate(remaining):
        partition = "locked_validation" if ordinal % 2 == 0 else "release"
        for position in component:
            assignments[position] = partition

    frame["partition"] = [assignments[position] for position in range(len(frame))]
    sort_columns = [column for column in ("record_id", "path") if column in frame.columns]
    if sort_columns:
        frame = frame.sort_values(sort_columns).reset_index(drop=True)
    validate_partition_isolation(frame)
    return frame


def validate_partition_isolation(records: pd.DataFrame) -> None:
    """Raise when a physical run or identical content crosses partitions."""

    if records.empty:
        return
    for column in ("physical_run_key", "content_sha256"):
        counts = records.groupby(column, dropna=False)["partition"].nunique()
        leaking = counts[counts > 1]
        if not leaking.empty:
            raise ValueError(
                f"Partition leakage through {column}: {sorted(map(str, leaking.index))}"
            )


def partition_manifest(records: pd.DataFrame, partition: str) -> dict[str, Any]:
    """Create the manifest shape consumed by the Rust ladder benchmark."""

    subset = records[records["partition"].eq(partition)].copy()
    sort_column = "record_id" if "record_id" in subset.columns else "path"
    subset = subset.sort_values(sort_column)
    files = [
        {
            "path": str(row["path"]),
            "expected_scan_indices": list(_scan_tuple(row["expected_scan_indices"])),
            "content_sha256": str(row["content_sha256"]),
            "physical_run_key": str(row["physical_run_key"]),
            "ladder": str(row["ladder"]),
            "truth_source": str(row["truth_source"]),
            "failure_family": str(row.get("failure_family") or ""),
        }
        for row in subset.to_dict(orient="records")
    ]
    return {
        "schema_version": PARTITION_SCHEMA_VERSION,
        "partition": partition,
        "file_count": len(files),
        "files": files,
    }
