"""Quick-run memory release contracts for native factor collection."""

from __future__ import annotations

import copy
import importlib.util
import json
import weakref
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = {
    "025": ROOT / "examples" / "backtest" / "025_factor_single" / "run.py",
    "026": ROOT / "examples" / "backtest" / "026_factor_multi" / "run.py",
    "027": ROOT / "examples" / "backtest" / "027_alpha003_panel_acceptance" / "run.py",
}


def _load_runner(key: str):
    spec = importlib.util.spec_from_file_location("factor_memory_runner_" + key, RUNNERS[key])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CycleNode:
    pass


class _PriceInputs(dict):
    pass


def _make_panel(key: str, config: Dict[str, Any]):
    timestamp = pd.Timestamp("2024-01-02", tz="UTC")
    index = pd.MultiIndex.from_tuples(
        [(timestamp, "000001")], names=("time", "asset")
    )
    if key == "025":
        names = (config["factor"]["name"],)
    elif key == "026":
        names = tuple(config["factors"])
    else:
        names = ("alpha003",)
    factors = pd.DataFrame({name: [1.0] for name in names}, index=index)
    return SimpleNamespace(
        factors=factors,
        target_order=("000001",),
        grid=pd.DataFrame(index=pd.DatetimeIndex([timestamp], name="close_time")),
    )


@pytest.mark.parametrize("key", ("025", "026", "027"))
def test_quick_runner_releases_run_graphs_before_report(
    key: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from backtrader import research

    runner = _load_runner(key)
    config = copy.deepcopy(runner._load_config())
    panel = _make_panel(key, config)
    references: List[Any] = []
    price_references: List[Any] = []
    long_frame_references: List[Any] = []

    def load_prices(_data_config):
        prices = _PriceInputs()
        price_references.append(weakref.ref(prices))
        return prices

    def make_strategy():
        strategy = _CycleNode()
        broker = _CycleNode()
        strategy.broker = broker
        broker.strategy = strategy
        broker.submit_count = 0
        broker.cancel_count = 0
        strategy.factor_instances = {}
        references.extend((weakref.ref(strategy), weakref.ref(broker)))
        return strategy, broker

    if key in {"025", "026"}:
        def collect(_config, prices, _runnext, *, consume_source_frames=False):
            assert consume_source_frames is True
            price_references.append(weakref.ref(prices))
            strategy, broker = make_strategy()
            return strategy, panel, broker

        monkeypatch.setattr(runner, "_run_native_collection", collect)
        monkeypatch.setattr(runner, "_actual_factor_mode", lambda _strategy, expected: expected)
        monkeypatch.setattr(runner, "_factor_class_identities", lambda _mode: {"test": "Factor"})
        monkeypatch.setattr(runner, "_evaluation_spec", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runner, "_evaluation_unavailable", lambda _exc: True)

        def unavailable(*_args, **_kwargs):
            raise RuntimeError("synthetic evaluation unavailable")

        monkeypatch.setattr(research, "evaluate_frames", unavailable)
    else:
        class Alpha003:
            operator_profile = "alpha101-v2"

        def collect(_config, prices, *, consume_source_frames=False):
            assert consume_source_frames is True
            price_references.append(weakref.ref(prices))
            strategy, broker = make_strategy()
            instance = SimpleNamespace(factor_mode=config.get("factor_mode", "native"))
            instance.strategy = strategy
            strategy.factor_instances = {"alpha003": instance}
            return strategy, panel, Alpha003

        monkeypatch.setattr(runner, "_run_factor", collect)

        original_reset_index = pd.DataFrame.reset_index

        def track_reset_index(frame, *args, **kwargs):
            result = original_reset_index(frame, *args, **kwargs)
            if frame is panel.factors:
                long_frame_references.append(weakref.ref(result))
            return result

        monkeypatch.setattr(pd.DataFrame, "reset_index", track_reset_index)

    def write_report(*_args, **_kwargs):
        assert references and all(reference() is None for reference in references)
        assert price_references and all(reference() is None for reference in price_references)
        assert all(reference() is None for reference in long_frame_references)
        return tmp_path / (key + "_report.html")

    monkeypatch.setattr(research, "write_factor_report", write_report)
    monkeypatch.setattr(runner, "_load_config", lambda: copy.deepcopy(config))
    monkeypatch.setattr(runner, "load_daily_panel", load_prices)

    output = tmp_path / ("quick_" + key)
    arguments = ["--output-dir", str(output), "--report"]
    arguments.extend(("--data-dir", "synthetic"))

    assert runner.main(arguments) == 0
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["broker"] == {"submit": 0, "cancel": 0}
    assert summary["factor_mode"] == config.get("factor_mode", "native")
    if key == "027":
        assert summary["cells"] == summary["finite"] == 1
        assert summary["indicator"].endswith(".Alpha003")
        assert summary["operator_profile"] == "alpha101-v2"
        assert summary["report"].endswith("_report.html")
    else:
        assert summary["factor_calculation"] == "RAN"
        assert summary["factor_classes"] == {"test": "Factor"}
        assert summary["status"] == "PANEL_ONLY"
