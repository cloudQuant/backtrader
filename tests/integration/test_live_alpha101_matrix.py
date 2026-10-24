"""Full production Alpha101 batch/live parity through ordinary Cerebro."""

from __future__ import annotations

import os

import pytest

from tests.test_utils.alpha101_full_reference import formula_ids, history_h
from tests.test_utils.alpha101_live_cohort_harness import (
    DEFAULT_EVALUATION_LENGTHS,
    EVALUATION_LENGTHS_ENV,
    alpha_partitions,
    assert_evaluation_witness,
    evaluation_lengths,
    evaluation_start_for,
    make_live_alpha_batch,
    materialize_live_presence_for_graph,
    positive_target_frames,
    snapshot_panel_trace_view,
    validate_live_run,
)
from tests.test_utils.alpha101_native_harness import (
    run_native_batch,
    selection_is_focused,
)
from tests.test_utils.alpha101_trace_validation import (
    compare_factor_graphs,
    validate_factor_trace,
)


def _assert_trace(
    factor,
    alpha_id,
    frames,
    assets,
    grid,
    *,
    strategy,
    evaluation_bars,
    warmup_start,
    lane,
):
    report = validate_factor_trace(
        factor,
        alpha_id,
        frames,
        assets,
        grid,
        strategy=strategy,
    )
    assert not report["failures"], "Alpha%d %s trace failed: %r" % (
        alpha_id,
        lane,
        report["failures"][:12],
    )
    witness = assert_evaluation_witness(
        alpha_id,
        report["expected"],
        evaluation_bars=evaluation_bars,
        warmup_start=warmup_start,
    )
    return report, witness


def _assert_graph_pair(left, right, alpha_id, label):
    report = compare_factor_graphs(left, right, alpha_id)
    assert report["equal"], "Alpha%d %s graph differs: %r" % (
        alpha_id,
        label,
        report["failures"][:12],
    )
    assert report["node_count_left"] == report["node_count_right"]
    assert report["matched_node_count"] > 0
    assert report["node_value_cells"] > 0
    assert report["node_reason_cells"] > 0


@pytest.mark.integration
@pytest.mark.slow
def test_full_alpha101_batch_and_live_cohort_match_independent_nodes_and_reasons():
    """Verify every selected production Alpha class on the real live Feed path.

    The unfiltered invocation covers all 101 formulas and T320/T640/T1280.
    Existing Alpha batch/ID selectors may partition a reviewed pilot without
    changing the full acceptance default.  Cohort execution remains ordinary
    runnext by API contract; the four batch lanes exercise runnext/runonce in
    both implementation modes, then each live mode is compared with both.
    """

    partitions = alpha_partitions()
    lengths = evaluation_lengths()
    selected_ids = tuple(alpha_id for _batch, ids in partitions for alpha_id in ids)
    if not selection_is_focused():
        assert tuple(sorted(selected_ids)) == tuple(formula_ids())
    if EVALUATION_LENGTHS_ENV not in os.environ:
        assert lengths == DEFAULT_EVALUATION_LENGTHS

    all_checked = set()
    for evaluation_bars in lengths:
        for batch_name, alpha_ids in partitions:
            total_bars, evaluation_start = evaluation_start_for(alpha_ids, evaluation_bars)
            frames = positive_target_frames(total_bars)
            assets = tuple(frames)
            grid = tuple(next(iter(frames.values())).index)
            assert len(grid) == total_bars
            for alpha_id in alpha_ids:
                assert total_bars - evaluation_bars >= history_h(alpha_id) + 30

            baseline = {}
            baseline_trace = {}
            for mode in ("native", "build"):
                for engine_name, runonce in (("runnext", False), ("runonce", True)):
                    strategy = run_native_batch(
                        frames,
                        alpha_ids,
                        runonce=runonce,
                        factor_mode=mode,
                        groups=dict.fromkeys(assets, "default"),
                    )
                    baseline[(mode, engine_name)] = strategy
                    for alpha_id in alpha_ids:
                        name = "alpha%d" % alpha_id
                        report, _witness = _assert_trace(
                            strategy.factor_instances[name],
                            alpha_id,
                            frames,
                            assets,
                            grid,
                            strategy=strategy,
                            evaluation_bars=evaluation_bars,
                            warmup_start=evaluation_start,
                            lane="batch-%s-%s/%s" % (batch_name, mode, engine_name),
                        )
                        baseline_trace[(mode, engine_name, alpha_id)] = report

            live = {}
            live_traces = {}
            for mode in ("native", "build"):
                strategy, cohort, clock, live_grid = make_live_alpha_batch(
                    frames,
                    alpha_ids,
                    factor_mode=mode,
                )
                assert tuple(live_grid) == tuple(point.to_pydatetime() for point in grid)
                trace_views = validate_live_run(
                    strategy,
                    cohort,
                    clock,
                    frames,
                    alpha_ids,
                    live_grid,
                )
                materialize_live_presence_for_graph(strategy)
                live[(mode, "runnext")] = (strategy, cohort, clock)
                panel_view = snapshot_panel_trace_view(strategy)
                for alpha_id in alpha_ids:
                    name = "alpha%d" % alpha_id
                    report, _witness = _assert_trace(
                        trace_views[name],
                        alpha_id,
                        frames,
                        assets,
                        grid,
                        strategy=panel_view,
                        evaluation_bars=evaluation_bars,
                        warmup_start=evaluation_start,
                        lane="live-%s-%s" % (batch_name, mode),
                    )
                    live_traces[(mode, alpha_id)] = (trace_views[name], report)

            for alpha_id in alpha_ids:
                name = "alpha%d" % alpha_id
                # The native/build live snapshots agree node-for-node,
                # including NaN masks and every logical reason line.
                _assert_graph_pair(
                    live_traces[("native", alpha_id)][0],
                    live_traces[("build", alpha_id)][0],
                    alpha_id,
                    "live-native/build",
                )
                for mode in ("native", "build"):
                    live_factor = live_traces[(mode, alpha_id)][0]
                    for engine_name in ("runnext", "runonce"):
                        batch_factor = baseline[(mode, engine_name)].factor_instances[name]
                        _assert_graph_pair(
                            live_factor,
                            batch_factor,
                            alpha_id,
                            "live-%s/batch-%s" % (mode, engine_name),
                        )
                # Batch runnext/runonce comparison is included explicitly in
                # this new acceptance closure as well as each lane's oracle.
                for mode in ("native", "build"):
                    _assert_graph_pair(
                        baseline[(mode, "runnext")].factor_instances[name],
                        baseline[(mode, "runonce")].factor_instances[name],
                        alpha_id,
                        "batch-%s-runnext/runonce" % mode,
                    )
                all_checked.add(alpha_id)

    if not selection_is_focused() and lengths == DEFAULT_EVALUATION_LENGTHS:
        assert all_checked == set(formula_ids())
    else:
        assert all_checked == set(selected_ids)
