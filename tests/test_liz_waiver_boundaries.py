"""Early-anchor waivers must preserve valid calibration below 75 bp."""
from types import SimpleNamespace

import numpy as np


def test_early_waiver_does_not_accept_50_bp_assignment_in_baseline():
    from core.rust_bridge import _legacy as bridge
    from fraggler.ladders import LADDERS

    sizes = np.asarray(LADDERS["LIZ500_250"]["sizes"], dtype=float)
    true_scans = np.rint(1400.0 + (sizes - 35.0) * 5.5).astype(int)
    times = np.arange(4600)
    trace = np.zeros(times.size)
    for index, scan in enumerate(true_scans):
        height = 1100.0 if index == 0 else 4500.0
        trace += height * np.exp(-0.5 * ((times - scan) / 2.0) ** 2)

    selected_scans = true_scans.copy()
    selected_scans[1] += 50
    # The selected 50 bp position is baseline, yet the first gap stays within
    # the more permissive 160-scan bound and the 75–500 bp core is pristine.
    assert trace[selected_scans[1]] < 1.0
    assert 95 < selected_scans[1] - selected_scans[0] <= 160
    fsa = SimpleNamespace(ladder="LIZ500_250", size_standard=trace)

    accepted, _reason = bridge._validate_rust_anchor_selection(
        fsa, selected_scans.tolist(), sizes.tolist(),
    )

    assert not accepted
