"""HemaFrag — Two-file comparison HTML report builder.

Given two analysis entry dicts (same assay, same or different DITs),
produces a single HTML report with side-by-side interactive plots
and peak tables for direct visual comparison.
"""
from __future__ import annotations

import time
from pathlib import Path
from html import escape
from typing import Any

import numpy as np

from core.html_reports._constants import REPORT_STYLE
from core.html_reports._legacy import (
    _atomic_write_html,
    _build_report_plot_fragment,
    _create_html_header,
    _format_report_metrics_summary,
    _new_report_metrics,
    _render_ighv_sample_type_line,
)
from core.plotting_plotly import compute_group_ymax_for_entries
from fraggler.fraggler import print_green


def build_comparison_html_report(
    entry_a: dict[str, Any],
    entry_b: dict[str, Any],
    outdir: Path,
    *,
    report_name: str | None = None,
) -> Path:
    """Build a side-by-side comparison HTML report for two entries.

    Args:
        entry_a: First analysis entry dict (from pipeline).
        entry_b: Second analysis entry dict (from pipeline).
        outdir: Output directory for the HTML file.
        report_name: Optional custom name for the report file (without extension).

    Returns:
        Path to the generated HTML file.

    Raises:
        ValueError: If entries have different assay types.
    """
    assay_a = entry_a.get("assay", "")
    assay_b = entry_b.get("assay", "")
    if assay_a != assay_b:
        raise ValueError(
            f"Cannot compare different assays: {assay_a} vs {assay_b}. "
            "Comparison requires identical assay type."
        )

    dit_a = entry_a.get("dit") or "no-dit"
    dit_b = entry_b.get("dit") or "no-dit"
    fsa_a = entry_a["fsa"].file_name
    fsa_b = entry_b["fsa"].file_name

    # Generate a stable filename
    if report_name is None:
        base_a = Path(fsa_a).stem
        base_b = Path(fsa_b).stem
        report_name = f"COMPARE_{dit_a}_{base_a}_vs_{dit_b}_{base_b}"

    html_path = outdir / f"{report_name}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)

    # Compute shared Y-axis max so both plots have identical scale
    ymax = compute_group_ymax_for_entries([entry_a, entry_b])

    # Build the HTML
    html_lines: list[str] = []
    report_metrics = _new_report_metrics()
    started = time.perf_counter()

    # Use the first DIT as "primary" for header
    primary_dit = dit_a if dit_a != "no-dit" else dit_b
    year = None
    try:
        if primary_dit and primary_dit != "no-dit":
            year = int(primary_dit[:4])
    except Exception:
        pass

    _create_html_header(
        dit=f"{dit_a} vs {dit_b}",
        year=year,
        num_entries=2,
        dit_root=html_path.parent,
        html_lines=html_lines,
        display_name=f"Comparison: {assay_a}",
    )

    # Override the title for comparison
    for i, line in enumerate(html_lines):
        if "<title>" in line:
            html_lines[i] = (
                f"<title>{escape(fsa_a)} vs {escape(fsa_b)} "
                f"({escape(assay_a)}) Comparison</title>"
            )
            break

    # Comparison header
    html_lines.append(
        f"<div class='comparison-header'>"
        f"<h2>Sammenligning: {escape(assay_a)}</h2>"
        f"<p class='small'><strong>Fil A:</strong> {escape(fsa_a)} (DIT: {escape(dit_a)})</p>"
        f"<p class='small'><strong>Fil B:</strong> {escape(fsa_b)} (DIT: {escape(dit_b)})</p>"
        f"</div>"
    )

    # Build plot fragments with forced shared Y range
    html_lines.append("<div class='comparison-grid'>")

    # File A plot
    html_lines.append("<div class='comparison-column'>")
    html_lines.append(f"<h3>{escape(fsa_a)}</h3>")
    html_lines.append(
        f"<p class='small'>DIT: {escape(dit_a)} | "
        f"Kanal: {escape(entry_a.get('primary_peak_channel', ''))}</p>"
    )
    # Force shared ymax via entry mutation (temporary, restored after)
    orig_ymax_a = entry_a.get("forced_ymax")
    entry_a["forced_ymax"] = ymax
    try:
        html_lines.append(_build_report_plot_fragment(entry_a, report_metrics))
    finally:
        if orig_ymax_a is None:
            entry_a.pop("forced_ymax", None)
        else:
            entry_a["forced_ymax"] = orig_ymax_a
    html_lines.append("</div>")

    # File B plot
    html_lines.append("<div class='comparison-column'>")
    html_lines.append(f"<h3>{escape(fsa_b)}</h3>")
    html_lines.append(
        f"<p class='small'>DIT: {escape(dit_b)} | "
        f"Kanal: {escape(entry_b.get('primary_peak_channel', ''))}</p>"
    )
    orig_ymax_b = entry_b.get("forced_ymax")
    entry_b["forced_ymax"] = ymax
    try:
        html_lines.append(_build_report_plot_fragment(entry_b, report_metrics))
    finally:
        if orig_ymax_b is None:
            entry_b.pop("forced_ymax", None)
        else:
            entry_b["forced_ymax"] = orig_ymax_b
    html_lines.append("</div>")

    html_lines.append("</div>")  # comparison-grid

    # Peak tables side by side
    html_lines.append("<h2>Peak-tabeller (side ved side)</h2>")
    html_lines.append("<div class='comparison-grid'>")

    for label, entry in [("A", entry_a), ("B", entry_b)]:
        html_lines.append("<div class='comparison-column'>")
        html_lines.append(f"<h4>{escape(entry['fsa'].file_name)}</h4>")
        peaks_html = _render_peak_table_for_comparison(entry, label)
        html_lines.append(peaks_html)
        html_lines.append("</div>")

    html_lines.append("</div>")  # comparison-grid

    # Footer / metrics
    total_sec = time.perf_counter() - started
    html_lines.append(
        """
<div class="print-fab no-print">
  <button class="print-btn" onclick="printReport()">🖨&nbsp; Print / PDF</button>
</div>
</body></html>"""
    )
    _atomic_write_html(html_path, "\n".join(html_lines))
    print_green(f"[COMPARE] Lagret: {html_path}")
    print_green(
        _format_report_metrics_summary(
            f"{dit_a} vs {dit_b}",
            report_metrics,
            total_sec,
            html_path.stat().st_size,
        )
    )

    return html_path


def build_group_comparison_html_report(
    entries: list[dict[str, Any]],
    outdir: Path,
    *,
    report_name: str | None = None,
) -> Path:
    """Build a multi-file comparison HTML report grouped per assay.

    Unlike :func:`build_comparison_html_report` (exactly two files), this
    accepts any number of entries — e.g. every FSA from one or more
    selected patients. Entries are grouped by assay in first-seen order;
    each assay section shares one Y-axis max so plots are directly
    comparable within the section.

    Args:
        entries: Analysis entry dicts (from pipeline).
        outdir: Output directory for the HTML file.
        report_name: Optional custom name (without extension).

    Returns:
        Path to the generated HTML file.

    Raises:
        ValueError: If ``entries`` is empty.
    """
    clean_entries = [e for e in entries if isinstance(e, dict)]
    if not clean_entries:
        raise ValueError("No analysis entries to compare.")

    sections: dict[str, list[dict[str, Any]]] = {}
    for entry in clean_entries:
        assay = str(entry.get("assay") or "UKJENT")
        sections.setdefault(assay, []).append(entry)

    if report_name is None:
        first_dit = next(
            (str(e.get("dit")) for e in clean_entries if e.get("dit")),
            "no-dit",
        )
        report_name = f"COMPARE_GROUP_{len(clean_entries)}filer_{first_dit}"

    html_path = Path(outdir) / f"{report_name}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)

    report_metrics = _new_report_metrics()
    started = time.perf_counter()

    primary_dit = next(
        (str(e.get("dit")) for e in clean_entries if e.get("dit")), "no-dit"
    )
    year = None
    try:
        if primary_dit and primary_dit != "no-dit":
            year = int(primary_dit[:4])
    except Exception:
        pass

    assay_summary = ", ".join(f"{a} ({len(v)})" for a, v in sections.items())
    html_lines: list[str] = []
    _create_html_header(
        dit=str(primary_dit),
        year=year,
        num_entries=len(clean_entries),
        dit_root=html_path.parent,
        html_lines=html_lines,
        display_name=f"Sammenligning: {len(clean_entries)} filer",
    )

    for i, line in enumerate(html_lines):
        if "<title>" in line:
            html_lines[i] = (
                f"<title>Sammenligning: {escape(assay_summary)}"
                f" — {len(clean_entries)} filer</title>"
            )
            break

    html_lines.append(
        "<div class='comparison-header'>"
        f"<h2>Sammenligning: {len(clean_entries)} filer</h2>"
        f"<p class='small'><strong>Analyser:</strong> {escape(assay_summary)}</p>"
        "</div>"
    )

    for assay, group_entries in sections.items():
        html_lines.append(
            f"<h2 class='comparison-section-title'>{escape(assay)}"
            f" ({len(group_entries)} filer)</h2>"
        )

        ymax = compute_group_ymax_for_entries(group_entries)

        html_lines.append("<div class='comparison-grid'>")
        for entry in group_entries:
            fsa_name = str(getattr(entry["fsa"], "file_name", "?"))
            dit = str(entry.get("dit") or "no-dit")
            channel = str(entry.get("primary_peak_channel", ""))
            html_lines.append("<div class='comparison-column'>")
            html_lines.append(f"<h3>{escape(fsa_name)}</h3>")
            html_lines.append(
                f"<p class='small'>DIT: {escape(dit)} | "
                f"Kanal: {escape(channel)}</p>"
            )
            if assay.startswith("IGHV"):
                # Prøvetype (DNA/RNA) + aktivt referanseområde per fil.
                html_lines.append(_render_ighv_sample_type_line(entry))
            orig_ymax = entry.get("forced_ymax")
            entry["forced_ymax"] = ymax
            try:
                html_lines.append(
                    _build_report_plot_fragment(entry, report_metrics)
                )
            finally:
                if orig_ymax is None:
                    entry.pop("forced_ymax", None)
                else:
                    entry["forced_ymax"] = orig_ymax
            html_lines.append("</div>")
        html_lines.append("</div>")  # comparison-grid

        html_lines.append("<h3>Peak-tabeller</h3>")
        html_lines.append("<div class='comparison-grid'>")
        for idx, entry in enumerate(group_entries, start=1):
            html_lines.append("<div class='comparison-column'>")
            html_lines.append(
                f"<h4>{escape(str(getattr(entry['fsa'], 'file_name', '?')))}</h4>"
            )
            html_lines.append(
                _render_peak_table_for_comparison(entry, str(idx))
            )
            html_lines.append("</div>")
        html_lines.append("</div>")  # comparison-grid

    total_sec = time.perf_counter() - started
    html_lines.append(
        """
<div class="print-fab no-print">
  <button class="print-btn" onclick="printReport()">🖨&nbsp; Print / PDF</button>
</div>
</body></html>"""
    )
    _atomic_write_html(html_path, "\n".join(html_lines))
    print_green(f"[COMPARE] Lagret gruppe-rapport: {html_path}")
    print_green(
        _format_report_metrics_summary(
            f"group:{primary_dit}",
            report_metrics,
            total_sec,
            html_path.stat().st_size,
        )
    )
    return html_path


def _render_peak_table_for_comparison(entry: dict[str, Any], label: str) -> str:
    """Render a simplified peak table for comparison view."""
    from core.html_reports._legacy import pd

    peaks_by_channel = entry.get("peaks_by_channel", {})
    primary_ch = entry.get("primary_peak_channel", "")
    df = peaks_by_channel.get(primary_ch)

    if df is None or df.empty:
        return (
            "<p class='small'><em>Ingen peaks oppdaget i primær kanal.</em></p>"
        )

    # Select relevant columns
    cols = ["basepairs", "peaks", "area"]
    available = [c for c in cols if c in df.columns]
    if not available:
        return "<p class='small'><em>Peak data ufullstendig.</em></p>"

    tbl = df[available].copy()
    tbl = tbl.sort_values("basepairs").reset_index(drop=True)

    # HTML table
    lines = [
        "<table class='peak-table-comparison'>",
        "<thead><tr>",
        "<th>#</th>",
        "<th>Størrelse (bp)</th>",
        "<th>Høyde (RFU)</th>",
        "<th>Areal</th>",
        "</tr></thead>",
        "<tbody>",
    ]
    for idx, row in tbl.iterrows():
        bp = row.get("basepairs", np.nan)
        ht = row.get("peaks", np.nan)
        ar = row.get("area", np.nan)
        bp_txt = f"{bp:.1f}" if np.isfinite(bp) else "&mdash;"
        ht_txt = f"{ht:.0f}" if np.isfinite(ht) else "&mdash;"
        ar_txt = f"{ar:.0f}" if np.isfinite(ar) else "&mdash;"
        lines.append(
            f"<tr><td>{idx + 1}</td>"
            f"<td>{bp_txt}</td>"
            f"<td>{ht_txt}</td>"
            f"<td>{ar_txt}</td></tr>"
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)