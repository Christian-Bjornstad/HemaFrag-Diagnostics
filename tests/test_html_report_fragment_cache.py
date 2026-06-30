import inspect

from core.html_reports import _legacy as html_reports


def test_save_peaks_script_escapes_closing_script_and_embeds_plot_payload(tmp_path):
    from core.plotting_plotly import _legacy as plotting_plotly

    html_lines = []
    html_reports._create_html_header(
        "26OUM00001",
        2026,
        1,
        tmp_path,
        html_lines,
        display_name="Klonalitet",
    )
    header_html = "\n".join(html_lines)

    assert '<\\/script>' in header_html
    assert 'type="application\\/json">[\\\\s\\\\S]*?<\\/script>' in header_html
    new_tag_line = next(line.strip() for line in header_html.splitlines() if line.strip().startswith("var newTag ="))
    new_plot_tag_line = next(line.strip() for line in header_html.splitlines() if line.strip().startswith("var newPlotTag ="))
    assert new_tag_line == r"""var newTag = '<script id="peak-data" type="application/json">\\n' + peakDataStr + '\\n<\/script>';"""
    assert new_plot_tag_line == r"""var newPlotTag = '<script id="plot-state" type="application/json">\\n' + plotStateStr + '\\n<\/script>';"""
    assert "_writeEmbeddedPeakData" in header_html
    assert "data-peak-payload" in inspect.getsource(plotting_plotly.build_interactive_peak_plot_for_entry)
    assert "data-peak-payload" in inspect.getsource(plotting_plotly.build_interactive_assay_batch_plot_html)


def test_default_report_plot_fragment_is_not_cached(monkeypatch):
    calls = {"count": 0}

    def fake_plot(_entry):
        calls["count"] += 1
        return f"<div>plot-{calls['count']}</div>"

    monkeypatch.setattr(html_reports, "build_interactive_peak_plot_for_entry", fake_plot)
    entry = {}
    metrics = html_reports._new_report_metrics()

    assert html_reports._build_report_plot_fragment(entry, metrics) == "<div>plot-1</div>"
    assert html_reports._build_report_plot_fragment(entry, metrics) == "<div>plot-2</div>"

    assert calls["count"] == 2
    assert metrics["plot_count"] == 2


def test_report_plot_fragment_cache_respects_qc_rules(monkeypatch):
    from core.qc.qc_rules import QCRules
    from core.html_reports import _legacy as html_reports

    calls = {"count": 0}

    def fake_qc_plot(_entry, _rules):
        calls["count"] += 1
        return f"<div>qc-{calls['count']}</div>"

    monkeypatch.setattr(html_reports, "build_interactive_peak_plot_for_entry_qc", fake_qc_plot)
    entry = {}
    metrics = html_reports._new_report_metrics()

    rules_a = QCRules(min_r2_ok=0.999)
    rules_b = QCRules(min_r2_ok=0.995)

    assert html_reports._build_report_plot_fragment(entry, metrics, qc_rules=rules_a) == "<div>qc-1</div>"
    assert html_reports._build_report_plot_fragment(entry, metrics, qc_rules=rules_a) == "<div>qc-1</div>"
    assert html_reports._build_report_plot_fragment(entry, metrics, qc_rules=rules_b) == "<div>qc-2</div>"

    assert calls["count"] == 2
