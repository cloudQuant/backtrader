"""Focused contracts for Alpha003's ordinary-Cerebro panel once kernels."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from tests.test_utils.alpha101_trace_validation import compare_factor_graphs
from tests.unit.test_factor_research_examples import (
    THIRD_RUNNER,
    _example_config,
    _load_module,
    _write_daily_panel,
)


def _alpha003_run(tmp_path: Path, runner: Any, *, mode: str, runonce: bool):
    root = tmp_path / "a_stocks"
    _write_daily_panel(root, symbol_count=5, day_count=40)
    manifest_path = root / "_metadata" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    columns = ("trade_time", "open", "high", "low", "close", "volume", "amount")
    for entry in manifest["output"]["symbols"]:
        path = root / entry["file"]
        pd.read_csv(path).loc[:, list(columns)].to_csv(path, index=False)
        raw = path.read_bytes()
        entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    config = _example_config(runner, root)
    config["factor_mode"] = mode
    panel = runner.load_daily_panel(config["data"])
    strategy, collected, indicator = runner._run_factor(
        config, panel, consume_source_frames=False, runonce=runonce
    )
    factor = strategy._factor_instances_by_name[runner.FACTOR_NAME][0]
    return strategy, collected, indicator, factor


def _assert_graphs_equal(left: Any, right: Any) -> None:
    report = compare_factor_graphs(left, right, 3)
    assert report["equal"], report["failures"]
    assert report["node_count_left"] == report["node_count_right"]
    assert report["node_value_cells"] > 0
    assert report["node_reason_cells"] > 0


def test_alpha003_panel_once_hits_all_three_kernels_and_matches_four_lanes(
    tmp_path, monkeypatch
):
    from backtrader.research import operators

    runner = _load_module(THIRD_RUNNER, "alpha003_panel_once_contract")
    calls = []
    final_feed_states = []
    run_panel_once = operators._run_panel_once

    def observe(instance, optimized_class, plan, start, end):
        calls.append((optimized_class, start, end))
        result = run_panel_once(instance, optimized_class, plan, start, end)
        if start < end:
            final_feed_states.append(
                tuple((target.datetime._idx, target.datetime.lencount) for target in plan.targets)
            )
        return result

    monkeypatch.setattr(operators, "_run_panel_once", observe)
    outcomes = {}
    for mode in ("native", "build"):
        for runonce in (True, False):
            outcomes[(mode, runonce)] = _alpha003_run(
                tmp_path / (mode + ("-once" if runonce else "-next")),
                runner,
                mode=mode,
                runonce=runonce,
            )

    native_once = outcomes[("native", True)][3]
    native_next = outcomes[("native", False)][3]
    build_once = outcomes[("build", True)][3]
    build_next = outcomes[("build", False)][3]
    _assert_graphs_equal(native_once, native_next)
    _assert_graphs_equal(build_once, build_next)
    _assert_graphs_equal(native_once, build_once)
    _assert_graphs_equal(native_next, build_next)

    assert Counter(node_type for node_type, _, _ in calls) == Counter(
        {
            operators.CrossSectionalRank: 4,
            operators._RollingCorrelationPanel: 1,
            operators._MultiplyPanel: 1,
        }
    )
    assert all(start < end for _, start, end in calls)
    assert final_feed_states
    assert all(
        all(index == end - 1 and length == end for index, length in states)
        for states, (_, _, end) in zip(final_feed_states, calls)
    )

    native_lifecycle = native_once.lifecycle_diagnostics
    assert native_lifecycle["grid_matches"]
    assert native_lifecycle["coverage_matches"]
    assert native_lifecycle["call_count"] == native_lifecycle["grid_count"]
    for instance in (native_once._nodes["rank_open"], native_once._nodes["rank_volume"]):
        diagnostics = instance.lifecycle_diagnostics
        assert diagnostics["coverage_matches"]
        assert diagnostics["once_ranges"]
        assert diagnostics["next_count"] < diagnostics["grid_count"]
    for instance in native_once._physical_nodes:
        diagnostics = instance.lifecycle_diagnostics
        assert diagnostics["coverage_matches"]
        assert diagnostics["once_ranges"]
        assert diagnostics["next_count"] < diagnostics["grid_count"]


@pytest.mark.parametrize(
    "hook", ("line-reader", "feed-buflen", "line-setter", "feed-binding", "output-binding")
)
def test_custom_panel_hooks_fall_back_without_changing_alpha003_graph(
    tmp_path, monkeypatch, hook
):
    from backtrader.linebuffer import LineBuffer
    from backtrader.research import operators

    runner = _load_module(THIRD_RUNNER, "alpha003_panel_once_fallback")
    _, _, _, expected = _alpha003_run(
        tmp_path / "reference", runner, mode="native", runonce=False
    )

    calls = []
    run_panel_once = operators._run_panel_once

    def observe(instance, optimized_class, plan, start, end):
        calls.append(optimized_class)
        return run_panel_once(instance, optimized_class, plan, start, end)

    monkeypatch.setattr(operators, "_run_panel_once", observe)
    if hook == "line-reader":
        original_getitem = LineBuffer.__getitem__

        def custom_reader(self, ago=0):
            return original_getitem(self, ago)

        monkeypatch.setattr(LineBuffer, "__getitem__", custom_reader)
    else:
        if hook == "feed-buflen":
            from backtrader import research

            original_align = research.align_to_grid

            def add_instance_buflen(*args, **kwargs):
                aligned = original_align(*args, **kwargs)
                feed = aligned.feed
                standard_buflen = feed.buflen
                feed.buflen = lambda: standard_buflen()
                return aligned

            monkeypatch.setattr(research, "align_to_grid", add_instance_buflen)
        elif hook == "line-setter":
            original_setitem = LineBuffer.__setitem__
            setter_calls = []

            def custom_setter(self, ago, value):
                setter_calls.append((self, ago))
                return original_setitem(self, ago, value)

            monkeypatch.setattr(LineBuffer, "__setitem__", custom_setter)
        elif hook == "feed-binding":
            from backtrader import research

            original_align = research.align_to_grid
            binding_writes = []

            class ObservedBinding(LineBuffer):
                def __setitem__(self, ago, value):
                    binding_writes.append((ago, value))
                    return super().__setitem__(ago, value)

            def add_feed_binding(*args, **kwargs):
                aligned = original_align(*args, **kwargs)
                aligned.feed.close.addbinding(ObservedBinding())
                return aligned

            monkeypatch.setattr(research, "align_to_grid", add_feed_binding)
        else:
            binding_writes = []

            class ObservedBinding(LineBuffer):
                def __setitem__(self, ago, value):
                    binding_writes.append((ago, value))
                    return super().__setitem__(ago, value)

            original_plan = operators._panel_once_plan

            def add_output_bindings(instance, optimized_class, start, end):
                for target in instance._factor_target_datas:
                    output = instance.outputs[target]
                    output.value.addbinding(ObservedBinding())
                    output.reason.addbinding(ObservedBinding())
                return original_plan(instance, optimized_class, start, end)

            monkeypatch.setattr(operators, "_panel_once_plan", add_output_bindings)
    _, _, _, fallback = _alpha003_run(
        tmp_path / "custom-reader", runner, mode="native", runonce=True
    )

    assert calls == []
    if hook in ("feed-binding", "output-binding"):
        assert binding_writes
    if hook == "line-setter":
        assert setter_calls
    assert fallback.lifecycle_diagnostics["coverage_matches"]
    assert fallback.lifecycle_diagnostics["once_ranges"] == ()
    assert fallback.lifecycle_diagnostics["next_count"] == fallback.lifecycle_diagnostics[
        "grid_count"
    ]
    for instance in (
        fallback._nodes["rank_open"],
        fallback._nodes["rank_volume"],
        *fallback._physical_nodes,
    ):
        diagnostics = instance.lifecycle_diagnostics
        assert diagnostics["coverage_matches"]
        assert diagnostics["once_ranges"] == ()
    _assert_graphs_equal(expected, fallback)


@pytest.mark.parametrize("hook", ("advance", "_tick_nullify", "_tick_fill"))
def test_feed_lifecycle_hook_replacement_falls_back_and_preserves_graph(
    tmp_path, monkeypatch, hook
):
    from backtrader import research
    from backtrader.research import operators

    runner = _load_module(THIRD_RUNNER, "alpha003_panel_feed_hook_fallback")
    _, _, _, expected = _alpha003_run(
        tmp_path / "reference", runner, mode="native", runonce=False
    )

    kernel_calls = []
    hook_calls = []
    run_panel_once = operators._run_panel_once

    def observe(instance, optimized_class, plan, start, end):
        kernel_calls.append(optimized_class)
        return run_panel_once(instance, optimized_class, plan, start, end)

    original_align = research.align_to_grid

    def replace_feed_hook(*args, **kwargs):
        aligned = original_align(*args, **kwargs)
        feed = aligned.feed
        original_hook = getattr(feed, hook)

        if hook == "advance":

            def replacement(size=1, datamaster=None, ticks=True):
                hook_calls.append(hook)
                return original_hook(size, datamaster, ticks)

        elif hook == "_tick_nullify":

            def replacement():
                hook_calls.append(hook)
                return original_hook()

        else:

            def replacement(force=False):
                hook_calls.append(hook)
                return original_hook(force=force)

        setattr(feed, hook, replacement)
        return aligned

    monkeypatch.setattr(operators, "_run_panel_once", observe)
    monkeypatch.setattr(research, "align_to_grid", replace_feed_hook)
    _, _, _, fallback = _alpha003_run(
        tmp_path / "custom-hook", runner, mode="native", runonce=True
    )

    assert kernel_calls == []
    assert hook_calls
    assert fallback.lifecycle_diagnostics["coverage_matches"]
    assert fallback.lifecycle_diagnostics["once_ranges"] == ()
    assert fallback.lifecycle_diagnostics["next_count"] == fallback.lifecycle_diagnostics[
        "grid_count"
    ]
    for instance in (
        fallback._nodes["rank_open"],
        fallback._nodes["rank_volume"],
        *fallback._physical_nodes,
    ):
        diagnostics = instance.lifecycle_diagnostics
        assert diagnostics["coverage_matches"]
        assert diagnostics["once_ranges"] == ()
    _assert_graphs_equal(expected, fallback)


def test_multiply_panel_custom_apply_falls_back_without_changing_alpha003_graph(
    tmp_path, monkeypatch
):
    from backtrader.research import operators

    runner = _load_module(THIRD_RUNNER, "alpha003_panel_once_multiply_fallback")
    _, _, _, expected = _alpha003_run(
        tmp_path / "reference", runner, mode="native", runonce=False
    )

    calls = []
    apply_calls = []
    run_panel_once = operators._run_panel_once
    original_apply = operators.Multiply._apply

    def observe(instance, optimized_class, plan, start, end):
        calls.append(optimized_class)
        return run_panel_once(instance, optimized_class, plan, start, end)

    def custom_apply(left, right):
        apply_calls.append((left, right))
        return original_apply(left, right)

    monkeypatch.setattr(operators, "_run_panel_once", observe)
    monkeypatch.setattr(operators.Multiply, "_apply", staticmethod(custom_apply))
    _, _, _, fallback = _alpha003_run(
        tmp_path / "custom-apply", runner, mode="native", runonce=True
    )

    assert calls
    assert operators._MultiplyPanel not in calls
    assert apply_calls
    multiply_nodes = [
        node for node in fallback._physical_nodes if isinstance(node, operators._MultiplyPanel)
    ]
    assert len(multiply_nodes) == 1
    diagnostics = multiply_nodes[0].lifecycle_diagnostics
    assert diagnostics["coverage_matches"]
    assert diagnostics["once_ranges"] == ()
    assert diagnostics["next_count"] == diagnostics["grid_count"]
    _assert_graphs_equal(expected, fallback)


def test_panel_once_strict_error_keeps_target_clock_and_asset(tmp_path, monkeypatch):
    from backtrader.errors import FactorComputationError
    from backtrader.research import operators
    from backtrader.research import strict

    runner = _load_module(THIRD_RUNNER, "alpha003_panel_once_strict_error")
    run_panel_once = operators._run_panel_once
    observed = []
    fail_computation = strict.fail_computation
    failure_message = "synthetic Alpha003 once-kernel failure"

    def inject(instance, optimized_class, plan, start, end):
        if optimized_class is operators._RollingCorrelationPanel:
            failed_target = plan.targets[2]
            failed_source_array = plan.values[2][0]
            expected_date = float(failed_target.datetime.array[start])
            read_window = operators._panel_once_window

            def fail_third_asset(source, index, period):
                if source[0] is failed_source_array:
                    raise ArithmeticError(failure_message)
                return read_window(source, index, period)

            monkeypatch.setattr(operators, "_panel_once_window", fail_third_asset)

            def observe_strict_failure(context, error, phase, operation=None):
                if str(error) == failure_message:
                    observed.append(
                        (
                            operation is failed_target,
                            float(operation.datetime[0]),
                            expected_date,
                            phase,
                        )
                    )
                return fail_computation(context, error, phase, operation=operation)

            monkeypatch.setattr(strict, "fail_computation", observe_strict_failure)
        return run_panel_once(instance, optimized_class, plan, start, end)

    monkeypatch.setattr(operators, "_run_panel_once", inject)
    with pytest.raises(FactorComputationError) as captured:
        _alpha003_run(
            tmp_path / "strict", runner, mode="native", runonce=True
        )

    error = captured.value
    assert observed
    target_matches, actual_date, expected_date, phase = observed[0]
    assert target_matches
    assert actual_date == expected_date
    assert error.factor == runner.FACTOR_NAME
    assert error.asset == "sh600002"
    assert error.phase == phase == "once_via_next"
    assert isinstance(error.__cause__, ArithmeticError)
