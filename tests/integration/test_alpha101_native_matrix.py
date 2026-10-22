"""Strict long-history Alpha101 matrix against the independent paper AST."""

from __future__ import annotations

import math

import pytest

from tests.test_utils.alpha101_full_reference import formula_ids, history_h
from tests.test_utils.alpha101_native_harness import (
    assert_finite_witness,
    make_positive_fixture,
    run_native_batch,
)
from tests.test_utils.alpha101_trace_validation import validate_factor_trace

BATCH_SIZE = 20
HISTORY_LENGTHS = (320, 640, 1280)


def _batches():
    ids = list(formula_ids())
    return [ids[index : index + BATCH_SIZE] for index in range(0, len(ids), BATCH_SIZE)]


def _long_history_fixture(periods):
    """Keep the union grid intact while exercising real gaps and source NaNs."""
    frames = {asset: frame.copy() for asset, frame in make_positive_fixture(periods).items()}
    grid = tuple(next(iter(frames.values())).index)
    # Asset-0 remains the full calendar source so every missing asset-1 bar is
    # represented by a real NaN slot in the rectangular reference matrix.
    missing_bar = grid[periods // 2]
    frames["asset-1"] = frames["asset-1"].drop(index=missing_bar)
    frames["asset-3"].loc[grid[periods // 4], "high"] = math.nan
    frames["asset-4"].loc[grid[-4], "close"] = math.nan
    return frames


@pytest.mark.slow
@pytest.mark.parametrize("periods", HISTORY_LENGTHS, ids=lambda value: "T%d" % value)
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_alpha101_matrix_matches_causal_float64_ast(periods, runonce):
    frames = _long_history_fixture(periods)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    failures = []
    checked = 0

    for batch in _batches():
        strategy = run_native_batch(frames, batch, runonce=runonce)
        for alpha_id in batch:
            factor = strategy.factor_instances["alpha%d" % alpha_id]
            report = validate_factor_trace(
                factor, alpha_id, frames, assets, grid, strategy=strategy
            )
            failures.extend(report["failures"])
            assert_finite_witness(alpha_id, report["expected"], history_h(alpha_id))
            checked += 1

    assert checked == 101
    assert not failures, "Alpha101 trace deviations:\n" + "\n".join(failures[:30])
