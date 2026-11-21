"""ADL and Chaikin oscillator independent recurrence and replay checks."""
import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.accumulation_distribution_line import (
    AccumulationDistributionLine, ChaikinOscillator,
)


def _frame(count=40):
    rows = []
    for i in range(count):
        low = 100.0 + i * 0.1
        high = low + 2.0
        close = low + 1.0 + 0.7 * math.sin(i * 0.6)
        rows.append((low + 1.0, high, low, close, 100.0 + i))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"],
                        index=pd.date_range("2024-01-01", periods=count, freq="min"))


def _reference(frame, fast=3, slow=5):
    adl, current = [], 0.0
    for row in frame.itertuples():
        if not all(math.isfinite(x) for x in (row.high, row.low, row.close, row.volume)):
            current = math.nan
        else:
            multiplier = 0.0 if row.high == row.low else (2.0 * row.close - row.high - row.low) / (row.high - row.low)
            current += multiplier * row.volume
        adl.append(current)

    def ema(period):
        out = [math.nan] * len(adl)
        if len(adl) >= period:
            out[period-1] = sum(adl[:period]) / period
            alpha = 2.0 / (period + 1)
            for i in range(period, len(adl)):
                out[i] = alpha * adl[i] + (1-alpha) * out[i-1]
        return out

    fast_values, slow_values = ema(fast), ema(slow)
    return adl, [f-s for f, s in zip(fast_values, slow_values)]


def _run(frame, runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.chaikin = ChaikinOscillator(self.data, fast_period=3, slow_period=5)

    engine = bt.Cerebro(stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe)
    indicator = engine.run(runonce=runonce, preload=True)[0].chaikin
    return list(indicator.adl.adl.array), list(indicator.cho.array)


def _assert_series(actual, expected):
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        if math.isnan(e):
            assert math.isnan(a)
        else:
            assert a == pytest.approx(e, rel=1e-11, abs=1e-11)


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("count", [1, 4, 5, 40])
def test_adl_and_chaikin_against_reference(runonce, count):
    frame = _frame(count)
    # Exercise the flat-price zero multiplier and a normal later bar.
    if count > 7:
        frame.iloc[7, frame.columns.get_indexer(["open", "high", "low", "close"])] = 101.0
    actual = _run(frame, runonce)
    expected = _reference(frame)
    for a, e in zip(actual, expected):
        _assert_series(a, e)


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("flat", [False, True], ids=["range", "flat"])
def test_missing_close_never_creates_valid_adl(runonce, flat):
    frame = _frame()
    if flat:
        frame.iloc[12, frame.columns.get_indexer(["high", "low"])] = 101.0
    frame.iloc[12, frame.columns.get_loc("close")] = math.nan
    actual = _run(frame, runonce)
    expected = _reference(frame)
    for a, e in zip(actual, expected):
        _assert_series(a, e)
    assert all(math.isnan(v) for v in actual[0][12:])


@pytest.mark.parametrize("flat", [False, True], ids=["range", "flat"])
def test_replay_each_revision_recomputes_adl_from_completed_bar(flat):
    frame = _frame(35)
    if flat:
        frame.loc[:, ["open", "high", "low", "close"]] = 100.0
    frame.iloc[8, frame.columns.get_loc("close")] = math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self.adl = AccumulationDistributionLine(self.data)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data), float(self.data.high[0]), float(self.data.low[0]),
                              float(self.data.close[0]), float(self.data.volume[0]), float(self.adl[0])))

    engine = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    engine.replaydata(bt.feeds.PandasData(dataname=frame), timeframe=bt.TimeFrame.Minutes, compression=5)
    engine.addstrategy(Probe)
    rows = engine.run()[0].rows
    previous, value, previous_bar = 0.0, 0.0, None
    saw_invalid = saw_recovery = False
    for bar, high, low, close, volume, actual in rows:
        if bar != previous_bar:
            previous = value
            previous_bar = bar
        if not all(math.isfinite(x) for x in (high, low, close, volume)):
            value = math.nan
            saw_invalid = True
        else:
            multiplier = 0.0 if high == low else (2*close-high-low)/(high-low)
            value = previous + multiplier * volume
            if saw_invalid and math.isfinite(previous):
                saw_recovery = True
        if math.isnan(value):
            assert math.isnan(actual)
        else:
            assert actual == pytest.approx(value, rel=1e-11, abs=1e-11)
    assert saw_invalid and saw_recovery


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("output", ["adl", "cho"])
def test_strict_factor_preserves_missing_input(runonce, output):
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec

    frame = _frames(periods=25)["asset-0"].copy()
    frame.iloc[12, frame.columns.get_indexer(["high", "low"])] = 101.0
    frame.iloc[12, frame.columns.get_loc("close")] = math.nan
    research = _research_spec({"asset-0": frame})

    instances = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.chaikin = ChaikinOscillator(self.data, fast_period=3, slow_period=5)
            instances.append(self)

        def next(self):
            line = self.chaikin.adl.adl if output == "adl" else self.chaikin.cho
            self.outputs[self.datas[0]].factor[0] = line[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    spec = FactorSpec(name="adl", indicator=Factor, panel_line="factor",
                      field_bindings={"close": "feed:target:close"}, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"adl": spec})
    engine.run(preload=True)
    indicator = instances[0].chaikin
    observed = indicator.adl.adl.array if output == "adl" else indicator.cho.array
    assert all(math.isnan(value) for value in observed[12:])

@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("field", ["high", "low", "close", "volume"])
def test_missing_input_invalidates_adl_and_chaikin(runonce, field):
    frame = _frame()
    frame.iloc[12, frame.columns.get_loc(field)] = math.nan
    adl, chaikin = _run(frame, runonce)
    assert all(math.isnan(value) for value in adl[12:])
    assert all(math.isnan(value) for value in chaikin[12:])
