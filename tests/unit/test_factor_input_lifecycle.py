"""Contracts for explicitly consuming raw frames during native factor setup."""

from __future__ import annotations

import importlib
import importlib.util
import weakref
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = {
    "025": ROOT / "examples" / "backtest" / "025_factor_single" / "run.py",
    "026": ROOT / "examples" / "backtest" / "026_factor_multi" / "run.py",
    "027": ROOT / "examples" / "backtest" / "027_alpha003_panel_acceptance" / "run.py",
}


def _load_runner(key: str):
    spec = importlib.util.spec_from_file_location("factor_input_runner_" + key, RUNNERS[key])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Factor:
    formula_fields = ()
    operator_profile = "alpha101-v2"


class _BaseBroker:
    def __init__(self) -> None:
        pass


@pytest.mark.parametrize("key", ("025", "026", "027"))
@pytest.mark.parametrize("consume_source_frames", (False, True))
@pytest.mark.parametrize("fail_adddata", (False, True))
def test_collection_consumes_source_frames_only_when_explicit(
    key: str,
    consume_source_frames: bool,
    fail_adddata: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backtrader as bt
    import backtrader.brokers as brokers
    import backtrader.research as research_api
    from backtrader.feeds.pandafeed import PandasData

    runner = _load_runner(key)
    config: Dict[str, Any] = runner._load_config()
    config["data"]["data_version"] = "input-lifecycle-fixture-v1"
    assets = ("AAA", "BBB")
    timestamp = pd.Timestamp("2024-01-02", tz="UTC")
    grid = pd.DataFrame(
        {"open_time": [timestamp]}, index=pd.DatetimeIndex([timestamp], name="close_time")
    )
    source_frames = {
        asset: pd.DataFrame(
            {
                "open": [1.0],
                "high": [2.0],
                "low": [0.5],
                "close": [1.5],
                "volume": [10.0],
            },
            index=grid.index,
        )
        for asset in assets
    }
    frame_refs = tuple(weakref.ref(frame) for frame in source_frames.values())
    panel = {
        "grid": grid,
        "assets": assets,
        "feeds": source_frames,
        "research_start_position": 0,
        "research_end_position": 0,
    }
    collected = SimpleNamespace()
    original_align = research_api.align_to_grid
    aligned_assets = []

    def tracked_align(frame, research, asset, *, data_version=None):
        assert asset in assets
        assert data_version == "input-lifecycle-fixture-v1"
        aligned = original_align(frame, research, asset, data_version=data_version)
        aligned_assets.append(asset)
        return aligned

    class FakeCerebro:
        def __init__(self, **_kwargs):
            self.datas = []
            self.strategy_kwargs = None

        def setbroker(self, _broker):
            pass

        def adddata(self, feed, name):
            assert type(feed) is PandasData
            assert isinstance(feed.p.dataname, pd.DataFrame)
            assert len(feed.p.dataname) == 1
            if fail_adddata and name == "BBB":
                raise RuntimeError("synthetic adddata failure")
            self.datas.append((feed, name))

        def addstrategy(self, _strategy, **kwargs):
            self.strategy_kwargs = kwargs

        def run(self, **_kwargs):
            assert len(self.datas) == len(assets)
            assert aligned_assets == list(assets)
            if consume_source_frames:
                assert all(reference() is None for reference in frame_refs)
                assert panel["feeds"] == {}
            else:
                assert all(reference() is not None for reference in frame_refs)
                assert set(panel["feeds"]) == set(assets)
            factor_specs = self.strategy_kwargs["factors"]
            instances = {
                name: [SimpleNamespace(factor_mode=spec.mode)]
                for name, spec in factor_specs.items()
            }
            strategy = SimpleNamespace(
                get_panel=lambda: collected,
                _factor_specs_by_name=factor_specs,
                _factor_instances_by_name=instances,
            )
            return [strategy]

    monkeypatch.setattr(bt, "Cerebro", FakeCerebro)
    monkeypatch.setattr(brokers, "BackBroker", _BaseBroker)
    monkeypatch.setattr(research_api, "FactorSpec", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(research_api, "FactorStrategy", object)
    monkeypatch.setattr(research_api, "MemorySink", lambda: None)
    monkeypatch.setattr(research_api, "align_to_grid", tracked_align)

    def collect() -> None:
        if key == "027":
            alpha_module = importlib.import_module("backtrader.research.alpha101")
            monkeypatch.setattr(alpha_module, "get_alpha", lambda _alpha_id: _Factor)
            runner._run_factor(config, panel, consume_source_frames=consume_source_frames)
        else:
            factor_names = ("close_ma",) if key == "025" else tuple(config["factors"])
            factor_classes = {name: _Factor for name in factor_names}
            monkeypatch.setattr(runner, "_factor_classes", lambda _mode: factor_classes)
            runner._run_native_collection(
                config,
                panel,
                False,
                consume_source_frames=consume_source_frames,
            )

    if fail_adddata:
        with pytest.raises(RuntimeError, match="synthetic adddata failure"):
            collect()
        assert aligned_assets == list(assets)
        if consume_source_frames:
            assert set(panel["feeds"]) == {"BBB"}
            assert frame_refs[0]() is None
            assert frame_refs[1]() is not None
        else:
            assert set(panel["feeds"]) == set(assets)
            assert all(reference() is not None for reference in frame_refs)
        return

    collect()
    if consume_source_frames:
        assert panel["feeds"] == {}
        assert all(reference() is None for reference in frame_refs)
    else:
        assert set(panel["feeds"]) == set(assets)
        assert all(reference() is not None for reference in frame_refs)
