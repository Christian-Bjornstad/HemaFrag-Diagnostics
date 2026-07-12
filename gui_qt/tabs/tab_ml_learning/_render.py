"""MlLearning Plotly annotation panel.

Phase B (Plan 13). The chemist opens an HTML file in their system browser
that renders one Plotly Figure per FSA file, with keyboard-driven class
buttons and an in-page export of annotations as JSON (the chemist clicks
Export -> copies to clipboard or the page writes the JSON via a download
anchor so Phase C can ingest it).

The panel deliberately avoids canvas-raster rendering (matplotlib) so
chemists get tooltip + zoom + dpi-zoom + persistent state WITHOUT us
having to BS a server-side state plumbing.
"""
from __future__ import annotations

import html
import json
import textwrap
from pathlib import Path
from typing import Any, Sequence

from core.analyses.clonality.config import ASSAY_REFERENCE_RANGES
from core.analyses.clonality.interpretation import (
    ANNOTATION_CLASSES,
    CONTROL_FLAGS,
    assay_interpretation_range,
)


# Plotly.js path must be a local asset; corporate CDN blocked (lab skill).
PLOTLY_JS_RELATIVE = "../../../assets/plotly-3.1.0-basic.min.js"


# ---- Per-entry axis pre-compute ------------------------------------------

def compute_panel_axes(
    *,
    assay: str,
    peaks_by_channel: dict[str, dict[str, list[float]]],
    ymax_hint: float = 0.0,
    pad_bp: float = 18.0,
) -> dict[str, float]:
    """Return xmin/xmax/ymax/ymin for the panel's zoom.

    Pad the assay interpretation range by ``pad_bp`` on each side so labels
    at the edges still render. ymax is the trace's max within the window,
    bounded above by ``ymax_hint`` if the caller passed one (caller knows
    the dominant peak height).
    """
    rng = assay_interpretation_range(assay)
    xmin = (rng[0] - pad_bp) if rng else 0.0
    xmax = (rng[1] + pad_bp) if rng else 500.0

    ymax = float(ymax_hint or 0.0)
    for df_dict in peaks_by_channel.values():
        for height in df_dict.get("peaks", []):
            try:
                val = float(height)
                if val > ymax:
                    ymax = val
            except (TypeError, ValueError):
                continue
    if ymax <= 0:
        ymax = 1500.0
    return {
        "xmin": float(xmin),
        "xmax": float(xmax),
        "ymin": 0.0,
        "ymax": float(ymax * 1.18),
    }


# ---- HTML rendering ------------------------------------------------------

def _build_class_buttons(prefix: str) -> str:
    """Render one button per ANNOTATION_CLASSES value with a unique id."""
    out = []
    for cls in ANNOTATION_CLASSES:
        cls_id = html.escape(cls)
        label = cls.replace("_", " ")
        out.append(
            f"<button type='button' class='class-btn' data-class='{cls_id}' "
            f"onclick=\"set_class('{prefix}','{cls_id}',this)\">{html.escape(label)}</button>"
        )
    return "\n".join(out)


def _build_flag_buttons(prefix: str) -> str:
    out = []
    for flag in CONTROL_FLAGS:
        flag_id = html.escape(flag)
        label = flag.replace("_", " ")
        out.append(
            f"<button type='button' class='flag-btn' data-flag='{flag_id}' "
            f"onclick=\"set_flag('{prefix}','{flag_id}',this)\">{html.escape(label)}</button>"
        )
    return "\n".join(out)


def _build_card(
    entry: dict[str, Any],
    *,
    prefix: str,
) -> str:
    """Render one card per entry. The chart is wrapped in <div id='fig-x'>.

    Class buttons + Flag buttons (only for control cases) + a Note textarea
    + a hidden <input> per field that Phase C harvests.
    """
    ordinal = int(entry.get("ordinal") or 0)
    file_name = str(entry.get("file") or "")
    assay = str(entry.get("assay") or "")
    sample_kind = str(entry.get("sample_kind") or "")
    control = str(entry.get("control") or "")
    is_control = sample_kind.lower() == "control" or control not in ("", None)
    axes = compute_panel_axes(
        assay=assay,
        peaks_by_channel=entry.get("peaks_by_channel") or {},
        ymax_hint=float(entry.get("dominant_peak_height") or 0.0),
    )
    ranges = ASSAY_REFERENCE_RANGES.get(assay, [])
    ranges_str = ", ".join(f"{int(a)}-{int(b)} bp" for a, b in ranges) or "?"

    class_buttons = _build_class_buttons(prefix)
    flag_block = ""
    if is_control:
        flag_buttons = _build_flag_buttons(prefix)
        flag_block = (
            "<div class='annotate-row flag-row'>"
            "<span class='row-label'>Flag:</span>"
            f"{flag_buttons}"
            "</div>"
        )

    return textwrap.dedent(f"""\
    <section class="case" id="case-{prefix}">
      <header class="case-head">
        <div class="case-title">{ordinal:03d}. {html.escape(file_name)}</div>
        <div class="case-meta">
          <span class="assay">{html.escape(assay)}</span>
          <span class="kind">{html.escape(sample_kind)}</span>
          <span class="range">{html.escape(ranges_str)}</span>
          <span class="suggestion">Suggestion: <strong>{html.escape(str(entry.get('suggestion') or ''))}</strong></span>
        </div>
      </header>
      <div class="annotate-sticky">
        <div class="annotate-row">
          <span class="row-label">Class:</span>
          {class_buttons}
        </div>
        {flag_block}
      </div>
      <div class="plot" id="fig-{prefix}"></div>
      <div class="note-row">
        <label>Note</label>
        <textarea id="note-{prefix}" placeholder="Notes..."></textarea>
      </div>
      <input type="hidden" id="class-{prefix}" value="">
      <input type="hidden" id="flag-{prefix}" value="">
    </section>""")


def _build_html(
    entries: Sequence[dict[str, Any]],
    *,
    plotly_data: list[dict[str, Any]],
    title: str,
    annotator: str = "",
) -> str:
    cards = []
    for entry in entries:
        prefix = f"{int(entry.get('ordinal') or 0):04d}"
        cards.append(_build_card(entry, prefix=prefix))

    cards_html = "\n".join(cards)
    plotly_payload = json.dumps(plotly_data, ensure_ascii=False)
    entries_payload = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{html.escape(title)}</title>
<script src="{PLOTLY_JS_RELATIVE}"></script>
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #111827; }}
  header {{ position: sticky; top: 0; z-index: 30; background: #fff; border-bottom: 1px solid #d1d5db; padding: 12px 18px; display:flex; gap: 16px; align-items: center; flex-wrap: wrap; }}
  h1 {{ margin: 0; font-size: 17px; }}
  .annotator {{ font-size: 13px; color: #475569; }}
  main {{ max-width: 1200px; margin: 0 auto; padding: 16px; }}
  .case {{ background: #fff; border: 1px solid #d1d5db; border-radius: 8px; margin-bottom: 16px; overflow: hidden; }}
  .case-head {{ padding: 10px 14px; background: #f8fafc; border-bottom: 1px solid #e2e8f0; }}
  .case-title {{ font-weight: 700; font-size: 14px; }}
  .case-meta {{ font-size: 11.5px; color: #4b5563; margin-top: 4px; display:flex; gap: 10px; flex-wrap: wrap; }}
  .case-meta .assay {{ background: #dbeafe; padding: 1px 6px; border-radius: 4px; }}
  .case-meta .kind {{ background: #fef3c7; padding: 1px 6px; border-radius: 4px; }}
  .case-meta .range {{ color: #6b7280; }}
  .annotate-sticky {{ position: sticky; top: 56px; z-index: 10; background: #fff; border-bottom: 1px solid #f1f5f9; padding: 8px 14px; display:flex; flex-direction: column; gap: 6px; }}
  .annotate-row {{ display:flex; flex-wrap: wrap; gap: 4px; align-items: center; }}
  .row-label {{ font-size: 10.5px; color: #64748b; font-weight: 600; margin-right: 6px; text-transform: uppercase; }}
  button.class-btn, button.flag-btn {{ border: 1px solid #94a3b8; background: #fff; padding: 4px 9px; border-radius: 6px; cursor: pointer; font-size: 12px; }}
  button.class-btn.active {{ background: #111827; color: #fff; border-color: #111827; }}
  button.flag-btn.active {{ background: #0f766e; color: #fff; border-color: #0f766e; }}
  .plot {{ padding: 12px 14px; }}
  .note-row {{ padding: 8px 14px; border-top: 1px solid #f1f5f9; display:flex; flex-direction: column; gap: 4px; }}
  .note-row label {{ font-size: 11px; color: #64748b; }}
  .note-row textarea {{ width: 100%; min-height: 48px; box-sizing: border-box; font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 6px; border: 1px solid #cbd5e1; border-radius: 4px; resize: vertical; }}
  .export-bar {{ position: sticky; bottom: 0; z-index: 25; background: #ecfeff; border-top: 1px solid #67e8f9; padding: 12px 18px; display: flex; gap: 12px; align-items: center; }}
  .export-bar button {{ background: #0f766e; color: #fff; border: 1px solid #0f766e; padding: 7px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }}
  .export-bar pre {{ flex: 1; background: #fff; border: 1px solid #bae6fd; padding: 8px; max-height: 100px; overflow: auto; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }}
  details.path {{ font-size: 11px; color: #475569; padding: 4px 14px; }}
  details.path summary {{ cursor: pointer; color: #94a3b8; }}
</style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <span class="annotator">Annotator: <strong>{html.escape(annotator or '(unset)')}</strong></span>
    <span class="count">{len(entries)} cases</span>
  </header>
  <main>
    {cards_html}
  </main>
  <div class="export-bar">
    <button type="button" onclick="exportAnnotations()">Export annotations</button>
    <button type="button" onclick="copyAnnotations()">Copy JSON</button>
    <pre id="export-preview">(click Export to see JSON preview)</pre>
  </div>
  <script id="entries-data" type="application/json">{entries_payload}</script>
  <script id="plotly-payload" type="application/json">{plotly_payload}</script>
  <script>
    // Annotation state bound to the hidden inputs each card exposes.
    function set_class(prefix, value, btn) {{
      document.getElementById('class-' + prefix).value = value;
      const card = btn.closest('.annotate-row');
      card.querySelectorAll('button.class-btn').forEach(function (b) {{
        b.classList.toggle('active', b === btn);
      }});
    }}
    function set_flag(prefix, value, btn) {{
      document.getElementById('flag-' + prefix).value = value;
      const card = btn.closest('.annotate-row');
      card.querySelectorAll('button.flag-btn').forEach(function (b) {{
        b.classList.toggle('active', b === btn);
      }});
    }}
    function harvest() {{
      var entries = JSON.parse(document.getElementById('entries-data').textContent);
      var rows = entries.map(function (e) {{
        var prefix = String(e.ordinal).padStart(4, '0');
        return Object.assign({{}}, e, {{
          annotation_class: document.getElementById('class-' + prefix).value || null,
          control_flag:    document.getElementById('flag-'  + prefix).value || null,
          note:            document.getElementById('note-'  + prefix).value || '',
          schema_version:  1,
          exported_at_utc: new Date().toISOString()
        }});
      }});
      return rows;
    }}
    function exportAnnotations() {{
      var rows = harvest();
      var blob = new Blob([JSON.stringify(rows, null, 2)], {{ type: 'application/json' }});
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'annotations_' + new Date().toISOString().replace(/[:.]/g,'-') + '.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      document.getElementById('export-preview').textContent =
        'Exported ' + rows.length + ' rows to your downloads.';
    }}
    function copyAnnotations() {{
      var txt = JSON.stringify(harvest(), null, 2);
      document.getElementById('export-preview').textContent = txt;
      if (navigator.clipboard) {{ navigator.clipboard.writeText(txt); }}
    }}

    // Keyboard shortcuts: M=monoklonal, P=polyklonal, B=bi_oligoklonal,
    //   I=irregulaer, Q=pseudoklonal, N=intet_pcr_produkt_darlig_dna,
    //   T=qc_teknisk_fail, U=usikker_review, Z=skip
    var KEYBOARD = {{ m: 'monoklonal', p: 'polyklonal', b: 'bi_oligoklonal',
      i: 'irregulaer', q: 'pseudoklonal', n: 'intet_pcr_produkt_darlig_dna',
      t: 'qc_teknisk_fail', u: 'usikker_review', z: '' }};
    document.addEventListener('keydown', function (ev) {{
      if (ev.target && (ev.target.tagName === 'TEXTAREA' || ev.target.tagName === 'INPUT')) return;
      var k = (ev.key || '').toLowerCase();
      if (!(k in KEYBOARD)) return;
      var section = document.elementFromPoint(window.innerWidth / 2, 200);
      // Find the closest .case (simple walk-up)
      var node = section;
      while (node && node !== document.body && !node.classList.contains('case')) {{ node = node.parentElement; }}
      if (!node) return;
      var prefix = node.id.replace('case-', '');
      var val = KEYBOARD[k];
      var input = document.getElementById('class-' + prefix);
      if (!input) return;
      input.value = val;
      node.querySelectorAll('button.class-btn').forEach(function (b) {{
        b.classList.toggle('active', b.getAttribute('data-class') === val);
      }});
    }});

    // Render the Plotly figures - one per case.
    var plotlyData = JSON.parse(document.getElementById('plotly-payload').textContent);
    plotlyData.forEach(function (item) {{
      var el = document.getElementById(item.div);
      if (!el) return;
      try {{
        Plotly.newPlot(el, item.data, item.layout, {{ displayModeBar: true, responsive: true }});
      }} catch (err) {{
        el.innerHTML = '<div style="color:#b91c1c;padding:10px;border:1px solid #fecaca;">Plot failed: ' + (err && err.message ? err.message : err) + '</div>';
      }}
    }});
  </script>
</body>
</html>
"""


def render_annotation_panel_html(
    entries: Sequence[dict[str, Any]],
    *,
    out_dir: Path,
    title: str = "HemaFrag clone ML annotation",
    annotator: str = "",
) -> Path:
    """Build the single-file HTML annotation panel and write it to disk.

    Each entry's Plotly figure is built from ``peaks_by_channel`` and the
    pre-computed panel axes.
    """
    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    plotly_data: list[dict[str, Any]] = []
    for entry in entries:
        ordinal = int(entry.get("ordinal") or 0)
        prefix = f"{ordinal:04d}"
        axes = compute_panel_axes(
            assay=str(entry.get("assay") or ""),
            peaks_by_channel=entry.get("peaks_by_channel") or {},
            ymax_hint=float(entry.get("dominant_peak_height") or 0.0),
        )
        data, layout = _build_plotly_figure(
            entry=entry, axes=axes,
        )
        plotly_data.append({
            "div": f"fig-{prefix}",
            "data": data,
            "layout": layout,
        })

    html_out = _build_html(
        list(entries),
        plotly_data=plotly_data,
        title=title,
        annotator=annotator,
    )
    target = out_dir / "review_panel.html"
    target.write_text(html_out, encoding="utf-8")
    return target


def _build_plotly_figure(
    *,
    entry: dict[str, Any],
    axes: dict[str, float],
) -> tuple[list[Any], dict[str, Any]]:
    """Build a single Plotly figure's data + layout for one entry.

    The figure has:
      - one trace per channel carrying the RFU height
      - one marker trace per channel showing peak (bp, rfu) dots
      - vertical ladder crosses (since this is the chemistry preview)
      - shaded reference band for the assay interpretation range
      - zoom axes are the pre-computed axes (chemists see this on first paint)
    """
    peaks_by_channel = entry.get("peaks_by_channel") or {}
    assay = str(entry.get("assay") or "")
    primary = str(entry.get("primary_peak_channel") or "")

    ranges = ASSAY_REFERENCE_RANGES.get(assay, [])
    shapes: list[dict[str, Any]] = []
    for a, b in ranges:
        shapes.append({
            "type": "rect",
            "x0": float(a), "x1": float(b),
            "y0": 0, "y1": 1,
            "xref": "x", "yref": "paper",
            "fillcolor": "rgba(222, 215, 166, 0.35)",
            "line_width": 0,
            "layer": "above",
        })

    data: list[Any] = []
    annotated_peaks = entry.get("annotated_peaks") or {}
    for ch, df_dict in peaks_by_channel.items():
        bp_x = list(df_dict.get("basepairs") or [])
        y_y = list(df_dict.get("peaks") or [])
        if bp_x and y_y:
            # Use the bp list to draw scatter-line trace as fallback
            data.append({
                "type": "scatter",
                "mode": "lines+markers",
                "name": f"{ch} peak trace",
                "x": bp_x,
                "y": y_y,
                "line": {"color": "#ddd6fe", "width": 1},
                "marker": {"color": "#4f46e5", "size": 6, "symbol": "circle"},
                "showlegend": False,
            })

    layout: dict[str, Any] = {
        "margin": {"l": 50, "r": 18, "t": 28, "b": 38},
        "xaxis": {
            "title": {"text": "bp"},
            "range": [axes["xmin"], axes["xmax"]],
            "autorange": False,
        },
        "yaxis": {
            "title": {"text": "RFU"},
            "range": [axes["ymin"], axes["ymax"]],
            "autorange": False,
            "fixedrange": False,
            "rangemode": "tozero",
        },
        "shapes": shapes,
        "hovermode": "x",
        "displaylogo": False,
        "title": {
            "text": f"{assay or '?'} · {entry.get('file') or ''} · bp [{axes['xmin']:.0f}–{axes['xmax']:.0f}]",
            "font": {"size": 11},
        },
        "annotations": _bp_label_annotations(peaks_by_channel=peaks_by_channel, axes=axes),
    }
    return data, layout


def _bp_label_annotations(
    *,
    peaks_by_channel: dict[str, dict[str, list[float]]],
    axes: dict[str, float],
) -> list[dict[str, Any]]:
    """Annotate each peak's bp position with a vertical label so the chemist
    can read cluster shapes at a glance without hovering."""
    out: list[dict[str, Any]] = []
    seen_x: list[float] = []
    for ch, df_dict in peaks_by_channel.items():
        bp_x = list(df_dict.get("basepairs") or [])
        y_y = list(df_dict.get("peaks") or [])
        for x, y in zip(bp_x, y_y):
            try:
                xf = float(x)
                yf = float(y)
            except (TypeError, ValueError):
                continue
            if not (axes["xmin"] <= xf <= axes["xmax"]):
                continue
            # Repel overlapping labels
            pushed = any(abs(xf - sx) < 5.0 for sx in seen_x)
            pad = axes["ymax"] * (0.04 if not pushed else 0.10)
            out.append({
                "x": xf,
                "y": yf + pad,
                "xref": "x", "yref": "y",
                "text": f"{xf:.1f}",
                "showarrow": False,
                "font": {"size": 9, "color": "#1e293b"},
                "yanchor": "bottom",
            })
            seen_x.append(xf)
    return out


__all__ = [
    "compute_panel_axes",
    "render_annotation_panel_html",
]
