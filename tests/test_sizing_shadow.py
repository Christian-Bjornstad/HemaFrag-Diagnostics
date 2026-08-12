from __future__ import annotations

import numpy as np
import pytest

from core.precision.sizing_shadow import (
    SIZING_SHADOW_SCHEMA,
    _local_southern_triplet,
    evaluate_anchor_leave_one_out,
)


def test_local_southern_recovers_exact_reciprocal_curve():
    times = np.asarray([100.0, 200.0, 300.0])
    sizes = -20000.0 / (times - 500.0) + 10.0
    expected = -20000.0 / (250.0 - 500.0) + 10.0

    predicted = _local_southern_triplet(times, sizes, 250.0)

    assert predicted == pytest.approx(expected, abs=1e-5)


def test_sizing_shadow_is_deterministic_and_never_promotion_eligible():
    sizes = np.asarray([35, 50, 75, 100, 139, 150, 160, 200, 250, 300])
    times = 900.0 + (sizes * 8.0) + (0.004 * sizes**2)

    first = evaluate_anchor_leave_one_out(times, sizes)
    second = evaluate_anchor_leave_one_out(times, sizes)

    assert first == second
    assert first["schema_version"] == SIZING_SHADOW_SCHEMA
    assert first["promotion_eligible"] is False
    assert first["anchor_count"] == len(sizes)
    assert first["methods"]["monotone_pchip"]["count"] == len(sizes) - 2
    assert first["methods"]["local_southern"]["count"] == len(sizes) - 4
    assert first["methods"]["global_quadratic"]["mae_bp"] < 0.5


@pytest.mark.parametrize(
    ("times", "sizes"),
    [
        ([1, 2, 3, 4], [10, 20, 30, 40]),
        ([1, 2, 2, 4, 5], [10, 20, 30, 40, 50]),
        ([1, 2, 3, 4, 5], [10, 20, 15, 40, 50]),
    ],
)
def test_sizing_shadow_rejects_insufficient_or_nonmonotonic_anchors(times, sizes):
    with pytest.raises(ValueError):
        evaluate_anchor_leave_one_out(times, sizes)
