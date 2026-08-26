"""IGHV prøvetype i HTML-rapporten (DNA/RNA) — regressjonsTester.

- _render_ighv_sample_type_line: RNA-farge matchet mot RNA-shading
- filename-derived prøvetype vises med «(filnavn)»-kilde
- ingen «Klonal topp … detektert.»-verdict i rapporten
- rødere RNA-shade i plottet for RNA-stemplede entries
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.html_reports._legacy import _render_ighv_sample_type_line


# ------------------------------------------------------------ helpers
def _entry(sample_type="DNA", from_filename=False):
    return {
        "assay": "IGHV Mix 1",
        "ighv_sample_type": sample_type,
        "ighv_sample_type_from_filename": from_filename,
        "fsa": SimpleNamespace(file_name="x.fsa"),
    }


# ------------------------------------------------------------ tests
class TestSampleTypeLine:
    def test_dna_shows_range_500_570(self):
        html = _render_ighv_sample_type_line(_entry("DNA"))
        assert "DNA" in html
        assert "500&ndash;570 bp" in html
        assert "#c05a44" not in html  # ingen rød farge på DNA

    def test_rna_shows_range_415_485_in_red(self):
        html = _render_ighv_sample_type_line(_entry("RNA"))
        assert "RNA" in html
        assert "415&ndash;485 bp" in html
        # Tekst og område i samme røde nyanse som shadingen.
        assert "color:#c05a44" in html

    def test_filename_source_annotated(self):
        html = _render_ighv_sample_type_line(_entry("RNA", from_filename=True))
        assert "(filnavn)" in html

    def test_mix2_always_310_380(self):
        entry = _entry("RNA")
        entry["assay"] = "IGHV Mix 2"
        html = _render_ighv_sample_type_line(entry)
        # Mix 2 har samme vindu uansett prøvetype.
        assert "310&ndash;380 bp" in html


class TestVerdictRemoved:
    def test_no_verdict_key_on_entry(self, monkeypatch):
        """attach_ighv_results skal ikke lenger sette ighv_verdict."""
        import core.ighv as m

        sig, bp = _synth_trace([(534.0, 9000.0)])
        fsa = SimpleNamespace(file_name="26OUM00001_A01.fsa")
        monkeypatch.setattr(m, "_trace_arrays", lambda f, ch="DATA1": (sig, bp))
        m.set_sample_type("IGHV Mix 1", "DNA")

        out = m.attach_ighv_results({"assay": "IGHV Mix 1", "fsa": fsa})
        assert "ighv_verdict" not in out


class TestRnaShade:
    def test_rna_stamped_entry_gets_redder_fill(self):
        """Plott-shading: RNA-entry → IGHV_RNA_SHADE_COLOR, DNA-entry → beige."""
        from core.plotting_plotly import _legacy as plot_legacy

        rna_entry = {"assay": "IGHV Mix 1", "ighv_sample_type": "RNA"}
        dna_entry = {"assay": "IGHV Mix 1", "ighv_sample_type": "DNA"}

        fill_rna = plot_legacy._reference_shape_fill(rna_entry)
        fill_dna = plot_legacy._reference_shape_fill(dna_entry)

        # Beige default er ded7a6; RNA-nyansen er rødere (e8b4a6).
        assert "222,215,166" in fill_dna or "ded7a6" in fill_dna.lower()
        assert "232,180,166" in fill_rna

    def test_non_ighv_entries_keep_default_beige(self):
        from core.plotting_plotly import _legacy as plot_legacy

        entry = {"assay": "FR1", "ighv_sample_type": "RNA"}
        fill = plot_legacy._reference_shape_fill(entry)
        assert "222,215,166" in fill or "ded7a6" in fill.lower()


def _synth_trace(peaks, bp_lo=50.0, bp_hi=700.0, n=6500):
    """Liten duplikat av test_core_ighv-helperen (unngår cross-import)."""
    import numpy as np

    bp = np.linspace(bp_lo, bp_hi, n)
    sig = np.full(bp.size, 150.0)
    for center, height in peaks:
        sig += height * np.exp(-0.5 * ((bp - center) / 1.5) ** 2)
    return sig, bp


if __name__ == "__main__":
    sys_exit = pytest.main([__file__, "-v"])
    raise SystemExit(sys_exit)
