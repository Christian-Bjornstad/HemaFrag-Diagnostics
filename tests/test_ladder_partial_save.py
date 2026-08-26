"""Delvis ladder-kartlegging (partial save) — regressjonsTester.

Brukeren skal kunne lagre en manuell ladderjustering uten a ha plassert
alle stige-topper: manglende trinn interpoleres/ekstrapoleres lineært i tid
fra de plasserte, dialogen spør om bekreftelse, og payloaden markeres som
``partial_mapping``.
"""
from __future__ import annotations

import numpy as np
import pytest


# ------------------------------------------------------------ helpers
class _FakeFsa:
    """Minimal FsaFile-standin for apply_manual_ladder_mapping."""

    def __init__(self, ladder_steps, ss_peaks):
        self.ladder = "ROX"
        self.expected_ladder_steps = np.asarray(ladder_steps, dtype=float)
        self.ladder_steps = np.asarray(ladder_steps, dtype=float)
        self.size_standard_peaks = np.asarray(ss_peaks, dtype=float)
        self.sample_data = np.zeros(10)
        # apply_manual_ladder_mapping -> fit_size_standard_to_ladder needs these:
        self.file_name = "fake.fsa"


def _fake_fit(fsa):
    fsa.fitted_to_model = True
    return fsa


# ------------------------------------------------------------ tests
class TestPartialInterpolation:
    def test_missing_middle_step_interpolated(self, monkeypatch):
        """Mellomrom mellom to plasserte topper fylles med linær interpolasjon."""
        import core.analysis._legacy as m

        steps = [50.0, 100.0, 150.0, 200.0]
        peaks = [100.0, 200.0, 400.0]  # step 1 (100 bp) er borte
        fsa = _FakeFsa(steps, peaks)
        monkeypatch.setattr(m, "fit_size_standard_to_ladder", _fake_fit)

        out = m.apply_manual_ladder_mapping(
            fsa,
            {"mapping": {}, "mapping_times": {0: 100.0, 2: 300.0}, "manual_candidates": []},
        )
        got = np.asarray(out.best_size_standard, dtype=float)
        assert np.isfinite(got).all()
        assert got[1] == pytest.approx(200.0)  # midpoint of 100/300
        assert list(got) == [100.0, 200.0, 300.0, 400.0]

    def test_trailing_steps_extrapolated(self, monkeypatch):
        """Skanne stopper før siste stigetopp — ekstrapolasjon utover."""
        import core.analysis._legacy as m

        fsa = _FakeFsa([50.0, 100.0, 150.0], [100.0, 200.0])
        monkeypatch.setattr(m, "fit_size_standard_to_ladder", _fake_fit)

        out = m.apply_manual_ladder_mapping(
            fsa,
            {
                "mapping": {},
                "mapping_times": {0: 100.0, 1: 200.0},
                "manual_candidates": [],
            },
        )
        got = np.asarray(out.best_size_standard, dtype=float)
        assert got[2] == pytest.approx(300.0)  # linear continuation

    def test_single_mapped_step_rejected(self):
        """Kun ett plassert trinn gir feil — ingen ankre a interpolere fra."""
        import core.analysis._legacy as m

        fsa = _FakeFsa([50.0, 100.0], [100.0])
        with pytest.raises(ValueError, match="at least two"):
            m.apply_manual_ladder_mapping(
                fsa,
                {"mapping": {}, "mapping_times": {0: 100.0}, "manual_candidates": []},
            )

    def test_strictly_increasing_still_enforced(self, monkeypatch):
        """Avvikende rekkefolge oppdages fortsatt etter interpolasjon."""
        import core.analysis._legacy as m

        fsa = _FakeFsa([50.0, 100.0, 150.0], [100.0, 500.0])
        monkeypatch.setattr(m, "fit_size_standard_to_ladder", lambda f: f)
        with pytest.raises(ValueError, match="strictly increasing"):
            m.apply_manual_ladder_mapping(
                fsa,
                {"mapping": {}, "mapping_times": {0: 500.0, 2: 100.0}, "manual_candidates": []},
            )


class TestPayloadFlag:
    def test_partial_mapping_flagged(self):
        """_build_adjustment_payload setter partial_mapping ved manglende trinn."""
        from gui_qt.dialogs.ladder_dialog._legacy import LadderAdjustmentDialog

        dlg = LadderAdjustmentDialog.__new__(LadderAdjustmentDialog)
        dlg.ladder_steps = np.array([50.0, 100.0, 150.0])
        dlg.mapping = {0: 0, 2: 2}
        dlg._missing_order = "ascending"
        dlg.candidates = None
        dlg._manual_candidate_times = []

        import pandas as pd

        dlg.candidates = pd.DataFrame({"time": [10.0, 20.0, 30.0]})
        payload = dlg._build_adjustment_payload()
        assert payload["partial_mapping"] is True
        assert set(payload["mapping"]) == {0, 2}

    def test_complete_mapping_not_flagged(self):
        from gui_qt.dialogs.ladder_dialog._legacy import LadderAdjustmentDialog
        import pandas as pd

        dlg = LadderAdjustmentDialog.__new__(LadderAdjustmentDialog)
        dlg.ladder_steps = np.array([50.0, 100.0])
        dlg.mapping = {0: 0, 1: 1}
        dlg._missing_order = "ascending"
        dlg._manual_candidate_times = []
        dlg.candidates = pd.DataFrame({"time": [10.0, 20.0]})
        payload = dlg._build_adjustment_payload()
        assert "partial_mapping" not in payload
