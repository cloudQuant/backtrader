"""Contracts for selecting native/build execution per FactorIndicator binding."""

from __future__ import annotations

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.errors import ResearchConfigError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.specs import FactorSpec
from tests.test_utils.alpha101_native_harness import make_positive_fixture, make_research_spec
from tests.unit.test_factor_research_representatives import _research_feed

_EVENTS = {
    "native_init": [],
    "native_next": [],
    "native_prenext": [],
    "native_nextstart": [],
    "native_preonce": [],
    "native_oncestart": [],
    "native_once": [],
    "build": [],
    "build_only": [],
    "resolved_params": [],
}


class _NativeParent(FactorIndicator):
    """Native implementation inherited by a dual-mode child class."""

    lines = ("factor",)
    params = (("scale", 1.0),)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        _EVENTS["native_init"].append(self)
        super().__init__()

    def next(self):
        _EVENTS["native_next"].append(self)
        for data, close in zip(self.target_datas, self.field_lines("close")):
            self.outputs[data].factor[0] = close[0] * self.p.scale

    def prenext(self):
        _EVENTS["native_prenext"].append(self)
        self.next()

    def nextstart(self):
        _EVENTS["native_nextstart"].append(self)
        self.next()

    def preonce(self, start, end):
        _EVENTS["native_preonce"].append(self)
        return self.preonce_via_prenext(start, end)

    def oncestart(self, start, end):
        _EVENTS["native_oncestart"].append(self)
        return self.oncestart_via_nextstart(start, end)

    def once(self, start, end):
        _EVENTS["native_once"].append(self)
        return self.once_via_next(start, end)


class _DualMode(_NativeParent):
    """A dual-mode class whose legacy declaration intentionally disagrees."""

    panel_mode = "expression"

    @classmethod
    def build(cls, ctx, scale=1.0, **params):
        _EVENTS["build"].append((cls, ctx, scale))
        return ctx.close * scale


class _BuildOnly(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    @classmethod
    def build(cls, ctx, **params):
        _EVENTS["build_only"].append((cls, ctx))
        return ctx.close


class _InheritedBuildOnly(_BuildOnly):
    """Build-only behavior inherited without declaring native lifecycle hooks."""


class _BuildParamsParent(FactorIndicator):
    lines = ("factor",)
    params = (("period", 3),)
    formula_fields = ("close",)

    @classmethod
    def lookback_h(cls, period=3):
        return period - 1

    @classmethod
    def build(cls, ctx, period=3):
        _EVENTS["resolved_params"].append((cls, period))
        return ctx.close * period


class _InheritedBuildParams(_BuildParamsParent):
    """Use the parent's real factor parameter defaults and build method."""


def _clear_events():
    for events in _EVENTS.values():
        events.clear()


def _factor_spec(name, *, mode=None, scale=1.0):
    params = {"scale": scale} if scale != 1.0 else {}
    return FactorSpec(
        name=name,
        indicator=_DualMode,
        panel_line="factor",
        params=params,
        field_bindings={"close": "feed:target:close"},
        mode=mode,
    )


def _run_factor_specs(frames, factors, *, runonce, groups=None):
    research = make_research_spec(frames, groups=groups)
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for asset, frame in frames.items():
        cerebro.adddata(_research_feed(frame, research, asset), name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    return cerebro.run(runonce=runonce)[0]


def _short_fixture(periods=8):
    return {asset: frame.iloc[:periods].copy() for asset, frame in make_positive_fixture().items()}


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_factor_capabilities_default_selection_and_metadata_are_per_spec(runonce):
    assert _NativeParent._resolve_factor_mode() == "native"
    assert _BuildOnly._resolve_factor_mode() == "build"
    assert _InheritedBuildOnly._resolve_factor_mode() == "build"
    assert _DualMode._resolve_factor_mode() == "native"
    assert _DualMode._resolve_factor_mode("build") == "build"

    native = FactorSpec(
        name="native",
        indicator=_DualMode,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
    )
    build = FactorSpec(
        name="build",
        indicator=_DualMode,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="build",
    )
    assert native.mode == "native"
    assert build.mode == "build"
    assert native.to_metadata()["mode"] == "native"
    assert native.to_metadata()["panel_mode"] == "next"
    assert build.to_metadata()["mode"] == "build"
    assert build.to_metadata()["panel_mode"] == "expression"
    mapped = FactorSpec.from_mapping(
        "mapped",
        {
            "indicator": _DualMode,
            "panel_line": "factor",
            "field_bindings": {"close": "feed:target:close"},
            "mode": "build",
        },
    )
    assert mapped.mode == "build"

    with pytest.raises(ResearchConfigError, match="mode"):
        FactorSpec(
            name="bad_mode",
            indicator=_DualMode,
            panel_line="factor",
            field_bindings={"close": "feed:target:close"},
            mode="dsl",
        )
    with pytest.raises(ResearchConfigError, match="no classmethod build"):
        FactorSpec(
            name="native_only_build",
            indicator=_NativeParent,
            panel_line="factor",
            field_bindings={"close": "feed:target:close"},
            mode="build",
        )
    with pytest.raises(ResearchConfigError, match="no native next"):
        FactorSpec(
            name="build_only_native",
            indicator=_BuildOnly,
            panel_line="factor",
            field_bindings={"close": "feed:target:close"},
            mode="native",
        )
    with pytest.raises(ResearchConfigError, match="params\['mode'\]"):
        FactorSpec(
            name="mode_in_params",
            indicator=_DualMode,
            panel_line="factor",
            params={"mode": "build"},
            field_bindings={"close": "feed:target:close"},
        )
    with pytest.raises(TypeError, match="parameter 'mode' is reserved"):
        type(
            "_ModeAsFactorParam",
            (FactorIndicator,),
            {
                "__module__": __name__,
                "lines": ("factor",),
                "params": (("mode", "build"),),
                "formula_fields": ("close",),
                "build": classmethod(lambda cls, ctx, **params: ctx.close),
            },
        )

    _clear_events()
    frames = _short_fixture()
    strategy = _run_factor_specs(frames, {"native": native}, runonce=runonce)
    factor = strategy.factor_instances["native"]
    assert factor.factor_mode == "native"
    assert not hasattr(factor, "_expression_context")
    assert len(_EVENTS["native_init"]) == 1
    assert _EVENTS["build"] == []

    for index, build_class in enumerate((_BuildOnly, _InheritedBuildOnly)):
        _EVENTS["build_only"].clear()
        name = "build_only_%d" % index
        spec = FactorSpec(
            name=name,
            indicator=build_class,
            panel_line="factor",
            field_bindings={"close": "feed:target:close"},
        )
        assert spec.mode == "build"
        strategy = _run_factor_specs(frames, {name: spec}, runonce=runonce)
        factor = strategy.factor_instances[name]
        assert factor.factor_mode == "build"
        assert not hasattr(factor, "_factor_mode")
        assert len(_EVENTS["build_only"]) == 1
        assert _EVENTS["build_only"][0][0].__mro__[1] is build_class
        for asset, data in zip(frames, factor.target_datas):
            expected = frames[asset]["close"].to_numpy(dtype="float64")
            assert list(factor.outputs[data].factor.array[: len(expected)]) == pytest.approx(
                list(expected)
            )
        with pytest.raises(AttributeError):
            factor.factor_mode = "native"


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_one_class_mixes_modes_params_groups_and_isolated_build_graphs(runonce):
    _clear_events()
    frames = _short_fixture()
    assets = tuple(frames)
    groups = {
        asset: ("left" if index < len(assets) // 2 else "right")
        for index, asset in enumerate(assets)
    }
    specs = {
        "native": _factor_spec("native", mode="native", scale=2.0),
        "build": _factor_spec("build", mode="build", scale=3.0),
        "build_other": _factor_spec("build_other", mode="build", scale=5.0),
    }
    strategy = _run_factor_specs(frames, specs, runonce=runonce, groups=groups)

    native_instances = strategy.factor_instances["native"].group_instances
    build_instances = strategy.factor_instances["build"].group_instances
    other_instances = strategy.factor_instances["build_other"].group_instances
    assert (
        set(native_instances) == set(build_instances) == set(other_instances) == {"left", "right"}
    )
    all_instances = [
        *native_instances.values(),
        *build_instances.values(),
        *other_instances.values(),
    ]
    assert len({id(instance) for instance in all_instances}) == 6
    assert {instance.factor_mode for instance in native_instances.values()} == {"native"}
    assert {instance.factor_mode for instance in build_instances.values()} == {"build"}
    assert {instance.factor_mode for instance in other_instances.values()} == {"build"}

    build_instances_all = (*build_instances.values(), *other_instances.values())
    contexts = [instance._expression_context for instance in build_instances_all]
    assert len(contexts) == 4
    assert len({id(context) for context in contexts}) == 4
    assert all(context._closed for context in contexts)
    assert len({id(instance._nodes) for instance in build_instances_all}) == 4
    assert all(
        not hasattr(instance, "_expression_context") for instance in native_instances.values()
    )

    assert len(_EVENTS["native_init"]) == 2
    assert len(_EVENTS["build"]) == 4
    if runonce:
        assert _EVENTS["native_once"]
    else:
        assert _EVENTS["native_next"]
    assert all(instance.factor_mode == "native" for instance in _EVENTS["native_init"])
    assert all(cls.__mro__[1] is _DualMode for cls, _context, _scale in _EVENTS["build"])
    for event_name in (
        "native_next",
        "native_prenext",
        "native_nextstart",
        "native_preonce",
        "native_oncestart",
        "native_once",
    ):
        assert all(instance.factor_mode == "native" for instance in _EVENTS[event_name])

    for asset in assets:
        factor_native = native_instances[groups[asset]]
        factor_build = build_instances[groups[asset]]
        factor_other = other_instances[groups[asset]]
        data = next(data for data in factor_native.target_datas if data._name == asset)
        native_values = factor_native.outputs[data].factor.array
        build_data = next(data for data in factor_build.target_datas if data._name == asset)
        other_data = next(data for data in factor_other.target_datas if data._name == asset)
        build_values = factor_build.outputs[build_data].factor.array
        other_values = factor_other.outputs[other_data].factor.array
        source = frames[asset]["close"].to_numpy(dtype="float64")
        assert list(native_values[: len(source)]) == pytest.approx(list(2.0 * source))
        assert list(build_values[: len(source)]) == pytest.approx(list(3.0 * source))
        assert list(other_values[: len(source)]) == pytest.approx(list(5.0 * source))


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_build_receives_only_resolved_factor_parameters_and_rejects_unknowns(runonce):
    frames = _short_fixture(periods=5)
    research = make_research_spec(frames)
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for asset, frame in frames.items():
        cerebro.adddata(_research_feed(frame, research, asset), name=asset)
    _EVENTS["resolved_params"].clear()
    default_spec = FactorSpec(
        name="default",
        indicator=_InheritedBuildParams,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
    )
    override_spec = FactorSpec(
        name="override",
        indicator=_InheritedBuildParams,
        panel_line="factor",
        params={"period": 5},
        field_bindings={"close": "feed:target:close"},
        mode="build",
    )
    assert default_spec.lookback_h == 2
    assert override_spec.lookback_h == 4
    assert default_spec.to_metadata()["lookback_h"] == 2
    assert override_spec.to_metadata()["lookback_h"] == 4
    cerebro.addstrategy(
        FactorStrategy,
        research=research,
        factors={"default": default_spec, "override": override_spec},
    )
    strategy = cerebro.run(runonce=runonce)[0]
    default_factor = strategy.factor_instances["default"]
    override_factor = strategy.factor_instances["override"]
    assert default_factor.p.period == 3
    assert override_factor.p.period == 5
    assert default_factor.factor_mode == override_factor.factor_mode == "build"
    assert default_factor._minperiod == 3
    assert override_factor._minperiod == 5
    assert default_factor._factor_runtime["factor_params"] == {"period": 3}
    assert override_factor._factor_runtime["factor_params"] == {"period": 5}
    assert len(_EVENTS["resolved_params"]) == 2
    assert {period for _cls, period in _EVENTS["resolved_params"]} == {3, 5}
    for asset, default_data, override_data in zip(
        frames, default_factor.target_datas, override_factor.target_datas
    ):
        close = frames[asset]["close"].to_numpy(dtype="float64")
        assert list(
            default_factor.outputs[default_data].factor.array[: len(close)]
        ) == pytest.approx(list(close * 3))
        assert list(
            override_factor.outputs[override_data].factor.array[: len(close)]
        ) == pytest.approx(list(close * 5))

    with pytest.raises(ResearchConfigError, match="unsupported factor params"):
        FactorSpec(
            name="unknown_parameter",
            indicator=_InheritedBuildParams,
            panel_line="factor",
            params={"movav": object()},
            field_bindings={"close": "feed:target:close"},
        )
    data = _research_feed(next(iter(frames.values())), research, "bind-target")
    with pytest.raises(ResearchConfigError, match="unsupported factor params"):
        _InheritedBuildParams.bind(data, mode="build", movav=object())


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_bound_mode_isolation_survives_multiple_runs_and_direct_bind(runonce):
    _clear_events()
    frames = _short_fixture(6)
    first = _run_factor_specs(
        frames,
        {"native": _factor_spec("native", mode="native")},
        runonce=runonce,
    ).factor_instances["native"]
    first_build = _run_factor_specs(
        frames,
        {"build": _factor_spec("build", mode="build")},
        runonce=runonce,
    ).factor_instances["build"]
    second_build = _run_factor_specs(
        frames,
        {"build": _factor_spec("build", mode="build")},
        runonce=runonce,
    ).factor_instances["build"]
    assert first.factor_mode == "native"
    assert first_build.factor_mode == second_build.factor_mode == "build"
    assert first_build is not second_build
    assert first_build._expression_context is not second_build._expression_context

    class _DirectBindStrategy(bt.Strategy):
        def __init__(self):
            self.native = _DualMode.bind(self.data, mode="native", scale=2.0)
            self.built = _DualMode.bind(self.data, mode="build", scale=3.0)

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    first_asset = next(iter(frames))
    cerebro.adddata(bt.feeds.PandasData(dataname=frames[first_asset]), name=first_asset)
    cerebro.addstrategy(_DirectBindStrategy)
    strategy = cerebro.run(runonce=runonce)[0]
    assert strategy.native.factor_mode == "native"
    assert strategy.built.factor_mode == "build"
    assert hasattr(strategy.built, "_expression_context")
    assert not hasattr(strategy.native, "_expression_context")
    with pytest.raises(ValueError, match="factor mode"):
        _DualMode._resolve_factor_mode("python")


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_ordinary_indicator_base_keeps_its_existing_run_modes(runonce):
    frame = pd.DataFrame(
        {
            "open": [1.0, 2.0, 3.0],
            "high": [2.0, 3.0, 4.0],
            "low": [0.0, 1.0, 2.0],
            "close": [1.0, 2.0, 3.0],
            "volume": [10.0, 20.0, 30.0],
        },
        index=pd.date_range("2025-01-01", periods=3, freq="D"),
    )

    class _SmaStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=2)

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="AAA")
    cerebro.addstrategy(_SmaStrategy)
    strategy = cerebro.run(runonce=runonce)[0]
    assert math.isnan(strategy.sma.lines.sma.array[0])
    assert list(strategy.sma.lines.sma.array[1:3]) == pytest.approx([1.5, 2.5])
