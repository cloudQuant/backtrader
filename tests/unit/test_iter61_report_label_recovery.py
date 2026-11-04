"""Recovered report-label forwarding contracts for synthetic factor examples."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from backtrader.errors import DependencyError
import backtrader.research as research

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = {
    "025": ("025_factor_single", ("close_ma",)),
    "026": ("026_factor_multi", ("close_ma", "kdj_j", "roc")),
}


def _runner(key):
    directory, _ = EXAMPLES[key]
    path = ROOT / "examples" / "backtest" / directory / "run.py"
    spec = importlib.util.spec_from_file_location("iter61_report_runner_" + key, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("key", ("025", "026"))
@pytest.mark.parametrize("label", ("next_open_to_open", "close_to_close"))
@pytest.mark.parametrize("batch_size", (0, 256), ids=("unbatched", "batched"))
@pytest.mark.parametrize("evaluation_available", (False, True), ids=("unavailable", "available"))
def test_each_report_receives_selected_evaluation_label(
    monkeypatch, tmp_path, key, label, batch_size, evaluation_available
):
    runner = _runner(key)
    _, factor_names = EXAMPLES[key]
    evaluation = {"periods": [1, 5], "quantiles": 5, "max_loss": 1.0, "label": label}
    config = {
        "example_id": runner.EXAMPLE_ID,
        "factor_mode": "native",
        "data": {},
        "evaluation": evaluation,
    }
    if key == "025":
        config["factor"] = {"name": "close_ma"}
    else:
        config["factors"] = {name: {} for name in factor_names}
    monkeypatch.setattr(runner, "_load_config", lambda: config)
    prices = object()
    monkeypatch.setattr(runner, "load_daily_panel", lambda data: prices)
    monkeypatch.setattr(runner, "_factor_class_identities", lambda mode: {})

    dates = pd.date_range("2025-01-02", periods=3, freq="B", tz="UTC", name="time")
    assets = ("ASSET_A", "ASSET_B")
    index = pd.MultiIndex.from_product((dates, assets), names=("time", "asset"))
    panel = SimpleNamespace(
        factors=pd.DataFrame({name: range(len(index)) for name in factor_names}, index=index),
        target_order=assets,
        grid=pd.DataFrame(index=dates),
    )
    broker = SimpleNamespace(submit_count=0, cancel_count=0)
    if batch_size:

        def collect_batches(actual_config, data, runnext, actual_batch_size):
            assert actual_config is config and data is prices and runnext is False
            assert actual_batch_size == batch_size
            return panel, {"submit": 0, "cancel": 0}

        monkeypatch.setattr(runner, "_run_batched_collection", collect_batches)
    else:

        def collect(actual_config, data, runnext, *, consume_source_frames):
            assert actual_config is config and data is prices and runnext is False
            assert consume_source_frames is True
            return object(), panel, broker

        monkeypatch.setattr(runner, "_run_native_collection", collect)
        monkeypatch.setattr(runner, "_actual_factor_mode", lambda strategy, mode: mode)

    evaluation_spec = SimpleNamespace(label=label)

    def make_spec(actual_config, actual_panel, periods):
        assert actual_config is config and actual_panel is panel
        assert actual_config["evaluation"]["label"] == label
        assert periods == (1, 5)
        return evaluation_spec

    monkeypatch.setattr(runner, "_evaluation_spec", make_spec)
    reports = []

    def capture_report(actual_panel, factor_name, target, **options):
        assert actual_panel is panel
        reports.append((factor_name, Path(target), options))
        return target

    calls = []

    def evaluate(actual_panel, actual_spec):
        calls.append((actual_panel, actual_spec))
        if not evaluation_available:
            raise DependencyError("synthetic unavailable evaluation")
        return SimpleNamespace(status="OK", export=lambda *args, **kwargs: None)

    monkeypatch.setattr(research, "write_factor_report", capture_report)
    monkeypatch.setattr(research, "evaluate_frames", evaluate)
    output = tmp_path / "output"
    assert (
        runner.main(
            ["--output-dir", str(output), "--asset-batch-size", str(batch_size), "--report"]
        )
        == 0
    )
    assert calls == [(panel, evaluation_spec)]
    assert [name for name, _, _ in reports] == list(factor_names)
    for name, target, options in reports:
        assert target == output / ("factor_report_%s.html" % name)
        assert options["label"] == label
        assert options["periods"] == (1, 5)
        assert options["quantiles"] == 5 and options["max_loss"] == 1.0
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == ("COMPLETED" if evaluation_available else "PANEL_ONLY")
