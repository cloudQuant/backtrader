"""Offline witnesses for retired factor example lifecycle and panel hook contracts."""

from collections import Counter
import math

import backtrader as bt
import numpy as np
import pytest

from backtrader.research.alpha101.alpha003 import Alpha003Native
from tests.unit import test_iter61_example_modes as examples
from tests.unit import test_iter61_factor_fastpaths as fast


def _independent_anchor(factor_class, asset_index, index=12):
    """Compute one pre-gap value from the fixture definition, without BT indicators."""
    bars = []
    for i in range(index + 1):
        opening = 10 + ((i * (asset_index + 2) + asset_index) % 7) * 0.3
        close = opening + (i % 3 - 1) * 0.05
        bars.append((max(opening, close) + 0.1, min(opening, close) - 0.1, close))
    if factor_class in (fast._SINGLE.CloseMAFactor, fast._MULTI.CloseMAFactor):
        return bars[index][2] / (sum(bar[2] for bar in bars[index - 4 : index + 1]) / 5)
    if factor_class is fast._MULTI.ROCFactor:
        return (bars[index][2] - bars[index - 5][2]) / bars[index - 5][2]

    def rsv(i):
        window = bars[i - 4 : i + 1]
        high, low = max(bar[0] for bar in window), min(bar[1] for bar in window)
        return 100.0 * (bars[i][2] - low) / (high - low)

    def k(i):
        return (rsv(i - 1) + rsv(i)) / 2.0

    current_k = k(index)
    return 3.0 * current_k - 2.0 * sum(k(i) for i in range(index - 2, index + 1)) / 3.0


@pytest.mark.parametrize(
    "factor_class,params",
    [
        (fast._SINGLE.CloseMAFactor, {"period": 5}),
        (fast._MULTI.CloseMAFactor, {"period": 5}),
        (fast._MULTI.ROCFactor, {"period": 5}),
        (fast._MULTI.KDJFactor, {"period": 5, "period_dfast": 2, "period_dslow": 3}),
    ],
    ids=["025-close-ma", "026-close-ma", "026-roc", "026-kdj"],
)
def test_class_next_replacement_forces_fallback_and_is_called(monkeypatch, factor_class, params):
    reference, baseline = fast._run(factor_class, params=params)
    assert baseline.lifecycle_diagnostics["once_ranges"]
    original = factor_class.next
    calls = []

    def replacement(self):
        calls.append(self)
        return original(self)

    monkeypatch.setattr(factor_class, "next", replacement)
    strategy, factor = fast._run(factor_class, params=params)
    diag = factor.lifecycle_diagnostics
    assert diag["coverage_matches"] and diag["grid_matches"]
    assert diag["coverage_count"] == diag["grid_count"] == 40
    assert not diag["once_ranges"]
    assert diag["next_count"] == diag["grid_count"]
    assert len(calls) == 40 and all(instance is factor for instance in calls)
    np.testing.assert_array_equal(
        reference.get_panel().factors.to_numpy(), strategy.get_panel().factors.to_numpy()
    )
    for asset_index, asset in enumerate(("A", "B", "C")):
        values = strategy.get_panel().factors.xs(asset, level="asset")["factor"].to_numpy()
        assert np.isfinite(values).any(), asset
        assert math.isfinite(values[12])
        assert values[12] == pytest.approx(
            _independent_anchor(factor_class, asset_index), rel=1e-12
        )


@pytest.mark.parametrize("key", ["025", "026"])
@pytest.mark.parametrize("mode", ["native", "build"])
@pytest.mark.parametrize("runonce", [True, False], ids=["once", "next"])
def test_runner_actual_factor_classes_and_lifecycle(tmp_path, monkeypatch, key, mode, runonce):
    runner = examples.load_runner(key)
    monkeypatch.syspath_prepend(str(examples.RUNNERS[key].parent))
    data = tmp_path / "data"
    _, dates = examples.write_panel(data)
    cfg = examples.config_for(runner, data)
    cfg["factor_mode"] = mode
    panel = runner.load_daily_panel(cfg["data"])
    strategy, collected, broker = runner._run_native_collection(cfg, panel, not runonce)
    classes = runner._factor_classes(mode)
    assert classes == runner._factor_classes("native") == runner._factor_classes("build")
    assert set(strategy._factor_instances_by_name) == set(classes)
    for name, cls in classes.items():
        spec = strategy._factor_specs_by_name[name]
        instances = strategy._factor_instances_by_name[name]
        assert spec.indicator is cls and spec.mode == mode
        assert len(instances) == 1
        instance = instances[0]
        assert isinstance(instance, cls) and instance.factor_mode == mode
        if mode == "build":
            assert instance._expression_context._closed is True
        else:
            assert not hasattr(instance, "_expression_context")
        diag = instance.lifecycle_diagnostics
        assert diag["coverage_matches"]
        assert diag["coverage_count"] == diag["grid_count"] == len(dates)
        if mode == "native" and runonce:
            assert diag["once_ranges"] and diag["once_count"] == len(dates)
            assert diag["next_count"] == diag["call_count"] == 0
        else:
            assert not diag["once_ranges"]
            assert diag["grid_matches"]
            assert diag["next_count"] == diag["call_count"] == len(dates)
    assert set(collected.factors.columns) == set(classes)
    assert broker.submit_count == broker.cancel_count == 0


def test_alpha003_panel_kernels_feed_states_and_each_node_coverage(monkeypatch):
    from backtrader.research import operators

    observed = []
    original = operators._run_panel_once

    def observe(instance, optimized_class, plan, start, end):
        result = original(instance, optimized_class, plan, start, end)
        observed.append(
            (
                optimized_class,
                start,
                end,
                tuple((t.datetime._idx, t.datetime.lencount) for t in plan.targets),
            )
        )
        return result

    monkeypatch.setattr(operators, "_run_panel_once", observe)
    _, root = fast._run(Alpha003Native, name="alpha003", runonce=True)
    assert Counter(kind for kind, _, _, _ in observed) == Counter(
        {
            operators.CrossSectionalRank: 2,
            operators._RollingCorrelationPanel: 1,
            operators._MultiplyPanel: 1,
        }
    )
    for _, start, end, states in observed:
        assert start < end and states
        assert all(index == end - 1 and length == end for index, length in states)
    for node in (root._nodes["rank_open"], root._nodes["rank_volume"], *root._physical_nodes):
        diag = node.lifecycle_diagnostics
        assert diag["coverage_matches"] and diag["coverage_count"] == diag["grid_count"] == 40
        assert diag["once_ranges"] and diag["next_count"] < diag["grid_count"]


def test_alpha003_multiply_fallback_is_driven_for_every_bar(monkeypatch):
    from backtrader.research import operators

    _, reference = fast._run(Alpha003Native, name="alpha003", runonce=False)
    applied, evaluated, active = [], [], []
    original = operators.Multiply._apply
    original_evaluate = operators._MultiplyPanel._evaluate_target

    def custom_apply(left, right):
        assert len(active) == 1
        applied.append(active[0])
        return original(left, right)

    def observe_target(instance, asset_index):
        target = instance._factor_target_datas[asset_index]
        key = (target._name, float(target.datetime[0]))
        evaluated.append(key)
        active.append(key)
        try:
            return original_evaluate(instance, asset_index)
        finally:
            active.pop()

    monkeypatch.setattr(operators.Multiply, "_apply", staticmethod(custom_apply))
    monkeypatch.setattr(operators._MultiplyPanel, "_evaluate_target", observe_target)
    strategy, fallback = fast._run(Alpha003Native, name="alpha003", runonce=True)
    node = next(
        item for item in fallback._physical_nodes if isinstance(item, operators._MultiplyPanel)
    )
    diag = node.lifecycle_diagnostics
    assert diag["coverage_matches"] and not diag["once_ranges"]
    assert diag["coverage_count"] == diag["next_count"] == diag["grid_count"] == 40
    evaluations = Counter(evaluated)
    applications = Counter(applied)
    assert len(evaluations) == 120 and set(evaluations.values()) == {1}
    finite_keys = set()
    for asset in ("A", "B", "C"):
        assert sum(count for (name, _), count in evaluations.items() if name == asset) == 40
        values = strategy.get_panel().factors.xs(asset, level="asset")["alpha003"]
        asset_keys = {
            (asset, bt.date2num(timestamp.to_pydatetime()))
            for timestamp, value in values.items()
            if np.isfinite(value)
        }
        assert asset_keys
        finite_keys.update(asset_keys)
    assert all(key in evaluations and count == 1 for key, count in applications.items())
    assert set(applications) == finite_keys
    fast._graphs_equal(reference, fallback)


@pytest.mark.parametrize("hook", ["advance", "_tick_nullify", "_tick_fill"])
def test_alpha003_feed_hooks_are_invoked_on_fallback(monkeypatch, hook):
    from backtrader.research import operators

    _, reference = fast._run(Alpha003Native, name="alpha003", runonce=False)
    calls, kernels = [], []
    align = fast.align_to_grid
    run_panel_once = operators._run_panel_once

    def observe_kernel(instance, optimized_class, plan, start, end):
        kernels.append(optimized_class)
        return run_panel_once(instance, optimized_class, plan, start, end)

    def aligned_with_hook(*args, **kwargs):
        aligned = align(*args, **kwargs)
        original = getattr(aligned.feed, hook)

        def observed_hook(*hook_args, **hook_kwargs):
            calls.append(aligned.feed)
            return original(*hook_args, **hook_kwargs)

        setattr(aligned.feed, hook, observed_hook)
        return aligned

    monkeypatch.setattr(operators, "_run_panel_once", observe_kernel)
    monkeypatch.setattr(fast, "align_to_grid", aligned_with_hook)
    _, fallback = fast._run(Alpha003Native, name="alpha003", runonce=True)
    assert calls and len({id(feed) for feed in calls}) == 3
    assert not kernels
    for node in (
        fallback._nodes["rank_open"],
        fallback._nodes["rank_volume"],
        *fallback._physical_nodes,
    ):
        diag = node.lifecycle_diagnostics
        assert diag["coverage_matches"] and not diag["once_ranges"]
        assert diag["coverage_count"] == diag["next_count"] == diag["grid_count"] == 40
    fast._graphs_equal(reference, fallback)
