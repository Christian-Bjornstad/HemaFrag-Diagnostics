"""Publish review tracking to the owning analysis and queued destinations."""
from pathlib import Path

from config import resolve_analysis_excel_output_path
from core.run_context import RunContext


def update_review_tracking_workbooks(
    entries: list[dict], output_dir: Path, analysis_id: str, *,
    run_context: RunContext | None = None,
) -> None:
    settings = run_context.settings_snapshot if run_context is not None else None
    context_kwargs = {} if settings is None else {"settings": settings}
    if analysis_id == "clonality":
        from core.analyses.clonality.tracking_excel import (
            CLONALITY_TRACKING_FILENAME as filename,
            update_clonality_tracking_workbook as update_local,
        )
        local_kwargs = context_kwargs
    elif analysis_id == "flt3":
        from core.analyses.flt3.qc_tracker import (
            FLT3_TRACKING_FILENAME as filename,
            update_flt3_npm1_qc_tracker_workbook as update_local,
        )
        local_kwargs = {}
    else:
        return

    path = resolve_analysis_excel_output_path(
        analysis_id, output_dir, filename,
        settings=(run_context.settings_copy() if run_context is not None else None),
    )
    if path is not None:
        update_local(path, entries, **local_kwargs)
