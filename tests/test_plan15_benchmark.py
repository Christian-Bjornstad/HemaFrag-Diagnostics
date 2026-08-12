from scripts.benchmark_plan15_runtime import _percentile, _synthetic_trace


def test_plan15_percentile_uses_linear_interpolation():
    assert _percentile([], 0.95) == 0.0
    assert _percentile([1.0, 2.0, 3.0], 0.5) == 2.0
    assert _percentile([1.0, 2.0, 3.0], 0.95) == 2.9


def test_plan15_synthetic_trace_is_deterministic_and_peak_bearing():
    first = _synthetic_trace()
    second = _synthetic_trace()
    assert first.shape == (6000,)
    assert (first == second).all()
    assert first.max() > 900.0
    assert first.min() < -100.0
