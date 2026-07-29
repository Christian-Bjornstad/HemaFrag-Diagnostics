from __future__ import annotations

import hashlib
from types import SimpleNamespace

from core.analysis_provenance import (
    ANALYSIS_PROVENANCE_SCHEMA,
    attach_analysis_provenance,
)
from core.ladder_adjustment_store import save_ladder_adjustment_record


def test_internal_provenance_records_manual_adjustment_and_source_hash(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "HEMAFRAG_LADDER_ADJUSTMENT_DB",
        str(tmp_path / "adjustments.sqlite3"),
    )
    source = tmp_path / "sample.fsa"
    source.write_bytes(b"fsa-bytes")
    save_ladder_adjustment_record(
        source,
        {"schema_version": "hemafrag_ladder_adjustment_v2"},
        ladder="ROX",
        size_standard_channel="DATA4",
    )
    entry = {
        "fsa": SimpleNamespace(
            file=source,
            file_name=source.name,
            size_standard_channel="DATA4",
        ),
        "file_name": source.name,
        "original_file_path": str(source),
        "ladder": "ROX",
        "ladder_fit_strategy": "manual_adjustment",
        "ladder_qc_status": "manual_adjustment",
        "ladder_review_reason_codes": ["reviewed"],
    }

    result = attach_analysis_provenance(entry)["analysis_provenance"]

    assert result["schema_version"] == ANALYSIS_PROVENANCE_SCHEMA
    assert result["source_sha256"] == hashlib.sha256(b"fsa-bytes").hexdigest()
    assert result["ladder_engine"] == "manual"
    assert result["manual_adjustment_consumed"] is True
    assert result["manual_adjustment_schema"] == "hemafrag_ladder_adjustment_v2"
    assert result["manual_adjustment_sha256"]
