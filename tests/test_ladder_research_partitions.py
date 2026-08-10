from __future__ import annotations

import pandas as pd
import pytest

from core.research.ladder.partitions import (
    assign_partitions,
    build_gold_records,
    partition_manifest,
    validate_partition_isolation,
)


def gold_record(
    record_id: str,
    *,
    run: str,
    content: str,
    family: str = "rejected",
    truth_source: str = "manual_v2",
    scans: list[int] | None = None,
) -> dict[str, object]:
    return {
        "record_id": record_id,
        "path": f"D:/allowed/{record_id}.fsa",
        "physical_run_key": run,
        "content_sha256": content,
        "ladder": "LIZ",
        "failure_family": family,
        "truth_source": truth_source,
        "expected_scan_indices": scans or [10, 20, 30],
        "gold_eligible": True,
    }


def test_v2_manual_beats_consensus_for_same_content():
    consensus = gold_record(
        "consensus",
        run="run-a",
        content="hash-a",
        truth_source="reviewed_consensus",
    )
    manual = gold_record(
        "manual",
        run="run-a",
        content="hash-a",
        truth_source="manual_v2",
    )

    records = build_gold_records([consensus, manual])

    assert len(records) == 1
    assert records.iloc[0]["truth_source"] == "manual_v2"
    assert records.iloc[0]["record_id"] == "manual"


def test_conflicting_gold_mappings_for_identical_content_are_rejected():
    first = gold_record("first", run="run-a", content="hash-a", scans=[10, 20])
    second = gold_record("second", run="run-b", content="hash-a", scans=[10, 21])

    with pytest.raises(ValueError, match="Conflicting gold mappings"):
        build_gold_records([first, second])


def test_physical_run_never_crosses_partitions():
    records = pd.DataFrame(
        [
            gold_record("a", run="shared-run", content="hash-a", family="missing"),
            gold_record("b", run="shared-run", content="hash-b", family="rejected"),
            gold_record("c", run="other-run", content="hash-c", family="wrong"),
        ]
    )

    assigned = assign_partitions(records, seed=20260810)
    by_run = assigned.groupby("physical_run_key")["partition"].nunique()

    assert by_run.max() == 1
    validate_partition_isolation(assigned)


def test_duplicate_content_and_transitive_run_groups_stay_together():
    records = pd.DataFrame(
        [
            gold_record("a", run="run-a", content="shared-content", family="missing"),
            gold_record("b", run="run-b", content="shared-content", family="rejected"),
            gold_record("c", run="run-b", content="third-content", family="wrong"),
            gold_record("d", run="run-c", content="fourth-content", family="correct"),
        ]
    )

    assigned = assign_partitions(records, seed=7)
    partitions = assigned.set_index("record_id")["partition"]

    assert partitions["a"] == partitions["b"] == partitions["c"]
    validate_partition_isolation(assigned)


def test_assignment_is_deterministic_and_development_covers_families():
    records = pd.DataFrame(
        [
            gold_record("a", run="run-a", content="hash-a", family="missing"),
            gold_record("b", run="run-b", content="hash-b", family="wrong"),
            gold_record("c", run="run-c", content="hash-c", family="rejected"),
            gold_record("d", run="run-d", content="hash-d", family="missing"),
            gold_record("e", run="run-e", content="hash-e", family="wrong"),
            gold_record("f", run="run-f", content="hash-f", family="rejected"),
        ]
    )

    first = assign_partitions(records, seed=42)
    second = assign_partitions(records.sample(frac=1, random_state=3), seed=42)

    first_map = first.set_index("record_id")["partition"].to_dict()
    second_map = second.set_index("record_id")["partition"].to_dict()
    assert first_map == second_map
    development = first[first["partition"].eq("development")]
    assert set(development["failure_family"]) == {"missing", "wrong", "rejected"}


def test_partition_manifest_matches_benchmark_contract():
    assigned = assign_partitions(
        pd.DataFrame([gold_record("a", run="run-a", content="hash-a")]),
        seed=1,
    )
    partition = assigned.iloc[0]["partition"]

    manifest = partition_manifest(assigned, partition)

    assert manifest["partition"] == partition
    assert manifest["files"] == [
        {
            "path": "D:/allowed/a.fsa",
            "expected_scan_indices": [10, 20, 30],
            "content_sha256": "hash-a",
            "physical_run_key": "run-a",
            "ladder": "LIZ",
            "truth_source": "manual_v2",
            "failure_family": "rejected",
        }
    ]
