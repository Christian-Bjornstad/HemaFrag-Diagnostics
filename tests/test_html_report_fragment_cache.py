from core.html_reports import _legacy as html_reports


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
