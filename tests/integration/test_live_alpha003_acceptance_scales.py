"""Acceptance-scale Alpha003 parity cases beyond the shared six-asset fixture.

The production formula, Cerebro runners, strict live cohort builder, and
independent oracle are shared with ``test_live_alpha003_parity``.  This file
adds the required five-asset matrix without introducing another formula or
scheduler implementation.
"""

from __future__ import annotations

import math

import pytest

from backtrader.research.alpha101 import get_alpha
from tests.integration import test_live_alpha003_parity as parity
from tests.test_utils.alpha101_native_harness import (
    assert_lifecycle,
    assert_matrix_matches,
    run_native_batch,
)
from tests.test_utils.alpha101_trace_validation import compare_factor_graphs, validate_factor_trace

# Alpha003's rolling-correlation window is 10; the live plan explicitly asks
# for 30 warmup bars.  Keep that larger configured prewarm outside each scored
# 320/640/1280-bar evaluation suffix.
_LIVE_WARMUP_BARS = 30


def _assert_nontrivial_ranks(factor, assets, *, evaluation_start, total_bars, label):
    """Require both Alpha003 rank panels to vary on the scored suffix."""
    for node_key in ("rank_open", "rank_volume"):
        panel = factor._nodes[node_key]
        varied_assets = []
        for target in factor.target_datas:
            assert target._name in assets
            values = tuple(float(value) for value in panel.outputs[target].value.array)
            assert len(values) == total_bars, (label, node_key, target._name, len(values))
            finite_values = {value for value in values[evaluation_start:] if math.isfinite(value)}
            if len(finite_values) > 1:
                varied_assets.append(target._name)
        assert varied_assets, (label, node_key, "no nontrivial rank variation")


@pytest.mark.integration
def test_alpha003_five_asset_full_batch_and_live_matrix():
    """Score 320/640/1280 bars after an explicit 30-bar live warmup."""
    assert parity._WARMUP_BARS == _LIVE_WARMUP_BARS
    for evaluation_bars in parity._HISTORY_LENGTHS:
        total_bars = _LIVE_WARMUP_BARS + evaluation_bars
        all_frames = parity._minute_frames(total_bars)
        assets = tuple(all_frames)[:5]
        frames = {asset: all_frames[asset] for asset in assets}
        grid = tuple(next(iter(frames.values())).index)
        evaluation_grid = grid[_LIVE_WARMUP_BARS:]
        assert len(evaluation_grid) == evaluation_bars
        finite_witnesses = {}
        live_modes = {}

        for mode in ("native", "build"):
            batch_runs = {}
            for engine_name, runonce in (("runnext", False), ("runonce", True)):
                strategy = run_native_batch(
                    frames,
                    (3,),
                    runonce=runonce,
                    factor_mode=mode,
                    alpha_classes={3: get_alpha(3)},
                )
                assert_lifecycle(strategy, (3,), grid, alpha_classes={3: get_alpha(3)})
                factor = strategy.factor_instances["alpha3"]
                trace = validate_factor_trace(factor, 3, frames, assets, grid, strategy=strategy)
                label = "5 assets %s evaluation T%d + warmup %d %s" % (
                    mode,
                    evaluation_bars,
                    _LIVE_WARMUP_BARS,
                    engine_name,
                )
                assert trace["failures"] == [], "%s: %r" % (label, trace["failures"][:20])
                assert trace["matched_nodes"] == 4, (label, trace["matched_nodes"])
                parity._assert_expected_reason_lines(factor, assets, trace["expected"])
                _assert_nontrivial_ranks(
                    factor,
                    assets,
                    evaluation_start=_LIVE_WARMUP_BARS,
                    total_bars=total_bars,
                    label=label,
                )

                matrix = [
                    [
                        float(
                            strategy.get_panel().factors.at[
                                (point.to_pydatetime(), asset), "alpha3"
                            ]
                        )
                        for asset in assets
                    ]
                    for point in grid
                ]
                assert_matrix_matches(matrix, trace["expected"], label=label)
                assert len(matrix[_LIVE_WARMUP_BARS:]) == evaluation_bars
                finite_witnesses[(mode, engine_name, evaluation_bars)] = sum(
                    math.isfinite(value) for row in matrix[_LIVE_WARMUP_BARS:] for value in row
                )
                assert finite_witnesses[(mode, engine_name, evaluation_bars)] >= 100, label
                batch_runs[engine_name] = strategy

            batch_runnext_factor = batch_runs["runnext"].factor_instances["alpha3"]
            batch_runonce_factor = batch_runs["runonce"].factor_instances["alpha3"]
            batch_report = compare_factor_graphs(batch_runnext_factor, batch_runonce_factor, 3)
            assert batch_report["equal"], "5 assets %s evaluation T%d batch runnext/runonce: %r" % (
                mode,
                evaluation_bars,
                batch_report["failures"][:20],
            )

            live_strategy, _cohort, _feeds = parity._run_live(frames, mode=mode)
            live_expected, live_factor = parity._validate_live(
                live_strategy,
                frames,
                label="5 assets live %s evaluation T%d + warmup %d"
                % (mode, evaluation_bars, _LIVE_WARMUP_BARS),
            )
            live_values = parity._snapshot_matrix(live_strategy, assets)
            assert len(live_values) == total_bars
            assert len(live_values[_LIVE_WARMUP_BARS:]) == evaluation_bars
            finite_witnesses[(mode, "live", evaluation_bars)] = sum(
                math.isfinite(float(value))
                for row in live_values[_LIVE_WARMUP_BARS:]
                for value in row
            )
            assert finite_witnesses[(mode, "live", evaluation_bars)] >= 100
            assert len(live_expected) == total_bars
            _assert_nontrivial_ranks(
                live_factor,
                assets,
                evaluation_start=_LIVE_WARMUP_BARS,
                total_bars=total_bars,
                label="5 assets live %s evaluation T%d" % (mode, evaluation_bars),
            )
            assert all(
                snapshot.readiness.value == "WARMUP"
                for snapshot in live_strategy.snapshots[: _LIVE_WARMUP_BARS - 1]
            )
            # The thirtieth delivered bar (index 29) completes the configured
            # 30-bar window and is already ready.  Keep it in the explicitly
            # excluded pre-evaluation prefix; score exactly the following T bars.
            assert all(
                snapshot.readiness.value == "LIVE_READY"
                for snapshot in live_strategy.snapshots[_LIVE_WARMUP_BARS - 1 :]
            )
            live_modes[mode] = (live_strategy, live_factor)

            live_trace_factor = parity._factor_trace_view(
                live_factor,
                live_strategy,
                grid,
                label="5 assets graph comparison live %s evaluation T%d"
                % (
                    mode,
                    evaluation_bars,
                ),
            )
            for engine_name in ("runnext", "runonce"):
                parity._compare_alpha003_registered_nodes(
                    batch_runs[engine_name].factor_instances["alpha3"],
                    live_trace_factor,
                    assets,
                    label="5 assets %s evaluation T%d %s-vs-live"
                    % (mode, evaluation_bars, engine_name),
                )

        native_strategy, native_factor = live_modes["native"]
        build_strategy, build_factor = live_modes["build"]
        native_trace_factor = parity._factor_trace_view(
            native_factor,
            native_strategy,
            grid,
            label="5 assets native live graph evaluation T%d" % evaluation_bars,
        )
        build_trace_factor = parity._factor_trace_view(
            build_factor,
            build_strategy,
            grid,
            label="5 assets build live graph evaluation T%d" % evaluation_bars,
        )
        native_build_report = compare_factor_graphs(native_trace_factor, build_trace_factor, 3)
        assert native_build_report["equal"], "5 assets evaluation T%d live native/build: %r" % (
            evaluation_bars,
            native_build_report["failures"][:20],
        )
        assert len(finite_witnesses) == 6
