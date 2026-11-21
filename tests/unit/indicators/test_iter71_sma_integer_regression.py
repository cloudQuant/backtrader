"""Targeted regression coverage for the optional exact long-window SMA path."""

import array
import math
import os
import subprocess
import sys
import warnings
from pathlib import Path

import backtrader as bt
import backtrader.indicators.sma as sma
import numpy as np
import pandas as pd
import pytest
from backtrader.errors import FactorComputationError
from backtrader.research import align_to_grid
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec, ResearchSpec
from backtrader.strategies.factor_strategy import FactorStrategy


def _frame(values):
    return pd.DataFrame(
        dict.fromkeys(("open", "high", "low", "close"), values),
        index=pd.date_range("2024-01-01", periods=len(values), freq="min"),
    )


def _run_sma(values, period=256):
    class Strategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.ind.SMA(self.data.close, period=period)

    cerebro = bt.Cerebro(stdstats=False, runonce=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Strategy)
    return cerebro.run()[0].sma.array


def _assert_windows(values, actual, period=256):
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if any(math.isnan(value) for value in window):
            assert math.isnan(actual[i]), i
        else:
            assert actual[i].hex() == (math.fsum(window) / period).hex(), i


def _observe_fast_path(monkeypatch):
    calls = []
    original = sma._once_integer_sma

    def observe(*args):
        result = original(*args)
        calls.append(result)
        return result

    monkeypatch.setattr(sma, "_once_integer_sma", observe)
    return calls


@pytest.mark.parametrize("period", [256, 512])
def test_enabled_fast_path_matches_fsum_each_slot(monkeypatch, period):
    values = [100.0 + (i % 17) / 8 for i in range(1900)]
    calls = _observe_fast_path(monkeypatch)
    actual = _run_sma(values, period)
    assert True in calls
    _assert_windows(values, actual, period)


def test_nan_window_falls_back_and_recovers(monkeypatch):
    values = [100.0 + (i % 17) / 8 for i in range(1600)]
    values[700] = math.nan
    calls = _observe_fast_path(monkeypatch)
    actual = _run_sma(values)
    assert calls and not any(calls)
    _assert_windows(values, actual)
    assert math.isfinite(actual[956])


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_raw_nonfinite_fast_path_falls_back_without_writing(bad):
    source = array.array("d", [100.0] * 1600)
    source[700] = bad
    target = array.array("d", [-12345.0] * 1600)
    before = target.tobytes()
    assert sma._once_integer_sma(source, target, 255, 1600, 256) is False
    assert target.tobytes() == before


@pytest.mark.skipif(not hasattr(np, "set_numeric_ops"), reason="NumPy 2 removed set_numeric_ops")
@pytest.mark.parametrize("name", ["add", "true_divide"])
def test_numpy_numeric_ops_cannot_change_fast_path(monkeypatch, name):
    values = [100.0 + (i % 17) / 8 for i in range(1600)]
    calls = _observe_fast_path(monkeypatch)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        original = np.set_numeric_ops()
    seen = []

    def hook(*args, **kwargs):
        seen.append(name)
        return original[name](*args, **kwargs)

    class Strategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.ind.SMA(self.data.close, period=256)

        def start(self):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                np.set_numeric_ops(**{name: hook})

    cerebro = bt.Cerebro(stdstats=False, runonce=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Strategy)
    try:
        actual = cerebro.run()[0].sma.array
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            np.set_numeric_ops(**original)
    assert True in calls
    assert not seen
    _assert_windows(values, actual)


def test_no_numpy_light_import_uses_fallback():
    script = r"""
import datetime
import importlib.abc
import math
import sys

class BlockNumpy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "numpy" or fullname.startswith("numpy."):
            raise ModuleNotFoundError("blocked numpy", name=fullname)

sys.meta_path.insert(0, BlockNumpy())
import backtrader as bt
import backtrader.indicators.sma as sma
values = [100.0 + (i % 17) / 8 for i in range(1600)]
calls = []
original = sma._once_integer_sma
def observe(*args):
    result = original(*args)
    calls.append(result)
    return result
sma._once_integer_sma = observe
class Feed(bt.feed.DataBase):
    def __init__(self):
        super().__init__()
        self.index = 0
    def _load(self):
        if self.index == len(values):
            return False
        value = values[self.index]
        self.lines.datetime[0] = bt.date2num(datetime.datetime(2024, 1, 1) + datetime.timedelta(minutes=self.index))
        self.lines.open[0] = self.lines.high[0] = self.lines.low[0] = self.lines.close[0] = value
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        self.index += 1
        return True
class Strategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.ind.SMA(self.data, period=256)
cerebro = bt.Cerebro(stdstats=False, runonce=True)
cerebro.adddata(Feed())
cerebro.addstrategy(Strategy)
actual = cerebro.run()[0].sma.array
assert calls and not any(calls)
assert "numpy" not in sys.modules
for i in range(255, len(values)):
    assert actual[i].hex() == (math.fsum(values[i-255:i+1]) / 256).hex()
"""
    root = Path(bt.__file__).resolve().parent.parent
    env = os.environ.copy()
    env["BACKTRADER_LIGHT_IMPORT"] = "1"
    env["PYTHONPATH"] = str(root)
    subprocess.run([sys.executable, "-B", "-c", script], cwd=root, env=env, check=True)


def _research_inputs():
    idx = pd.date_range("2024-01-01", periods=1600, freq="D", tz="UTC").rename("close_time")
    values = [100.0 + i * 0.01 + math.sin(i / 13) for i in range(len(idx))]
    data = pd.DataFrame(
        {
            "open": values,
            "high": [v + 1 for v in values],
            "low": [v - 1 for v in values],
            "close": values,
            "volume": 100.0,
            "openinterest": 0.0,
        },
        index=idx,
    )
    grid = pd.DataFrame({"open_time": idx - pd.Timedelta(hours=6)}, index=idx)
    research = ResearchSpec(
        grid=grid,
        start=idx[0],
        end=idx[-1],
        targets=("asset-0",),
        source_timezone="UTC",
        snapshot_id="sma-grid-test",
        price_basis="synthetic",
        calendar_id="daily",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"asset-0": "market"},
    )
    return data, research


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("case", ["finite", "missing", "overflow"])
def test_real_factor_strategy_strict_contract(monkeypatch, once, case):
    data, research = _research_inputs()
    if case == "missing":
        data.loc[data.index[700], "close"] = math.nan
    elif case == "overflow":
        data.loc[:, "close"] = 1e308
    calls = _observe_fast_path(monkeypatch)
    children = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = bt.ind.SMA(self.data.close, period=256)
            children.append(self.child)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child[0]

    cerebro = bt.Cerebro(stdstats=False, runonce=once)
    cerebro.adddata(align_to_grid(data, research, "asset-0").feed, name="asset-0")
    factor = FactorSpec(
        name="f",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"f": factor})
    if case == "overflow":
        with pytest.raises(FactorComputationError):
            cerebro.run(preload=True)
    else:
        cerebro.run(preload=True)
        if once:
            assert (case == "finite") in calls
        _assert_windows(list(data["close"]), children[0].array)
