"""HemaFrag GUI Qt — QThreadPool worker callables for `tab_ladder`.

Phase 12.1 — extracted from the previously-monolithic
`gui_qt/tabs/tab_ladder/_legacy.py` so they can be unit-tested
without a Qt event loop running.

Pure-Python worker bodies — they take simple types and return plain
dicts / lists. The result and error wiring stays on `TabLadder`;
the callables here only do CPU-bound or IO-bound work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gui_qt.ladder_utils import detect_fsa_for_ladder, load_adjustable_fsa
from core.html_reports import extract_dit_from_name

from gui_qt.tabs.tab_ladder._summary import entry_cache_key


def scan_fsa_files_worker(source: Path) -> list[Path]:
    """Return every .fsa in `source`, sorted by lowercased filename."""
    return sorted(source.rglob("*.fsa"), key=lambda p: p.name.lower())


def load_metadata_worker(file_path: Path, analysis_id: str | None) -> dict:
    """Detect + load an FSA + return a dict for the GUI to apply."""
    meta = detect_fsa_for_ladder(file_path, preferred_analysis=analysis_id)
    if not meta:
        return {"file_path": file_path, "meta": None, "fsa": None}
    fsa, refreshed_meta = load_adjustable_fsa(
        file_path, preferred_analysis=analysis_id, metadata=meta
    )
    return {"file_path": file_path, "meta": refreshed_meta, "fsa": fsa}


def find_report_matches_worker(file_path: Path, root_text: str) -> dict:
    """Match HTML reports whose filename carries the DIT or FSA stem.

    Walks `root_text` and returns report paths that contain any of
    those tokens, so a user who picked a single file gets the right
    subset of HTML reports back without having to enumerate them.
    """
    root = Path(root_text).expanduser()
    if not root.exists():
        raise FileNotFoundError("Report root does not exist.")

    dit = extract_dit_from_name(file_path.name)
    stem = file_path.stem.lower()
    tokens = [token for token in [dit, stem] if token]

    html_matches = []
    for path in root.rglob("*.html"):
        lower = path.name.lower()
        if any(token.lower() in lower for token in tokens):
            html_matches.append(path)

    return {"root": root, "matches": sorted(set(html_matches))}


def review_bundle_rerun_worker(
    file_paths: list[Path],
    session_entries: list[dict],
    output_root: Path,
    analysis_id: str,
    pipeline_scope: str,
    assay_filter: str,
    aggregate_dit_reports: bool,
    aggregate_by_patient: bool,
    patient_regex: str,
    aggregate_outdir_name: str | None,
) -> dict:
    """Run batch_jobs() over the bundle's resolved files only.

    Preserves the old static-method body byte-for-byte for backward
    compatibility. Has special session-cache wiring that defers
    tracking-workbook refresh + DIT HTML reports in-process so the
    user does not need to switch tabs and click 'Run Manual Fixes
    + Build DIT' themselves.
    """
    # Lazy imports keep the rest of `tab_ladder` importable
    # without the heavy batch runtime stack loaded.
    from config import APP_SETTINGS
    from core.batch import generate_jobs, run_batch_jobs

    APP_SETTINGS["active_analysis"] = analysis_id
    jobs = generate_jobs(
        file_paths,
        aggregate_patients=aggregate_by_patient,
        patient_regex=patient_regex,
    )
    if not jobs:
        raise RuntimeError(
            "No runnable jobs could be generated for the reviewed files."
        )

    has_session_cache = (
        bool(session_entries)
        and aggregate_dit_reports
        and analysis_id == "clonality"
    )
    result = run_batch_jobs(
        jobs=jobs,
        output_base=output_root,
        out_folder_tmpl="ASSAY_REPORTS",
        outfile_html_tmpl="QC_REPORT_{name}.html",
        excel_name_tmpl="HemaFrag_QC_Trends.xlsx",
        pipeline_scope=pipeline_scope,
        assay_filter=assay_filter,
        aggregate_dit_reports=aggregate_dit_reports,
        continue_on_error=True,
        update_callback=None,
        aggregate_outdir_name=aggregate_outdir_name,
        defer_tracking_workbook_refresh=has_session_cache,
        defer_dit_html_reports=has_session_cache,
        preserve_deferred_entries=has_session_cache,
    )

    final_session_reports_built = False
    final_session_entry_count = 0
    gate = result.get("ladder_review_gate") or {}
    review_count = (
        int(gate.get("review_case_count") or 0) if isinstance(gate, dict) else 0
    )

    combined_entries: list[dict] = []
    if has_session_cache:
        combined_by_path: dict[Path, dict] = {}
        for entry in session_entries:
            cache_key = entry_cache_key(entry)
            if cache_key is not None:
                combined_by_path[cache_key] = entry
        for entry in result.get("collected_entries") or []:
            cache_key = entry_cache_key(entry)
            if cache_key is not None:
                combined_by_path[cache_key] = entry

        combined_entries = list(combined_by_path.values())
        if combined_entries:
            result["collected_entries"] = combined_entries

    if has_session_cache and review_count <= 0 and not result.get("failed_jobs"):
        if combined_entries:
            from core.assay_config import OUTDIR_NAME
            from core.html_reports import build_dit_html_reports
            from core.analyses.clonality.tracking_excel import (
                CLONALITY_TRACKING_FILENAME,
                update_global_clonality_tracking_workbook,
                update_clonality_tracking_workbook,
            )
            from config import resolve_analysis_excel_output_path

            agg_outdir = output_root / (aggregate_outdir_name or OUTDIR_NAME)
            agg_outdir.mkdir(parents=True, exist_ok=True)
            build_dit_html_reports(combined_entries, agg_outdir)
            update_clonality_tracking_workbook(
                resolve_analysis_excel_output_path(
                    "clonality",
                    agg_outdir,
                    CLONALITY_TRACKING_FILENAME,
                ),
                combined_entries,
            )
            try:
                update_global_clonality_tracking_workbook(combined_entries)
            except Exception:
                pass
            result["final_session_reports_built"] = True
            result["final_session_entry_count"] = len(combined_entries)
            final_session_reports_built = True
            final_session_entry_count = len(combined_entries)

    matches_by_file: dict[str, list[Path]] = {}
    for file_path in file_paths:
        try:
            report_result = find_report_matches_worker(file_path, str(output_root))
            matches_by_file[str(file_path)] = list(report_result.get("matches", []))
        except Exception:
            matches_by_file[str(file_path)] = []

    return {
        "file_paths": file_paths,
        "output_root": output_root,
        "jobs": jobs,
        "result": result,
        "matches_by_file": matches_by_file,
        "final_session_reports_built": final_session_reports_built,
        "final_session_entry_count": final_session_entry_count,
    }


def single_file_rerun_worker(
    file_path: Path,
    output_root: Path,
    analysis_id: str,
    pipeline_scope: str,
    assay_filter: str,
    aggregate_dit_reports: bool,
    aggregate_by_patient: bool,
    patient_regex: str,
    aggregate_outdir_name: str | None,
) -> dict:
    """Run a single-file batch_jobs() invocation and return its result."""
    # Lazy imports keep the rest of `tab_ladder` importable without
    # the heavy batch/runtime stack loaded.
    from config import APP_SETTINGS
    from core.batch import generate_jobs, run_batch_jobs

    APP_SETTINGS["active_analysis"] = analysis_id
    jobs = generate_jobs(
        [file_path],
        aggregate_patients=aggregate_by_patient,
        patient_regex=patient_regex,
    )
    if not jobs:
        raise RuntimeError(f"No runnable job could be generated for {file_path.name}.")

    result = run_batch_jobs(
        jobs=jobs,
        output_base=output_root,
        out_folder_tmpl="ASSAY_REPORTS",
        outfile_html_tmpl="QC_REPORT_{name}.html",
        excel_name_tmpl="HemaFrag_QC_Trends.xlsx",
        pipeline_scope=pipeline_scope,
        assay_filter=assay_filter,
        aggregate_dit_reports=aggregate_dit_reports,
        continue_on_error=True,
        update_callback=None,
        aggregate_outdir_name=aggregate_outdir_name,
    )
    try:
        report_result = find_report_matches_worker(file_path, str(output_root))
        matches = list(report_result.get("matches", []))
    except Exception:
        matches = []
    return {
        "file_path": file_path,
        "output_root": output_root,
        "jobs": jobs,
        "result": result,
        "matches": matches,
    }
