"""Focused contracts for build-mode FactorIndicator expressions."""

from __future__ import annotations

import math
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.errors import DatasetError, FactorComputationError, ResearchConfigError
from backtrader.research import operators
from backtrader.research._expression import _ExpressionContext
from backtrader.research.alpha101 import (
    ALPHA_REGISTRY,
    Alpha003Build,
    Alpha003Native,
    get_alpha,
    list_alphas,
)
from backtrader.research.alpha101.alpha001 import Alpha001Build, Alpha001Native
from backtrader.research.alpha101.alpha029 import Alpha029Build, Alpha029Native
from backtrader.research.alpha101.alpha048 import Alpha048Build, Alpha048Native
from backtrader.research.alpha101.alpha100 import Alpha100Build, Alpha100Native
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.specs import FactorSpec
from tests.test_utils.alpha101_native_harness import (
    actual_matrix,
    assert_lifecycle,
    make_positive_fixture,
    make_research_spec,
    run_native_batch,
)
from tests.test_utils.alpha101_trace_validation import (
    compare_factor_graphs,
    validate_factor_trace,
)
from tests.unit.test_factor_research_representatives import _factor_spec, _research_feed


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_alpha003_build_matches_native_trace_values_reasons_and_lifecycle(runonce):
    frames = make_positive_fixture(320)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    native = run_native_batch(frames, (3,), runonce=runonce)
    built = run_native_batch(
        frames,
        (3,),
        runonce=runonce,
        alpha_classes={3: get_alpha(3, mode="build")},
    )

    native_factor = native.factor_instances["alpha3"]
    build_factor = built.factor_instances["alpha3"]
    assert native_factor._minperiod == build_factor._minperiod == 10
    assert_lifecycle(native, (3,), grid)
    assert_lifecycle(built, (3,), grid, alpha_classes={3: Alpha003Build})
    assert (
        native._alpha101_broker_call_counts
        == built._alpha101_broker_call_counts
        == {
            "submit": 0,
            "cancel": 0,
        }
    )

    native_trace = validate_factor_trace(native_factor, 3, frames, assets, grid, strategy=native)
    build_trace = validate_factor_trace(build_factor, 3, frames, assets, grid, strategy=built)
    assert native_trace["failures"] == []
    assert build_trace["failures"] == []
    assert native_trace["finite_witness"] and build_trace["finite_witness"]
    assert native_trace["matched_nodes"] == build_trace["matched_nodes"]
    native_values = actual_matrix(native, 3, assets, grid)
    build_values = actual_matrix(built, 3, assets, grid)
    assert len(native_values) == len(build_values) == len(grid)
    for row_index, (native_row, build_row) in enumerate(zip(native_values, build_values)):
        for asset_index, (native_value, build_value) in enumerate(zip(native_row, build_row)):
            assert math.isnan(native_value) == math.isnan(build_value), (row_index, asset_index)
            if math.isfinite(native_value):
                assert build_value == native_value
    first_finite = next(
        row_index
        for row_index, row in enumerate(build_values)
        if any(math.isfinite(value) for value in row)
    )
    assert first_finite == 9

    # Native and build graphs have the same operator topology and preserve the
    # operator's concrete failure reasons at every intermediate line.
    assert set(native_factor._nodes) == set(build_factor._nodes)
    graph_pair = compare_factor_graphs(native_factor, build_factor, 3)
    assert graph_pair["equal"], graph_pair["failures"]
    for key in native_factor._nodes:
        native_node = native_factor._nodes[key]
        build_node = build_factor._nodes[key]
        assert type(native_node).__name__ == type(build_node).__name__, key
        if isinstance(native_node, operators._PanelOperator):
            for native_data, build_data in zip(
                native_factor.target_datas, build_factor.target_datas
            ):
                native_reason = native_node.outputs[native_data].reason.array
                build_reason = build_node.outputs[build_data].reason.array
                assert list(native_reason) == list(build_reason), (key, native_data._name)
        else:
            assert list(native_node.lines.reason.array) == list(build_node.lines.reason.array), key


@pytest.mark.parametrize(
    ("alpha_id", "native_class", "build_class"),
    (
        (1, Alpha001Native, Alpha001Build),
        (29, Alpha029Native, Alpha029Build),
        (48, Alpha048Native, Alpha048Build),
        (100, Alpha100Native, Alpha100Build),
    ),
    ids=("alpha001", "alpha029", "alpha048", "alpha100"),
)
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_representative_build_companions_match_native_trace_values_and_lifecycle(
    alpha_id, native_class, build_class, runonce
):
    frames = make_positive_fixture(320)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    native = run_native_batch(frames, (alpha_id,), runonce=runonce)
    built = run_native_batch(
        frames,
        (alpha_id,),
        runonce=runonce,
        alpha_classes={alpha_id: build_class},
    )

    native_factor = native.factor_instances["alpha%d" % alpha_id]
    build_factor = built.factor_instances["alpha%d" % alpha_id]
    assert get_alpha(alpha_id, mode="build") is build_class
    assert native_factor._minperiod == build_factor._minperiod == native_class.lookback_h + 1
    assert build_class.lookback_h == native_class.lookback_h
    assert build_class.case_id == native_class.case_id
    assert build_class.formula_fields == native_class.formula_fields
    assert build_class.required_fields == native_class.required_fields
    assert build_class.formula == native_class.formula
    assert build_class.operator_profile == native_class.operator_profile
    assert build_class.input_policy == native_class.input_policy
    assert_lifecycle(native, (alpha_id,), grid)
    assert_lifecycle(built, (alpha_id,), grid, alpha_classes={alpha_id: build_class})

    native_trace = validate_factor_trace(
        native_factor, alpha_id, frames, assets, grid, strategy=native
    )
    build_trace = validate_factor_trace(
        build_factor, alpha_id, frames, assets, grid, strategy=built
    )
    assert native_trace["failures"] == []
    assert build_trace["failures"] == []
    assert native_trace["finite_witness"] and build_trace["finite_witness"]
    assert native_trace["matched_nodes"] == build_trace["matched_nodes"]
    graph_pair = compare_factor_graphs(native_factor, build_factor, alpha_id)
    assert graph_pair["equal"], graph_pair["failures"]

    _assert_alpha003_values_equal(
        actual_matrix(native, alpha_id, assets, grid),
        actual_matrix(built, alpha_id, assets, grid),
        label="Alpha%d native/build" % alpha_id,
    )
    assert (
        native._alpha101_broker_call_counts
        == built._alpha101_broker_call_counts
        == {
            "submit": 0,
            "cancel": 0,
        }
    )


def _run_alpha003_mode_pair(frames, *, runonce):
    native = run_native_batch(frames, (3,), runonce=runonce)
    build = run_native_batch(
        frames,
        (3,),
        runonce=runonce,
        alpha_classes={3: Alpha003Build},
    )
    return native, build


def _assert_alpha003_values_equal(left, right, *, label, require_finite=True):
    assert len(left) == len(right), label
    finite_witness = False
    for row_index, (left_row, right_row) in enumerate(zip(left, right)):
        assert len(left_row) == len(right_row), (label, row_index)
        for asset_index, (left_value, right_value) in enumerate(zip(left_row, right_row)):
            location = (label, row_index, asset_index)
            assert math.isnan(left_value) == math.isnan(right_value), location
            assert not math.isinf(left_value) and not math.isinf(right_value), location
            if math.isfinite(left_value):
                finite_witness = True
                assert left_value == right_value, location
    if require_finite:
        assert finite_witness, "%s must retain a finite output witness" % label


def test_alpha003_value_pair_helper_rejects_shared_infinity():
    with pytest.raises(AssertionError):
        _assert_alpha003_values_equal([[math.inf]], [[math.inf]], label="shared infinity")


def _assert_alpha003_reasons_equal(native_factor, build_factor):
    assert set(native_factor._nodes) == set(build_factor._nodes)
    for key, native_node in native_factor._nodes.items():
        build_node = build_factor._nodes[key]
        assert type(native_node).__name__ == type(build_node).__name__, key
        if isinstance(native_node, operators._PanelOperator):
            for native_data, build_data in zip(
                native_factor.target_datas, build_factor.target_datas
            ):
                assert list(native_node.outputs[native_data].reason.array) == list(
                    build_node.outputs[build_data].reason.array
                ), (key, native_data._name)
        else:
            assert list(native_node.lines.reason.array) == list(build_node.lines.reason.array), key


def _assert_alpha003_raw_panel_order(strategy, assets, grid):
    panel = strategy.get_panel()
    assert tuple(panel.target_order) == tuple(assets)
    index = panel.factors.index
    assert tuple(index.get_level_values("asset")) == tuple(assets) * len(grid)
    expected_times = tuple(point for point in grid for _asset in assets)
    assert tuple(index.get_level_values("time")) == expected_times


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_alpha003_causality_and_reversed_asset_order_contract(runonce):
    base = make_positive_fixture(320)
    frames = {asset: frame.iloc[:36].copy() for asset, frame in base.items()}
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    cut = 24
    perturbed = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    for day_index, point in enumerate(grid[cut:], start=cut):
        for asset_index, asset in enumerate(assets):
            # Rotate both cross-sectional rankings after the causal cut so the
            # perturbed run has a real changed-future witness.
            perturbed[asset].loc[point, "open"] = 100.0 + (asset_index + day_index) % len(assets)
            perturbed[asset].loc[point, "volume"] = 1000.0 + (2 * day_index - asset_index) % len(
                assets
            )
    reversed_frames = dict(reversed(tuple(frames.items())))
    baseline_native, baseline_build = _run_alpha003_mode_pair(frames, runonce=runonce)
    changed_native, changed_build = _run_alpha003_mode_pair(perturbed, runonce=runonce)
    reversed_native, reversed_build = _run_alpha003_mode_pair(reversed_frames, runonce=runonce)
    baseline = {"native": baseline_native, "build": baseline_build}
    changed = {"native": changed_native, "build": changed_build}
    reversed_runs = {"native": reversed_native, "build": reversed_build}

    future_changed_witness = False
    for mode in ("native", "build"):
        original = baseline[mode]
        changed_run = changed[mode]
        reversed_run = reversed_runs[mode]
        original_values = actual_matrix(original, 3, assets, grid)
        changed_values = actual_matrix(changed_run, 3, assets, grid)
        reversed_values = actual_matrix(reversed_run, 3, assets, grid)

        _assert_alpha003_raw_panel_order(original, assets, grid)
        _assert_alpha003_raw_panel_order(changed_run, assets, grid)
        _assert_alpha003_raw_panel_order(reversed_run, tuple(reversed(assets)), grid)
        _assert_alpha003_values_equal(
            original_values, reversed_values, label=mode + " reversed asset semantics"
        )

        assert any(math.isfinite(value) for row in original_values[:cut] for value in row)
        for row_index in range(cut):
            _assert_alpha003_values_equal(
                [original_values[row_index]],
                [changed_values[row_index]],
                label="%s causal prefix row %d" % (mode, row_index),
                require_finite=False,
            )
        for original_row, changed_row in zip(original_values[cut:], changed_values[cut:]):
            for original_value, changed_value in zip(original_row, changed_row):
                if math.isnan(original_value) != math.isnan(changed_value) or (
                    math.isfinite(original_value) and original_value != changed_value
                ):
                    future_changed_witness = True
    assert future_changed_witness, "future perturbation must change at least one future factor cell"

    baseline_native = baseline["native"].factor_instances["alpha3"]
    baseline_build = baseline["build"].factor_instances["alpha3"]
    _assert_alpha003_reasons_equal(baseline_native, baseline_build)
    _assert_alpha003_values_equal(
        actual_matrix(baseline["native"], 3, assets, grid),
        actual_matrix(baseline["build"], 3, assets, grid),
        label="native/build baseline",
    )
    for pair_name, pair in (("perturbed", changed), ("reversed", reversed_runs)):
        _assert_alpha003_reasons_equal(
            pair["native"].factor_instances["alpha3"],
            pair["build"].factor_instances["alpha3"],
        )
        _assert_alpha003_values_equal(
            actual_matrix(pair["native"], 3, assets, grid),
            actual_matrix(pair["build"], 3, assets, grid),
            label="native/build " + pair_name,
        )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_alpha003_degenerate_recovery_missing_bar_nan_trace_and_reason_pair(runonce):
    base = make_positive_fixture(320)
    frames = {asset: frame.iloc[:48].copy() for asset, frame in base.items()}
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)

    # A fixed cross-sectional order gives every asset constant rank inputs;
    # correlation is undefined until the original varying inputs resume.
    for asset_index, asset in enumerate(assets):
        frames[asset].loc[list(grid[:16]), "open"] = 10.0 + asset_index
        frames[asset].loc[list(grid[:16]), "volume"] = 1000.0 + 10.0 * asset_index
    missing_asset = assets[1]
    frames[missing_asset] = frames[missing_asset].drop(index=grid[27])
    nan_asset = assets[2]
    frames[nan_asset].loc[grid[30], "volume"] = math.nan

    native, build = _run_alpha003_mode_pair(frames, runonce=runonce)
    native_factor = native.factor_instances["alpha3"]
    build_factor = build.factor_instances["alpha3"]
    native_trace = validate_factor_trace(native_factor, 3, frames, assets, grid, strategy=native)
    build_trace = validate_factor_trace(build_factor, 3, frames, assets, grid, strategy=build)
    assert native_trace["failures"] == []
    assert build_trace["failures"] == []
    assert native_trace["finite_witness"] and build_trace["finite_witness"]
    assert native_trace["matched_nodes"] == build_trace["matched_nodes"]
    _assert_alpha003_reasons_equal(native_factor, build_factor)

    native_values = actual_matrix(native, 3, assets, grid)
    build_values = actual_matrix(build, 3, assets, grid)
    _assert_alpha003_values_equal(native_values, build_values, label="gap/NaN native/build")
    assert all(
        math.isnan(value) for row in native_values[9:16] for value in row
    ), "constant-rank correlation windows must be undefined"
    assert any(
        math.isfinite(value) for row in native_values[24:27] for value in row
    ), "finite factors must recover after the degenerate interval"
    assert grid[27] not in frames[missing_asset].index
    assert grid[30] in frames[nan_asset].index
    assert math.isnan(float(frames[nan_asset].loc[grid[30], "volume"]))

    correlation_nodes = [
        node
        for node in native_factor._nodes.values()
        if isinstance(node, operators.RollingCorrelation)
    ]
    assert len(correlation_nodes) == len(assets)
    assert all(
        int(node.lines.reason.array[14]) == int(operators.OperatorReason.DOMAIN_ERROR)
        for node in correlation_nodes
    ), "constant rank inputs must carry the correlation domain reason"

    rank_nodes = [
        node
        for node in native_factor._nodes.values()
        if isinstance(node, operators.CrossSectionalRank)
    ]
    assert len(rank_nodes) == 2
    missing_index = assets.index(missing_asset)
    nan_index = assets.index(nan_asset)
    for node in rank_nodes:
        assert int(node.outputs[native_factor.target_datas[missing_index]].reason.array[27]) == int(
            operators.OperatorReason.FORMULA_INELIGIBLE
        )
    volume_rank = native_factor._nodes["rank_volume"]
    assert int(volume_rank.outputs[native_factor.target_datas[nan_index]].reason.array[30]) == int(
        operators.OperatorReason.NONFINITE_INPUT
    )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_expression_context_is_per_group_closed_after_build_and_targets_are_identity_bound(
    runonce, monkeypatch
):
    frames = make_positive_fixture(320)
    assets = tuple(frames)
    groups = {
        asset: ("left" if index < len(assets) // 2 else "right")
        for index, asset in enumerate(assets)
    }
    original_build = Alpha003Build.build
    contexts = []

    def counted_build(cls, ctx, **params):
        contexts.append(ctx)
        return original_build(ctx, **params)

    monkeypatch.setattr(Alpha003Build, "build", classmethod(counted_build))
    strategy = run_native_batch(
        frames,
        (3,),
        runonce=runonce,
        alpha_classes={3: Alpha003Build},
        groups=groups,
    )
    aggregate = strategy.factor_instances["alpha3"]
    instances = aggregate.group_instances
    assert set(instances) == {"left", "right"}
    assert len(contexts) == len(instances) == 2
    assert len({id(context._token) for context in contexts}) == 2
    assert all(context._closed for context in contexts)
    for context in contexts:
        with pytest.raises(RuntimeError, match="closed"):
            context.field("open")

    for group, factor in instances.items():
        group_assets = tuple(asset for asset in assets if groups[asset] == group)
        assert tuple(data._name for data in factor.target_datas) == group_assets
        assert set(factor.outputs) == set(factor.target_datas)
        assert all(
            data not in factor.outputs for data in strategy.datas if data not in factor.target_datas
        )
        assert factor.lifecycle_diagnostics["call_count"] == len(frames[group_assets[0]])
        for node in factor._nodes.values():
            if isinstance(node, operators._PanelOperator):
                assert tuple(node.target_datas) == factor.target_datas


class _WhereArithmeticBuild(FactorIndicator):
    lines = ("factor",)
    panel_mode = "expression"
    formula_fields = ("close",)
    lookback_h = 0

    @classmethod
    def build(cls, ctx, **params):
        close = ctx.close
        return ctx.where(close > 10.0, 2.0 / close, close - 2.0) + 3.0


class _ConstantSubtractBuild(FactorIndicator):
    lines = ("factor",)
    panel_mode = "expression"
    formula_fields = ()
    lookback_h = 0

    @classmethod
    def build(cls, ctx, **params):
        return ctx.subtract(1.0, 0.728317)


class _ParameterizedBuild(FactorIndicator):
    lines = ("factor",)
    params = (("scale", 2.0),)
    panel_mode = "expression"
    formula_fields = ("close",)
    build_contexts = []

    @staticmethod
    def lookback_h(scale=2.0, **params):
        return int(scale) - 1

    @classmethod
    def build(cls, ctx, scale=2.0, **params):
        cls.build_contexts.append((ctx, scale))
        return ctx.close * scale


def _double_value(value):
    return 2.0 * value


class _ApplyBuild(FactorIndicator):
    lines = ("factor",)
    panel_mode = "expression"
    formula_fields = ("close",)
    lookback_h = 0
    build_calls = []

    @classmethod
    def build(cls, ctx, **params):
        cls.build_calls.append(ctx)
        return ctx.apply(_double_value, ctx.close)


class _InvalidReturnBuild(FactorIndicator):
    lines = ("factor",)
    params = (("return_kind", "none"),)
    panel_mode = "expression"
    formula_fields = ("close",)
    lookback_h = 0

    @classmethod
    def build(cls, ctx, return_kind="none"):
        if return_kind == "none":
            return None
        return ctx.close._lines[0]


class _DoubleInitializeBuild(FactorIndicator):
    lines = ("factor",)
    panel_mode = "expression"
    formula_fields = ("close",)
    lookback_h = 0
    build_calls = []
    fail_build = False
    retry_after_failed_build = False

    @classmethod
    def build(cls, ctx, **params):
        cls.build_calls.append(ctx)
        if cls.fail_build:
            raise ValueError("intentional first build failure")
        return ctx.close

    def __init__(self):
        try:
            super().__init__()
        except ValueError:
            if not self.__class__.retry_after_failed_build:
                raise
        # This second call must fail before reconstructing outputs or building
        # another graph, including when the first build error was caught.
        super().__init__()


class _OperatorSurfaceBuild(FactorIndicator):
    lines = ("factor",)
    params = (("period", 2.9),)
    panel_mode = "expression"
    formula_fields = ("close", "subindustry")

    @staticmethod
    def lookback_h(period=2.9, **params):
        return math.floor(float(period))

    @classmethod
    def build(cls, ctx, period=2.9, **params):
        close = ctx.close
        absolute = ctx.abs(close)
        sign = ctx.sign(close)
        logged = ctx.log(absolute + 1.0)
        powered = ctx.signed_power(close, 2.0)
        minimum = ctx.minimum(absolute, powered)
        maximum = ctx.maximum(absolute, powered)
        delayed = ctx.delay(close, period)
        delta = ctx.delta(close, period)
        summed = ctx.sum(close, period)
        product = ctx.product(close, period)
        deviation = ctx.stddev(close, period)
        minimum_window = ctx.ts_min(close, period)
        maximum_window = ctx.ts_max(close, period)
        rank = ctx.ts_rank(close, period)
        argmin = ctx.ts_argmin(close, period)
        argmax = ctx.ts_argmax(close, period)
        decay = ctx.decay_linear(close, period)
        covariance = ctx.covariance(close, close, period)
        scaled = ctx.scale(close, a=1.5)
        neutralized = ctx.indneutralize(
            scaled,
            ctx.subindustry,
            level="subindustry",
        )
        ordered_less_than = ctx.less_than(0.0, close)
        ordered_equal_to = ctx.equal_to(0.0, close)
        logical = ctx.logical_or(close > 0.0, close < 0.0)
        components = (
            absolute,
            sign,
            logged,
            powered,
            minimum,
            maximum,
            delayed,
            delta,
            summed,
            product,
            deviation,
            minimum_window,
            maximum_window,
            rank,
            argmin,
            argmax,
            decay,
            covariance,
            scaled,
            neutralized,
            ordered_less_than,
            ordered_equal_to,
            logical,
        )
        result = components[0]
        for component in components[1:]:
            result = result + component
        return result


class _ClassificationBuild(FactorIndicator):
    lines = ("factor",)
    panel_mode = "expression"
    formula_fields = ("close", "subindustry")
    lookback_h = 0

    @classmethod
    def build(cls, ctx, **params):
        return ctx.indneutralize(ctx.close, ctx.subindustry, level="subindustry")


def _run_custom_expression(factor_class, frames, *, runonce=True, factor_params=None, groups=None):
    research = make_research_spec(frames, groups=groups)
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for asset, frame in frames.items():
        cerebro.adddata(_research_feed(frame, research, asset), name=asset)
    spec = FactorSpec(
        name="custom",
        indicator=factor_class,
        panel_line="factor",
        params=factor_params or {},
        field_bindings={field: "feed:target:%s" % field for field in factor_class.formula_fields},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"custom": spec})
    return cerebro.run()[0]


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_expression_arithmetic_where_and_safe_unselected_division(runonce):
    base = make_positive_fixture(320)
    frames = {asset: frame.iloc[:6].copy() for asset, frame in tuple(base.items())[:2]}
    closes = (0.0, 2.0, 20.0, 0.0, 11.0, 5.0)
    for frame in frames.values():
        frame.loc[:, "close"] = closes
    strategy = _run_custom_expression(_WhereArithmeticBuild, frames, runonce=runonce)
    values = strategy.get_panel().factors["custom"].to_numpy(dtype="float64")
    assert len(values) == len(closes) * len(frames)
    # The zero denominators occur only in the unselected branch. Divide marks
    # its own domain error while Where safely selects the other branch.
    assert all(math.isfinite(float(value)) for value in values)
    for row, close in enumerate(closes):
        expected = (2.0 / close if close > 10.0 else close - 2.0) + 3.0
        for asset_index in range(len(frames)):
            actual = float(values[row * len(frames) + asset_index])
            assert actual == pytest.approx(expected)
    factor = strategy.factor_instances["custom"]
    divisions = [node for node in factor._nodes.values() if isinstance(node, operators.Divide)]
    assert len(divisions) == len(frames)
    assert all(
        float(node.lines.reason.array[0]) == float(operators.OperatorReason.DOMAIN_ERROR)
        for node in divisions
    )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_apply_builds_one_native_indicator_per_target_once_and_registers_with_owner(runonce):
    frames = make_positive_fixture(320)
    frames = {asset: frame.iloc[:12].copy() for asset, frame in tuple(frames.items())[:2]}
    _ApplyBuild.build_calls.clear()
    strategy = _run_custom_expression(_ApplyBuild, frames, runonce=runonce)
    factor = strategy.factor_instances["custom"]
    nodes = tuple(factor._nodes.values())

    assert len(_ApplyBuild.build_calls) == 1
    assert len(nodes) == len(factor.target_datas) == len(frames)
    for index, (asset, target, node) in enumerate(zip(frames, factor.target_datas, nodes)):
        assert not isinstance(node, FactorIndicator)
        assert node.p.function is _double_value
        assert node._owner is factor
        assert node.datas[0] is factor._field_line_cache["close"][index]
        registrations = [
            child
            for children in factor._lineiterators.values()
            for child in children
            if child is node
        ]
        assert registrations == [node]
        actual = [
            float(value) for value in factor.outputs[target].factor.get(size=len(frames[asset]))
        ]
        for observed, close in zip(actual, frames[asset]["close"]):
            assert observed == 2.0 * close


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_constant_subtract_builds_target_marked_native_nodes_with_reasons(runonce):
    base = make_positive_fixture(320)
    frames = {asset: frame.iloc[:7].copy() for asset, frame in tuple(base.items())[:2]}
    strategy = _run_custom_expression(_ConstantSubtractBuild, frames, runonce=runonce)
    factor = strategy.factor_instances["custom"]

    assert tuple(factor._nodes) == ("subtract_0", "subtract_1")
    assert len(factor._nodes) == len(factor.target_datas) == len(frames)
    expected = 1.0 - 0.728317
    for target, node in zip(factor.target_datas, factor._nodes.values()):
        assert type(node) is operators.Subtract
        assert node._operand_args == (1.0, 0.728317)
        assert node.lines.value._factor_research_target is target
        assert node.lines.value._factor_research_reason_line is node.lines.reason
        assert list(node.lines.value.array) == [expected] * len(frames[target._name])
        assert list(node.lines.reason.array) == [float(operators.OperatorReason.READY)] * len(
            frames[target._name]
        )
        registrations = [
            child
            for children in factor._lineiterators.values()
            for child in children
            if child is node
        ]
        assert registrations == [node]

        output = factor.outputs[target].factor.array
        assert list(output) == [expected] * len(frames[target._name])


def test_apply_rejects_foreign_closed_and_invalid_inputs():
    target = object()
    line = SimpleNamespace(array=[])

    class FakeFactor:
        target_datas = (target,)
        formula_fields = ("close",)

        @staticmethod
        def field_lines(alias):
            return (line,)

    first = _ExpressionContext(FakeFactor())
    foreign = _ExpressionContext(FakeFactor())
    expression = first.field("close")

    with pytest.raises(TypeError, match="different factor build context"):
        first.apply(_double_value, foreign.field("close"))
    with pytest.raises(TypeError, match="callback must be callable"):
        first.apply(None, expression)
    with pytest.raises(TypeError, match="at least one expression"):
        first.apply(_double_value)

    first._close()
    with pytest.raises(RuntimeError, match="closed"):
        first.apply(_double_value, expression)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_expression_maps_auxiliary_inputs_to_target_outputs_by_identity(runonce):
    base = make_positive_fixture(320)
    assets = tuple(base)[:2]
    target_frames = {asset: base[asset].iloc[:6].copy() for asset in assets}
    auxiliary = base["asset-2"].iloc[:6].copy()
    auxiliary.loc[:, "close"] = (0.0, 2.0, 20.0, 0.0, 11.0, 5.0)

    class AuxiliaryInputStrategy(bt.Strategy):
        def __init__(self):
            self.factor = _WhereArithmeticBuild._bind_for_research(
                self.data0,
                self.data1,
                self.data2,
                output_datas=(self.data0, self.data1),
                asset_names=assets,
                factor_name=None,
                field_bindings={"close": "feed:AUX:close"},
                research=None,
                available_datas=self.datas,
                strict=False,
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for asset, frame in target_frames.items():
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=asset)
    cerebro.adddata(bt.feeds.PandasData(dataname=auxiliary), name="AUX")
    cerebro.addstrategy(AuxiliaryInputStrategy)
    strategy = cerebro.run()[0]
    factor = strategy.factor

    assert tuple(factor.datas) == tuple(strategy.datas)
    assert factor.target_datas == tuple(strategy.datas[:2])
    assert len(factor.datas) == 3 and len(factor.target_datas) == 2
    assert set(factor.outputs) == set(factor.target_datas)
    bound_lines = factor._field_line_cache["close"]
    assert len(bound_lines) == 2 and bound_lines[0] is bound_lines[1]
    for index, close in enumerate((0.0, 2.0, 20.0, 0.0, 11.0, 5.0)):
        expected = (2.0 / close if close > 10.0 else close - 2.0) + 3.0
        for target in factor.target_datas:
            assert float(factor.outputs[target].factor.array[index]) == pytest.approx(expected)
    assert all(data not in factor.outputs for data in strategy.datas[2:])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("period", (2.9, 3.9), ids=("floor-two", "floor-three"))
def test_research_operator_surface_preserves_floor_members_groups_and_owner(period, runonce):
    base = make_positive_fixture(320)
    frames = {asset: frame.iloc[:12].copy() for asset, frame in tuple(base.items())[:6]}
    assets = tuple(frames)
    groups = {asset: ("left" if index < 3 else "right") for index, asset in enumerate(assets)}
    strategy = _run_custom_expression(
        _OperatorSurfaceBuild,
        frames,
        runonce=runonce,
        factor_params={"period": period},
        groups=groups,
    )
    aggregate = strategy.factor_instances["custom"]
    instances = aggregate.group_instances
    expected_window = math.floor(period)
    assert _OperatorSurfaceBuild.lookback_h(period=period) == expected_window
    assert any(
        math.isfinite(float(value))
        for output in aggregate.outputs.values()
        for value in output.factor.array
    )
    assert set(instances) == {"left", "right"}
    for group, factor in instances.items():
        group_assets = tuple(asset for asset in assets if groups[asset] == group)
        assert factor._minperiod == expected_window + 1
        assert tuple(data._name for data in factor.target_datas) == group_assets
        node_types = tuple(type(node) for node in factor._nodes.values())
        for expected in (
            operators.Abs,
            operators.Sign,
            operators.Log,
            operators.SignedPower,
            operators.Minimum,
            operators.Maximum,
            operators.Delay,
            operators.Delta,
            operators.RollingSum,
            operators.RollingProduct,
            operators.RollingStd,
            operators.TsMin,
            operators.TsMax,
            operators.TsRank,
            operators.TsArgMin,
            operators.TsArgMax,
            operators.DecayLinear,
            operators.RollingCovariance,
            operators.CrossSectionalScale,
            operators.IndNeutralize,
            operators.LogicalOr,
            operators.LessThan,
            operators.EqualTo,
        ):
            assert any(issubclass(node_type, expected) for node_type in node_types), expected

        rolling_nodes = [
            node for node in factor._nodes.values() if getattr(node, "_period", None) is not None
        ]
        assert rolling_nodes
        assert all(node._period == expected_window for node in rolling_nodes)
        scale_nodes = [
            node
            for node in factor._nodes.values()
            if isinstance(node, operators.CrossSectionalScale)
        ]
        neutralize_nodes = [
            node for node in factor._nodes.values() if isinstance(node, operators.IndNeutralize)
        ]
        assert len(scale_nodes) == len(neutralize_nodes) == 1
        scale = scale_nodes[0]
        neutralize = neutralize_nodes[0]
        assert scale.p.a == 1.5
        assert all(
            actual is expected for actual, expected in zip(scale._members, factor.formula_members)
        )
        assert tuple(scale._groups) == factor.research_groups
        assert all(
            actual is expected
            for actual, expected in zip(neutralize._members, factor.formula_members)
        )
        assert all(
            actual is expected
            for actual, expected in zip(neutralize._groups, factor.field_lines("subindustry"))
        )
        assert neutralize.p.level == "subindustry"

        close_lines = factor.field_lines("close")
        ordered_less_nodes = [
            node
            for node in factor._nodes.values()
            if type(node) is operators.LessThan and node._operand_args[0] == 0.0
        ]
        ordered_equal_nodes = [
            node
            for node in factor._nodes.values()
            if type(node) is operators.EqualTo and node._operand_args[0] == 0.0
        ]
        assert len(ordered_less_nodes) == len(ordered_equal_nodes) == len(group_assets)
        for index, (less_node, equal_node) in enumerate(
            zip(ordered_less_nodes, ordered_equal_nodes)
        ):
            assert less_node._operand_args[1] is close_lines[index]
            assert equal_node._operand_args[1] is close_lines[index]

        nodes = tuple(factor._nodes.values())
        assert len({id(node) for node in nodes}) == len(nodes)
        for key, node in factor._nodes.items():
            if not isinstance(node, operators._PanelOperator):
                assert key.rsplit("_", 1)[-1].isdigit(), key
            assert node._owner is factor
            registrations = [
                child
                for children in factor._lineiterators.values()
                for child in children
                if child is node
            ]
            assert registrations == [node]


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_indneutralize_unknown_classification_retains_reason_and_factor_output(runonce):
    base = make_positive_fixture(320)
    frames = {asset: frame.iloc[:5].copy() for asset, frame in tuple(base.items())[:4]}
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    unknown_asset = assets[0]
    unknown_time = grid[2]
    frames[unknown_asset].loc[unknown_time, "subindustry"] = math.nan

    strategy = _run_custom_expression(_ClassificationBuild, frames, runonce=runonce)
    factor = strategy.factor_instances["custom"]
    node = next(
        value for value in factor._nodes.values() if isinstance(value, operators.IndNeutralize)
    )
    unknown_target = factor.target_datas[assets.index(unknown_asset)]
    index = grid.index(unknown_time)
    assert math.isnan(float(node.outputs[unknown_target].value.array[index]))
    assert int(node.outputs[unknown_target].reason.array[index]) == int(
        operators.OperatorReason.UNKNOWN_CLASSIFICATION
    )
    assert math.isnan(float(factor.outputs[unknown_target].factor.array[index]))
    assert any(
        math.isfinite(float(value))
        for output in factor.outputs.values()
        for value in output.factor.array
    )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_native_and_multiple_build_factors_share_one_strategy_without_shared_nodes(runonce):
    frames = make_positive_fixture(320)
    research = make_research_spec(frames)
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for asset, frame in frames.items():
        cerebro.adddata(_research_feed(frame, research, asset), name=asset)
    _ParameterizedBuild.build_contexts.clear()
    specs = {
        "native": _factor_spec("native", Alpha003Native),
        "build": _factor_spec("build", Alpha003Build),
        "scaled_default": FactorSpec(
            name="scaled_default",
            indicator=_ParameterizedBuild,
            panel_line="factor",
            field_bindings={"close": "feed:target:close"},
        ),
        "scaled_override": FactorSpec(
            name="scaled_override",
            indicator=_ParameterizedBuild,
            panel_line="factor",
            params={"scale": 4.0},
            field_bindings={"close": "feed:target:close"},
        ),
    }
    assert specs["scaled_default"].lookback_h == 1
    assert specs["scaled_override"].lookback_h == 3
    cerebro.addstrategy(FactorStrategy, research=research, factors=specs)
    strategy = cerebro.run()[0]

    native = strategy.factor_instances["native"]
    built = strategy.factor_instances["build"]
    assert native._minperiod == built._minperiod == 10
    assert all(
        native.outputs[data].factor.array[index] == built.outputs[data].factor.array[index]
        or (
            math.isnan(native.outputs[data].factor.array[index])
            and math.isnan(built.outputs[data].factor.array[index])
        )
        for data in native.target_datas
        for index in range(len(next(iter(frames.values()))))
    )

    default_factor = strategy.factor_instances["scaled_default"]
    override_factor = strategy.factor_instances["scaled_override"]
    assert default_factor._minperiod == 2
    assert override_factor._minperiod == 4
    assert [scale for _context, scale in _ParameterizedBuild.build_contexts] == [2.0, 4.0]
    assert len({id(context) for context, _scale in _ParameterizedBuild.build_contexts}) == 2
    for asset, data in zip(frames, default_factor.target_datas):
        for index, close in enumerate(frames[asset]["close"]):
            assert default_factor.outputs[data].factor.array[index] == pytest.approx(2.0 * close)
            assert override_factor.outputs[
                override_factor.target_datas[tuple(frames).index(asset)]
            ].factor.array[index] == pytest.approx(4.0 * close)

    trees = [
        FactorStrategy._factor_tree(strategy.factor_instances[name])
        for name in ("native", "build", "scaled_default", "scaled_override")
    ]
    tree_ids = [{id(node) for node in tree} for tree in trees]
    for left_index, left in enumerate(tree_ids):
        assert len(left) == len(trees[left_index])
        for right in tree_ids[left_index + 1 :]:
            assert left.isdisjoint(right)
    factor_instances = [
        strategy.factor_instances[name]
        for name in ("native", "build", "scaled_default", "scaled_override")
    ]
    operator_nodes = [tuple(factor._nodes.values()) for factor in factor_instances]
    operator_ids = [{id(node) for node in nodes} for nodes in operator_nodes]
    for index, (factor, nodes, node_ids) in enumerate(
        zip(factor_instances, operator_nodes, operator_ids)
    ):
        assert len(node_ids) == len(nodes)
        for node in nodes:
            assert node._owner is factor
            registered = [
                child
                for children in factor._lineiterators.values()
                for child in children
                if child is node
            ]
            assert len(registered) == 1
        for other_ids in operator_ids[index + 1 :]:
            assert node_ids.isdisjoint(other_ids)
    assert all(
        node.lifecycle_diagnostics["call_count"] == len(research.calculation_grid)
        for tree in trees
        for node in tree
    )


@pytest.mark.parametrize("return_kind", ("none", "raw"))
def test_factor_strategy_rejects_none_and_raw_line_build_results_with_init_context(return_kind):
    frames = make_positive_fixture(320)
    with pytest.raises(FactorComputationError) as raised:
        _run_custom_expression(
            _InvalidReturnBuild,
            frames,
            runonce=True,
            factor_params={"return_kind": return_kind},
        )
    assert raised.value.factor == "custom"
    assert raised.value.phase == "init"
    assert isinstance(raised.value.__cause__, TypeError)


@pytest.mark.parametrize("fail_build", (False, True), ids=("second-super", "failed-build-retry"))
def test_expression_build_initialization_is_once_even_after_a_failed_build(fail_build):
    frames = make_positive_fixture(320)
    _DoubleInitializeBuild.build_calls.clear()
    _DoubleInitializeBuild.fail_build = fail_build
    _DoubleInitializeBuild.retry_after_failed_build = fail_build

    with pytest.raises(FactorComputationError) as raised:
        _run_custom_expression(_DoubleInitializeBuild, frames, runonce=True)

    assert raised.value.factor == "custom"
    assert raised.value.phase == "init"
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert "only be initialized once" in str(raised.value.__cause__)
    assert len(_DoubleInitializeBuild.build_calls) == 1


def test_expression_declarations_and_results_fail_closed():
    def define(name, **attributes):
        return type(name, (FactorIndicator,), {"__module__": __name__, **attributes})

    with pytest.raises(TypeError, match="exactly one output line"):
        define(
            "_TwoOutputsBuild",
            lines=("one", "two"),
            panel_mode="expression",
            formula_fields=("close",),
            build=classmethod(lambda cls, ctx, **params: ctx.close),
        )
    with pytest.raises(TypeError, match="custom next"):
        define(
            "_CustomNextBuild",
            lines=("factor",),
            panel_mode="expression",
            formula_fields=("close",),
            build=classmethod(lambda cls, ctx, **params: ctx.close),
            next=lambda self: None,
        )
    with pytest.raises(TypeError, match="build\(\)/expression"):
        define(
            "_MixedNativeBuild",
            lines=("factor",),
            panel_mode="next",
            formula_fields=("close",),
            build=classmethod(lambda cls, ctx, **params: ctx.close),
            next=lambda self: None,
        )
    with pytest.raises(TypeError, match="expression factors cannot declare expression"):
        define(
            "_MixedExpressionBuild",
            lines=("factor",),
            panel_mode="expression",
            formula_fields=("close",),
            build=classmethod(lambda cls, ctx, **params: ctx.close),
            expression=lambda self: None,
        )

    target = object()
    line = SimpleNamespace(array=[])

    class FakeFactor:
        target_datas = (target,)
        formula_fields = ("close",)

        @staticmethod
        def field_lines(alias):
            return (line,)

    first = _ExpressionContext(FakeFactor())
    foreign = _ExpressionContext(FakeFactor())
    expression = first.field("close")
    with pytest.raises(TypeError, match="different factor build context"):
        first.binary(operators.Add, expression, foreign.field("close"))
    with pytest.raises(TypeError, match="different factor build context"):
        first.indneutralize(
            expression,
            foreign.field("close"),
            level="subindustry",
        )
    with pytest.raises(TypeError, match="no line for this factor target"):
        expression._line_for(object())
    with pytest.raises(TypeError, match="factor expression"):
        first.result_lines(line)
    with pytest.raises(ResearchConfigError, match="did not declare formula field"):
        first.field("volume")
    with pytest.raises(TypeError, match="converted to bool"):
        bool(expression)
    with pytest.raises(TypeError, match="converted to bool"):
        _ = expression and expression
    with pytest.raises(TypeError, match="converted to bool"):
        _ = expression or expression
    first._close()
    with pytest.raises(RuntimeError, match="closed"):
        first.field("close")


@pytest.mark.parametrize("method", ("sma", "roc", "highest", "lowest"))
@pytest.mark.parametrize("period", (0, -1, True, 1.0))
def test_expression_rolling_methods_require_a_positive_non_bool_integer(method, period):
    target = object()
    line = SimpleNamespace(array=[])

    class FakeFactor:
        target_datas = (target,)
        formula_fields = ("close",)

        @staticmethod
        def field_lines(alias):
            return (line,)

    context = _ExpressionContext(FakeFactor())
    expression = context.field("close")

    with pytest.raises(ValueError, match="positive integer"):
        getattr(context, method)(expression, period)
    assert context.nodes == {}


def test_alpha_registry_build_mode_is_companion_lookup_without_changing_native_registry(
    monkeypatch,
):
    assert get_alpha(3) is Alpha003Native is ALPHA_REGISTRY[3]
    assert get_alpha(3, mode="build") is Alpha003Build
    assert list_alphas() == tuple(range(1, 102))
    native_four = ALPHA_REGISTRY[4]
    module = __import__(native_four.__module__, fromlist=["*"])
    companion_name = native_four.__name__[:-6] + "Build"
    monkeypatch.delattr(module, companion_name, raising=False)
    with pytest.raises(NotImplementedError, match="Alpha4 build"):
        get_alpha(4, mode="build")
    with pytest.raises(ValueError, match="mode"):
        get_alpha(3, mode="dsl")
    with pytest.raises(KeyError, match="not registered"):
        get_alpha(102, mode="build")


def test_expression_class_does_not_require_a_duplicate_required_fields_declaration():
    class FormulaFieldsOnly(FactorIndicator):
        lines = ("factor",)
        panel_mode = "expression"
        formula_fields = ("close",)
        lookback_h = 0

        @classmethod
        def build(cls, ctx, **params):
            return ctx.close

    assert FormulaFieldsOnly._validate_factor_declaration() == "expression"
    with pytest.raises(DatasetError, match="missing explicit field bindings"):
        FactorSpec(name="missing", indicator=FormulaFieldsOnly, panel_line="factor")


def test_factor_spec_rejects_missing_and_non_classmethod_build_declarations(monkeypatch):
    with monkeypatch.context() as patch:
        patch.delattr(_WhereArithmeticBuild, "build")
        with pytest.raises(ResearchConfigError, match="build\(\) as a classmethod"):
            FactorSpec(
                name="missing_build",
                indicator=_WhereArithmeticBuild,
                panel_line="factor",
                field_bindings={"close": "feed:target:close"},
            )
    with monkeypatch.context() as patch:
        patch.setattr(_WhereArithmeticBuild, "build", lambda cls, ctx, **params: ctx.close)
        with pytest.raises(ResearchConfigError, match="build\(\) as a classmethod"):
            FactorSpec(
                name="function_build",
                indicator=_WhereArithmeticBuild,
                panel_line="factor",
                field_bindings={"close": "feed:target:close"},
            )
