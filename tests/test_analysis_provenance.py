from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from core.analysis_provenance import (
    ANALYSIS_PROVENANCE_SCHEMA,
    attach_analysis_provenance,
)
from core.html_reports._legacy import _render_analysis_provenance_table


def test_analysis_provenance_records_manual_sidecar_and_source_hash(tmp_path):
    source = tmp_path / "sample.fsa"
    source.write_bytes(b"fsa-bytes")
    sidecar = source.with_suffix(".ladder_adj.json")
    sidecar.write_text(
        json.dumps({"schema_version": "hemafrag_ladder_adjustment_v2"}),
        encoding="utf-8",
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


def test_report_provenance_table_escapes_values_and_shows_full_hash():
    digest = "a" * 64
    entries = [
        {
            "file_name": "sample<1>.fsa",
            "analysis_provenance": {
                "source_file": "sample<1>.fsa",
                "source_sha256": digest,
                "ladder_engine": "rust",
                "ladder_fit_strategy": "auto_full",
                "manual_adjustment_consumed": False,
                "ladder_reason_codes": ["tail<warning"],
                "app_version": "1.2.3",
            },
        }
    ]
    html_lines: list[str] = []

    _render_analysis_provenance_table(entries, html_lines)
    html = "".join(html_lines)

    assert digest in html
    assert "sample&lt;1&gt;.fsa" in html
    assert "tail&lt;warning" in html
    assert "Analyseproveniens" in html
