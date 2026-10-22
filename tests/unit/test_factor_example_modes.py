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
    config = copy.deepcopy(runner._load_config())
    config["factor_mode"] = factor_mode
    config["data"]["directory"] = str(data_dir)
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
def test_quick_mode_cli_config_and_default_precedence(key: str, tmp_path: Path):
    runner = _load_runner(key, "factor_mode_precedence_" + key)

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
    ("key", "factor_names", "build_class_names"),
    (
        ("025", ("close_ma",), {"close_ma": "CloseMAFactorBuild"}),
        (
            "026",
            ("close_ma", "kdj_j", "roc"),
            {
                "close_ma": "CloseMAFactorBuild",
                "kdj_j": "KDJFactorBuild",
                "roc": "ROCFactorBuild",
            },
        ),
    ),
)
def test_single_and_multi_quick_modes_export_exact_complete_factor_panels(
    key: str,
    factor_names: Tuple[str, ...],
    build_class_names: Dict[str, str],
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
    build_result, build_values, build_summary = _run_quick_panel(
        runner, build_config, tmp_path / (key + "_build")
    )

    assert native_result == build_result == 0
    assert native_summary["status"] == build_summary["status"] == "PANEL_ONLY"
    assert native_summary["factor_mode"] == "native"
    assert build_summary["factor_mode"] == "build"
    assert native_summary["factor_calculation"] == build_summary["factor_calculation"] == "RAN"
    assert set(native_summary["factor_classes"]) == set(factor_names)
    assert set(build_summary["factor_classes"]) == set(factor_names)
    for name, class_name in build_class_names.items():
        assert build_summary["factor_classes"][name].endswith("." + class_name)
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
    build_result, build_values, build_summary = _run_quick_panel(
        runner, config, tmp_path / "alpha003_build"
    )

    assert native_result == build_result == 0
    assert native_summary["factor_mode"] == "native"
    assert build_summary["factor_mode"] == "build"
    assert native_summary["indicator"].endswith(".Alpha003Native")
    assert build_summary["indicator"].endswith(".Alpha003Build")
    assert len(native_values) == len(build_values) == len(dates) * 3
    assert native_values[["time", "asset"]].equals(build_values[["time", "asset"]])
    for values in (native_values, build_values):
        factor = pd.to_numeric(values["alpha003"], errors="raise").to_numpy(dtype=float)
        assert np.isfinite(factor).any()
    pd.testing.assert_frame_equal(native_values, build_values, check_dtype=False)
