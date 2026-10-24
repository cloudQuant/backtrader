"""Alpha003 live formula edge cases on the ordinary Cerebro feed path.

The cohort, BtApiFeed, Cerebro scheduler, LiveFactorSet, and production
Alpha003 graph are real.  Only source bars and the replay clock are synthetic.
Expected rank/correlation/final matrices come from the independent paper
formula reference.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backtrader.research import operators
from backtrader.research.live import LiveFactorSet
from tests.integration import test_live_alpha003_parity as parity
from tests.test_utils.alpha101_full_reference import (
    _Context,
    _parse,
    reference,
)
from tests.test_utils.alpha101_native_harness import oracle_frames, presence_matrix
from tests.test_utils.alpha101_trace_validation import _postorder


_PERIODS = 30
_GROUPS = {
    "tie-0": "ties",
    "tie-1": "ties",
    "tie-2": "ties",
    "tie-3": "ties",
    "open-flat-0": "open-flat-rank",
    "open-flat-1": "open-flat-rank",
    "volume-flat-0": "volume-flat-rank",
    "volume-flat-1": "volume-flat-rank",
    "single": "singleton",
}


def _edge_frames(periods=_PERIODS):
    """Create tied, degenerate-rank, and singleton pools with valid OHLCV."""
    index = pd.date_range("2025-01-02 09:31:00", periods=periods, freq="min", tz="UTC")
    open_ties = (10.0, 20.0, 20.0, 40.0)
    volume_ties = (1.0, 1.0, 5.0, 9.0)
    frames = {}

    def build(asset, opens, volumes):
        closes = [value + 0.125 for value in opens]
        frames[asset] = pd.DataFrame(
            {
                "open": opens,
                "high": [value + 0.5 for value in closes],
                "low": [value - 0.5 for value in opens],
                "close": closes,
                "volume": volumes,
                "openinterest": [0.0] * periods,
            },
            index=index,
        )

    for asset_index in range(4):
        opens = [100.0 + open_ties[(asset_index + row) % 4] + row * 0.1 for row in range(periods)]
        volumes = [
            1000.0 + volume_ties[(asset_index + 3 * row) % 4] + row * 0.25 for row in range(periods)
        ]
        build("tie-%d" % asset_index, opens, volumes)

    # Both raw prices move while their cross-sectional order stays fixed.
    build(
        "open-flat-0",
        [50.0 + row * 0.4 for row in range(periods)],
        [200.0 + (10.0 if row % 2 else 0.0) + row * 0.1 for row in range(periods)],
    )
    build(
        "open-flat-1",
        [100.0 + row * 0.2 for row in range(periods)],
        [200.0 + (0.0 if row % 2 else 10.0) + row * 0.1 for row in range(periods)],
    )

    build(
        "volume-flat-0",
        [300.0 + (10.0 if row % 2 else 0.0) + row * 0.1 for row in range(periods)],
        [500.0 + row * 0.2 for row in range(periods)],
    )
    build(
        "volume-flat-1",
        [300.0 + (0.0 if row % 2 else 10.0) + row * 0.1 for row in range(periods)],
        [700.0 + row * 0.3 for row in range(periods)],
    )

    # A changing price and volume cannot make a one-member cross-section rank
    # into a time-varying series: the formula oracle's normalized average rank
    # is exactly 1.0 every bar for a singleton.
    build(
        "single",
        [900.0 + row * 1.7 for row in range(periods)],
        [3000.0 + row * 13.0 for row in range(periods)],
    )
    return frames


class _GroupedLiveCapture(parity._LiveAlpha003Capture):
    """Use the existing capture callbacks with more than one live factor group."""

    def __init__(self):
        feeds = {data._name: data for data in self.datas}
        self.live_factor_set = LiveFactorSet.bind(self.p.plan, feeds, cohort=self.p.cohort)
        self.target_order = tuple(self.p.target_order)
        self.snapshots = []


def _run_grouped_live(frames, groups, *, mode, monkeypatch, **run_kwargs):
    original_plan_builder = parity._live_alpha003_plan

    def grouped_plan_builder(targets, **kwargs):
        base = original_plan_builder(targets, **kwargs)
        return parity.LiveFactorPlan(
            plan_id=base.plan_id,
            targets=base.targets,
            groups=groups,
            factors=base.factors,
            calendar_id=base.calendar_id,
            frequency=base.frequency,
            warmup_min_bars=base.warmup_min_bars,
            max_pending_slots=base.max_pending_slots,
            max_window_bars=base.max_window_bars,
            wait_timeout_ns=base.wait_timeout_ns,
            max_live_bar_age_seconds=base.max_live_bar_age_seconds,
            max_future_skew_seconds=base.max_future_skew_seconds,
            allow_history_prewarm=base.allow_history_prewarm,
        )

    with monkeypatch.context() as patch:
        patch.setattr(parity, "_live_alpha003_plan", grouped_plan_builder)
        patch.setattr(parity, "_LiveAlpha003Capture", _GroupedLiveCapture)
        return parity._run_live(frames, mode=mode, **run_kwargs)[0]


def _close_enough(actual, expected, *, label):
    actual = float(actual)
    expected = float(expected)
    if math.isnan(expected):
        assert math.isnan(actual), (label, actual, expected)
    else:
        assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12), (
            label,
            actual,
            expected,
        )


def _assert_group_oracle(strategy, frames, groups, *, label):
    """Compare real rank/correlation/final nodes to the paper AST oracle."""
    grid = tuple(next(iter(frames.values())).index)
    all_assets = tuple(frames)
    snapshots = strategy.snapshots
    assert len(snapshots) == len(grid)
    assert all(snapshot.batch_complete for snapshot in snapshots)
    assert all(len(data) == len(grid) for data in strategy.datas)

    group_targets = {}
    for asset in all_assets:
        group_targets.setdefault(groups[asset], []).append(asset)

    formula_root = _parse(3)
    ast_nodes = tuple(_postorder(formula_root))
    rank_expressions = {
        expression[2][0][1]: expression
        for expression in ast_nodes
        if expression[0] == "call" and expression[1] == "rank" and expression[2][0][0] == "name"
    }
    assert set(rank_expressions) == {"open", "volume"}
    correlation_expression = next(
        expression
        for expression in ast_nodes
        if expression[0] == "call" and expression[1] == "correlation"
    )

    for group, assets_list in group_targets.items():
        assets = tuple(assets_list)
        source_frames = {asset: frames[asset] for asset in assets}
        matrices = oracle_frames(source_frames, grid=grid)
        members = presence_matrix(source_frames, grid)
        context = _Context(
            matrices,
            formula_universe=members,
            snap_correlation_bounds=False,
        )
        expected = reference(3, matrices, formula_universe=members)
        context_expected = context.evaluate(formula_root)
        for row_index, (left, right) in enumerate(zip(expected, context_expected)):
            for column, (got, wanted) in enumerate(zip(left, right)):
                _close_enough(got, wanted, label=(label, group, "oracle", row_index, column))
        expected_ranks = {
            field: context.evaluate(expression) for field, expression in rank_expressions.items()
        }
        expected_correlation = context.evaluate(correlation_expression)
        factor = strategy.live_factor_set.factor_instances["alpha003"][group]
        assert tuple(data._name for data in factor.datas) == assets
        assert factor._factor_call_count == len(grid)

        expected_nodes = {"rank_open", "rank_volume"}
        expected_nodes.update("correlation10_%d" % index for index in range(len(assets)))
        expected_nodes.update("negate_%d" % index for index in range(len(assets)))
        assert set(factor._nodes) == expected_nodes, (label, group, sorted(factor._nodes))

        for field in ("open", "volume"):
            node = factor._nodes["rank_" + field]
            assert isinstance(node, operators.CrossSectionalRank)
            for column, asset in enumerate(assets):
                actual_line = node.outputs[factor.datas[column]].value.array
                actual_reason = node.outputs[factor.datas[column]].reason.array
                assert len(actual_line) == len(grid)
                assert all(
                    int(reason) == int(operators.OperatorReason.READY) for reason in actual_reason
                ), (label, group, field, asset, "rank reasons")
                for row_index, actual_value in enumerate(actual_line):
                    assert float(actual_value) == float(expected_ranks[field][row_index][column]), (
                        label,
                        group,
                        field,
                        asset,
                        row_index,
                    )

        for column, asset in enumerate(assets):
            correlation = factor._nodes["correlation10_%d" % column]
            negate = factor._nodes["negate_%d" % column]
            for row_index, point in enumerate(grid):
                wanted_correlation = expected_correlation[row_index][column]
                wanted_final = expected[row_index][column]
                _close_enough(
                    correlation.lines.value.array[row_index],
                    wanted_correlation,
                    label=(label, group, "correlation", asset, row_index),
                )
                _close_enough(
                    negate.lines.value.array[row_index],
                    wanted_final,
                    label=(label, group, "negate", asset, row_index),
                )
                expected_reason = (
                    operators.OperatorReason.NOT_READY
                    if row_index < 9
                    else operators.OperatorReason.READY
                    if math.isfinite(float(wanted_final))
                    else operators.OperatorReason.DOMAIN_ERROR
                )
                assert int(correlation.lines.reason.array[row_index]) == int(expected_reason), (
                    label,
                    group,
                    "correlation reason",
                    asset,
                    row_index,
                )
                assert int(negate.lines.reason.array[row_index]) == int(expected_reason), (
                    label,
                    group,
                    "final reason",
                    asset,
                    row_index,
                )
                output = snapshots[row_index].factors["alpha003"].values[asset]
                _close_enough(output.value, wanted_final, label=(label, group, asset, row_index))
                if math.isfinite(float(wanted_final)):
                    assert output.status.value == "OUTPUT_AVAILABLE" and output.reason is None
                else:
                    assert output.status.value == "OUTPUT_UNAVAILABLE"
                    assert output.reason == expected_reason.name


def _perturb_suffix(frames, *, cut):
    changed = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    for asset_index, (asset, frame) in enumerate(changed.items()):
        for row in range(cut, len(frame)):
            open_value = 1000.0 + asset_index * 37.0 + (row - cut) * (asset_index + 1.0)
            volume = 8000.0 + (len(changed) - asset_index) * 53.0 + (row - cut) * 11.0
            frame.iloc[row, frame.columns.get_loc("open")] = open_value
            frame.iloc[row, frame.columns.get_loc("high")] = open_value + 0.625
            frame.iloc[row, frame.columns.get_loc("low")] = open_value - 0.5
            frame.iloc[row, frame.columns.get_loc("close")] = open_value + 0.125
            frame.iloc[row, frame.columns.get_loc("volume")] = volume
    return changed


def _assert_prefix_equal(left, right, *, assets, cut, label):
    for row in range(cut):
        assert left.snapshots[row].close_time == right.snapshots[row].close_time
        assert left.snapshots[row].available_at == right.snapshots[row].available_at
        for asset in assets:
            old = left.snapshots[row].factors["alpha003"].values[asset]
            new = right.snapshots[row].factors["alpha003"].values[asset]
            _close_enough(old.value, new.value, label=(label, row, asset, "value"))
            assert (old.status, old.reason, old.present, old.quality) == (
                new.status,
                new.reason,
                new.present,
                new.quality,
            ), (label, row, asset, "status")


@pytest.mark.integration
@pytest.mark.parametrize("mode", ("native", "build"))
def test_live_alpha003_ties_degenerate_ranks_grouping_and_sealed_prefix(mode, monkeypatch):
    """Prove grouped live ranks, ties, degeneracy, and prefix causality."""
    frames = _edge_frames()
    cut = 18
    future = _perturb_suffix(frames, cut=cut)
    groups = dict(_GROUPS)
    assets = tuple(frames)

    baseline = _run_grouped_live(frames, groups, mode=mode, monkeypatch=monkeypatch)
    changed = _run_grouped_live(
        future,
        groups,
        mode=mode,
        monkeypatch=monkeypatch,
        arrival_delay=lambda asset, row: 0.05 * (assets.index(asset) + 1) if row >= cut else 0.0,
        max_future_skew_seconds=1.0,
    )
    _assert_group_oracle(baseline, frames, groups, label="baseline " + mode)
    _assert_group_oracle(changed, future, groups, label="future " + mode)
    _assert_prefix_equal(baseline, changed, assets=assets, cut=cut, label="grouped " + mode)

    # The first grid proves midrank ties are handled within each configured
    # cross-section rather than ranked against every feed in the cohort.
    ties = baseline.live_factor_set.factor_instances["alpha003"]["ties"]
    expected_open = (0.25, 0.625, 0.625, 1.0)
    expected_volume = (0.375, 0.375, 0.75, 1.0)
    for field, expected in (("open", expected_open), ("volume", expected_volume)):
        node = ties._nodes["rank_" + field]
        actual = tuple(float(node.outputs[data].value.array[0]) for data in ties.datas)
        assert actual == expected, (mode, field, actual, expected)
        assert len(set(actual)) < len(actual), (mode, field, "fixture must contain ties")
    assert any(
        math.isfinite(float(snapshot.factors["alpha003"].values[asset].value))
        for snapshot in baseline.snapshots
        for asset in ("tie-0", "tie-1", "tie-2", "tie-3")
    ), (mode, "tie fixture needs a finite-correlation witness")

    # Raw prices/volume move, but either constant cross-sectional rank makes
    # its rolling correlation undefined. This guards against replacing the
    # formula with a correlation of unranked levels or invented fallback data.
    for group, assets_in_group, fixed_field in (
        ("open-flat-rank", ("open-flat-0", "open-flat-1"), "open"),
        ("volume-flat-rank", ("volume-flat-0", "volume-flat-1"), "volume"),
        ("singleton", ("single",), None),
    ):
        factor = baseline.live_factor_set.factor_instances["alpha003"][group]
        field = "open" if fixed_field is None else fixed_field
        source = frames[assets_in_group[0]][field]
        assert source.nunique() > 1, (mode, group, field, "raw input must change")
        rank_node = factor._nodes["rank_" + field]
        rank_matrix = [
            [float(rank_node.outputs[data].value.array[row]) for data in factor.datas]
            for row in range(_PERIODS)
        ]
        assert all(row == rank_matrix[0] for row in rank_matrix), (
            mode,
            group,
            field,
            "rank should remain constant",
        )
        if group == "singleton":
            assert all(row == [1.0] for row in rank_matrix)
            volume_rank = factor._nodes["rank_volume"]
            assert all(
                float(volume_rank.outputs[factor.datas[0]].value.array[row]) == 1.0
                for row in range(_PERIODS)
            )
        assert not any(
            math.isfinite(float(snapshot.factors["alpha003"].values[asset].value))
            for snapshot in baseline.snapshots
            for asset in assets_in_group
        ), (mode, group, "constant ranks must not fabricate a finite score")


@pytest.mark.integration
@pytest.mark.parametrize("mode", ("native", "build"))
def test_single_asset_live_alpha003_has_no_fabricated_finite_correlation(mode):
    """A globally singleton live target has only constant midranks."""
    frames = {"only": _edge_frames()["single"]}
    strategy, _cohort, _feeds = parity._run_live(frames, mode=mode)
    grid = tuple(next(iter(frames.values())).index)
    factor = strategy.live_factor_set.factor_instances["alpha003"]["default"]
    matrices = oracle_frames(frames, grid=grid)
    mask = presence_matrix(frames, grid)
    context = _Context(matrices, formula_universe=mask, snap_correlation_bounds=False)
    formula = _parse(3)
    expected = reference(3, matrices, formula_universe=mask)
    expected_open = context.evaluate(("call", "rank", (("name", "open"),)))
    expected_volume = context.evaluate(("call", "rank", (("name", "volume"),)))
    assert all(row == [1.0] for row in expected_open)
    assert all(row == [1.0] for row in expected_volume)
    assert all(math.isnan(float(row[0])) for row in expected)

    correlation_expression = next(
        node for node in _postorder(formula) if node[0] == "call" and node[1] == "correlation"
    )
    expected_correlation = context.evaluate(correlation_expression)
    correlation = factor._nodes["correlation10_0"]
    negate = factor._nodes["negate_0"]
    for row in range(len(grid)):
        assert float(factor._nodes["rank_open"].outputs[factor.datas[0]].value.array[row]) == 1.0
        assert float(factor._nodes["rank_volume"].outputs[factor.datas[0]].value.array[row]) == 1.0
        assert math.isnan(float(expected_correlation[row][0]))
        assert math.isnan(float(correlation.lines.value.array[row]))
        assert math.isnan(float(negate.lines.value.array[row]))
        output = strategy.snapshots[row].factors["alpha003"].values["only"]
        assert math.isnan(float(output.value))
        assert output.status.value == "OUTPUT_UNAVAILABLE"
        assert output.reason == ("NOT_READY" if row < 9 else "DOMAIN_ERROR")
