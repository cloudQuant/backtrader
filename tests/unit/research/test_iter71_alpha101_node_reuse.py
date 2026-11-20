"""Focused native/build regressions for R71-116 duplicate-node reuse."""

from __future__ import annotations

import math
from collections import Counter

import pytest

from backtrader.research import operators
from tests.test_utils.alpha101_full_reference import formula_metadata
from tests.test_utils.alpha101_native_harness import make_positive_fixture, run_native_batch
from tests.test_utils.alpha101_trace_validation import compare_factor_graphs, validate_factor_trace

_ALPHA_IDS = (46, 49, 51, 62)


def _multi_feed_missing_fixture():
    frames = {asset: frame.copy() for asset, frame in make_positive_fixture(320).items()}
    grid = tuple(next(iter(frames.values())).index)
    # Keep the union grid intact so real-bar absence is distinct from source NaN.
    frames["asset-1"] = frames["asset-1"].drop(index=grid[160])
    frames["asset-3"].loc[grid[80], "open"] = math.nan
    frames["asset-4"].loc[grid[-4], "close"] = math.nan
    return frames, grid


def _operator_nodes(factor, operator_type):
    return [node for node in factor._nodes.values() if isinstance(node, operator_type)]


def _assert_reused_nodes(factor, alpha_id, target_count):
    if alpha_id in (46, 49, 51):
        delays = _operator_nodes(factor, operators.Delay)
        periods = Counter(int(node.p.period) for node in delays)
        assert periods == {1: target_count, 10: target_count, 20: target_count}
        reason_codes = {
            int(value)
            for node in delays
            for value in node.lines.reason.array
            if math.isfinite(float(value))
        }
        assert int(operators.OperatorReason.NOT_READY) in reason_codes
        assert int(operators.OperatorReason.NONFINITE_INPUT) in reason_codes
        return

    ranks = _operator_nodes(factor, operators.CrossSectionalRank)
    assert len(ranks) == 5
    assert formula_metadata(62)["operator_call_counts"]["rank"] == 6
    reason_codes = {
        int(value)
        for node in ranks
        for output in node.outputs.values()
        for value in output.reason.array
        if math.isfinite(float(value))
    }
    assert int(operators.OperatorReason.NONFINITE_INPUT) in reason_codes
    assert int(operators.OperatorReason.FORMULA_INELIGIBLE) in reason_codes
    additions = [
        node
        for node in factor._nodes.values()
        if isinstance(node, operators.Add)
        and node._operand_args[0] is node._operand_args[1]
    ]
    assert len(additions) == target_count
    assert all(node._operand_args[0] is node._operand_args[1] for node in additions)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_alpha101_duplicate_delay_and_rank_nodes_are_shared_without_trace_changes(runonce):
    frames, grid = _multi_feed_missing_fixture()
    assets = tuple(frames)
    strategies = {}

    for mode in ("native", "build"):
        strategy = run_native_batch(
            frames,
            _ALPHA_IDS,
            runonce=runonce,
            factor_mode=mode,
        )
        strategies[mode] = strategy

        for alpha_id in _ALPHA_IDS:
            factor = strategy.factor_instances["alpha%d" % alpha_id]
            strict_context = factor._factor_strict_context
            assert strict_context.factor == "alpha%d" % alpha_id
            assert strict_context.failed is False
            diagnostics = factor.lifecycle_diagnostics
            assert diagnostics["diagnostic_kind"] == "captured_offline_trace"
            assert diagnostics["call_times"] == tuple(point.to_pydatetime() for point in grid)
            assert diagnostics["coverage_matches"] is True

            report = validate_factor_trace(
                factor,
                alpha_id,
                frames,
                assets,
                grid,
                strategy=strategy,
            )
            assert report["failures"] == []
            _assert_reused_nodes(factor, alpha_id, len(assets))

    for alpha_id in _ALPHA_IDS:
        left = strategies["native"].factor_instances["alpha%d" % alpha_id]
        right = strategies["build"].factor_instances["alpha%d" % alpha_id]
        pair = compare_factor_graphs(left, right, alpha_id)
        assert pair["equal"], pair["failures"]
        assert pair["node_reason_cells"] > 0
