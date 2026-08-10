from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from core.research.ladder.contracts import ResearchRoots
from core.research.ladder.corrections import (
    discover_adjustments,
    parse_adjustment_sidecar,
    reconcile_manual_evidence,
)


def fake_roots(tmp_path: Path) -> ResearchRoots:
    data = tmp_path / "DATA"
    raw_roots = tuple(data / name for name in ("2024_DATA", "2025_data", "2026_data"))
    for root in raw_roots:
        root.mkdir(parents=True)
    return ResearchRoots(
        raw_roots=raw_roots,
        archive_root=tmp_path / "archive",
        output_root=tmp_path / "research",
        excluded_backup_root=data / "backup",
    )


def write_source(tmp_path: Path, name: str = "sample.fsa") -> Path:
    source = tmp_path / name
    source.write_bytes(b"fsa-content")
    return source


def write_sidecar(source: Path, payload: dict[str, object]) -> Path:
    sidecar = source.with_suffix(".ladder_adj.json")
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    return sidecar


def legacy_payload(steps: tuple[int, ...]) -> dict[str, object]:
    return {
        "mapping": {str(step): ordinal for ordinal, step in enumerate(steps)},
        "mapping_times": {str(step): 100.0 + ordinal * 10 for ordinal, step in enumerate(steps)},
        "manual_candidates": [100.0 + ordinal * 10 for ordinal in range(len(steps))],
    }


def v2_payload(source: Path, *, source_hash: str | None = None) -> dict[str, object]:
    times = [100.0 + index * 10 for index in range(16)]
    return {
        "schema_version": "hemafrag_ladder_adjustment_v2",
        "source": {
            "file_name": source.name,
            "sha256": source_hash or hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "analysis": {
            "analysis_id": "clonality",
            "assay": "TCRgA",
            "ladder": "LIZ500_250",
            "size_standard_channel": "DATA4",
        },
        "mapping": {str(index): index for index in range(16)},
        "mapping_times": {str(index): time for index, time in enumerate(times)},
        "selected_peaks": [
            {
                "step_index": index,
                "candidate_index": index,
                "expected_bp": float(index),
                "observed_time": time,
            }
            for index, time in enumerate(times)
        ],
        "review": {"operator": "chemist", "saved_at_utc": "2026-01-01T00:00:00Z"},
        "validation": {"save_verified": True},
    }


def test_legacy_partial_mapping_preserves_missing_step(tmp_path):
    source = write_source(tmp_path)
    selected_steps = tuple(index for index in range(16) if index != 14)
    sidecar = write_sidecar(source, legacy_payload(selected_steps))

    record = parse_adjustment_sidecar(
        sidecar,
        source,
        expected_ladder="LIZ",
        expected_step_count=16,
    )

    assert record.selected_steps == selected_steps
    assert record.complete is False
    assert record.ladder == "LIZ"
    assert "partial_mapping" in record.issue_codes


def test_complete_configured_legacy_mapping_is_gold_eligible(tmp_path):
    source = write_source(tmp_path)
    sidecar = write_sidecar(source, legacy_payload(tuple(range(16))))

    record = parse_adjustment_sidecar(
        sidecar,
        source,
        expected_ladder="LIZ",
        expected_step_count=16,
    )

    assert record.schema_kind == "legacy"
    assert record.complete is True
    assert record.gold_eligible is True


def test_legacy_mapping_without_inventory_configuration_is_not_gold(tmp_path):
    source = write_source(tmp_path)
    sidecar = write_sidecar(source, legacy_payload(tuple(range(16))))

    record = parse_adjustment_sidecar(sidecar, source)

    assert record.gold_eligible is False
    assert "legacy_configuration_missing" in record.issue_codes


def test_v2_hash_mismatch_is_not_gold_eligible(tmp_path):
    source = write_source(tmp_path)
    sidecar = write_sidecar(source, v2_payload(source, source_hash="0" * 64))

    record = parse_adjustment_sidecar(sidecar, source)

    assert record.gold_eligible is False
    assert "source_hash_mismatch" in record.issue_codes


def test_discovery_ignores_appledouble_sidecars(tmp_path):
    roots = fake_roots(tmp_path)
    run = roots.raw_roots[1] / "run-a"
    run.mkdir()
    source = write_source(run)
    write_sidecar(source, legacy_payload(tuple(range(16))))
    (run / "._sample.ladder_adj.json").write_bytes(b"\x00\x05not-json")

    records = discover_adjustments(roots)

    assert len(records) == 1
    assert records[0].source_path == source.resolve()


def test_reconciliation_keeps_annotation_and_workbook_evidence_without_sidecar(tmp_path):
    roots = fake_roots(tmp_path)
    source = roots.raw_roots[0] / "run-a" / "sample.fsa"
    source.parent.mkdir()
    source.write_bytes(b"fsa")
    reviews = pd.DataFrame(
        [
            {
                "resolved_full_path": str(source.resolve()),
                "full_path": r"F:\DATA\2024_DATA\run-a\sample.fsa",
                "label": "manual_adjusted",
                "adjustment_path": r"F:\DATA\2024_DATA\run-a\sample.ladder_adj.json",
            }
        ]
    )
    tracking = pd.DataFrame(
        [
            {
                "IdentityKey": "run-a::sample.fsa",
                "File": "sample.fsa",
                "SourceRunDir": "run-a",
                "ManualAdjustmentUsed": True,
            }
        ]
    )

    result = reconcile_manual_evidence([], reviews, tracking)

    assert set(result.evidence["evidence_kind"]) == {"annotation", "workbook"}
    assert set(result.issues["issue_code"]) == {
        "annotation_sidecar_missing",
        "workbook_manual_without_sidecar",
    }
    assert result.summary["sidecar_record_count"] == 0
