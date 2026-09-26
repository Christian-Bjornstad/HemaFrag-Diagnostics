from types import SimpleNamespace

import numpy as np
import pytest
from PyQt6 import QtWidgets  # Ensure pyqtgraph uses the app's Qt binding.

from gui_qt.dialogs.ladder_dialog import LadderAdjustmentDialog


@pytest.mark.parametrize("with_marker_identity,offset", [(False, 0.005), (True, 0.0000005)])
def test_restore_preserves_exact_saved_coordinate_among_nearby_candidates(
    with_marker_identity, offset
):
    saved_x = 1000.0 + offset
    adjustment = {
        "mapping": {0: 1},
        "mapping_times": {0: saved_x},
        "manual_candidates": [saved_x],
    }
    if with_marker_identity:
        adjustment.update({
            "markers": [{
                "marker_id": "saved-exact-marker",
                "scan_x": saved_x,
                "requested_x": saved_x,
                "source_kind": "manual_exact",
            }],
            "marker_id_by_step": {0: "saved-exact-marker"},
        })
    fsa = SimpleNamespace(
        file_name="nearby-markers.fsa",
        size_standard=np.ones(1200),
        size_standard_baseline_corrected=True,
        size_standard_peaks=np.array([1000.0, saved_x]),
        manual_ladder_candidates=[saved_x],
        best_size_standard=np.array([]),
    )
    dialog = SimpleNamespace(
        fsa=fsa,
        _initial_adjustment=adjustment,
        _recommended_missing_order=lambda: "ascending",
        _sync_missing_order_button=lambda: None,
    )
    dialog.candidates = LadderAdjustmentDialog._get_candidates(dialog)

    LadderAdjustmentDialog._restore_initial_adjustment(dialog)

    restored = dialog.candidates.iloc[dialog.mapping[0]]
    assert restored["time"] == saved_x
    if with_marker_identity:
        assert restored["marker_id"] == "saved-exact-marker"
