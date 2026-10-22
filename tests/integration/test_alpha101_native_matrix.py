"""Full Alpha101 matrix against an independent float64 reference.

The production operators run float64 (``alpha101-v2``).  This module compares
every formula on the same synthetic fixture with the independent float64
reference in :mod:`tests.test_utils.alpha101_full_reference` and enforces:

* identical NaN masks (missing bars, incomplete lookback windows),
* identical value multisets per row for 91 formulas (a cross-sectional rank
  permutation from a ULP-level tie split is tolerated), and
* for the ten formulas whose outputs are themselves cross-sectional ranks of
  short-window correlations, an explicit deviation catalogue: masks still
  match, the induced order must agree with the reference, and the absolute
  difference and the number of order inversions must stay inside the frozen
  budget below.

The catalogue records the documented consequence of replacing exact rational
correlation/covariance kernels with stable float64: values within a few ULP of
each other can swap ranks.  It is not a tolerance on the factor arithmetic
itself, and no formula is removed from the matrix.
"""

from __future__ import annotations

import math

import pytest

from tests.test_utils.alpha101_native_harness import (
    actual_matrix,
    alpha_name,
    make_positive_fixture,
    oracle_expected,
    run_native_batch,
)

# Formula ID -> (max |production - reference|, max order inversions per run).
# Frozen from the 2026-10-22 float64 migration census; a formula exceeding its
# budget is a regression, and lowering a budget requires a new census record.
RANK_TIE_BUDGET = {
    13: (0.17, 1, 20),
    15: (0.34, 1, 150),
    16: (0.17, 1, 12),
    50: (0.09, 1, 6),
    68: (1.01, 1, 2),
    94: (0.15, 1, 6),
    97: (0.17, 1, 5),
    98: (0.67, 2, 22),
}

BATCH_SIZE = 20
TOLERANCE = 1e-12


def _batches():
    ids = list(range(1, 102))
    return [ids[index : index + BATCH_SIZE] for index in range(0, len(ids), BATCH_SIZE)]


def _compare_row(actual, expected):
    actual_nan = [index for index, value in enumerate(actual) if not math.isfinite(float(value))]
    expected_nan = [index for index, value in enumerate(expected) if not math.isfinite(float(value))]
    return actual_nan, expected_nan


def _sorted_values(row):
    return sorted(float(value) for value in row if math.isfinite(float(value)))


def _close(left, right):
    return abs(left - right) <= TOLERANCE + 1e-10 * abs(right)


def _order_inversions(actual, expected):
    finite = [index for index, value in enumerate(expected) if math.isfinite(float(value))]
    inversions = 0
    for left in finite:
        for right in finite:
            if float(expected[left]) < float(expected[right]) and float(actual[left]) > (
                float(actual[right]) + TOLERANCE
            ):
                inversions += 1
    return inversions


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_alpha101_matrix_matches_float64_reference(runonce):
    frames = make_positive_fixture(320)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    failures = []
    checked = 0
    tie_rows = {}
    for batch in _batches():
        strategy = run_native_batch(frames, batch, runonce=runonce)
        for alpha_id in batch:
            expected_matrix, declared_h = oracle_expected(alpha_id, frames)
            actual = actual_matrix(strategy, alpha_id, assets, grid)
            label = "Alpha%d runonce=%s" % (alpha_id, runonce)
            budget = RANK_TIE_BUDGET.get(alpha_id)
            for row in range(declared_h, len(grid)):
                actual_row, expected_row = actual[row], expected_matrix[row]
                actual_nan, expected_nan = _compare_row(actual_row, expected_row)
                if actual_nan != expected_nan:
                    failures.append(
                        "%s row %d: NaN mask %r != %r" % (label, row, actual_nan, expected_nan)
                    )
                    continue
                checked += 1
                if budget is None:
                    got = _sorted_values(actual_row)
                    wanted = _sorted_values(expected_row)
                    if len(got) != len(wanted) or any(
                        not _close(left, right) for left, right in zip(got, wanted)
                    ):
                        failures.append(
                            "%s row %d: values differ beyond tolerance (%r != %r)"
                            % (label, row, actual_row, expected_row)
                        )
                    continue
                max_delta, max_inversions, max_rows = budget
                delta = max(
                    (
                        abs(float(a) - float(e))
                        for a, e in zip(actual_row, expected_row)
                        if math.isfinite(float(e))
                    ),
                    default=0.0,
                )
                if delta > max_delta + TOLERANCE:
                    failures.append(
                        "%s row %d: |delta| %.6g exceeds the frozen tie budget %.6g"
                        % (label, row, delta, max_delta)
                    )
                inversions = _order_inversions(actual_row, expected_row)
                if inversions > max_inversions:
                    failures.append(
                        "%s row %d: %d order inversions exceed the frozen budget %d"
                        % (label, row, inversions, max_inversions)
                    )
                if delta > TOLERANCE:
                    tie_rows[alpha_id] = tie_rows.get(alpha_id, 0) + 1
                    if tie_rows[alpha_id] > max_rows:
                        failures.append(
                            "%s: %d tie-split rows exceed the frozen budget %d"
                            % (label, tie_rows[alpha_id], max_rows)
                        )
    assert checked > 0
    assert not failures, "matrix deviations:\n" + "\n".join(failures[:20])


def test_tie_budget_catalogue_matches_the_implementation():
    from backtrader.research.alpha101 import get_alpha

    for alpha_id in RANK_TIE_BUDGET:
        indicator = get_alpha(alpha_id)
        assert "correlation" in indicator.formula or "covariance" in indicator.formula, (
            "Alpha%d is budgeted as a rank-tie formula but does not call "
            "correlation/covariance" % alpha_id
        )
