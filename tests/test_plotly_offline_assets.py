from pathlib import Path


def test_local_plotly_tag_copies_shared_asset(tmp_path, monkeypatch):
    from core import plotly_offline

    monkeypatch.delenv("HEMAFRAG_INLINE_PLOTLY_REPORTS", raising=False)
    tag = plotly_offline.local_plotly_tag(tmp_path)

    assert 'src="assets/plotly-3.1.0.min.js"' in tag
    assert (tmp_path / "assets" / "plotly-3.1.0.min.js").exists()


def test_local_plotly_tag_can_inline_for_single_file_portability(tmp_path, monkeypatch):
    from core import plotly_offline

    monkeypatch.setenv("HEMAFRAG_INLINE_PLOTLY_REPORTS", "1")
    tag = plotly_offline.local_plotly_tag(tmp_path)

    assert tag.startswith("<script>")
    assert "Plotly" in tag
