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
from tests.test_utils.alpha101_trace_validation import validate_factor_trace
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


def _run_custom_expression(factor_class, frames, *, runonce=True, factor_params=None):
    research = make_research_spec(frames)
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


def test_alpha_registry_build_mode_is_companion_lookup_without_changing_native_registry():
    assert get_alpha(3) is Alpha003Native is ALPHA_REGISTRY[3]
    assert get_alpha(3, mode="build") is Alpha003Build
    assert list_alphas() == tuple(range(1, 102))
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
