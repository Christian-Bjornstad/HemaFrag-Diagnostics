"""
HemaFrag Diagnostics — DIT HTML Reports & SL Quality Interpretation.

Builds per-patient DIT HTML reports with embedded interactive Plotly figures.
"""
from __future__ import annotations

import re
import uuid
import json
import os
import tempfile
import time
from pathlib import Path
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from html import escape
from datetime import datetime


class _PandasModuleProxy:
    """Minimal module-like proxy so `pd.DataFrame()` calls and annotations
    keep working with a deferred pandas import (report building happens
    long after startup; pandas costs ~0.6 s to import)."""

    def __getattr__(self, name: str):
        import pandas

        return getattr(pandas, name)


pd = _PandasModuleProxy()

from core.analyses.registry import get_active_analysis_name
from core.analyses.flt3.distance import (
    calculate_bp_distance_metrics,
    calculate_entry_bp_distance_metrics,
)

import numpy as np

from fraggler.fraggler import print_green, print_warning

import core.assay_config as assay_config
from core.html_reports._constants import (DIT_PATTERN, DIT_QC_CONTROL_IDS, REPORT_STYLE, D835_DIGEST_HEIGHT_MIN, D835_DIGEST_AREA_MIN)
from core.assay_config import (
    CHANNEL_COLORS,
    DEFAULT_TRACE_COLOR,
    merged_analysis_attr,
    OUTDIR_NAME,
)
from core.plotly_offline import local_plotly_tag as _local_plotly_tag
from core.plotting_plotly import (
    compute_group_ymax_for_entries,
    build_interactive_peak_plot_for_entry,
)
from core.qc.qc_markers import control_id_from_filename
from core.qc.qc_plots import build_interactive_peak_plot_for_entry_qc
from core.qc.qc_rules import QCRules, normalize_assay_qc
from config import APP_SETTINGS


def _atomic_write_html(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(html)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _assay_config() -> dict:
    return getattr(assay_config, "ASSAY_CONFIG", {})


def _assay_display_order() -> list[str]:
    return list(getattr(assay_config, "ASSAY_DISPLAY_ORDER", []))


def _assay_reference_ranges() -> dict:
    return merged_analysis_attr("ASSAY_REFERENCE_RANGES")


def _assay_reference_label() -> dict:
    return merged_analysis_attr("ASSAY_REFERENCE_LABEL")


def _assay_rearrangement_info() -> dict:
    return merged_analysis_attr("ASSAY_REARRANGEMENT_INFO")


def _channel_text_colors() -> dict:
    return merged_analysis_attr("CHANNEL_TEXT_COLORS") or {
        "DATA1": "#2563eb",
        "DATA2": "#16a34a",
        "DATA3": "#1e293b",
    }


def _render_rearrangement_info_html(assay_name: str) -> str:
    """Build a compact, color-coded rearrangement info block for a clonality assay."""
    info = _assay_rearrangement_info().get(assay_name)
    if not info:
        # Fall back to simple label if available
        label = _assay_reference_label().get(assay_name)
        if label:
            ref_ranges = _assay_reference_ranges().get(assay_name)
            ranges_str = ", ".join(f"{int(a)}–{int(b)} bp" for (a, b) in ref_ranges) if ref_ranges else ""
            return (
                f"<p class='small'><strong>Referanseområde:</strong> {escape(ranges_str)}"
                f"<br>{escape(label)}</p>"
            )
        return ""

    colors = _channel_text_colors()
    title = info.get("title", assay_name)
    rows = info.get("rows", [])
    prefix_parts = info.get("prefix_parts")  # e.g. IGK: [("Jk1-4", "DATA2"), ("Jk5", "DATA1")]

    lines: list[str] = []
    lines.append(
        "<div class='rearrangement-info' style='"
        "background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; "
        "padding:8px 14px; margin-bottom:6px; font-size:0.82rem; line-height:1.5;"
        "'>"
    )
    lines.append(f"<strong style='color:#334155;'>{escape(title)}</strong>")

    should_render_rows = bool(rows)

    if rows and should_render_rows:
        lines.append("<div style='margin-top:4px;'>")
        for row in rows:
            name = row.get("name", "")
            bp_range = row.get("range", "")
            channel = row.get("channel")
            channels = row.get("channels")  # for dual-channel (TCRb)

            if prefix_parts:
                # IGK-style: "Jk1-4/Jk5: Vk1f/6: 120–140"
                prefix_html = "/".join(
                    f"<span style='color:{colors.get(ch, '#334155')}; font-weight:600;'>{escape(part)}</span>"
                    for part, ch in prefix_parts
                )
                lines.append(
                    f"<div>{prefix_html}: "
                    f"<span style='color:#334155;'>{escape(name)}: {escape(bp_range)}</span></div>"
                )
            elif channels:
                # Dual-channel (TCRb): show colored dots
                dots = " ".join(
                    f"<span style='color:{colors.get(ch, '#334155')};'>●</span>"
                    for ch in channels
                )
                lines.append(
                    f"<div>{dots} "
                    f"<span style='color:#334155; font-weight:500;'>{escape(name)}: {escape(bp_range)}</span></div>"
                )
            elif channel:
                # Single-channel: color the whole row
                color = colors.get(channel, "#334155")
                lines.append(
                    f"<div style='color:{color}; font-weight:500;'>"
                    f"{escape(name)}: {escape(bp_range)}</div>"
                )
            else:
                lines.append(
                    f"<div style='color:#334155;'>{escape(name)}: {escape(bp_range)}</div>"
                )
        lines.append("</div>")

    lines.append("</div>")
    return "\n".join(lines)




def _build_plotly_reflow_script() -> str:
    """Global Plotly reflow helpers for embedded/hidden report viewers."""
    return """
<script>
window.ReportPlotManager = (function() {
    var plots = {};
    var plotMeta = {};
    var initialStates = {};
    var refreshTimer = null;

    function loadInitialStates() {
        if (Object.keys(initialStates).length) return;
        try {
            var tag = document.getElementById('plot-state');
            if (!tag) return;
            var raw = JSON.parse(tag.textContent || '{}');
            if (raw && typeof raw === 'object') initialStates = raw;
        } catch (e) {
            initialStates = {};
        }
    }

    function cloneRange(range) {
        if (!Array.isArray(range) || range.length !== 2) return null;
        var a = Number(range[0]);
        var b = Number(range[1]);
        if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
        return [a, b];
    }

    function getPlotMeta(gd) {
        if (!gd || !gd.id) return null;
        if (!plotMeta[gd.id]) {
            plotMeta[gd.id] = {
                lastMeasuredWidth: 0,
                lastMeasuredHeight: 0,
                stableReadyCount: 0,
                firstReadyAt: 0,
                stableAncestor: null
            };
        }
        return plotMeta[gd.id];
    }

    function measureBox(node) {
        if (!node) return { width: 0, height: 0 };
        var rect = (typeof node.getBoundingClientRect === 'function')
            ? node.getBoundingClientRect()
            : { width: 0, height: 0 };
        var width = Math.max(
            Number(node.clientWidth) || 0,
            Number(node.offsetWidth) || 0,
            Number(rect.width) || 0
        );
        var height = Math.max(
            Number(node.clientHeight) || 0,
            Number(node.offsetHeight) || 0,
            Number(rect.height) || 0
        );
        return { width: width, height: height };
    }

    function hasUsableBox(box) {
        return !!box && box.width > 0 && box.height > 0;
    }

    function recordBoxMeasurement(gd) {
        var meta = getPlotMeta(gd);
        if (!meta) return { box: { width: 0, height: 0 }, becameReady: false };
        var box = measureBox(gd);
        var wasReady = meta.lastMeasuredWidth > 0 && meta.lastMeasuredHeight > 0;
        var isReady = hasUsableBox(box);
        if (isReady) {
            if (!wasReady) {
                meta.firstReadyAt = Date.now();
                meta.stableReadyCount = 1;
            } else if (Math.abs(meta.lastMeasuredWidth - box.width) < 1 && Math.abs(meta.lastMeasuredHeight - box.height) < 1) {
                meta.stableReadyCount += 1;
            } else {
                meta.stableReadyCount = 1;
            }
        } else {
            meta.stableReadyCount = 0;
        }
        meta.lastMeasuredWidth = box.width;
        meta.lastMeasuredHeight = box.height;
        return { box: box, becameReady: !wasReady && isReady };
    }

    function findStableAncestor(gd) {
        var node = gd ? gd.parentElement : null;
        var fallback = node || gd || document.body;
        while (node && node !== document.body) {
            fallback = node;
            if (hasUsableBox(measureBox(node))) return node;
            node = node.parentElement;
        }
        return fallback || document.body;
    }

    function resizeOne(gd) {
        if (!gd || !window.Plotly) return false;
        if (typeof gd.isConnected === 'boolean' && !gd.isConnected) return false;
        var measurement = recordBoxMeasurement(gd);
        if (!hasUsableBox(measurement.box)) return false;
        try { Plotly.Plots.resize(gd); } catch (e) {}
        try { Plotly.relayout(gd, {autosize: true}); } catch (e) {}
        return true;
    }

    function refreshAll() {
        for (var id in plots) {
            if (Object.prototype.hasOwnProperty.call(plots, id)) resizeOne(plots[id]);
        }
    }

    function captureState(gd) {
        if (!gd || !gd.layout) return null;
        var xRange = cloneRange(gd.layout.xaxis && gd.layout.xaxis.range);
        var yRange = cloneRange(gd.layout.yaxis && gd.layout.yaxis.range);
        if (!xRange && !yRange) return null;
        return {
            xaxis_range: xRange,
            yaxis_range: yRange
        };
    }

    function scheduleRefresh() {
        if (refreshTimer) {
            clearTimeout(refreshTimer);
            refreshTimer = null;
        }
        var delays = [0, 80, 220, 500, 1100, 2200, 4200];
        for (var i = 0; i < delays.length; i++) {
            setTimeout(refreshAll, delays[i]);
        }
        if (window.requestAnimationFrame) {
            window.requestAnimationFrame(function() { refreshAll(); });
        }
        refreshTimer = setTimeout(function() {
            refreshAll();
            refreshTimer = null;
        }, 6200);
    }

    function stabilizePlot(gd) {
        var delays = [0, 40, 120, 300, 700, 1400, 2600];
        for (var i = 0; i < delays.length; i++) {
            (function(delay) {
                setTimeout(function() {
                    if (!gd || !plots[gd.id]) return;
                    resizeOne(gd);
                }, delay);
            })(delays[i]);
        }
    }

    function whenContainerReady(gd) {
        return new Promise(function(resolve) {
            if (!gd) {
                resolve(null);
                return;
            }

            var done = false;
            var deadlineMs = 7000;
            var delays = [0, 40, 120, 260, 520, 900, 1500, 2400, 3600, 5200, 6800];
            var meta = getPlotMeta(gd);

            function finish() {
                if (done) return;
                done = true;
                resolve(gd);
            }

            function checkReady() {
                if (done) return;
                var measurement = recordBoxMeasurement(gd);
                if (measurement.becameReady) scheduleRefresh();
                var now = Date.now();
                var stableEnough = meta && meta.stableReadyCount >= 2;
                var waitedLongEnough = meta && meta.firstReadyAt > 0 && (now - meta.firstReadyAt) >= 120;
                if (hasUsableBox(measurement.box) && (stableEnough || waitedLongEnough)) {
                    finish();
                }
            }

            if (window.requestAnimationFrame) {
                window.requestAnimationFrame(checkReady);
            }
            for (var i = 0; i < delays.length; i++) {
                setTimeout(checkReady, delays[i]);
            }
            setTimeout(finish, deadlineMs);
        });
    }

    function mountPlot(gd, data, layout, config) {
        return whenContainerReady(gd).then(function() {
            return Plotly.newPlot(gd, data, layout, config || {});
        }).then(function(g) {
            api.register(g);
            scheduleRefresh();
            stabilizePlot(g);
            return g;
        });
    }

    function attachObservers(gd) {
        if (!gd || gd.__fragglerObserversAttached) return;
        gd.__fragglerObserversAttached = true;
        var meta = getPlotMeta(gd);
        if (meta) meta.stableAncestor = findStableAncestor(gd);

        function onPotentialSizeChange() {
            var measurement = recordBoxMeasurement(gd);
            if (measurement.becameReady) {
                scheduleRefresh();
                stabilizePlot(gd);
                return;
            }
            if (hasUsableBox(measurement.box)) scheduleRefresh();
        }

        if (typeof ResizeObserver === 'function') {
            try {
                var ro = new ResizeObserver(function() { onPotentialSizeChange(); });
                ro.observe(gd);
                if (gd.parentElement) ro.observe(gd.parentElement);
                if (meta && meta.stableAncestor && meta.stableAncestor !== gd.parentElement) {
                    ro.observe(meta.stableAncestor);
                }
                gd.__fragglerResizeObserver = ro;
            } catch (e) {}
        }

        if (typeof IntersectionObserver === 'function') {
            try {
                var io = new IntersectionObserver(function(entries) {
                    for (var i = 0; i < entries.length; i++) {
                        if (entries[i].isIntersecting) {
                            scheduleRefresh();
                            break;
                        }
                    }
                });
                io.observe(gd);
                gd.__fragglerIntersectionObserver = io;
            } catch (e) {}
        }

        if (typeof MutationObserver === 'function' && gd.parentElement) {
            try {
                var mo = new MutationObserver(function() { onPotentialSizeChange(); });
                mo.observe(gd.parentElement, {
                    attributes: true,
                    attributeFilter: ['style', 'class'],
                });
                gd.__fragglerMutationObserver = mo;
            } catch (e) {}
        }

        if (typeof MutationObserver === 'function' && meta && meta.stableAncestor && meta.stableAncestor !== gd.parentElement) {
            try {
                var rootMo = new MutationObserver(function() { onPotentialSizeChange(); });
                rootMo.observe(meta.stableAncestor, {
                    attributes: true,
                    attributeFilter: ['style', 'class'],
                });
                gd.__fragglerRootMutationObserver = rootMo;
            } catch (e) {}
        }
    }

    window.addEventListener('load', scheduleRefresh);
    window.addEventListener('resize', scheduleRefresh);
    window.addEventListener('pageshow', scheduleRefresh);
    window.addEventListener('focus', scheduleRefresh);
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'visible') scheduleRefresh();
    });
    if (document.fonts && document.fonts.ready && typeof document.fonts.ready.then === 'function') {
        document.fonts.ready.then(scheduleRefresh).catch(function() {});
    }

    loadInitialStates();

    var api = {
        register: function(gd) {
            if (!gd || !gd.id) return;
            plots[gd.id] = gd;
            getPlotMeta(gd);
            attachObservers(gd);
            scheduleRefresh();
            stabilizePlot(gd);
        },
        mountPlot: mountPlot,
        getInitialStateForPlot: function(id) {
            loadInitialStates();
            return initialStates[id] || null;
        },
        getAllStates: function() {
            var all = {};
            for (var id in plots) {
                if (!Object.prototype.hasOwnProperty.call(plots, id)) continue;
                var state = captureState(plots[id]);
                if (state) all[id] = state;
            }
            return all;
        },
        refreshAll: scheduleRefresh,
        resizeOne: resizeOne,
        whenContainerReady: whenContainerReady,
        measureBox: measureBox,
        findStableAncestor: findStableAncestor
    };
    return api;
})();
</script>
"""

def extract_dit_from_name(name: str) -> str | None:
    """Finner første forekomst av 2-sifret år + 'OUM' + 5 siffer."""
    m = DIT_PATTERN.search(name)
    return m.group(1).upper() if m else None

def dit_to_year(dit: str) -> int | None:
    """25OUM10166 -> 2025, 26OUMxxxxx -> 2026, etc."""
    if not dit or len(dit) < 2: return None
    try:
        return 2000 + int(dit[:2])
    except ValueError:
        return None

def _resolve_report_display_name(entries: list[dict] | None = None) -> str:
    analysis_name = get_active_analysis_name()
    if entries:
        assays = {e.get("assay") for e in entries}
        if assays and assays.issubset({"FLT3-ITD", "FLT3-D835", "NPM1"}):
            return "Flt3"
    return "Klonalitet" if analysis_name == "clonality" else analysis_name.capitalize()


def _new_report_metrics() -> dict[str, float | int]:
    return {
        "plot_build_seconds": 0.0,
        "plot_count": 0,
        "plot_errors": 0,
    }


def _build_report_plot_fragment(
    entry: dict,
    report_metrics: dict[str, float | int] | None,
    *,
    qc_rules: QCRules | None = None,
) -> str:
    started = time.perf_counter()
    try:
        cache = None
        cache_key = None
        if qc_rules is not None:
            cache = entry.setdefault("_html_report_fragment_cache", {})
            if is_dataclass(qc_rules):
                cache_key = ("qc", tuple(sorted(asdict(qc_rules).items())))
            else:
                cache_key = ("qc", id(qc_rules))
            cached = cache.get(cache_key) if isinstance(cache, dict) else None
            if isinstance(cached, str):
                return cached

        fragment = (
            build_interactive_peak_plot_for_entry_qc(entry, qc_rules)
            if qc_rules is not None
            else build_interactive_peak_plot_for_entry(entry)
        )
        fragment = fragment or "<p class='small'><em>Ingen data å vise.</em></p>"
        if cache_key is not None and isinstance(cache, dict):
            cache[cache_key] = fragment
        return fragment
    except Exception as ex:
        if report_metrics is not None:
            report_metrics["plot_errors"] = int(report_metrics.get("plot_errors", 0)) + 1
        prefix = "QC-plott" if qc_rules is not None else "plott"
        return f"<p class='small'><em>Kunne ikke lage {prefix}: {escape(str(ex))}</em></p>"
    finally:
        if report_metrics is not None:
            report_metrics["plot_count"] = int(report_metrics.get("plot_count", 0)) + 1
            report_metrics["plot_build_seconds"] = float(report_metrics.get("plot_build_seconds", 0.0)) + (
                time.perf_counter() - started
            )


def _format_report_metrics_summary(label: str, report_metrics: dict[str, float | int], total_seconds: float, html_bytes: int) -> str:
    return (
        f"[HTML] {label}: "
        f"{int(report_metrics.get('plot_count', 0))} plott, "
        f"{int(report_metrics.get('plot_errors', 0))} feil, "
        f"plot-tid {float(report_metrics.get('plot_build_seconds', 0.0)):.2f}s, "
        f"total {total_seconds:.2f}s, "
        f"størrelse {html_bytes / (1024 * 1024):.2f} MB"
    )


def _create_html_header(
    dit: str,
    year: int | None,
    num_entries: int,
    dit_root: Path,
    html_lines: list[str],
    *,
    display_name: str,
):
    """Appends the HTML head and page header to html_lines."""
    html_lines.extend(["<!DOCTYPE html>", "<html lang='no'>", "<head>", "<meta charset='utf-8'>"])
    html_lines.append(f"<title>{escape(dit)}_{display_name}_Resultater</title>")
    html_lines.append(REPORT_STYLE)
    html_lines.append('<script id="peak-data" type="application/json">{}</script>')
    html_lines.append('<script id="plot-state" type="application/json">{}</script>')
    html_lines.append('<script id="clonality-decisions" type="application/json">{}</script>')
    html_lines.append(r"""
<script>
// Toggle comment boxes
function toggleComment(btn) {
    var body = btn.nextElementSibling;
    var caret = btn.querySelector('.caret');
    var isOpen = body.classList.toggle('open');
    caret.textContent = isOpen ? '▲' : '▼';
    if (isOpen) btn.querySelector('.comment-label').textContent = 'Skjul kommentar';
    else btn.querySelector('.comment-label').textContent = 'Legg til kommentar';
}

window.PeakManager = {
    plots: {},
    registerPlot: function(id, plotObj) { this.plots[id] = plotObj; },
    _readPeakData: function() {
        try {
            var tag = document.getElementById('peak-data');
            return tag ? JSON.parse(tag.textContent || '{}') : {};
        } catch(e) {
            return {};
        }
    },
    _normalizePeakPayload: function(payload) {
        if (Array.isArray(payload)) {
            return { peaks: payload.slice(), flt3_manual_ratio_selection: null };
        }
        if (payload && typeof payload === 'object') {
            return {
                peaks: Array.isArray(payload.peaks) ? payload.peaks.slice() : [],
                flt3_manual_ratio_selection: (payload.flt3_manual_ratio_selection && typeof payload.flt3_manual_ratio_selection === 'object')
                    ? payload.flt3_manual_ratio_selection
                    : null
            };
        }
        return { peaks: [], flt3_manual_ratio_selection: null };
    },
    getAllPeaks: function() {
        var all = {};
        for (var id in this.plots) {
            if (!Object.prototype.hasOwnProperty.call(this.plots, id)) continue;
            all[id] = this.plots[id].getPeaks();
        }
        return all;
    },
    getAllPeakData: function() {
        var all = {};
        for (var id in this.plots) {
            if (!Object.prototype.hasOwnProperty.call(this.plots, id)) continue;
            var plot = this.plots[id];
            if (plot && typeof plot.getPeakData === 'function') {
                all[id] = plot.getPeakData();
            } else if (plot && typeof plot.getPeaks === 'function') {
                all[id] = plot.getPeaks();
            }
        }
        return all;
    },
    getInitialPeakDataForPlot: function(id) {
        var data = this._readPeakData();
        return this._normalizePeakPayload(data[id]);
    },
    getInitialPeaksForPlot: function(id) {
        return this.getInitialPeakDataForPlot(id).peaks;
    },
    downloadUpdatedHtml: function() {
        // Force textareas back to innerHTML so they persist
        var tas = document.querySelectorAll('textarea.report-comment');
        for (var i = 0; i < tas.length; i++) {
            var val = tas[i].value.trim();
            tas[i].innerHTML = val;
            
            var container = tas[i].closest('.comment-box-container');
            var body = tas[i].closest('.comment-body');
            
            if (val !== "") {
                // If there's content, make sure it's open/visible
                body.classList.add('open');
            } else {
                // If empty, hide it (even from print)
                body.classList.remove('open');
            }
        }
        
        var allPeaks = this.getAllPeakData();
        var allPlotStates = (window.ReportPlotManager && window.ReportPlotManager.getAllStates)
            ? window.ReportPlotManager.getAllStates()
            : {};
        var currentHtml = document.documentElement.outerHTML;
        var peakDataStr = JSON.stringify(allPeaks);
        var plotStateStr = JSON.stringify(allPlotStates);
        var decisionsStr = (window.ClonalityDecisionLog && window.ClonalityDecisionLog.serializeDecisions)
            ? JSON.stringify(window.ClonalityDecisionLog.serializeDecisions())
            : '{}';
        var pattern = /<script id="peak-data" type="application\/json">[\s\S]*?<\/script>/;
        var newTag = '<script id="peak-data" type="application/json">\n' + peakDataStr + '\n<\/script>';
        var plotPattern = /<script id="plot-state" type="application\/json">[\s\S]*?<\/script>/;
        var newPlotTag = '<script id="plot-state" type="application/json">\n' + plotStateStr + '\n<\/script>';
        var decisionsPattern = /<script id="clonality-decisions" type="application\/json">[\s\S]*?<\/script>/;
        var newDecisionsTag = '<script id="clonality-decisions" type="application/json">\n' + decisionsStr + '\n<\/script>';
        var updatedHtml = currentHtml
            .replace(pattern, newTag)
            .replace(plotPattern, newPlotTag)
            .replace(decisionsPattern, newDecisionsTag);
        var blob = new Blob(['<!DOCTYPE html>\n' + updatedHtml], {type: 'text/html'});
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a'); a.href = url; a.download = document.title + '.html'; a.click(); URL.revokeObjectURL(url);
    }
};

// Clonality ML badge dismissal — chemist-presses-button to hide a
// single ML badge from the printed page.  Restore is the inverse.
window.ClonalityDecisionLog = {
    _store: {},
    _readSaved: function() {
        try {
            var tag = document.getElementById('clonality-decisions');
            var saved = tag ? JSON.parse(tag.textContent || '{}') : {};
            return (saved && typeof saved === 'object') ? saved : {};
        } catch(e) { return {}; }
    },
    applySaved: function() {
        var saved = this._readSaved();
        var nodes = document.querySelectorAll('.clonality-ml-badge');
        for (var i = 0; i < nodes.length; i++) {
            var node = nodes[i];
            var id = node.id;
            if (!id) continue;
            var entry = saved[id];
            if (entry && entry.dismissed) {
                node.dataset.state = 'dismissed';
                var dismissBtn = node.querySelector('.ml-dismiss');
                var restoreBtn = node.querySelector('.ml-restore');
                if (dismissBtn) dismissBtn.hidden = true;
                if (restoreBtn) restoreBtn.hidden = false;
            }
        }
    },
    dismiss: function(btn) {
        var badge = btn.closest('.clonality-ml-badge');
        if (!badge) return;
        badge.dataset.state = 'dismissed';
        var dismissBtn = badge.querySelector('.ml-dismiss');
        var restoreBtn = badge.querySelector('.ml-restore');
        if (dismissBtn) dismissBtn.hidden = true;
        if (restoreBtn) restoreBtn.hidden = false;
    },
    restore: function(btn) {
        var badge = btn.closest('.clonality-ml-badge');
        if (!badge) return;
        badge.dataset.state = 'active';
        var dismissBtn = badge.querySelector('.ml-dismiss');
        var restoreBtn = badge.querySelector('.ml-restore');
        if (dismissBtn) dismissBtn.hidden = false;
        if (restoreBtn) restoreBtn.hidden = true;
    },
    serializeDecisions: function() {
        var decisions = {};
        var nodes = document.querySelectorAll('.clonality-ml-badge');
        for (var i = 0; i < nodes.length; i++) {
            var node = nodes[i];
            if (!node.id) continue;
            decisions[node.id] = {
                dit: node.dataset.dit || '',
                assay: node.dataset.assay || '',
                file: node.dataset.file || '',
                ml_label: node.dataset.mlLabel || '',
                dismissed: node.dataset.state === 'dismissed'
            };
        }
        return decisions;
    }
};

// On load, reapply any previously-saved dismissal state
(function() {
    function ready() {
        if (window.ClonalityDecisionLog) {
            window.ClonalityDecisionLog.applySaved();
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', ready);
    } else {
        ready();
    }
})();

function printReport() { window.print(); }
</script>
""")
    html_lines.append(_local_plotly_tag(dit_root, version="2.35.2"))
    html_lines.append(_build_plotly_reflow_script())
    html_lines.extend(["</head>", "<body>"])

    gen_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta = [f"År: {year}"] if year else []
    meta.extend([f"{num_entries} analyserte filer", f"Generert: {gen_date}"])
    meta_str = " &nbsp;&bull;&nbsp; ".join(meta)
    
    html_lines.append(f"""
<div class='report-header no-print'>
  <h1>{escape(dit)}_{display_name}_Resultater</h1>
  <div class='meta'>{meta_str}</div>
</div>
<div style='display:none' class='print-only-header'>
  <h1>{escape(dit)}_{display_name}_Resultater</h1>
  <p>{" | ".join(meta)}</p>
</div>
""")

def _render_file_summary_table(dit_entries: list[dict], html_lines: list[str]):
    """Renders the overview table of all analyzed files."""
    html_lines.append("<h2>Oversikt over analyserte filer</h2>")
    is_flt3 = {e.get("assay") for e in dit_entries}.issubset({"FLT3-ITD", "FLT3-D835", "NPM1"})
    if is_flt3:
        html_lines.append(
            "<table><tr><th>Filnavn</th><th>Assay</th><th>Behandling</th><th>WT</th><th>Mutert</th><th>Ratio</th><th>Δbp / kodoner</th><th>Ladder QC</th><th>R²</th></tr>"
        )
        for e in sorted(dit_entries, key=lambda x: (x["assay"], x.get("well_id") or "", x["fsa"].file_name)):
            status_badge = _render_ladder_status_badge(e)
            r2 = e.get("ladder_r2", None)
            r2_str = f"{r2:.4f}" if r2 is not None and not np.isnan(r2) else "&mdash;"
            peaks = e["peaks_by_channel"].get(e["primary_peak_channel"], pd.DataFrame())
            wt_rows = peaks[peaks.label == "WT"].sort_values("peaks", ascending=False) if not peaks.empty else pd.DataFrame()
            mut_rows = peaks[peaks.label.isin(["MUT", "ITD"])].sort_values("area", ascending=False) if not peaks.empty else pd.DataFrame()
            if e.get("assay") in ("FLT3-ITD", "FLT3-D835") and e.get("ratio_mode") != "manual":
                wt_text = "<span class='small'>Manuell WT</span>"
                mut_text = "<span class='small'>Velg mutantpeaks manuelt</span>"
            else:
                wt_text = _flt3_manual_wt_text(e, peaks) or _peak_text(_dominant_peak(wt_rows))
                mut_text = _flt3_manual_mutant_text(e, peaks) or _peak_text(_dominant_peak(mut_rows))
            ratio = float(e.get("ratio", 0.0))
            ratio_str = f"{ratio:.4f}" if ratio > 0 else "&mdash;"
            if e.get("ratio_mode") == "manual":
                ratio_str += " <span class='status-badge manual'>Manual</span>"
            fname = escape(e['fsa'].file_name)
            fname_safe = e['fsa'].file_name.replace('.', '_').replace(' ', '_')
            distance_text = _format_flt3_bp_distance_html(_flt3_bp_distance_metrics(e, peaks))
            html_lines.append(
                f"<tr data-filename='{fname}'>"
                f"<td>{fname}</td><td>{escape(e['assay'])}</td>"
                f"<td>{escape(_format_flt3_treatment(e))}</td>"
                f"<td><span id='overview_wt_{fname_safe}'>{wt_text}</span></td>"
                f"<td><span id='overview_mut_{fname_safe}'>{mut_text}</span></td>"
                f"<td><span id='overview_ratio_{fname_safe}'>{ratio_str}</span></td>"
                f"<td><span id='overview_delta_{fname_safe}'>{distance_text}</span></td>"
                f"<td>{status_badge}</td><td>{r2_str}</td></tr>"
            )
    else:
        html_lines.append("<table><tr><th>Filnavn</th><th>Assay</th><th>Ladder</th><th>bp-område</th><th>Ladder QC</th><th>R²</th></tr>")
        for e in sorted(dit_entries, key=lambda x: (x["assay"], x["fsa"].file_name)):
            status_badge = _render_ladder_status_badge(e)
            r2 = e.get("ladder_r2", None)
            r2_str = f"{r2:.4f}" if r2 is not None and not np.isnan(r2) else "&mdash;"
            html_lines.append(
                f"<tr><td>{escape(e['fsa'].file_name)}</td><td>{escape(e['assay'])}</td>"
                f"<td>{escape(e['ladder'])}</td><td>{int(e['bp_min'])}–{int(e['bp_max'])} bp</td>"
                f"<td>{status_badge}</td><td>{r2_str}</td></tr>"
            )
    html_lines.append("</table>")


def _ladder_status_payload(entry: dict) -> tuple[str, str, str]:
    status = str(entry.get("ladder_qc_status", "unknown"))
    if status == "manual_adjustment":
        label = "Manual"
        css = "manual"
        note = str(entry.get("ladder_fit_note") or "Manual ladder correction was used.")
    elif status == "missing_ladder":
        label = "Missing ladder"
        css = "failed"
        note = str(entry.get("ladder_fit_note") or "No usable ladder signal was found.")
    elif status == "review_required":
        label = "Warning"
        css = "warning"
        note = str(entry.get("ladder_fit_note") or "Usable ladder fit, but missing expected ladder steps require review.")
    elif status == "ladder_qc_failed":
        label = "Failed"
        css = "failed"
        note = str(entry.get("ladder_fit_note") or "Ladder QC failed.")
    elif status == "ok":
        label = "OK"
        css = "ok"
        note = str(entry.get("ladder_fit_note") or "All expected ladder steps were fitted.")
    else:
        label = "Unknown"
        css = "unknown"
        note = str(entry.get("ladder_fit_note") or "Ladder status unknown.")
    return label, css, note


def _render_ladder_status_badge(entry: dict) -> str:
    label, css, note = _ladder_status_payload(entry)
    title_attr = escape(note, quote=True)
    return f"<span class='status-badge {css}' title='{title_attr}'>{escape(label)}</span>"


def _render_status_badge(label: str, css: str, note: str = "") -> str:
    title_attr = escape(note, quote=True) if note else ""
    return f"<span class='status-badge {css}' title='{title_attr}'>{escape(label)}</span>"


def _flt3_qc_status_badge(row: dict) -> str:
    status = str(row.get("Status", "")).upper()
    details = str(row.get("Details") or "")
    if status == "PASS":
        return _render_status_badge("PASS", "ok", details or "Kontrollen bestod.")
    if status == "REVIEW":
        return _render_status_badge("REVIEW", "warning", details or "Kontrollen krever vurdering.")
    return _render_status_badge("FAIL", "failed", details or "Kontrollen feilet.")

def _format_flt3_treatment(entry: dict) -> str:
    atype = entry["analysis_type"]
    treatment = "Standard"
    if atype == "TKD_digested":
        treatment = "Digert (EcoRV)"
    elif atype == "10x_diluted":
        treatment = "Fortynnet 1:10"
    elif atype == "25x_diluted":
        treatment = "Fortynnet 1:25"
    elif atype == "ratio_quant":
        treatment = "Ratio-sett"
    elif atype == "undiluted":
        treatment = "Ufortynnet"
    protocol_inj = entry.get("protocol_injection_time", entry.get("injection_time", 0))
    return f"{treatment} - {protocol_inj}s protokoll"


def _format_flt3_selection(entry: dict) -> str:
    selected = entry.get("selected_injection") or f"{entry.get('injection_time', 0)}s"
    source = entry.get("source_run_dir") or "ukjent kjøring"
    sizing = entry.get("sizing_method") or "ukjent sizing"
    reason = entry.get("selection_reason") or ""
    return f"Valgt {selected} fra {source} ({sizing}). {reason}".strip()


def _flt3_display_priority(entry: dict) -> int:
    assay = entry.get("assay")
    analysis_type = entry.get("analysis_type")
    if assay == "FLT3-ITD" and analysis_type == "ratio_quant":
        return 0
    if assay == "FLT3-D835":
        return 1
    if assay == "FLT3-ITD":
        return 2
    return 3


def _flt3_display_sort_key(entry: dict) -> tuple[int, str, str]:
    return (
        _flt3_display_priority(entry),
        entry.get("well_id") or "",
        entry["fsa"].file_name,
    )


def _flt3_report_blocks(assays: dict[str, list[dict]]) -> list[tuple[str, str, list[dict]]]:
    blocks: list[tuple[str, str, list[dict]]] = []
    itd_entries = assays.get("FLT3-ITD", [])
    itd_ratio_entries = [e for e in itd_entries if e.get("analysis_type") == "ratio_quant"]
    itd_10x_entries = [e for e in itd_entries if e.get("analysis_type") == "10x_diluted"]
    itd_25x_entries = [e for e in itd_entries if e.get("analysis_type") == "25x_diluted"]
    itd_standard_entries = [
        e for e in itd_entries
        if e.get("analysis_type") not in {"ratio_quant", "10x_diluted", "25x_diluted"}
    ]

    if itd_ratio_entries:
        blocks.append(("FLT3-ITD", "FLT3-ITD-ratio", itd_ratio_entries))
    if "FLT3-D835" in assays:
        blocks.append(("FLT3-D835", "FLT3-D835", assays["FLT3-D835"]))
    if itd_standard_entries:
        blocks.append(("FLT3-ITD", "FLT3-ITD", itd_standard_entries))
    if itd_10x_entries:
        blocks.append(("FLT3-ITD", "FLT3-ITD - fortynnet 1:10", itd_10x_entries))
    if itd_25x_entries:
        blocks.append(("FLT3-ITD", "FLT3-ITD - fortynnet 1:25", itd_25x_entries))
    if "NPM1" in assays:
        blocks.append(("NPM1", "NPM1", assays["NPM1"]))
    return blocks

def _format_peak_list(mut_rows: pd.DataFrame, max_peaks: int = 3) -> str:
    if mut_rows.empty:
        return "Ingen mutasjoner detektert"
    mut_rows = mut_rows.sort_values("basepairs")
    parts = []
    for idx, (_, row) in enumerate(mut_rows.iterrows(), start=1):
        if idx > max_peaks:
            remaining = len(mut_rows) - max_peaks
            parts.append(f"+ {remaining} andre topper")
            break
        parts.append(f"{row.basepairs:.1f} bp ({row.area:,.0f})")
    return "<br>".join(parts)

def _peak_text(row: pd.Series | None, area_key: str = "area") -> str:
    if row is None:
        return "&mdash;"
    return f"{float(row.basepairs):.1f} bp <span class='small'>({float(row.get(area_key, 0.0)):,.0f})</span>"


def _flt3_channel_label(channel: str | None) -> str:
    if channel == "DATA1":
        return "blue"
    if channel == "DATA2":
        return "green"
    if channel == "DATA3":
        return "orange"
    return "auto"


def _flt3_lookup_peak(peaks: pd.DataFrame, peak_id: str | None) -> pd.Series | None:
    if peaks.empty or not peak_id or "peak_id" not in peaks.columns:
        return None
    match = peaks[peaks["peak_id"].astype(str) == str(peak_id)]
    if match.empty:
        return None
    return match.iloc[0]


def _flt3_selected_area(row: pd.Series | None, channel: str | None) -> float:
    if row is None:
        return 0.0
    if channel in {"DATA1", "DATA2"}:
        return float(row.get(f"area_{channel}", 0.0) or 0.0)
    return float(row.get("area", 0.0) or 0.0)


def _flt3_manual_wt_text(entry: dict, peaks: pd.DataFrame) -> str | None:
    peak_id = entry.get("selected_wt_peak_id")
    channel = entry.get("selected_wt_channel")
    row = _flt3_lookup_peak(peaks, peak_id)
    if row is None:
        return None
    area = _flt3_selected_area(row, channel)
    return f"{float(row.basepairs):.1f} bp <span class='small'>({_flt3_channel_label(channel)}; {area:,.0f})</span>"


def _flt3_manual_mutant_text(entry: dict, peaks: pd.DataFrame) -> str | None:
    peak_ids = entry.get("selected_mutant_peak_ids") or []
    channels = entry.get("selected_mutant_channels") or []
    parts = []
    for idx, peak_id in enumerate(peak_ids):
        row = _flt3_lookup_peak(peaks, peak_id)
        if row is None:
            continue
        channel = channels[idx] if idx < len(channels) else None
        area = _flt3_selected_area(row, channel)
        parts.append(f"{float(row.basepairs):.1f} bp <span class='small'>({_flt3_channel_label(channel)}; {area:,.0f})</span>")
    return "<br>".join(parts) if parts else None


def _flt3_bp_distance_metrics(entry: dict, peaks: pd.DataFrame | None = None) -> list[dict[str, object]]:
    metrics = calculate_entry_bp_distance_metrics(entry)
    if metrics or peaks is None or peaks.empty:
        return metrics

    wt_rows = peaks[peaks.label == "WT"].sort_values("peaks", ascending=False)
    mut_rows = peaks[peaks.label.isin(["MUT", "ITD"])].sort_values("area", ascending=False)
    wt_main = _dominant_peak(wt_rows)
    if wt_main is None or mut_rows.empty:
        return []
    return calculate_bp_distance_metrics(
        [float(wt_main.basepairs)],
        [float(value) for value in mut_rows.basepairs.tolist()],
    )


def _format_flt3_bp_distance_html(metrics: list[dict[str, object]]) -> str:
    if not metrics:
        return "&mdash;"
    parts: list[str] = []
    for metric in metrics:
        delta = float(metric["delta_bp"])
        rounded_delta = int(metric["rounded_delta_bp"])
        channel = _flt3_channel_label(str(metric.get("channel") or ""))
        channel_prefix = f"{escape(channel)}: " if channel != "auto" else ""
        if metric["divisible_by_3"]:
            codons = abs(rounded_delta) // 3
            frame = f"{codons} kodon{'er' if codons != 1 else ''}; delbar med 3"
        else:
            frame = f"ikke delbar med 3; rest {int(metric['frame_remainder'])}"
        parts.append(f"{channel_prefix}{delta:+.1f} bp <span class='small'>(≈{rounded_delta:+d} bp; {frame})</span>")
    return "<br>".join(parts)


def _flt3_distance_summary_span(entry: dict, peaks: pd.DataFrame) -> str:
    plot_id = str(entry.get("_report_plot_id") or "")
    span_id = f" id='{escape(plot_id)}_flt3_bp_distance_summary'" if plot_id else ""
    return f"<span{span_id}>{_format_flt3_bp_distance_html(_flt3_bp_distance_metrics(entry, peaks))}</span>"


def _flt3_manual_channel_totals(entry: dict, peaks: pd.DataFrame) -> tuple[float, float, float, float]:
    wt_blue = wt_green = mut_blue = mut_green = 0.0
    wt_row = _flt3_lookup_peak(peaks, entry.get("selected_wt_peak_id"))
    wt_channel = entry.get("selected_wt_channel")
    if wt_channel == "DATA1":
        wt_blue = _flt3_selected_area(wt_row, "DATA1")
    elif wt_channel == "DATA2":
        wt_green = _flt3_selected_area(wt_row, "DATA2")

    peak_ids = entry.get("selected_mutant_peak_ids") or []
    channels = entry.get("selected_mutant_channels") or []
    for idx, peak_id in enumerate(peak_ids):
        row = _flt3_lookup_peak(peaks, peak_id)
        if row is None:
            continue
        channel = channels[idx] if idx < len(channels) else None
        if channel == "DATA1":
            mut_blue += _flt3_selected_area(row, "DATA1")
        elif channel == "DATA2":
            mut_green += _flt3_selected_area(row, "DATA2")
    return wt_blue, wt_green, mut_blue, mut_green


def _dominant_peak(rows: pd.DataFrame, area_key: str = "area") -> pd.Series | None:
    if rows.empty:
        return None
    return rows.sort_values(area_key, ascending=False).iloc[0]

def _find_peak_in_range(peaks: pd.DataFrame, bp_min: float, bp_max: float) -> pd.DataFrame:
    if peaks.empty:
        return pd.DataFrame()
    return peaks[(peaks.basepairs >= bp_min) & (peaks.basepairs <= bp_max)].copy()


def _reportable_itd_mut_rows_for_report(entry: dict, peaks: pd.DataFrame, wt_rows: pd.DataFrame, mut_rows: pd.DataFrame) -> pd.DataFrame:
    if entry.get("assay") != "FLT3-ITD" or peaks.empty or mut_rows.empty or wt_rows.empty:
        return mut_rows
    if entry.get("analysis_type") == "ratio_quant":
        return mut_rows

    wt_main = wt_rows.iloc[0]
    wt_bp = float(wt_main.basepairs)
    wt_area = float(wt_main.area)
    shoulder_bp_limit = wt_bp + 12.0
    shoulder_area_limit = max(4000.0, wt_area * 0.02)

    keep_mask = ~(
        (mut_rows.basepairs <= shoulder_bp_limit)
        & (mut_rows.area <= shoulder_area_limit)
    )
    return mut_rows[keep_mask].copy()

def _itd_concordance_text(wt_row: pd.Series | None, mut_rows: pd.DataFrame) -> str:
    if wt_row is None and mut_rows.empty:
        return ""
    wt_blue = float(wt_row.get("area_DATA1", 0.0)) if wt_row is not None else 0.0
    wt_green = float(wt_row.get("area_DATA2", 0.0)) if wt_row is not None else 0.0
    mut_blue = float(mut_rows.get("area_DATA1", pd.Series(0.0)).sum()) if not mut_rows.empty else 0.0
    mut_green = float(mut_rows.get("area_DATA2", pd.Series(0.0)).sum()) if not mut_rows.empty else 0.0

    seen_blue = mut_blue > max(1000.0, wt_blue * 0.02)
    seen_green = mut_green > max(1000.0, wt_green * 0.02)
    if seen_blue and seen_green:
        return "Mutant signal i begge kanaler"
    if seen_blue:
        return "Mutant signal mest tydelig i bla kanal"
    if seen_green:
        return "Mutant signal mest tydelig i gronn kanal"
    return ""




def _d835_digest_status(peaks: pd.DataFrame, wt_row: pd.Series | None, mut_row: pd.Series | None) -> tuple[str, pd.Series | None]:
    digest_rows = _find_peak_in_range(peaks, 145.0, 155.5)
    digest_row = _dominant_peak(digest_rows)
    digest_area = float(digest_row.area) if digest_row is not None else 0.0
    digest_height = float(digest_row.peaks) if digest_row is not None else 0.0
    wt_area = float(wt_row.area) if wt_row is not None else 0.0
    mut_area = float(mut_row.area) if mut_row is not None else 0.0

    if digest_row is None or digest_height < D835_DIGEST_HEIGHT_MIN or digest_area < D835_DIGEST_AREA_MIN:
        return "", None
    if digest_area >= max(wt_area, mut_area) * 0.60:
        return "Mulig ufullstendig kutting", digest_row
    return "", digest_row

def _build_flt3_summary_table(e: dict) -> str:
    """Validation-oriented FLT3/NPM1 table below each figure."""
    assay = e["assay"]
    ratio = float(e.get("ratio", 0.0))
    ratio_str = f"{ratio:.4f}" if ratio > 0 else "&mdash;"
    positive_ratio = float(_assay_config().get(assay, {}).get("positive_ratio", 0.01))
    peaks = e["peaks_by_channel"].get(e["primary_peak_channel"], pd.DataFrame())

    wt_row = peaks[peaks.label == "WT"].sort_values("peaks", ascending=False) if not peaks.empty else pd.DataFrame()
    mut_rows = peaks[peaks.label.isin(["MUT", "ITD"])].sort_values(["peaks", "basepairs"], ascending=[False, True]) if not peaks.empty else pd.DataFrame()
    wt_main = _dominant_peak(wt_row)
    mut_main = _dominant_peak(mut_rows)

    if assay == "FLT3-ITD":
        if e.get("ratio_mode") != "manual":
            return ""
        wt_blue = wt_green = mut_blue = mut_green = 0.0
        reportable_mut_rows = peaks[0:0].copy() if peaks.empty else peaks.iloc[0:0].copy()
        wt_text = _flt3_manual_wt_text(e, peaks) or "<span class='small'>WT valgt manuelt</span>"
        mut_text = _flt3_manual_mutant_text(e, peaks) or "Ingen mutant valgt"
        wt_blue, wt_green, mut_blue, mut_green = _flt3_manual_channel_totals(e, peaks)
        reportable_mut_rows = peaks.iloc[0:0].copy() if peaks is not None else pd.DataFrame()
        if e.get("selected_mutant_peak_ids"):
            reportable_mut_rows = pd.DataFrame(
                [
                    _flt3_lookup_peak(peaks, peak_id)
                    for peak_id in e.get("selected_mutant_peak_ids") or []
                    if _flt3_lookup_peak(peaks, peak_id) is not None
                ]
            )
        ratio_num = float(e.get("ratio_numerator_area", 0.0))
        ratio_den = float(e.get("ratio_denominator_area", 0.0))
        mut_prop = (ratio_num / (ratio_num + ratio_den)) if (ratio_num + ratio_den) > 0 else 0.0
        label = "Positiv" if ratio >= positive_ratio else "Negativ"
        if ratio < positive_ratio and not reportable_mut_rows.empty:
            label = "Negativ, dokumentert"
        concordance_row = _flt3_lookup_peak(peaks, e.get("selected_wt_peak_id")) if e.get("ratio_mode") == "manual" else wt_main
        concordance = _itd_concordance_text(concordance_row, reportable_mut_rows)
        validation_text = f"<strong>{label}</strong>"
        validation_text += "<br><span class='status-badge manual'>Manual ratio</span>"
        if concordance:
            validation_text += f"<br><span class='small'>{concordance}</span>"
        distance_text = _flt3_distance_summary_span(e, peaks)
        return (
            "<div style='margin-top:10px; margin-bottom:24px;'>"
            "<table style='width:100%; border:1px solid #e2e8f0; table-layout:fixed;'>"
            "<tr><th>WT-topp</th><th>Muterte topper</th><th>Δbp / kodoner</th><th>Bla kanal</th><th>Gronn kanal</th><th>Ratioer</th><th>Validering</th></tr>"
            f"<tr><td>{wt_text}</td>"
            f"<td>{mut_text}</td>"
            f"<td>{distance_text}</td>"
            f"<td>WT: {wt_blue:,.0f}<br>Mut: {mut_blue:,.0f}</td>"
            f"<td>WT: {wt_green:,.0f}<br>Mut: {mut_green:,.0f}</td>"
            f"<td>ITD-ratio: <strong>{ratio_str}</strong><br>"
            f"<span class='small'>Mut/WT: {float(e.get('ratio_numerator_area', 0.0)):,.0f} / {float(e.get('ratio_denominator_area', 0.0)):,.0f}<br>"
            f"Mut/(Mut+WT): {mut_prop:.4f}<br>Positiv grense > {positive_ratio:.2f}</span></td>"
            f"<td>{validation_text}</td></tr></table></div>"
        )

    if assay == "FLT3-D835":
        if e.get("ratio_mode") != "manual":
            return ""

        selected_mut_rows = peaks.iloc[0:0].copy() if peaks is not None else pd.DataFrame()
        if e.get("selected_mutant_peak_ids"):
            selected_mut_rows = pd.DataFrame(
                [
                    _flt3_lookup_peak(peaks, peak_id)
                    for peak_id in e.get("selected_mutant_peak_ids") or []
                    if _flt3_lookup_peak(peaks, peak_id) is not None
                ]
            )
        wt_selected_row = _flt3_lookup_peak(peaks, e.get("selected_wt_peak_id"))
        digest_status, digest_row = _d835_digest_status(peaks, wt_selected_row, _dominant_peak(selected_mut_rows))
        label = "Positiv" if ratio >= positive_ratio else "Negativ" if selected_mut_rows.empty else "Under positiv grense"
        digest_text = "&mdash;"
        if digest_row is not None:
            digest_text = _peak_text(digest_row)
            if digest_status:
                digest_text += f"<br><span class='small'>{digest_status}</span>"
        wt_text = _flt3_manual_wt_text(e, peaks) or "<span class='small'>WT valgt manuelt</span>"
        mut_text = _flt3_manual_mutant_text(e, peaks) or "Ingen mutant valgt"
        distance_text = _flt3_distance_summary_span(e, peaks)
        validation_text = f"<strong>{label}</strong><br><span class='status-badge manual'>Manual ratio</span>"
        return (
            "<div style='margin-top:10px; margin-bottom:24px;'>"
            "<table style='width:100%; border:1px solid #e2e8f0; table-layout:fixed;'>"
            "<tr><th>WT-topp</th><th>Mutert topp</th><th>Δbp / kodoner</th><th>150 bp kontroll</th><th>TKD-ratio</th><th>Validering</th></tr>"
            f"<tr><td>{wt_text}</td>"
            f"<td>{mut_text}</td>"
            f"<td>{distance_text}</td>"
            f"<td>{digest_text}</td>"
            f"<td><strong>{ratio_str}</strong><br><span class='small'>Mut/WT: {float(e.get('ratio_numerator_area', 0.0)):,.0f} / {float(e.get('ratio_denominator_area', 0.0)):,.0f}<br>Positiv grense > {positive_ratio:.2f}</span></td>"
            f"<td>{validation_text}</td></tr></table></div>"
        )

    if assay == "NPM1":
        label = "Positiv" if ratio >= positive_ratio else "Negativ" if mut_main is None else "Manuell vurdering"
        distance_text = _flt3_distance_summary_span(e, peaks)
        return (
            "<div style='margin-top:10px; margin-bottom:24px;'>"
            "<table style='width:100%; border:1px solid #e2e8f0; table-layout:fixed;'>"
            "<tr><th>Villtype</th><th>Mutert</th><th>Δbp / kodoner</th><th>Ratio</th><th>Validering</th></tr>"
            f"<tr><td>{_peak_text(wt_main)}</td><td>{_format_peak_list(mut_rows, max_peaks=4)}</td>"
            f"<td>{distance_text}</td><td><strong>{ratio_str}</strong></td><td><strong>{label}</strong></td></tr></table></div>"
        )

    return ""


def _clonality_ml_label_for_entry(entry: dict) -> str:
    """Return the ML suggestion label for an entry, or '' if absent.

    Pure helper — no HTML, no I/O. Used by the badge renderer and
    by the JS dismissal serialiser so they share a single source
    of truth for what counts as 'present'.
    """
    label = str(entry.get("ClonalityMLSuggestion") or "").strip()
    return label


def _clonality_ml_confidence_for_entry(entry: dict) -> str:
    raw = entry.get("ClonalityMLConfidence", "")
    if raw in (None, "", 0):
        return ""
    try:
        return f"{float(raw):.2f}"
    except (TypeError, ValueError):
        return ""


def _clonality_ml_threshold_for_entry(entry: dict) -> str:
    raw = entry.get("ClonalityMLThreshold", "")
    if raw in (None, ""):
        return ""
    try:
        return f"{float(raw):.2f}"
    except (TypeError, ValueError):
        return ""


def _render_clonality_ml_badge(entry: dict, html_lines: list[str]) -> None:
    """Render a dismissible ML badge for a single sample.

    No-op when ``entry['ClonalityMLSuggestion']`` is empty. Otherwise
    the badge carries:
        - the label (e.g. "monoklonal") and confidence
        - a "Skjul for patolog" button that hides the badge from the
          pathologist's view without re-running the pipeline
        - a hidden "Gjenopprett" button that pops back when dismissed
        - dataset attributes the JS uses to persist dismissal state
          when the chemist presses Save Peaks.

    ID is keyed on identity_key + assay + file_name so re-running
    the same sample lands on the same badge after the chart re-render.
    """
    label = _clonality_ml_label_for_entry(entry)
    if not label:
        return
    confidence = _clonality_ml_confidence_for_entry(entry)
    threshold = _clonality_ml_threshold_for_entry(entry)
    review_needed = entry.get("ClonalityMLReviewNeeded", False)
    evidence = str(entry.get("ClonalityMLEvidence") or "").strip()
    rule_label = str(entry.get("ClonalitySuggestion") or "").strip()
    identity_key = (
        str(entry.get("dit") or entry.get("DIT") or "")
        or str(getattr(entry.get("fsa"), "file_name", "") or entry.get("file_name") or "")
    )
    assay = str(entry.get("assay") or "")
    file_name = str(getattr(entry.get("fsa"), "file_name", "") or entry.get("file_name") or "")
    import hashlib
    badge_id_src = f"{identity_key}|{assay}|{file_name}".encode("utf-8")
    badge_id = "ml-" + hashlib.md5(badge_id_src).hexdigest()[:16]
    rule_gloss = (
        f"<span class='ml-rule-gloss'>regel: {escape(rule_label or 'ukjent')}</span>"
        if rule_label
        else ""
    )
    review_gloss = (
        "<span class='ml-review-tag ml-review-flagged' "
        f"title='{escape(evidence or 'Lav konfidens eller uenighet med regellaget')}'"
        ">&#9888; vurder</span>"
        if review_needed
        else ""
    )
    confidence_text = f" ({confidence})" if confidence else ""
    threshold_gloss = (
        f"<span class='ml-rule-gloss'>grense: {escape(threshold)}</span>"
        if threshold
        else ""
    )
    html_lines.append(
        f"<div class='clonality-ml-badge' "
        f"id='{badge_id}' data-state='active' "
        f"data-dit='{escape(identity_key)}' data-assay='{escape(assay)}' "
        f"data-file='{escape(file_name)}' data-ml-label='{escape(label)}' "
        f"data-ml-review='{1 if review_needed else 0}'>"
        f"<span class='ml-badge-label'>ML: <strong>{escape(label)}</strong>"
        f"{escape(confidence_text)}</span>"
        f"{review_gloss}"
        f"{rule_gloss}"
        f"{threshold_gloss}"
        f"<button class='ml-dismiss no-print' type='button' "
        f"onclick='ClonalityDecisionLog.dismiss(this)'>Skjul for patolog</button>"
        f"<button class='ml-restore no-print' type='button' hidden "
        f"onclick='ClonalityDecisionLog.restore(this)'>Gjenopprett</button>"
        f"</div>"
    )


def _render_clonality_channel_ml_results(
    entry: dict,
    html_lines: list[str],
) -> None:
    """Render independent channel-level technical suggestions in shadow mode."""
    results = entry.get("ClonalityMLChannelResults")
    if not isinstance(results, list) or not results:
        return
    rows = []
    for result in results:
        if not isinstance(result, dict):
            continue
        channel = str(result.get("channel") or "")
        target = str(result.get("target_name") or channel)
        label = str(result.get("label") or "")
        if not label:
            continue
        try:
            confidence = f"{float(result.get('confidence')):.2f}"
        except (TypeError, ValueError):
            confidence = ""
        status = (
            "Vurder"
            if bool(result.get("review_needed", False))
            else "Akseptert skyggeforslag"
        )
        rows.append(
            "<tr>"
            f"<td>{escape(channel)}</td>"
            f"<td>{escape(target)}</td>"
            f"<td><strong>{escape(label)}</strong></td>"
            f"<td>{escape(confidence)}</td>"
            f"<td>{escape(status)}</td>"
            "</tr>"
        )
    if not rows:
        return
    html_lines.append(
        "<div class='clonality-channel-ml' style='margin:8px 0 14px;'>"
        "<table style='width:100%;border:1px solid #e2e8f0;'>"
        "<tr><th>Kanal</th><th>Teknisk mal</th><th>ML-forslag</th>"
        "<th>Konfidens</th><th>Status</th></tr>"
        + "".join(rows)
        + "</table></div>"
    )


def _render_ighv_peak_table(peaks: list[dict], html_lines: list[str]) -> None:
    """IGHV-topptabell: alle detekterte topper i referanseområdet."""
    if not peaks:
        html_lines.append(
            "<p class='small'>Ingen topper &gt; 5000 RFU i referanseområdet.</p>"
        )
        return
    rows = []
    for p in peaks:
        bp = float(p.get("bp", float("nan")))
        ht = float(p.get("height", float("nan")) or p.get("peaks", float("nan")))
        ar = float(p.get("area", float("nan")))
        bp_txt = f"{bp:.0f}" if bp == bp else "&mdash;"
        ht_txt = f"{ht:,.0f}" if ht == ht else "&mdash;"
        ar_txt = f"{ar:,.0f}" if ar == ar else "&mdash;"
        rows.append(f"<tr><td>{bp_txt}</td><td>{ht_txt}</td><td>{ar_txt}</td></tr>")
    html_lines.append(
        "<table class='peak-table'><thead><tr>"
        "<th>Topp (bp)</th><th>H&oslash;yde (RFU)</th><th>Areal</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_ighv_qc_table(qc_rows: dict, html_lines: list[str]) -> None:
    """IGHV QC-tabell: 300 bp stigetopp + PK-fragment."""
    if not qc_rows:
        return
    ladder = qc_rows.get("ladder_300") or {}
    pk = qc_rows.get("pk") or {}

    def _cell(row: dict, key: str, decimals: int = 0) -> str:
        val = row.get(key, float("nan"))
        try:
            val = float(val)
        except (TypeError, ValueError):
            return "&mdash;"
        if val != val:
            return "&mdash;"
        return f"{val:,.{decimals}f}"

    def _pk_flag(pk_row: dict) -> str:
        """«(utenfor forventet område)&raquo; kun når PK-topp ligger utenfor vinduet."""
        bp = pk_row.get("bp", float("nan"))
        lo = pk_row.get("window_lo")
        hi = pk_row.get("window_hi")
        try:
            bp_v = float(bp)
            lo_v = float(lo)
            hi_v = float(hi)
        except (TypeError, ValueError):
            return ""
        if bp_v != bp_v or lo_v != lo_v or hi_v != hi_v:
            return ""
        if not (lo_v <= bp_v <= hi_v):
            return f" <span class='ighv-pk-flag'>(utenfor {lo_v:.0f}&ndash;{hi_v:.0f} bp)</span>"
        return ""

    pk_flag_html = _pk_flag(pk)

    html_lines.append(
        "<table class='peak-table ighv-qc-table'><thead><tr>"
        "<th>Kontroll</th><th>Topp (bp)</th><th>H&oslash;yde (RFU)</th><th>Areal</th>"
        "</tr></thead><tbody>"
        f"<tr><td>Stige 300 bp</td><td>{_cell(ladder, 'bp')}</td>"
        f"<td>{_cell(ladder, 'height')}</td><td>{_cell(ladder, 'area')}</td></tr>"
        f"<tr><td>PK</td><td>{_cell(pk, 'bp', 1)}{pk_flag_html}</td>"
        f"<td>{_cell(pk, 'height')}</td><td>{_cell(pk, 'area')}</td></tr>"
        "</tbody></table>"
    )


def _render_assay_block(
    assay_name: str,
    assay_entries: list[dict],
    html_lines: list[str],
    report_metrics: dict[str, float | int] | None = None,
):
    """Renders a single assay block with plots for each file."""
    display_name = assay_name
    reference_assay = assay_name
    if assay_name.startswith("FLT3-ITD"):
        reference_assay = "FLT3-ITD"

    html_lines.append("<div class='assay-block'>")
    html_lines.append(f"<h3>{escape(display_name)}</h3>")

    # Rearrangement info once per assay block keeps replicate sections compact.
    rearrangement_html = _render_rearrangement_info_html(reference_assay)
    if rearrangement_html:
        html_lines.append(rearrangement_html)

    sort_key = _flt3_display_sort_key if reference_assay in {"FLT3-ITD", "FLT3-D835", "NPM1"} else (lambda x: x["fsa"].file_name)
    for e in sorted(assay_entries, key=sort_key):
        fsa, primary_ch = e["fsa"], e["primary_peak_channel"]
        html_lines.append(f"<p class='sample-header'>{escape(fsa.file_name)} ({escape(primary_ch)})</p>")
        if reference_assay in {"FLT3-ITD", "FLT3-D835", "NPM1"}:
            sub = [
                f"Well: {e.get('well_id') or '&mdash;'}",
                f"Injeksjon: {e.get('selected_injection') or ''}",
            ]
            html_lines.append(f"<p class='small'>{escape(' | '.join(sub))}</p>")
        html_lines.append(_build_report_plot_fragment(e, report_metrics))
        if reference_assay.startswith("IGHV"):
            # Klonal-topp-verdict + topptabell + (for kontroller) QC-tabell.
            from core.ighv import format_clonal_verdict

            peaks = e.get("ighv_clonal_peaks")
            if peaks is None:
                tbl = e.get("peaks_by_channel", {}).get(primary_ch)
                try:
                    if tbl is not None and hasattr(tbl, "itertuples") and len(tbl):
                        peaks = [
                            {"bp": r.basepairs, "height": r.peaks, "area": getattr(r, "area", float("nan"))}
                            for r in tbl.itertuples(index=False)
                        ]
                    else:
                        peaks = []
                except Exception:
                    peaks = []
            if not e.get("ighv_verdict"):
                e["ighv_verdict"] = format_clonal_verdict(peaks)
            html_lines.append(
                f"<p class='ighv-verdict'><strong>{escape(str(e.get('ighv_verdict') or ''))}</strong></p>"
            )
            _render_ighv_peak_table(peaks or [], html_lines)
            _render_ighv_qc_table(e.get("ighv_qc_rows") or {}, html_lines)
        # ML badge (clonality only) — inserts before the FLT3 summary
        # table so the dismiss buttons line up vertically. We also call
        # this for FLT3 entries; they just won't render anything since
        # the entry has no ClonalityML* keys.
        _render_clonality_channel_ml_results(e, html_lines)
        _render_clonality_ml_badge(e, html_lines)

        if reference_assay in {"FLT3-ITD", "FLT3-D835", "NPM1"}:
            html_lines.append(_build_flt3_summary_table(e))

    # Add collapsible Comment Box for the overall assay
    html_lines.append(
        "<div class='comment-box-container'>"
        "<button class='comment-toggle-btn' onclick='toggleComment(this)'>"
        "💬 <span class='comment-label'>Legg til kommentar</span>"
        f" <em style='font-weight:400;opacity:0.7;'>({escape(display_name)})</em>"
        "<i class='caret'>&#x25BC;</i>"
        "</button>"
        "<div class='comment-body'>"
        "<textarea class='report-comment' placeholder='Skriv inn eventuelle kommentarer her...'></textarea>"
        "</div>"
        "</div>"
    )

    html_lines.append("</div>")

def _render_tcrb_rep_block(
    entries: list[dict],
    replicate_num: str,
    html_lines: list[str],
    report_metrics: dict[str, float | int] | None = None,
):
    """Renders a combination block for TCRb replicates."""
    if not entries: return
    html_lines.append("<div class='assay-block'>")
    html_lines.append("<div class='combo-grid'>")
    group_y = compute_group_ymax_for_entries(entries)
    
    # Calculate global X range
    forced_xmin = min((float(e["bp_min"]) for e in entries), default=0)
    forced_xmax = max((float(e["bp_max"]) for e in entries), default=1000)

    for e in sorted(entries, key=lambda x: x["assay"]):
        fsa, primary_ch = e["fsa"], e["primary_peak_channel"]
        e_combo = dict(e)
        e_combo["forced_ymax"] = group_y
        e_combo["forced_xmin"] = forced_xmin
        e_combo["forced_xmax"] = forced_xmax
        e_combo["compact"] = True

        html_lines.append("<div class='combo-item'>")
        html_lines.append(_build_report_plot_fragment(e_combo, report_metrics))
        html_lines.append("</div>")
    html_lines.append("</div></div>")

def _render_tcrg_combo_block(
    tcrg_entries: list[dict],
    html_lines: list[str],
    report_metrics: dict[str, float | int] | None = None,
):
    """Renders a combined block for TCRg assays."""
    if not tcrg_entries: return
    group_y = compute_group_ymax_for_entries(tcrg_entries)
    
    # Calculate global X range
    forced_xmin = min((float(e["bp_min"]) for e in tcrg_entries), default=0)
    forced_xmax = max((float(e["bp_max"]) for e in tcrg_entries), default=1000)

    html_lines.append("<h2>Kombinasjonsfigur – TCRγ</h2><div class='assay-block'>")
    html_lines.append("<div class='combo-grid'>")
    for e in sorted(tcrg_entries, key=lambda x: x["assay"]):
        fsa, primary_ch = e["fsa"], e["primary_peak_channel"]
        e_combo = dict(e)
        e_combo["forced_ymax"] = group_y
        e_combo["forced_xmin"] = forced_xmin
        e_combo["forced_xmax"] = forced_xmax
        e_combo["compact"] = True

        html_lines.append("<div class='combo-item'>")
        html_lines.append(_build_report_plot_fragment(e_combo, report_metrics))
        html_lines.append("</div>")
    html_lines.append("</div></div>")


def _render_sl_metrics_table(sl_metrics: dict, html_lines: list[str]):
    targets = sl_metrics.get("targets_bp", [])
    areas = sl_metrics.get("areas", [])
    pcts = sl_metrics.get("percents", [])
    total_area = sl_metrics.get("total_area", float("nan"))

    html_lines.append("<table><tr><th>Fragment (bp)</th><th>Area</th><th>% av total</th></tr>")
    for bp_val, area_val, pct_val in zip(targets, areas, pcts):
        area_str = f"{area_val:,.0f}".replace(",", " ") if not np.isnan(area_val) else "&mdash;"
        pct_str = f"{pct_val:.1f} %" if pct_val is not None and not np.isnan(pct_val) else "&mdash;"
        html_lines.append(f"<tr><td>{bp_val:.0f}</td><td>{area_str}</td><td>{pct_str}</td></tr>")
    tot_str = f"{total_area:,.0f}".replace(",", " ") if not np.isnan(total_area) else "&mdash;"
    html_lines.append(f"<tr><td><strong>Total</strong></td><td><strong>{tot_str}</strong></td><td></td></tr></table>")


def _render_sl_section(all_sl_entries: list[dict], html_lines: list[str]):
    """Renders the Size Ladder (DNA quality) section."""
    valid_entries = [e for e in all_sl_entries if e.get("sl_metrics")]
    if not valid_entries: return
    html_lines.append("<h2>Size Ladder (SL) – DNA-kvalitet</h2>")
    for e in sorted(valid_entries, key=lambda x: x.get("fsa").file_name if x.get("fsa") else ""):
        sl_metrics = e.get("sl_metrics")
        html_lines.append(f"<h3>SL-fil: {escape(e['fsa'].file_name)}</h3>")
        if not sl_metrics:
            html_lines.append("<p><em>Ingen SL-area-metrikker tilgjengelig.</em></p>")
            continue
        _render_sl_metrics_table(sl_metrics, html_lines)


def _qc_rules_from_settings() -> QCRules:
    s_qc = APP_SETTINGS.get("qc", {})
    sample_window = s_qc.get("sample_peak_window_bp", s_qc.get("w_sample", 3.0))
    ladder_window = s_qc.get("ladder_peak_window_bp", s_qc.get("w_ladder", 3.0))
    return QCRules(
        min_r2_ok=s_qc.get("min_r2_ok", 0.999),
        min_r2_warn=s_qc.get("min_r2_warn", 0.995),
        nk_ymax_floor=s_qc.get("nk_ymax_floor", 250.0),
        sample_peak_window_bp=sample_window,
        sample_peak_window_bp_fallback=s_qc.get("sample_peak_window_bp_fallback", max(float(sample_window) + 4.0, 8.0)),
        ladder_peak_window_bp=ladder_window,
    )


def _control_id_for_entry(entry: dict) -> str:
    fsa = entry.get("fsa")
    return control_id_from_filename(str(getattr(fsa, "file_name", "") or entry.get("file_name") or ""))


def _is_dit_qc_control(entry: dict) -> bool:
    return _control_id_for_entry(entry) in DIT_QC_CONTROL_IDS


_QC_CONTROL_RANK = {"PK": 0, "PK1": 0, "PK2": 0, "RK": 1, "NK": 2}


def _qc_entry_sort_key(entry: dict) -> tuple[str, int, str]:
    fsa = entry.get("fsa")
    return (
        normalize_assay_qc(str(entry.get("assay") or "")),
        _QC_CONTROL_RANK.get(_control_id_for_entry(entry), 99),
        str(getattr(fsa, "file_name", "") or entry.get("file_name") or ""),
    )


def _render_relevant_qc_section(
    dit_entries: list[dict],
    control_entries: list[dict],
    html_lines: list[str],
    report_metrics: dict[str, float | int] | None = None,
) -> None:
    patient_assays = {
        normalize_assay_qc(str(e.get("assay") or ""))
        for e in dit_entries
        if e.get("assay")
    }
    if not patient_assays:
        return

    relevant_controls = [
        e for e in control_entries
        if normalize_assay_qc(str(e.get("assay") or "")) in patient_assays
        and _is_dit_qc_control(e)
    ]
    if not relevant_controls:
        return

    relevant_controls = sorted(relevant_controls, key=_qc_entry_sort_key)
    rules = _qc_rules_from_settings()
    plot_fragments: dict[int, str] = {}

    for idx, entry in enumerate(relevant_controls):
        plot_fragments[idx] = _build_report_plot_fragment(entry, report_metrics, qc_rules=rules)

    assay_label = ", ".join(sorted(patient_assays))
    html_lines.append("<details class='dit-qc-section'>")
    html_lines.append(
        f"<summary>Relevant QC ({escape(assay_label)} - {len(relevant_controls)} kontrollfiler)</summary>"
    )
    html_lines.append("<div class='dit-qc-body'>")

    for assay in sorted({normalize_assay_qc(str(e.get("assay") or "")) for e in relevant_controls}):
        html_lines.append(f"<h3>QC - {escape(assay)}</h3>")
        for idx, entry in enumerate(relevant_controls):
            if normalize_assay_qc(str(entry.get("assay") or "")) != assay:
                continue
            fsa = entry.get("fsa")
            html_lines.append(
                f"<p class='sample-header'>{escape(_control_id_for_entry(entry))} - "
                f"{escape(str(getattr(fsa, 'file_name', '') or entry.get('file_name') or ''))}</p>"
            )
            html_lines.append(plot_fragments.get(idx, "<p class='small'><em>Ingen QC-data a vise.</em></p>"))
            if normalize_assay_qc(str(entry.get("assay") or "")) == "SL" and entry.get("sl_metrics"):
                _render_sl_metrics_table(entry["sl_metrics"], html_lines)

    html_lines.append("</div></details>")


def build_flt3_qc_html_report(entries: list[dict], qc_rows: list[dict], assay_outdir: Path) -> Path | None:
    """Build an FLT3 control/QC HTML report using the shared report styling."""
    report_started = time.perf_counter()
    report_metrics = _new_report_metrics()
    control_entries = [
        e for e in entries
        if e.get("group") in {"negative_control", "positive_control", "reactive_control"}
    ]
    if not control_entries or not qc_rows:
        return None

    assay_outdir.mkdir(exist_ok=True, parents=True)
    title = "FLT3_QC_Resultater"
    report_name = "FLT3 QC"
    html_lines: list[str] = []
    html_lines.extend(["<!DOCTYPE html>", "<html lang='no'>", "<head>", "<meta charset='utf-8'>"])
    html_lines.append(f"<title>{escape(title)}</title>")
    html_lines.append(REPORT_STYLE)
    html_lines.append(_local_plotly_tag(assay_outdir, version="2.35.2"))
    html_lines.append(_build_plotly_reflow_script())
    html_lines.extend(["</head>", "<body>"])

    gen_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    run_dirs = sorted({str(e.get("source_run_dir") or "") for e in control_entries if e.get("source_run_dir")})
    meta = [f"{len(control_entries)} kontrollfiler", f"{len(run_dirs)} kjoringer", f"Generert: {gen_date}"]
    html_lines.append(
        f"""
<div class='report-header no-print'>
  <h1>{escape(title)}</h1>
  <div class='meta'>{' &nbsp;&bull;&nbsp; '.join(meta)}</div>
</div>
<div style='display:none' class='print-only-header'>
  <h1>{escape(title)}</h1>
  <p>{' | '.join(meta)}</p>
</div>
"""
    )

    pass_count = sum(1 for row in qc_rows if str(row.get("Status", "")).upper() == "PASS")
    fail_count = sum(1 for row in qc_rows if str(row.get("Status", "")).upper() == "FAIL")
    html_lines.append("<h2>QC-oversikt</h2>")
    html_lines.append(
        "<table><tr><th>Rapport</th><th>Kontroller</th><th>Bestatt</th><th>Feilet</th><th>Kjoringer</th></tr>"
        f"<tr><td>{escape(report_name)}</td><td>{len(qc_rows)}</td><td>{pass_count}</td><td>{fail_count}</td>"
        f"<td>{', '.join(escape(r) for r in run_dirs) if run_dirs else '&mdash;'}</td></tr></table>"
    )

    html_lines.append("<h2>Kontrolltabell</h2>")
    html_lines.append(
        "<table><tr><th>Filnavn</th><th>Assay</th><th>Kontroll</th><th>Status</th><th>Forventning</th>"
        "<th>Valgt injeksjon</th><th>Ratio</th><th>Ladder QC</th><th>Detaljer</th></tr>"
    )
    entry_map = {e["fsa"].file_name: e for e in control_entries}
    for row in sorted(qc_rows, key=lambda item: (item.get("Assay", ""), item.get("ControlGroup", ""), item.get("File", ""))):
        entry = entry_map.get(row["File"])
        ladder_badge = _render_ladder_status_badge(entry) if entry is not None else _render_status_badge("Unknown", "unknown")
        ratio = float(row.get("Ratio", 0.0))
        ratio_text = f"{ratio:.4f}" if ratio > 0 else "&mdash;"
        html_lines.append(
            f"<tr><td>{escape(str(row.get('File', '')))}</td>"
            f"<td>{escape(str(row.get('Assay', '')))}</td>"
            f"<td>{escape(str(row.get('ControlGroup', '')))}</td>"
            f"<td>{_flt3_qc_status_badge(row)}</td>"
            f"<td>{escape(str(row.get('Expectation', '')))}</td>"
            f"<td>{escape(str(row.get('SelectedInjection', '') or ''))}</td>"
            f"<td>{ratio_text}</td>"
            f"<td>{ladder_badge}</td>"
            f"<td>{escape(str(row.get('Details', '') or '')) or '&mdash;'}</td></tr>"
        )
    html_lines.append("</table>")

    html_lines.append("<h2>Detaljer per kontroll</h2>")
    for row in sorted(qc_rows, key=lambda item: (item.get("Assay", ""), item.get("ControlGroup", ""), item.get("File", ""))):
        entry = entry_map.get(row["File"])
        if entry is None:
            continue
        html_lines.append("<div class='assay-block'>")
        html_lines.append(f"<h3>{escape(str(row.get('Assay', '')))} - {escape(str(row.get('ControlGroup', '')))}</h3>")
        html_lines.append(f"<p class='sample-header'>{escape(entry['fsa'].file_name)}</p>")
        meta_parts = [
            f"Well: {entry.get('well_id') or '—'}",
            f"Injeksjon: {entry.get('selected_injection') or '—'}",
            f"Run: {entry.get('source_run_dir') or '—'}",
        ]
        html_lines.append(f"<p class='small'>{escape(' | '.join(meta_parts))}</p>")
        html_lines.append(
            "<table><tr><th>QC-status</th><th>Forventning</th><th>WT area</th><th>Mutant area</th><th>Ratio</th><th>Ladder QC</th></tr>"
            f"<tr><td>{_flt3_qc_status_badge(row)}</td>"
            f"<td>{escape(str(row.get('Expectation', '')))}</td>"
            f"<td>{float(row.get('WT_Area', 0.0)):,.2f}</td>"
            f"<td>{float(row.get('Mutant_Area', 0.0)):,.2f}</td>"
            f"<td>{float(row.get('Ratio', 0.0)):.4f}</td>"
            f"<td>{_render_ladder_status_badge(entry)}</td></tr></table>"
        )
        details = str(row.get("Details") or "")
        if details:
            html_lines.append(f"<p class='small'><strong>Kommentar:</strong> {escape(details)}</p>")
        html_lines.append(_build_report_plot_fragment(entry, report_metrics))
        html_lines.append(_build_flt3_summary_table(entry))
        html_lines.append("</div>")

    html_lines.append("""
<div class="print-fab no-print">
  <button class="print-btn" onclick="window.print()">🖨&nbsp; Print / PDF</button>
</div>
</body></html>""")

    out_html = assay_outdir / "QC_FLT3_Injections.html"
    _atomic_write_html(out_html, "\n".join(html_lines))
    print_green(f"FLT3 QC HTML report saved to {out_html}")
    print_green(
        _format_report_metrics_summary(
            "FLT3_QC_Resultater",
            report_metrics,
            time.perf_counter() - report_started,
            out_html.stat().st_size,
        )
    )
    return out_html


def build_dit_html_reports(entries: list[dict], assay_outdir: Path):
    """Main entry for building per-patient DIT reports."""
    control_entries = []
    per_dit: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        ctrl_id = control_id_from_filename(e["fsa"].file_name)
        if ctrl_id in DIT_QC_CONTROL_IDS:
            control_entries.append(e)
        if (dit := e.get("dit")) and ctrl_id not in DIT_QC_CONTROL_IDS:
            per_dit[dit].append(e)

    if not per_dit:
        print_warning("[DIT] Fant ingen DIT-nummer – ingen rapporter generert.")
        return

    assay_outdir.mkdir(exist_ok=True, parents=True)
    print_green(f"[DIT] Lager pasientrapporter i {assay_outdir}")
    display_name = _resolve_report_display_name(entries)

    for dit, dit_entries in sorted(per_dit.items()):
        report_started = time.perf_counter()
        report_metrics = _new_report_metrics()
        year = dit_to_year(dit)
        assays: dict[str, list[dict]] = defaultdict(list)
        for e in dit_entries: assays[e["assay"]].append(e)

        html_lines: list[str] = []
        _create_html_header(dit, year, len(dit_entries), assay_outdir, html_lines, display_name=display_name)
        _render_file_summary_table(dit_entries, html_lines)

        html_lines.append("<h2>Assay-spesifikke oversikter</h2>")
        if "FLT3-ITD" in assays or "FLT3-D835" in assays or "NPM1" in assays:
            flt3_blocks = _flt3_report_blocks(assays)
            handled = {"FLT3-ITD", "FLT3-D835", "NPM1"}
            display_order = _assay_display_order()
            ordered = [a for a in display_order if a in assays and a not in handled] + [a for a in assays if a not in display_order and a not in handled]
            for assay_key, block_title, block_entries in flt3_blocks:
                _render_assay_block(block_title, block_entries, html_lines, report_metrics)

            for name in ordered:
                _render_assay_block(name, assays[name], html_lines, report_metrics)
                
                # Special Combination Sections
                if name == "TCRbC":
                    present = [a for a in ["TCRbA", "TCRbB", "TCRbC"] if a in assays]
                    sorted_rep = {a: sorted(assays[a], key=lambda x: x["fsa"].file_name) for a in present}
                    rep1 = [lst[0] for a, lst in sorted_rep.items() if len(lst) >= 1]
                    rep2 = [lst[1] for a, lst in sorted_rep.items() if len(lst) >= 2]
                    if rep1: html_lines.append("<h2>Kombinasjonsfigurer – TCRβ</h2>")
                    _render_tcrb_rep_block(rep1, "1", html_lines, report_metrics)
                    _render_tcrb_rep_block(rep2, "2", html_lines, report_metrics)
                
                if name == "TCRgB":
                    tcrg_all = []
                    for a in ["TCRgA", "TCRgB"]:
                        if a in assays: tcrg_all.extend(sorted(assays[a], key=lambda x: x["fsa"].file_name))
                    _render_tcrg_combo_block(tcrg_all, html_lines, report_metrics)
            _render_sl_section(dit_entries, html_lines)
            _render_relevant_qc_section(dit_entries, control_entries, html_lines, report_metrics)
            
            html_lines.append("""
<div class="print-fab no-print">
  <button class="print-btn save-peaks-btn" onclick="PeakManager.downloadUpdatedHtml()">💾&nbsp; Save Peaks</button>
  <button class="print-btn" onclick="printReport()">🖨&nbsp; Print / PDF</button>
</div>
</body></html>""")
            
            out_html = assay_outdir / f"{dit}_{display_name}_Resultater.html"
            _atomic_write_html(out_html, "\n".join(html_lines))
            print_green(f"[DIT] Lagret: {out_html}")
            print_green(
                _format_report_metrics_summary(
                    dit,
                    report_metrics,
                    time.perf_counter() - report_started,
                    out_html.stat().st_size,
                )
            )
            continue

        display_order = _assay_display_order()
        ordered = [a for a in display_order if a in assays] + [a for a in assays if a not in display_order]
        
        for name in ordered:
            _render_assay_block(name, assays[name], html_lines, report_metrics)
            
            # Special Combination Sections
            if name == "TCRbC":
                present = [a for a in ["TCRbA", "TCRbB", "TCRbC"] if a in assays]
                sorted_rep = {a: sorted(assays[a], key=lambda x: x["fsa"].file_name) for a in present}
                rep1 = [lst[0] for a, lst in sorted_rep.items() if len(lst) >= 1]
                rep2 = [lst[1] for a, lst in sorted_rep.items() if len(lst) >= 2]
                if rep1: html_lines.append("<h2>Kombinasjonsfigurer – TCRβ</h2>")
                _render_tcrb_rep_block(rep1, "1", html_lines, report_metrics)
                _render_tcrb_rep_block(rep2, "2", html_lines, report_metrics)
            
            if name == "TCRgB":
                tcrg_all = []
                for a in ["TCRgA", "TCRgB"]:
                    if a in assays: tcrg_all.extend(sorted(assays[a], key=lambda x: x["fsa"].file_name))
                _render_tcrg_combo_block(tcrg_all, html_lines, report_metrics)

        _render_sl_section(dit_entries, html_lines)
        _render_relevant_qc_section(dit_entries, control_entries, html_lines, report_metrics)
        
        html_lines.append("""
<div class="print-fab no-print">
  <button class="print-btn save-peaks-btn" onclick="PeakManager.downloadUpdatedHtml()">💾&nbsp; Save Peaks</button>
  <button class="print-btn" onclick="printReport()">🖨&nbsp; Print / PDF</button>
</div>
</body></html>""")
        
        out_html = assay_outdir / f"{dit}_{display_name}_Resultater.html"
        _atomic_write_html(out_html, "\n".join(html_lines))
        print_green(f"[DIT] Lagret: {out_html}")
        print_green(
            _format_report_metrics_summary(
                dit,
                report_metrics,
                time.perf_counter() - report_started,
                out_html.stat().st_size,
            )
        )


def interpret_sl_quality(percents, total_area):
    """Automatisk fortolkning av DNA-kvalitet basert på fragmentfordeling."""
    p100, p200, p300, p400, p600 = (percents[i] if i < len(percents) else float("nan") for i in range(5))
    if np.isnan(total_area) or total_area < 1e4: return "Materialet er uegnet (svært lite signal)."
    if np.isnan(p100) or p100 < 5: return "Materialet er uegnet (svært svak 100 bp-peak)."
    if p100 >= 85 and p200 <= 15 and p300 <= 5: return "Svært fragmentert materiale."
    sum_100_300, sum_100_200 = p100 + p200 + p300, p100 + p200
    if p100 >= 60 and sum_100_200 >= 80 and p300 <= 15: return "Mer enn 50 % fragmentert – redusert sensitivitet."
    if p100 >= 45 and sum_100_300 >= 70: return "Litt fragmentert – kan redusere sensitivitet."
    if p100 <= 50 and sum_100_200 <= 70 and p300 >= 10 and p400 >= 5: return "Bra kvalitet."
    return "Uvanlig fordeling – vurder manuelt."
