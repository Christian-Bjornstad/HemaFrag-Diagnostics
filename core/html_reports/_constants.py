"""
HemaFrag — html_reports constants and inline styles.

Auto-curated from the previously-monolithic `core/html_reports.py` during
the 2026-06-27 `code-cleanup` Phase 6. Re-exported via the package
facade unchanged.
"""
import re

__all__ = [
    "DIT_PATTERN",
    "DIT_QC_CONTROL_IDS",
    "REPORT_STYLE",
    "D835_DIGEST_HEIGHT_MIN",
    "D835_DIGEST_AREA_MIN",
]


DIT_PATTERN = re.compile(r"(\d{2}OUM\d{5})")
DIT_QC_CONTROL_IDS = {"PK", "PK1", "PK2", "NK", "RK"}


REPORT_STYLE = """
<style>
/* ── Base Typography ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

body {
    font-family: 'Inter', -apple-system, sans-serif;
    margin: 1.5rem 2rem 5rem;
    background: #f4f7fb;
    color: #0f172a;
    line-height: 1.5;
}
h1 { font-size: 1.6rem; font-weight: 800; color: #0f172a; margin-bottom: 0.2rem; }
h2 { font-size: 1.15rem; font-weight: 700; color: #1e293b; margin-top: 2rem; margin-bottom: 0.5rem; padding-bottom: 6px; border-bottom: 2px solid #e2e8f0; }
h3 { font-size: 1rem; font-weight: 700; color: #4338ca; margin-top: 1rem; margin-bottom: 0.3rem; }
p  { margin-top: 0.2rem; margin-bottom: 0.4rem; color: #334155; }

/* ── Header banner ── */
.report-header {
    background: linear-gradient(135deg, #06b6d4 0%, #4338ca 100%);
    color: white;
    padding: 24px 28px;
    border-radius: 12px;
    margin-bottom: 24px;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.05);
}
.report-header h1 { color: white; font-size: 1.8rem; font-weight: 800; margin: 0 0 4px; letter-spacing: -0.6px; }
.report-header .meta { font-size: 0.9rem; font-weight: 500; color: rgba(255, 255, 255, 0.85); }

/* ── Tables ── */
table { 
    border-collapse: collapse; 
    margin-bottom: 1.2rem; 
    width: 100%; 
    background: white; 
    border-radius: 8px; 
    overflow: hidden; 
    box-shadow: 0 4px 12px rgba(0,0,0,0.03); 
}
th, td { border-bottom: 1px solid #e2e8f0; padding: 12px 14px; font-size: 0.85rem; }
th { 
    background: #f8fafc; 
    font-weight: 800; 
    color: #4338ca; 
    text-transform: uppercase; 
    font-size: 0.75rem; 
    letter-spacing: 0.8px; 
    border-bottom: 2px solid #e2e8f0;
}
tr:nth-child(even) td { background: #fafbfc; }
tr:hover td { background: #f0fdfa; /* Soft teal hover */ transition: background 0.15s ease; }

.status-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    white-space: nowrap;
}
.status-badge.ok {
    background: #dcfce7;
    color: #166534;
}
.status-badge.warning {
    background: #fef3c7;
    color: #92400e;
}
.status-badge.manual {
    background: #dbeafe;
    color: #1d4ed8;
}
.status-badge.failed {
    background: #fee2e2;
    color: #b91c1c;
}
.status-badge.unknown {
    background: #e2e8f0;
    color: #475569;
}

/* ── Cards ── */
.assay-block {
    padding: 18px 22px;
    margin-bottom: 20px;
    background: #ffffff;
    border-radius: 12px;
    border: 1px solid rgba(226, 232, 240, 0.8);
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.01);
    transition: box-shadow 0.3s ease;
}
.assay-block:hover { box-shadow: 0 14px 28px -5px rgba(0, 0, 0, 0.08); }
.sample-header { font-size: 0.9rem; font-weight: 700; margin-top: 0.4rem; color: #0f172a; }
.small { font-size: 0.85rem; color: #64748b; font-weight: 500; }
.peak-editor-block { margin-top: 0.5rem; margin-bottom: 1.2rem; border-radius: 8px; overflow: hidden; }
.combo-grid { display: block; }
.combo-item { margin-bottom: 1.2rem; }
/* ── Floating Print Button ── */
.print-fab {
    position: fixed;
    bottom: 28px;
    right: 28px;
    z-index: 9999;
    display: flex;
    gap: 10px;
    align-items: center;
    flex-direction: column;
}
.print-btn {
    background: linear-gradient(135deg, #06b6d4, #4338ca);
    color: white;
    border: none;
    border-radius: 50px;
    padding: 14px 26px;
    font-size: 14px;
    font-weight: 700;
    font-family: inherit;
    cursor: pointer;
    box-shadow: 0 6px 16px rgba(67, 56, 202, 0.4);
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    display: flex;
    align-items: center;
    gap: 8px;
    white-space: nowrap;
    letter-spacing: 0.3px;
}
.print-btn:hover { transform: translateY(-3px); box-shadow: 0 10px 20px rgba(67, 56, 202, 0.5); filter: brightness(1.1); }
.print-btn:active { transform: translateY(0); }

/* ── Print Media ── */
@media print {
    .print-fab { display: none !important; }
    body { background: white; color: black; margin: 0; font-size: 11pt; line-height: 1.4; }
    .report-header { background: #4338ca; -webkit-print-color-adjust: exact; print-color-adjust: exact; border-radius: 0; margin: 0 0 16px; box-shadow: none; }
    h1 { font-size: 18pt; }
    h2 { font-size: 13pt; page-break-after: avoid; }
    h3 { font-size: 11pt; page-break-after: avoid; }
    .assay-block { border: 1px solid #e2e8f0; page-break-inside: avoid; box-shadow: none; margin-bottom: 10px; }
    .peak-editor-block { page-break-inside: avoid; border: none; }
    table { page-break-inside: avoid; box-shadow: none; border: 1px solid #e2e8f0; }
    th { background: #f8fafc !important; color: #0f172a; -webkit-print-color-adjust: exact; print-color-adjust: exact; border-bottom: 1px solid #cbd5e1; }
    td { border-bottom: 1px solid #e2e8f0; }
    img { max-width: 100%; page-break-inside: avoid; }
    .modebar { display: none !important; }
    .js-plotly-plot .plotly .modebar { display: none !important; }
}

/* ── Save Peaks Button ── */
.save-peaks-btn {
    background: #0ea5e9;
    color: white;
    box-shadow: 0 6px 16px rgba(14, 165, 233, 0.4);
}
.save-peaks-btn:hover {
    box-shadow: 0 10px 20px rgba(14, 165, 233, 0.5);
}

/* ── Interactive Peak Tables ── */
.peak-table-container {
    margin-top: 10px;
    padding: 0 10px 10px 10px;
}
.peak-table-container table {
    width: auto;
    min-width: 300px;
    margin: 0;
    box-shadow: none;
    border: 1px solid #e2e8f0;
}
.peak-table-container th {
    padding: 8px 12px;
    background: #f1f5f9;
}
.peak-table-container td {
    padding: 6px 12px;
}
.peak-table-container tr.selected-wt td {
    background: #dbeafe !important;
}
.peak-table-container tr.selected-mut td {
    background: #dcfce7 !important;
}

.dit-qc-section {
    margin-top: 2rem;
    margin-bottom: 1.5rem;
    padding: 0;
    background: #ffffff;
    border-radius: 8px;
    border: 1px solid rgba(226, 232, 240, 0.9);
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.04);
}
.dit-qc-section summary {
    cursor: pointer;
    padding: 14px 18px;
    font-weight: 800;
    color: #1e293b;
}
.dit-qc-section[open] summary {
    border-bottom: 1px solid #e2e8f0;
}
.dit-qc-body {
    padding: 16px 18px 18px;
}

/* ── Comment Boxes ── */
.comment-box-container {
    margin-top: 15px;
    border-radius: 8px;
    border: 1px dashed #cbd5e1;
    background: #f8fafc;
    overflow: hidden;
    transition: border-color 0.2s ease;
}
.comment-box-container:has(.comment-body.open) {
    border-color: #0ea5e9;
}
.comment-toggle-btn {
    width: 100%;
    background: none;
    border: none;
    padding: 10px 14px;
    text-align: left;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    font-family: inherit;
    font-size: 0.85rem;
    font-weight: 600;
    color: #64748b;
    transition: color 0.15s ease, background 0.15s ease;
    user-select: none;
}
.comment-toggle-btn:hover { color: #0ea5e9; background: #f1f5f9; }
.comment-toggle-btn .caret {
    margin-left: auto;
    transition: transform 0.2s ease;
    font-style: normal;
    font-size: 0.75rem;
    opacity: 0.6;
}
.comment-body {
    display: none;
    padding: 0 14px 14px;
}
.comment-body.open { display: block; }
.report-comment {
    width: 100%;
    min-height: 80px;
    padding: 10px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    font-family: inherit;
    font-size: 0.9rem;
    resize: vertical;
    box-sizing: border-box;
    background: white;
}
.report-comment:focus {
    outline: none;
    border-color: #0ea5e9;
    box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.2);
}

@media print {
    .comment-box-container { border: none; background: transparent; }
    .comment-toggle-btn { display: none; }
    .comment-body { display: block !important; padding: 0; }
    .report-comment { border: none; padding: 0; resize: none; overflow: hidden; background: transparent; }
}
</style>
"""


D835_DIGEST_HEIGHT_MIN = 100.0
D835_DIGEST_AREA_MIN = 500.0
