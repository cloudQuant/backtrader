"""Runner summaries identify the factor classes used in actual calculations."""

import copy
import importlib
import inspect
import json
from pathlib import Path

import pytest

from tests.unit.test_iter61_example_modes import (
    EXAMPLES,
    NAMES,
    RUNNERS,
    block_evaluation,
    config_for,
    load_runner,
    write_panel,
)


@pytest.mark.parametrize("key", ("025", "026", "027"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runnext", (False, True), ids=("runonce", "runnext"))
def test_summary_uses_actual_factor_class(key, mode, runnext, monkeypatch, tmp_path):
    runner = load_runner(key)
    monkeypatch.syspath_prepend(str(RUNNERS[key].parent))
    source = tmp_path / "source"
    write_panel(source)
    config = config_for(runner, source)
    config["factor_mode"] = mode
    monkeypatch.setattr(runner, "_load_config", lambda: copy.deepcopy(config))

    # Inspect the exact strategy produced by the runner, rather than deriving
    # expectations from the helper that also writes the summary.
    observed = []
    method = "_run_factor" if key == "027" else "_run_native_collection"
    original = getattr(runner, method)

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        observed.append(result)
        return result

    monkeypatch.setattr(runner, method, capture)
    if key != "027":
        block_evaluation(monkeypatch)

    output = tmp_path / "output"
    args = ["--output-dir", str(output), "--data-dir", str(source), "--factor-mode", mode]
    if key != "027":
        args += ["--asset-batch-size", "0"]
    if runnext:
        args.append("--runnext")
    assert runner.main(args) == 0
    assert len(observed) == 1
    strategy, panel, third = observed[0]
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["factor_mode"] == mode

    if key == "025":
        expected_classes = {
            "close_ma": importlib.import_module("close_ma_factor_strategy").CloseMAFactor
        }
        expected_path = EXAMPLES / "025_factor_single/close_ma_factor_strategy.py"
    elif key == "026":
        module = importlib.import_module("multi_factor_strategy")
        expected_classes = {
            "close_ma": module.CloseMAFactor,
            "kdj_j": module.KDJFactor,
            "roc": module.ROCFactor,
        }
        expected_path = EXAMPLES / "026_factor_multi/multi_factor_strategy.py"
    else:
        from backtrader.research.alpha101.alpha003 import Alpha003Native

        expected_classes = {"alpha003": Alpha003Native}
        expected_path = Path(inspect.getfile(Alpha003Native))
        assert third is Alpha003Native

    assert tuple(strategy._factor_specs_by_name) == NAMES[key]
    identities = {}
    for name, expected in expected_classes.items():
        spec = strategy._factor_specs_by_name[name]
        assert spec.indicator is expected
        assert Path(inspect.getfile(expected)).resolve() == expected_path.resolve()
        assert spec.mode == mode
        identities[name] = expected.__module__ + "." + expected.__qualname__
        instances = strategy._factor_instances_by_name[name]
        assert instances
        for instance in instances:
            assert isinstance(instance, expected)
            assert instance.factor_mode == mode
            context = instance.__dict__.get("_expression_context")
            if mode == "build":
                assert context is not None and context._closed
                assert instance._nodes
            else:
                assert context is None
            diagnostics = instance.lifecycle_diagnostics
            assert diagnostics["coverage_matches"]
            assert diagnostics["coverage_count"] == diagnostics["grid_count"] == len(panel.grid)
            if runnext:
                assert diagnostics["next_count"] == diagnostics["grid_count"]
                assert diagnostics["once_count"] == 0
            elif key != "027" and mode == "native":
                assert diagnostics["once_count"] == diagnostics["grid_count"]
                assert diagnostics["next_count"] == 0

    if key == "027":
        assert summary["indicator"] == identities["alpha003"]
    else:
        assert summary["factor_classes"] == identities
