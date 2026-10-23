"""CLI and source-panel contracts for the Iteration 47 factor modes."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TESTS_PATH = ROOT / "tests" / "unit" / "test_factor_research_examples.py"
EXAMPLE_TESTS_SPEC = importlib.util.spec_from_file_location(
    "factor_mode_example_test_helpers", EXAMPLE_TESTS_PATH
)
assert EXAMPLE_TESTS_SPEC is not None and EXAMPLE_TESTS_SPEC.loader is not None
EXAMPLE_TESTS = importlib.util.module_from_spec(EXAMPLE_TESTS_SPEC)
EXAMPLE_TESTS_SPEC.loader.exec_module(EXAMPLE_TESTS)

EXAMPLE_ROOT = ROOT / "examples" / "backtest"
QUICK_RUNNERS = {
    "025": EXAMPLE_ROOT / "025_factor_single" / "run.py",
    "026": EXAMPLE_ROOT / "026_factor_multi" / "run.py",
    "027": EXAMPLE_ROOT / "027_alpha003_panel_acceptance" / "run.py",
}


def _load_runner(key: str, name: str) -> Any:
    return EXAMPLE_TESTS._load_module(QUICK_RUNNERS[key], name)


def _config_for_panel(runner: Any, data_dir: Path, *, factor_mode: str) -> Dict[str, Any]:
    config = EXAMPLE_TESTS._example_config(runner, data_dir)
    config["factor_mode"] = factor_mode
    config["data"]["max_symbols"] = 3
    return config


def _run_quick_panel(
    runner: Any,
    config: Dict[str, Any],
    output_dir: Path,
    *,
    factor_mode: Optional[str] = None,
) -> Tuple[int, pd.DataFrame, dict]:
    runner._load_config = lambda: copy.deepcopy(config)
    runner._evaluation_spec = lambda *args, **kwargs: None
    collection_name = (
        "_run_native_collection"
        if hasattr(runner, "_run_native_collection")
        else "_run_factor"
    )
    original_collection = getattr(
        runner, "_factor_mode_test_original_collection", getattr(runner, collection_name)
    )
    runner._factor_mode_test_original_collection = original_collection

    def capture_collection(*args: Any, **kwargs: Any) -> Any:
        result = original_collection(*args, **kwargs)
        runner._factor_mode_test_last_strategy = result[0]
        return result

    setattr(runner, collection_name, capture_collection)
    arguments = ["--output-dir", str(output_dir)]
    if factor_mode is not None:
        arguments.extend(("--factor-mode", factor_mode))
    if runner.EXAMPLE_ID != "027_alpha003_panel_acceptance":
        arguments.extend(("--data-dir", config["data"]["directory"], "--max-symbols", "3"))
    else:
        arguments.extend(("--data-dir", config["data"]["directory"], "--max-symbols", "3"))
    result = runner.main(arguments)
    values = pd.read_csv(output_dir / "factor_values.csv")
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    return result, values, summary


@pytest.mark.parametrize("key", ("025", "026", "027"))
def test_quick_mode_cli_config_and_default_precedence(
    key: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    runner = _load_runner(key, "factor_mode_precedence_" + key)
    config = EXAMPLE_TESTS._example_config(runner)
    monkeypatch.setattr(runner, "_load_config", lambda: copy.deepcopy(config))

    assert runner._load_config()["factor_mode"] == "native"
    assert runner._resolve_factor_mode(None, None) == "native"
    assert runner._resolve_factor_mode(None, "build") == "build"
    assert runner._resolve_factor_mode("native", "build") == "native"
    with pytest.raises(ValueError, match="factor_mode must be"):
        runner._resolve_factor_mode(None, "future")

    assert (
        runner._parser().parse_args(["--output-dir", str(tmp_path / "default")]).factor_mode is None
    )
    with pytest.raises(SystemExit):
        runner._parser().parse_args(
            ["--output-dir", str(tmp_path / "invalid"), "--factor-mode", "invalid"]
        )


@pytest.mark.parametrize(
    ("key", "factor_names", "factor_class_names"),
    (
        ("025", ("close_ma",), {"close_ma": "CloseMAFactor"}),
        (
            "026",
            ("close_ma", "kdj_j", "roc"),
            {
                "close_ma": "CloseMAFactor",
                "kdj_j": "KDJFactor",
                "roc": "ROCFactor",
            },
        ),
    ),
)
def test_single_and_multi_quick_modes_export_exact_complete_factor_panels(
    key: str,
    factor_names: Tuple[str, ...],
    factor_class_names: Dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from backtrader.errors import DependencyError
    import backtrader.research as research

    runner = _load_runner(key, "factor_mode_panel_" + key)
    monkeypatch.syspath_prepend(str(QUICK_RUNNERS[key].parent))
    data_dir = tmp_path / ("daily_" + key)
    symbols, dates = EXAMPLE_TESTS._write_daily_panel(data_dir, symbol_count=4, day_count=30)
    invalid_config = _config_for_panel(runner, data_dir, factor_mode="invalid")
    build_config = _config_for_panel(runner, data_dir, factor_mode="build")

    def evaluation_unavailable(*args: Any, **kwargs: Any) -> None:
        raise DependencyError("expected mode-test evaluation boundary")

    monkeypatch.setattr(research, "evaluate_frames", evaluation_unavailable)
    native_result, native_values, native_summary = _run_quick_panel(
        runner, invalid_config, tmp_path / (key + "_native"), factor_mode="native"
    )
    native_strategy = runner._factor_mode_test_last_strategy
    build_result, build_values, build_summary = _run_quick_panel(
        runner, build_config, tmp_path / (key + "_build")
    )
    build_strategy = runner._factor_mode_test_last_strategy

    assert native_result == build_result == 0
    assert native_summary["status"] == build_summary["status"] == "PANEL_ONLY"
    assert native_summary["factor_mode"] == "native"
    assert build_summary["factor_mode"] == "build"
    assert native_summary["factor_calculation"] == build_summary["factor_calculation"] == "RAN"
    assert set(native_summary["factor_classes"]) == set(factor_names)
    assert set(build_summary["factor_classes"]) == set(factor_names)
    assert build_summary["factor_classes"] == native_summary["factor_classes"]
    native_classes = runner._factor_classes("native")
    build_classes = runner._factor_classes("build")
    assert native_classes.keys() == build_classes.keys()
    assert all(native_classes[name] is build_classes[name] for name in factor_names)
    for name, class_name in factor_class_names.items():
        assert native_summary["factor_classes"][name].endswith("." + class_name)
        assert build_summary["factor_classes"][name].endswith("." + class_name)
        native_spec = native_strategy._factor_specs_by_name[name]
        build_spec = build_strategy._factor_specs_by_name[name]
        assert native_spec.indicator is build_spec.indicator
        assert native_spec.mode == native_strategy.factor_instances[name].factor_mode == "native"
        assert build_spec.mode == build_strategy.factor_instances[name].factor_mode == "build"
        assert not hasattr(native_strategy.factor_instances[name], "_expression_context")
        assert build_strategy.factor_instances[name]._expression_context._closed is True
        native_instances = native_strategy._factor_instances_by_name[name]
        build_instances = build_strategy._factor_instances_by_name[name]
        assert len(native_instances) == len(build_instances) == 1
        native_lifecycle = native_instances[0].lifecycle_diagnostics
        build_lifecycle = build_instances[0].lifecycle_diagnostics
        assert native_lifecycle["coverage_matches"]
        assert native_lifecycle["coverage_count"] == native_lifecycle["grid_count"] == len(dates)
        assert native_lifecycle["once_ranges"]
        assert native_lifecycle["once_count"] == len(dates)
        assert native_lifecycle["next_count"] == native_lifecycle["call_count"] == 0
        assert native_lifecycle["call_times"] == native_lifecycle["next_times"] == ()
        assert build_lifecycle["coverage_matches"] and build_lifecycle["grid_matches"]
        assert build_lifecycle["next_count"] == build_lifecycle["call_count"] == len(dates)
        assert build_lifecycle["once_ranges"] == ()
    assert len(native_values) == len(build_values) == len(dates) * 3
    assert tuple(name for name in native_values if name in factor_names) == factor_names
    assert tuple(name for name in build_values if name in factor_names) == factor_names
    assert native_values[["time", "asset"]].equals(build_values[["time", "asset"]])
    for name in factor_names:
        native = pd.to_numeric(native_values[name], errors="raise").to_numpy(dtype=float)
        build = pd.to_numeric(build_values[name], errors="raise").to_numpy(dtype=float)
        assert np.array_equal(np.isfinite(native), np.isfinite(build))
        assert np.isfinite(native).any(), "fixture must witness finite values for " + name
        np.testing.assert_array_equal(native, build)
    pd.testing.assert_frame_equal(native_values, build_values, check_dtype=False)
    assert native_summary["broker"] == {"submit": 0, "cancel": 0}
    assert build_summary["broker"] == {"submit": 0, "cancel": 0}


def test_026_safe_rsv_once_fast_path_hits_each_asset_and_matches_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Observe the ordinary RSV child's once kernel, independently of KDJ's factor callback."""
    from backtrader.errors import DependencyError
    import backtrader.research as research

    runner = _load_runner("026", "factor_mode_safe_rsv_once")
    factor_classes = runner._factor_classes("native")
    strategy_module = __import__(factor_classes["kdj_j"].__module__, fromlist=["_SafeRSV"])
    safe_rsv_class = strategy_module._SafeRSV
    original_once_range = safe_rsv_class._once_range
    ranges_by_instance: Dict[int, list[Tuple[int, int]]] = {}

    def observe_once_range(indicator: Any, start: int, end: int) -> None:
        ranges_by_instance.setdefault(id(indicator), []).append((start, end))
        return original_once_range(indicator, start, end)

    monkeypatch.setattr(safe_rsv_class, "_once_range", observe_once_range)

    data_dir = tmp_path / "safe_rsv_daily"
    _, dates = EXAMPLE_TESTS._write_daily_panel(data_dir, symbol_count=4, day_count=30)
    native_config = _config_for_panel(runner, data_dir, factor_mode="native")
    build_config = _config_for_panel(runner, data_dir, factor_mode="build")

    def evaluation_unavailable(*args: Any, **kwargs: Any) -> None:
        raise DependencyError("expected mode-test evaluation boundary")

    monkeypatch.setattr(research, "evaluate_frames", evaluation_unavailable)
    native_result, native_values, _ = _run_quick_panel(
        runner, native_config, tmp_path / "safe_rsv_native"
    )
    native_strategy = runner._factor_mode_test_last_strategy
    native_factor = native_strategy._factor_instances_by_name["kdj_j"][0]
    rsv_instances = tuple(native_factor._rsv.values())
    assert len(rsv_instances) == 3
    assert set(ranges_by_instance) == {id(instance) for instance in rsv_instances}
    for instance in rsv_instances:
        ranges = sorted(ranges_by_instance[id(instance)])
        nonempty_ranges = [(start, end) for start, end in ranges if start < end]
        assert nonempty_ranges
        assert nonempty_ranges[0][0] == 0
        assert nonempty_ranges[-1][1] == len(dates)
        assert all(
            previous_end == start
            for (_, previous_end), (start, _) in zip(nonempty_ranges, nonempty_ranges[1:])
        )
        assert sum(end - start for start, end in nonempty_ranges) == len(dates)

    native_ranges = {key: tuple(ranges) for key, ranges in ranges_by_instance.items()}
    build_result, build_values, _ = _run_quick_panel(
        runner, build_config, tmp_path / "safe_rsv_build"
    )
    assert native_result == build_result == 0
    assert ranges_by_instance == {key: list(ranges) for key, ranges in native_ranges.items()}
    assert native_values[["time", "asset"]].equals(build_values[["time", "asset"]])
    native = pd.to_numeric(native_values["kdj_j"], errors="raise").to_numpy(dtype=float)
    build = pd.to_numeric(build_values["kdj_j"], errors="raise").to_numpy(dtype=float)
    assert np.array_equal(np.isfinite(native), np.isfinite(build))
    assert np.isfinite(native).any(), "fixture must witness finite KDJ values"
    np.testing.assert_array_equal(native, build)


def test_025_once_fast_path_falls_back_for_custom_factor_subclass():
    """Keep subclass callback semantics while proving the base fast path is used."""
    factor_module = EXAMPLE_TESTS._load_module(
        EXAMPLE_TESTS.SINGLE_STRATEGY, "factor_once_custom_subclass_fallback"
    )

    class _CustomCloseMA(factor_module.CloseMAFactor):
        def nextstart(self):
            return super().nextstart()

    frame = EXAMPLE_TESTS._known_close_bars()
    base_strategy, _ = EXAMPLE_TESTS._run_factor_strategy(
        frame,
        factor_name="close_ma",
        factor_class=factor_module.CloseMAFactor,
        params={"period": 20},
        runonce=True,
    )
    custom_strategy, _ = EXAMPLE_TESTS._run_factor_strategy(
        frame,
        factor_name="close_ma",
        factor_class=_CustomCloseMA,
        params={"period": 20},
        runonce=True,
    )

    base_factor = base_strategy.factor_instances["close_ma"]
    custom_factor = custom_strategy.factor_instances["close_ma"]
    base_lifecycle = base_factor.lifecycle_diagnostics
    custom_lifecycle = custom_factor.lifecycle_diagnostics
    assert base_lifecycle["once_ranges"]
    assert base_lifecycle["next_count"] == 0
    assert custom_lifecycle["once_ranges"] == ()
    assert custom_lifecycle["next_count"] == custom_lifecycle["grid_count"] == len(frame)
    assert custom_lifecycle["coverage_matches"] and custom_lifecycle["grid_matches"]
    base_values = base_factor.outputs[base_strategy.datas[0]].factor.get(size=len(frame))
    custom_values = custom_factor.outputs[custom_strategy.datas[0]].factor.get(size=len(frame))
    np.testing.assert_array_equal(base_values, custom_values)


@pytest.mark.parametrize("hook", ("factor_next", "advance", "_tick_nullify", "_tick_fill"))
def test_025_once_fast_path_falls_back_for_monkeypatched_lifecycle_hooks(
    hook: str, monkeypatch: pytest.MonkeyPatch
):
    """Do not bypass standard callback/feed hooks that callers have replaced."""
    from backtrader.feeds.pandafeed import PandasData

    factor_module = EXAMPLE_TESTS._load_module(
        EXAMPLE_TESTS.SINGLE_STRATEGY, "factor_once_monkeypatched_" + hook
    )
    if hook == "factor_next":
        original = factor_module.CloseMAFactor.next

        def factor_replacement(self):
            return original(self)

        monkeypatch.setattr(factor_module.CloseMAFactor, "next", factor_replacement)
    else:
        original = getattr(PandasData, hook)

        def feed_replacement(self, *args, **kwargs):
            return original(self, *args, **kwargs)

        monkeypatch.setattr(PandasData, hook, feed_replacement)

    frame = EXAMPLE_TESTS._known_close_bars()
    strategy, _ = EXAMPLE_TESTS._run_factor_strategy(
        frame,
        factor_name="close_ma",
        factor_class=factor_module.CloseMAFactor,
        params={"period": 20},
        runonce=True,
    )
    factor = strategy.factor_instances["close_ma"]
    lifecycle = factor.lifecycle_diagnostics
    assert lifecycle["once_ranges"] == ()
    assert lifecycle["next_count"] == lifecycle["grid_count"] == len(frame)
    assert lifecycle["coverage_matches"] and lifecycle["grid_matches"]


@pytest.mark.parametrize("key", ("025", "026"))
def test_offline_panel_does_not_run_factor_mode_and_rejects_explicit_mode(
    key: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from backtrader.errors import DependencyError
    import backtrader.research as research

    runner = _load_runner(key, "factor_mode_offline_" + key)
    monkeypatch.syspath_prepend(str(QUICK_RUNNERS[key].parent))
    data_dir = tmp_path / ("offline_daily_" + key)
    EXAMPLE_TESTS._write_daily_panel(data_dir, symbol_count=4, day_count=30)
    config = _config_for_panel(runner, data_dir, factor_mode="native")
    offline_config = copy.deepcopy(config)
    prices = runner.load_daily_panel(config["data"])
    _, panel, _ = runner._run_native_collection(config, prices, False)
    panel_dir = tmp_path / ("saved_panel_" + key)
    panel.to_csv(panel_dir)

    def evaluation_unavailable(*args: Any, **kwargs: Any) -> None:
        raise DependencyError("expected offline-panel evaluation boundary")

    def calculation_forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("offline panel must not calculate factors")

    monkeypatch.setattr(research, "evaluate_frames", evaluation_unavailable)
    offline_config["factor_mode"] = "invalid"
    monkeypatch.setattr(runner, "_load_config", lambda: copy.deepcopy(offline_config))
    monkeypatch.setattr(runner, "_run_native_collection", calculation_forbidden)

    output_dir = tmp_path / ("offline_result_" + key)
    assert runner.main(["--panel", str(panel_dir), "--output-dir", str(output_dir)]) == 0
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["factor_mode"] == "NOT_APPLICABLE"
    assert summary["factor_calculation"] == "NOT_RUN"
    assert summary["factor_classes"] == {}

    with pytest.raises(SystemExit):
        runner.main(
            [
                "--panel",
                str(panel_dir),
                "--factor-mode",
                "native",
                "--output-dir",
                str(tmp_path / ("offline_conflict_" + key)),
            ]
        )


def test_alpha003_quick_native_build_panels_match_with_cli_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    runner = _load_runner("027", "factor_mode_alpha003_quick")
    data_dir = tmp_path / "alpha003_quick_daily"
    _, dates = EXAMPLE_TESTS._write_daily_panel(data_dir, symbol_count=4, day_count=30)
    config = _config_for_panel(runner, data_dir, factor_mode="build")
    monkeypatch.setattr(runner, "_load_config", lambda: copy.deepcopy(config))

    native_result, native_values, native_summary = _run_quick_panel(
        runner, config, tmp_path / "alpha003_native", factor_mode="native"
    )
    native_strategy = runner._factor_mode_test_last_strategy
    build_result, build_values, build_summary = _run_quick_panel(
        runner, config, tmp_path / "alpha003_build"
    )
    build_strategy = runner._factor_mode_test_last_strategy

    assert native_result == build_result == 0
    assert native_summary["factor_mode"] == "native"
    assert build_summary["factor_mode"] == "build"
    assert native_summary["indicator"].endswith(".Alpha003Native")
    assert build_summary["indicator"] == native_summary["indicator"]
    native_spec = native_strategy._factor_specs_by_name["alpha003"]
    build_spec = build_strategy._factor_specs_by_name["alpha003"]
    assert native_spec.indicator is build_spec.indicator
    assert native_spec.mode == native_strategy.factor_instances["alpha003"].factor_mode == "native"
    assert build_spec.mode == build_strategy.factor_instances["alpha003"].factor_mode == "build"
    assert not hasattr(native_strategy.factor_instances["alpha003"], "_expression_context")
    assert build_strategy.factor_instances["alpha003"]._expression_context._closed is True
    assert native_summary["broker"] == {"submit": 0, "cancel": 0}
    assert build_summary["broker"] == {"submit": 0, "cancel": 0}
    assert len(native_values) == len(build_values) == len(dates) * 3
    assert native_values[["time", "asset"]].equals(build_values[["time", "asset"]])
    for values in (native_values, build_values):
        factor = pd.to_numeric(values["alpha003"], errors="raise").to_numpy(dtype=float)
        assert np.isfinite(factor).any()
    pd.testing.assert_frame_equal(native_values, build_values, check_dtype=False)
