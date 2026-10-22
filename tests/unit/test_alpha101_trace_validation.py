"""Adversarial contracts for the strict Alpha101 trace comparator."""

import math

from tests.test_utils.alpha101_full_reference import _rank
from tests.test_utils.alpha101_trace_validation import (
    _compare_matrices,
    _exact_discrete_ast,
)


def test_matrix_comparison_rejects_asset_permutations():
    expected = [[0.0, 0.5, 1.0]]
    swapped = [[1.0, 0.5, 0.0]]

    ok, message = _compare_matrices(swapped, expected, exact=False, label="asset swap")

    assert not ok
    assert "asset 0" in message


def test_collector_panel_comparison_rejects_swapped_assets():
    expected = [[0.25, 0.75]]
    swapped_panel = [[0.75, 0.25]]

    ok, message = _compare_matrices(swapped_panel, expected, exact=True, label="collector panel")

    assert not ok
    assert "collector panel" in message


def test_collector_panel_comparison_rejects_shifted_nan_mask():
    expected = [[math.nan, 0.5]]
    shifted_mask = [[0.5, math.nan]]

    ok, message = _compare_matrices(shifted_mask, expected, exact=True, label="collector panel")

    assert not ok
    assert "expected NaN" in message


def test_collector_mask_checks_current_physical_inputs_when_h_is_zero():
    import pandas as pd

    from tests.test_utils.alpha101_trace_validation import _collector_expected_matrix

    class DeclaredAlpha101Inputs:
        formula_fields = ("open", "high", "low", "close")
        _factor_runtime = {"field_bindings": {}}

    point = pd.Timestamp("2024-01-02", tz="UTC")
    frames = {
        "asset-0": pd.DataFrame(
            {"open": [10.0], "high": [math.nan], "low": [9.0], "close": [9.5]},
            index=[point],
        )
    }

    masked = _collector_expected_matrix(
        DeclaredAlpha101Inputs(), 101, frames, ("asset-0",), (point,), [[0.5]]
    )

    assert math.isnan(masked[0][0])


def test_exact_rank_check_rejects_one_ulp_order_inversion():
    inputs = [1.0, math.nextafter(1.0, math.inf)]
    expected_rank = _rank(inputs)
    deliberately_swapped = list(reversed(expected_rank))

    ok, message = _compare_matrices(
        [deliberately_swapped], [expected_rank], exact=True, label="near-tie rank"
    )

    assert expected_rank == [0.5, 1.0]
    assert not ok
    assert "exact" in message


def test_fixed_continuous_tolerance_rejects_correlation_kernel_bias():
    ok, message = _compare_matrices([[0.251]], [[0.25]], exact=False, label="correlation kernel")

    assert not ok
    assert "tolerance" in message


def test_exact_branch_check_rejects_wrong_selected_value():
    branch_node = (
        "ternary",
        ("binary", "<", ("name", "x"), ("number", 0.0)),
        ("number", 2.0),
        ("number", 3.0),
    )
    assert _exact_discrete_ast(branch_node)

    ok, message = _compare_matrices([[3.0]], [[2.0]], exact=True, label="branch")

    assert not ok
    assert "exact" in message


def test_default_reference_snap_policy_remains_enabled():
    from tests.test_utils.alpha101_full_reference import _Context, _pair_rolling

    context = _Context({"close": [[1.0]], "volume": [[2.0]]})

    assert context.snap_correlation_bounds is True
    strict_trace_context = _Context(
        {"close": [[1.0]], "volume": [[2.0]]}, snap_correlation_bounds=False
    )
    assert strict_trace_context.snap_correlation_bounds is False


def test_unsnapped_correlation_uses_exact_binary64_samples_at_the_bound():
    from tests.test_utils.alpha101_full_reference import _pair_rolling

    # Both columns have the same two-level pattern, so their exact Pearson
    # correlation is +1. NumPy's centered dot product rounds to 1.0000000000000002
    # for this input and the old unsnapped reference discarded the result as NaN.
    left = [[0.0], [1.0 / 12.0], [1.0 / 12.0]]
    right = [[0.0], [0.75], [0.75]]

    result = _pair_rolling(left, right, 3, covariance=False, snap_correlation_bounds=False)

    assert math.isnan(result[0][0])
    assert math.isnan(result[1][0])
    assert result[2][0] == 1.0


def test_unsnapped_correlation_keeps_distinct_subnormal_window_finite():
    from tests.test_utils.alpha101_full_reference import _pair_rolling

    tiny = math.ulp(0.0)
    left = [[0.0], [tiny], [0.0]]
    right = [[0.0], [1.0], [0.0]]

    result = _pair_rolling(left, right, 3, covariance=False, snap_correlation_bounds=False)

    # min != max, and the exact binary64 sample vectors have Pearson +1 even
    # though a float64 squared deviation underflows to zero.
    assert result[2][0] == 1.0
