from __future__ import annotations

import csv
import json
import random
from collections import Counter
from pathlib import Path

import pytest

from core.research.ladder.round_two import (
    load_round_two_inputs,
    select_round_two_cohort,
)


def _candidate_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    diagnostics: list[dict[str, object]] = []
    inventory: list[dict[str, object]] = []
    ordinal = 0
    for cohort_group, ladder, count in (
        ("suspicious", "LIZ", 8),
        ("suspicious", "ROX", 8),
        ("control", "LIZ", 5),
        ("control", "ROX", 5),
    ):
        for group_ordinal in range(count):
            ordinal += 1
            source = Path(f"C:/allowed/{2024 + group_ordinal % 3}/run-{ordinal}/case-{ordinal}.fsa")
            content_hash = f"hash-{ordinal:03d}"
            outcome = (
                "fit_rejected_with_usable_signal"
                if cohort_group == "suspicious"
                else "unresolved"
            )
            diagnostics.append(
                {
                    "source_path": str(source),
                    "configured_ladder": f"{ladder}500_250",
                    "outcome": outcome,
                    "accepted": cohort_group == "control",
                    "review_required": cohort_group == "suspicious",
                    "reason_codes": [f"reason-{group_ordinal % 3}"],
                    "assay": f"assay-{group_ordinal % 2}",
                    "preview_scan_indices": [100, 200, 300],
                }
            )
            inventory.append(
                {
                    "raw_path": str(source.resolve()),
                    "file": source.name,
                    "year": str(2024 + group_ordinal % 3),
                    "physical_run_key": f"run-{ordinal:03d}",
                    "content_sha256": content_hash,
                }
            )
    return diagnostics, inventory


def _classification(row: dict[str, object]) -> str:
    if row["outcome"] == "fit_rejected_with_usable_signal":
        return "suspicious"
    return "control"


def test_round_two_selection_is_balanced_blind_and_isolated():
    diagnostics, inventory = _candidate_rows()
    manual_hashes = {"hash-018"}
    first_round_hashes = {"hash-001", "round-one-b", "round-one-c"}

    result = select_round_two_cohort(
        diagnostics, inventory, manual_hashes, first_round_hashes, seed=7
    )

    counts = Counter((case["cohort_group"], case["ladder"]) for case in result.cases)
    assert counts == {
        ("suspicious", "LIZ"): 6,
        ("suspicious", "ROX"): 6,
        ("control", "LIZ"): 3,
        ("control", "ROX"): 3,
    }
    assert len({case["content_sha256"] for case in result.cases}) == 18
    assert len({case["physical_run_key"] for case in result.cases}) == 18
    assert not first_round_hashes & {
        case["content_sha256"] for case in result.cases
    }
    assert not manual_hashes & {
        case["content_sha256"]
        for case in result.cases
        if case["cohort_group"] == "control"
    }
    assert len({case["year"] for case in result.cases}) >= 2


def test_round_two_selection_is_independent_of_input_order():
    diagnostics, inventory = _candidate_rows()
    expected = select_round_two_cohort(
        diagnostics,
        inventory,
        {"hash-018"},
        {"hash-001", "round-one-b", "round-one-c"},
        seed=17,
    )
    random.Random(11).shuffle(diagnostics)
    random.Random(29).shuffle(inventory)

    shuffled = select_round_two_cohort(
        diagnostics,
        inventory,
        {"hash-018"},
        {"hash-001", "round-one-b", "round-one-c"},
        seed=17,
    )

    assert [case["content_sha256"] for case in shuffled.cases] == [
        case["content_sha256"] for case in expected.cases
    ]


@pytest.mark.parametrize(
    ("missing_group", "missing_ladder", "expected_message"),
    [
        ("suspicious", "LIZ", "suspicious LIZ"),
        ("suspicious", "ROX", "suspicious ROX"),
        ("control", "LIZ", "control LIZ"),
        ("control", "ROX", "control ROX"),
    ],
)
def test_round_two_selection_reports_each_group_shortage(
    missing_group: str, missing_ladder: str, expected_message: str
):
    diagnostics, inventory = _candidate_rows()
    kept_diagnostics = [
        row
        for row in diagnostics
        if not (
            _classification(row) == missing_group
            and str(row["configured_ladder"]).startswith(missing_ladder)
        )
    ]

    with pytest.raises(ValueError, match=expected_message):
        select_round_two_cohort(
            kept_diagnostics,
            inventory,
            set(),
            {"round-one-a", "round-one-b", "round-one-c"},
            seed=7,
        )


def test_load_round_two_inputs_reads_existing_research_artifacts(tmp_path: Path):
    diagnostics = [{"source_path": "C:/allowed/a.fsa", "outcome": "unresolved"}]
    (tmp_path / "diagnostics.ndjson").write_text(
        "".join(json.dumps(row) + "\n" for row in diagnostics), encoding="utf-8"
    )
    inventory = [
        {
            "raw_path": "C:/allowed/a.fsa",
            "content_sha256": "inventory-hash",
            "physical_run_key": "run-a",
        }
    ]
    with (tmp_path / "inventory.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=inventory[0])
        writer.writeheader()
        writer.writerows(inventory)
    with (tmp_path / "manual_corrections.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=("source_sha256",))
        writer.writeheader()
        writer.writerow({"source_sha256": "manual-hash"})
    (tmp_path / "development_manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {"content_sha256": "round-one-a"},
                    {"content_sha256": "round-one-b"},
                    {"content_sha256": "round-one-c"},
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = load_round_two_inputs(tmp_path)

    assert loaded == (
        diagnostics,
        inventory,
        {"manual-hash"},
        {"round-one-a", "round-one-b", "round-one-c"},
    )
