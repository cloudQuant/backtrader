"""Synthetic witnesses for example factor once kernels and guarded fallbacks."""

import importlib.util
from pathlib import Path
import sys

import backtrader as bt
import numpy as np
import pandas as pd
import pytest

from backtrader.research import FactorSpec, ResearchSpec, align_to_grid
from backtrader.research.alpha101.alpha003 import Alpha003Native
from backtrader.strategies.factor_strategy import FactorStrategy
from tests.test_utils.alpha101_trace_validation import compare_factor_graphs

_ROOT = Path(__file__).resolve().parents[2] / "examples/backtest"


def _module(relative, name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_SINGLE = _module("025_factor_single/close_ma_factor_strategy.py", "iter61_fast_single")
_MULTI = _module("026_factor_multi/multi_factor_strategy.py", "iter61_fast_multi")


def _run(factor_class, *, name="factor", params=None, mode="native", runonce=True, feed_hook=None):
    times = pd.date_range("2024-01-01 16:00", periods=40, freq="B", tz="UTC", name="close_time")
    assets = ("A", "B", "C")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[0],
        end=times[-1],
        targets=assets,
        groups=dict.fromkeys(assets, "all"),
        source_timezone="UTC",
        snapshot_id="synthetic-fastpaths",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1session",
        feed_time_kind="close_time",
    )
    factor = FactorSpec(
        name=name,
        indicator=factor_class,
        mode=mode,
        panel_line="factor",
        params=params or {},
        field_bindings={field: "feed:target:" + field for field in factor_class.formula_fields},
    )
    cerebro = bt.Cerebro(stdstats=False)
    for asset_index, asset in enumerate(assets):
        rows = []
        for i in range(len(times)):
            open_value = 10 + ((i * (asset_index + 2) + asset_index) % 7) * 0.3
            close = open_value + (i % 3 - 1) * 0.05
            rows.append(
                (
                    open_value,
                    max(open_value, close) + 0.1,
                    min(open_value, close) - 0.1,
                    close,
                    1000 + ((i * (asset_index + 3) + asset_index) % 11) * 10,
                )
            )
        frame = pd.DataFrame(rows, index=times, columns=("open", "high", "low", "close", "volume"))
        if asset == "B":
            frame = frame.drop(index=times[20])
        feed = align_to_grid(frame, research, asset).feed
        if feed_hook:
            original = getattr(feed, feed_hook)

            def wrapped(*args, _original=original, **kwargs):
                return _original(*args, **kwargs)

            setattr(feed, feed_hook, wrapped)
        cerebro.adddata(feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors={name: factor})
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    return strategy, strategy._factor_instances_by_name[name][0]


def _graphs_equal(left, right):
    report = compare_factor_graphs(left, right, 3)
    assert report["equal"], report["failures"]
    assert report["node_value_cells"] > 0 and report["node_reason_cells"] > 0


@pytest.mark.parametrize(
    "factor_class,params",
    [
        (_SINGLE.CloseMAFactor, {"period": 5}),
        (_MULTI.CloseMAFactor, {"period": 5}),
        (_MULTI.ROCFactor, {"period": 5}),
        (_MULTI.KDJFactor, {"period": 5, "period_dfast": 2, "period_dslow": 3}),
    ],
    ids=["025-close-ma", "026-close-ma", "026-roc", "026-kdj"],
)
@pytest.mark.parametrize("mode", ["native", "build"])
@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_example_once_paths_and_subclass_fallback(factor_class, params, mode, runonce):
    class CustomFactor(factor_class):
        def nextstart(self):
            return super().nextstart()

    reference, root = _run(factor_class, params=params, mode=mode, runonce=runonce)
    fallback, custom = _run(CustomFactor, params=params, mode=mode, runonce=runonce)
    diag = root.lifecycle_diagnostics
    custom_diag = custom.lifecycle_diagnostics
    assert diag["coverage_matches"] and custom_diag["coverage_matches"]
    if mode == "native" and runonce:
        assert diag["once_ranges"] and diag["next_count"] == 0
        assert not custom_diag["once_ranges"]
        assert custom_diag["next_count"] == custom_diag["grid_count"]
    else:
        assert not diag["once_ranges"] and not custom_diag["once_ranges"]
    np.testing.assert_allclose(
        reference.get_panel().factors.to_numpy(),
        fallback.get_panel().factors.to_numpy(),
        equal_nan=True,
    )


@pytest.mark.parametrize("hook", ["advance", "_tick_nullify", "_tick_fill"])
def test_025_feed_hook_forces_fallback(hook):
    expected, _ = _run(_SINGLE.CloseMAFactor, params={"period": 5})
    actual, root = _run(_SINGLE.CloseMAFactor, params={"period": 5}, feed_hook=hook)
    diag = root.lifecycle_diagnostics
    assert diag["coverage_matches"] and not diag["once_ranges"]
    assert diag["next_count"] == diag["grid_count"]
    np.testing.assert_allclose(
        expected.get_panel().factors.to_numpy(),
        actual.get_panel().factors.to_numpy(),
        equal_nan=True,
    )


def test_alpha003_kernels_and_four_lanes(monkeypatch):
    from backtrader.research import operators

    calls = []
    original = operators._run_panel_once

    def observe(instance, optimized_class, plan, start, end):
        calls.append((optimized_class, start, end))
        return original(instance, optimized_class, plan, start, end)

    monkeypatch.setattr(operators, "_run_panel_once", observe)
    roots = {}
    for mode in ("native", "build"):
        for runonce in (True, False):
            calls.clear()
            _, roots[mode, runonce] = _run(
                Alpha003Native, name="alpha003", mode=mode, runonce=runonce
            )
            expected = set()
            if runonce:
                expected.add(operators.CrossSectionalRank)
                if mode == "native":
                    expected.update((operators._RollingCorrelationPanel, operators._MultiplyPanel))
            assert {item[0] for item in calls} == expected
            assert all(start < end for _, start, end in calls)
    for root in roots.values():
        _graphs_equal(roots["native", True], root)


@pytest.mark.parametrize(
    "hook", ["line-reader", "line-setter", "feed-binding", "output-binding", "feed-buflen"]
)
def test_alpha003_panel_hooks_fall_back_with_equal_values_and_reasons(monkeypatch, hook):
    from backtrader.linebuffer import LineBuffer
    from backtrader.research import operators

    _, reference = _run(Alpha003Native, name="alpha003", runonce=False)
    calls, hook_calls = [], []
    original_kernel = operators._run_panel_once

    def observe_kernel(instance, optimized_class, plan, start, end):
        calls.append(optimized_class)
        return original_kernel(instance, optimized_class, plan, start, end)

    monkeypatch.setattr(operators, "_run_panel_once", observe_kernel)
    if hook == "line-reader":
        original_reader = LineBuffer.__getitem__

        def reader(self, ago=0):
            hook_calls.append(ago)
            return original_reader(self, ago)

        monkeypatch.setattr(LineBuffer, "__getitem__", reader)
    elif hook == "line-setter":
        original_setter = LineBuffer.__setitem__

        def setter(self, ago, value):
            hook_calls.append(ago)
            return original_setter(self, ago, value)

        monkeypatch.setattr(LineBuffer, "__setitem__", setter)
    elif hook in ("feed-binding", "feed-buflen"):
        original_align = align_to_grid

        class ObservedBinding(LineBuffer):
            def __setitem__(self, ago, value):
                hook_calls.append(ago)
                return super().__setitem__(ago, value)

        def custom_align(*args, **kwargs):
            aligned = original_align(*args, **kwargs)
            if hook == "feed-binding":
                aligned.feed.close.addbinding(ObservedBinding())
            else:
                original_buflen = aligned.feed.buflen

                def buflen():
                    hook_calls.append(True)
                    return original_buflen()

                aligned.feed.buflen = buflen
            return aligned

        monkeypatch.setitem(globals(), "align_to_grid", custom_align)
    else:

        class ObservedBinding(LineBuffer):
            def __setitem__(self, ago, value):
                hook_calls.append(ago)
                return super().__setitem__(ago, value)

        original_plan = operators._panel_once_plan

        def custom_plan(instance, optimized_class, start, end):
            for target in instance._factor_target_datas:
                output = instance.outputs[target]
                output.value.addbinding(ObservedBinding())
                output.reason.addbinding(ObservedBinding())
            return original_plan(instance, optimized_class, start, end)

        monkeypatch.setattr(operators, "_panel_once_plan", custom_plan)

    _, fallback = _run(Alpha003Native, name="alpha003")
    assert not calls and hook_calls
    diagnostics = fallback.lifecycle_diagnostics
    assert diagnostics["coverage_matches"] and not diagnostics["once_ranges"]
    assert diagnostics["next_count"] == diagnostics["grid_count"]
    for node in (
        fallback._nodes["rank_open"],
        fallback._nodes["rank_volume"],
        *fallback._physical_nodes,
    ):
        assert node.lifecycle_diagnostics["coverage_matches"]
        assert not node.lifecycle_diagnostics["once_ranges"]
    _graphs_equal(reference, fallback)


@pytest.mark.parametrize("hook", ["advance", "_tick_nullify", "_tick_fill"])
def test_alpha003_feed_hook_fallback_preserves_graph(monkeypatch, hook):
    from backtrader.research import operators

    _, reference = _run(Alpha003Native, name="alpha003", runonce=False)
    calls = []
    original = operators._run_panel_once

    def observe(instance, optimized_class, plan, start, end):
        calls.append(optimized_class)
        return original(instance, optimized_class, plan, start, end)

    monkeypatch.setattr(operators, "_run_panel_once", observe)
    _, fallback = _run(Alpha003Native, name="alpha003", feed_hook=hook)
    assert not calls
    for node in (
        fallback._nodes["rank_open"],
        fallback._nodes["rank_volume"],
        *fallback._physical_nodes,
    ):
        assert node.lifecycle_diagnostics["coverage_matches"]
        assert not node.lifecycle_diagnostics["once_ranges"]
    _graphs_equal(reference, fallback)


def test_alpha003_custom_apply_falls_back(monkeypatch):
    from backtrader.research import operators

    _, reference = _run(Alpha003Native, name="alpha003", runonce=False)
    calls, applied = [], []
    original_kernel, original_apply = operators._run_panel_once, operators.Multiply._apply

    def observe(instance, optimized_class, plan, start, end):
        calls.append(optimized_class)
        return original_kernel(instance, optimized_class, plan, start, end)

    def apply(left, right):
        applied.append(True)
        return original_apply(left, right)

    monkeypatch.setattr(operators, "_run_panel_once", observe)
    monkeypatch.setattr(operators.Multiply, "_apply", staticmethod(apply))
    _, fallback = _run(Alpha003Native, name="alpha003")
    assert calls and operators._MultiplyPanel not in calls and applied
    node = next(
        node for node in fallback._physical_nodes if isinstance(node, operators._MultiplyPanel)
    )
    assert (
        node.lifecycle_diagnostics["coverage_matches"]
        and not node.lifecycle_diagnostics["once_ranges"]
    )
    _graphs_equal(reference, fallback)


def test_alpha003_once_strict_error_context(monkeypatch):
    from backtrader.errors import FactorComputationError
    from backtrader.research import operators, strict

    observed = []
    original_kernel, fail_computation = operators._run_panel_once, strict.fail_computation

    def inject(instance, optimized_class, plan, start, end):
        if optimized_class is operators._RollingCorrelationPanel:
            target, source = plan.targets[2], plan.values[2][0]
            expected_date = float(target.datetime.array[start])
            original_window = operators._panel_once_window

            def fail_window(values, index, period):
                if values[0] is source:
                    raise ArithmeticError("synthetic failure")
                return original_window(values, index, period)

            def observe_failure(context, error, phase, operation=None):
                if str(error) == "synthetic failure":
                    observed.append(
                        (operation is target, float(operation.datetime[0]), expected_date, phase)
                    )
                return fail_computation(context, error, phase, operation=operation)

            monkeypatch.setattr(operators, "_panel_once_window", fail_window)
            monkeypatch.setattr(strict, "fail_computation", observe_failure)
        return original_kernel(instance, optimized_class, plan, start, end)

    monkeypatch.setattr(operators, "_run_panel_once", inject)
    with pytest.raises(FactorComputationError) as caught:
        _run(Alpha003Native, name="alpha003")
    assert observed and observed[0][0] and observed[0][1] == observed[0][2]
    assert caught.value.factor == "alpha003" and caught.value.asset == "C"
    assert caught.value.phase == observed[0][3] == "once_via_next"
    assert isinstance(caught.value.__cause__, ArithmeticError)


@pytest.mark.parametrize("mode", ["native", "build"])
@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_026_safe_rsv_child_once_kernel(monkeypatch, mode, runonce):
    calls = []
    original = _MULTI._SafeRSV._once_range

    def observe(instance, start, end):
        calls.append((instance, start, end))
        return original(instance, start, end)

    monkeypatch.setattr(_MULTI._SafeRSV, "_once_range", observe)
    _, factor = _run(
        _MULTI.KDJFactor,
        params={"period": 5, "period_dfast": 2, "period_dslow": 3},
        mode=mode,
        runonce=runonce,
    )
    if mode == "native" and runonce:
        children = tuple(factor._rsv.values())
        assert len(children) == 3
        assert {id(instance) for instance, start, end in calls if start < end} == {
            id(child) for child in children
        }
        for child in children:
            ranges = sorted(
                (start, end) for instance, start, end in calls if instance is child and start < end
            )
            assert ranges[0][0] == 0 and ranges[-1][1] == 40
            assert all(end == next_start for (_, end), (next_start, _) in zip(ranges, ranges[1:]))
    else:
        assert not calls
