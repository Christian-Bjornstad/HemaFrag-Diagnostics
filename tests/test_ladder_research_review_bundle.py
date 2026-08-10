from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from core.research.ladder.contracts import ResearchRoots
from core.research.ladder.review_bundle import prepare_development_review_bundle
from gui_qt.tabs.tab_ladder._io import load_review_bundle_worker


def _write_manifest(tmp_path: Path, *, bad_hash: bool = False) -> tuple[Path, ResearchRoots]:
    data_root = tmp_path / "DATA"
    raw_root = data_root / "2025_data"
    raw_root.mkdir(parents=True)
    records = []
    for ordinal, payload in enumerate((b"first-fsa", b"second-fsa", b"third-fsa"), 1):
        source = raw_root / f"run-{ordinal}" / "duplicate-name.fsa"
        source.parent.mkdir()
        source.write_bytes(payload)
        source.with_suffix(".ladder_adj.json").write_text("historical", encoding="utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        records.append(
            {
                "path": str(source),
                "content_sha256": ("0" * 64 if bad_hash and ordinal == 1 else digest),
                "physical_run_key": f"2025_data/run-{ordinal}",
                "ladder": "ROX" if ordinal == 3 else "LIZ",
                "truth_source": "manual_legacy",
                "failure_family": "manual_corrected",
                "expected_scan_indices": [10, 20, 30],
            }
        )
    manifest = tmp_path / "development_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "partition": "development",
                "file_count": 3,
                "files": records,
            }
        ),
        encoding="utf-8",
    )
    roots = ResearchRoots(
        raw_roots=(raw_root,),
        archive_root=tmp_path / "archive",
        output_root=tmp_path / "research",
        excluded_backup_root=data_root / "backup",
    )
    return manifest, roots


def test_prepare_bundle_copies_fsa_without_historical_sidecar(tmp_path: Path):
    manifest, roots = _write_manifest(tmp_path)
    bundle = roots.output_root / "current" / "development_review_bundle"

    result = prepare_development_review_bundle(manifest, bundle, roots)

    assert result.case_count == 3
    assert result.adjustment_database == bundle / "ladder_adjustments.sqlite3"
    assert len(list(bundle.rglob("*.fsa"))) == 3
    assert not list(bundle.rglob("*.ladder_adj.json"))
    loaded = load_review_bundle_worker(bundle)
    assert len(loaded["rows"]) == 3
    assert loaded["missing_paths"] == []
    with (bundle / "ladder_review_cases.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert [row["label"] for row in rows] == ["", "", ""]
    assert [Path(row["full_path"]).parent.name for row in rows] == ["001", "002", "003"]
    assert "HEMAFRAG_LADDER_ADJUSTMENT_DB" in (bundle / "README.md").read_text(
        encoding="utf-8"
    )


def test_prepare_bundle_rejects_manifest_hash_mismatch(tmp_path: Path):
    manifest, roots = _write_manifest(tmp_path, bad_hash=True)
    bundle = roots.output_root / "current" / "development_review_bundle"

    with pytest.raises(ValueError, match="SHA-256"):
        prepare_development_review_bundle(manifest, bundle, roots)

    assert not bundle.exists()


def test_prepare_bundle_refuses_nonempty_destination(tmp_path: Path):
    manifest, roots = _write_manifest(tmp_path)
    bundle = roots.output_root / "current" / "development_review_bundle"
    bundle.mkdir(parents=True)
    marker = bundle / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="non-empty"):
        prepare_development_review_bundle(manifest, bundle, roots)

    assert marker.read_text(encoding="utf-8") == "keep"
