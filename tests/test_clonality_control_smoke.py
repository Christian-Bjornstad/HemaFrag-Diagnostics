import json
import os
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from core.analyses.clonality.pipeline import run_pipeline
from core.rust_bridge import reset_rust_engine_stats, rust_engine_stats_snapshot


@pytest.mark.skipif(
    os.environ.get("HEMAFRAG_RUN_CONTROL_SMOKE") != "1",
    reason="set HEMAFRAG_RUN_CONTROL_SMOKE=1 to run the real clonality control smoke",
)
def test_clonality_control_smoke_preserves_tracking_contract(tmp_path):
    fsa_dir = Path("data/kontroll/filer_kontroll")
    if not fsa_dir.exists():
        pytest.skip("control FSA directory is not available")

    tracking_path = tmp_path / "clonality_tracking.xlsx"
    reset_rust_engine_stats()
    entries = run_pipeline(
        fsa_dir=fsa_dir,
        base_outdir=tmp_path,
        assay_folder_name="reports_smoke",
        return_entries=True,
        make_dit_reports=False,
        mode="all",
        tracking_excel_path=tracking_path,
        update_tracking_workbook=True,
    )

    entries = entries or []
    ladder_status = Counter(str(entry.get("ladder_qc_status") or "") for entry in entries)
    assays = Counter(str(entry.get("assay") or "") for entry in entries)
    rust_stats = rust_engine_stats_snapshot()

    summary = {
        "entries": len(entries),
        "ladder_status": dict(ladder_status),
        "assays": dict(sorted(assays.items())),
        "rust_engine_stats": rust_stats,
        "tracking": str(tracking_path),
    }
    (tmp_path / "control_smoke_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    assert len(entries) == 41
    assert ladder_status == {"ok": 41}
    assert rust_stats["failures"] == 0
    assert rust_stats["prewarm_cached"] == 41
    assert rust_stats["cache_hits"] == 41
    assert tracking_path.exists()

    pk_peaks = pd.read_excel(tracking_path, sheet_name="PK_Peaks")
    assert len(pk_peaks) == 41
    assert pk_peaks["OK"].eq(True).all()
    assert set(pk_peaks["Assay"].astype(str)) == set(assays)
