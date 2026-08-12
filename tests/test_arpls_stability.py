from __future__ import annotations

import warnings

import numpy as np
from scipy import sparse
from scipy.sparse import linalg

from fraggler.fraggler import baseline_arPLS


def _legacy_reference(y, ratio=0.99, lam=100, niter=1000):
    values = np.asarray(y, dtype=float)
    length = len(values)
    diag = np.ones(length - 2)
    difference = sparse.spdiags([diag, -2 * diag, diag], [0, -1, -2], length, length - 2)
    penalty = lam * difference.dot(difference.T)
    weights = np.ones(length)
    weight_matrix = sparse.spdiags(weights, 0, length, length)
    criterion = 1.0
    count = 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        while criterion > ratio:
            baseline = linalg.spsolve(weight_matrix + penalty, weight_matrix * values)
            residual = values - baseline
            negative = residual[residual < 0]
            mean = np.mean(negative)
            stddev = np.std(negative)
            new_weights = 1 / (1 + np.exp(2 * (residual - (2 * stddev - mean)) / stddev))
            criterion = np.linalg.norm(new_weights - weights) / np.linalg.norm(weights)
            weights = new_weights
            weight_matrix.setdiag(weights)
            count += 1
            if count > niter:
                break
    return baseline


def _representative_trace(length=2200):
    rng = np.random.default_rng(20260809)
    x = np.arange(length, dtype=float)
    values = -140.0 + 0.025 * x + 3.0 * np.sin(x / 83.0) + rng.normal(0.0, 1.5, length)
    for center, height, width in ((260, 500, 5), (610, 900, 7), (1120, 650, 6), (1810, 1000, 8)):
        values += height * np.exp(-0.5 * ((x - center) / width) ** 2)
    return values


def test_arpls_csc_solver_preserves_legacy_numerical_result():
    values = _representative_trace()
    expected = _legacy_reference(values)
    actual = baseline_arPLS(values)
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-8)


def test_arpls_does_not_emit_sparse_efficiency_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        baseline_arPLS(_representative_trace())
    assert not [item for item in caught if "CSC or CSR" in str(item.message)]


def test_arpls_flat_and_nonfinite_inputs_stay_finite():
    flat = np.full(120, -250.0)
    flat_result = baseline_arPLS(flat)
    assert np.all(np.isfinite(flat_result))
    np.testing.assert_allclose(flat_result, flat, atol=1e-8)

    damaged = _representative_trace(300)
    damaged[[0, 40, 180, -1]] = [np.nan, np.inf, -np.inf, np.nan]
    damaged_result = baseline_arPLS(damaged)
    assert damaged_result.shape == damaged.shape
    assert np.all(np.isfinite(damaged_result))


def test_arpls_short_input_contract_is_stable():
    assert baseline_arPLS([]).size == 0
    np.testing.assert_array_equal(baseline_arPLS([3.0]), np.array([3.0]))
    np.testing.assert_array_equal(baseline_arPLS([3.0, 4.0]), np.array([3.0, 4.0]))
