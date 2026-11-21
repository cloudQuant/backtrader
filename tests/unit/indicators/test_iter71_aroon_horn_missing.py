"""Aroon-Horn must not emit a signal from an incomplete input window."""

import importlib.util
import math
import random
import sys
from pathlib import Path

import pandas as pd
import pytest

import backtrader as bt


def _frame(seed=1, count=40):
    rng = random.Random(seed)
    prices = [100.0]
    for _ in range(count - 1):
        prices.append(prices[-1] + rng.choice([-2.0, -1.0, 0.0, 1.0, 2.0]))
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + 2 for p in prices],
            "low": [p - 2 for p in prices],
            "close": prices,
            "volume": [1.0] * len(prices),
            "openinterest": [0.0] * len(prices),
        },
        index=pd.date_range("2024-01-01", periods=len(prices), freq="h"),
    )


def _reference(frame, ap, atr_period):
    result = [(math.nan, math.nan)] * len(frame)
    trend = 0
    for index in range(max(ap, atr_period) + 2, len(frame)):
        window = frame.iloc[index - ap + 1 : index + 1]
        if window[["high", "low"]].isna().any().any():
            continue
        highs = list(reversed(window.high.tolist()))
        lows = list(reversed(window.low.tolist()))
        bulls = 100 - (highs.index(max(highs)) + 0.5) * 100 / ap
        bears = 100 - (lows.index(min(lows)) + 0.5) * 100 / ap
        new_trend = trend
        if bulls > bears and bulls >= 50:
            new_trend = 1
        if bulls < bears and bears >= 50:
            new_trend = -1
        bear = bull = 0.0
        if trend * new_trend < 0:
            trs = []
            for j in range(atr_period):
                row, previous = frame.iloc[index - j], frame.iloc[index - j - 1]
                if any(math.isnan(v) for v in (row.high, row.low, previous.close)):
                    break
                trs.append(
                    max(
                        row.high - row.low,
                        abs(row.high - previous.close),
                        abs(row.low - previous.close),
                    )
                )
            if len(trs) != atr_period:
                continue
            atr = sum(trs) / atr_period
            if new_trend > 0:
                bull = float(frame.low.iloc[index]) - atr * 3 / 8
            else:
                bear = float(frame.high.iloc[index]) + atr * 3 / 8
        trend = new_trend
        result[index] = (bear, bull)
    return result


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize(
    "field,index", [(None, 0), ("high", 12), ("low", 12), ("close", 12), ("close", 9)]
)
def test_visible_window_missing_and_recovery_against_independent_reference(once, field, index):
    frame = _frame()
    if field:
        frame.loc[frame.index[index], field] = math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = bt.ind.AroonHornSignIndicator(self.data, aroon_period=3, atr_period=1)

    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe)
    ind = engine.run()[0].ind
    assert ind._minperiod == 6
    for actual, expected in zip(
        zip(ind.bears_aroon.array, ind.bulls_aroon.array), _reference(frame, 3, 1)
    ):
        for value, ref in zip(actual, expected):
            if math.isnan(ref):
                assert math.isnan(value)
            else:
                assert value == pytest.approx(ref)
    if field in ("high", "low"):
        assert math.isnan(ind.bears_aroon.array[13])
        assert math.isnan(ind.bulls_aroon.array[14])
        assert math.isfinite(ind.bears_aroon.array[15])
    if field == "close" and index == 9:
        assert math.isnan(ind.bears_aroon.array[10])
        assert math.isnan(ind.bulls_aroon.array[10])


def _strategy_class():
    root = next(
        parent for parent in Path(__file__).resolve().parents if (parent / "backtrader").is_dir()
    )
    path = root / "tests/functional/strategies/trend_following/test_0252_0894_aroonhornsign.py"
    spec = importlib.util.spec_from_file_location("_aroon_missing_strategy", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    class Probe(module.ExpAroonHornSignStrategy):
        def __init__(self):
            super().__init__()
            self.messages = []
            self.actions = []

        def log(self, text):
            self.messages.append((len(self.signal_data) - 1, text))

        def buy(self, *args, **kwargs):
            self.actions.append(("buy", len(self.signal_data) - 1))
            return super().buy(*args, **kwargs)

        def sell(self, *args, **kwargs):
            self.actions.append(("sell", len(self.signal_data) - 1))
            return super().sell(*args, **kwargs)

    return Probe


@pytest.mark.parametrize("once", [False, True])
def test_existing_strategy_does_not_trade_on_a_missing_aroon_window(once):
    Probe = _strategy_class()
    base = _frame()
    signal = base.copy()
    signal.loc[signal.index[12], "high"] = math.nan
    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=base))
    engine.adddata(bt.feeds.PandasData(dataname=signal))
    engine.addstrategy(
        Probe, aroon_period=3, atr_period=1, stop_loss_points=0, take_profit_points=0
    )
    strategy = engine.run(preload=True)[0]
    assert not [action for action in strategy.actions if action[1] in (13, 14)]
    assert not [
        message
        for message in strategy.messages
        if message[0] in (13, 14) and "signal" in message[1]
    ]


@pytest.mark.parametrize("once", [False, True])
def test_missing_arrow_blocks_historical_signal_exit(once):
    Probe = _strategy_class()
    base = _frame(seed=0, count=101).iloc[1:].copy()
    signal = base.copy()
    signal.loc[signal.index[18], "high"] = math.nan
    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=base))
    engine.adddata(bt.feeds.PandasData(dataname=signal))
    engine.addstrategy(
        Probe, aroon_period=3, atr_period=1, fixed_lot=1, stop_loss_points=0, take_profit_points=0
    )
    strategy = engine.run(preload=True)[0]
    assert math.isnan(strategy.indicator.bears_aroon.array[18])
    assert math.isnan(strategy.indicator.bulls_aroon.array[18])
    assert not [action for action in strategy.actions if action[1] == 18]
    assert not [
        message for message in strategy.messages if message[0] == 18 and "hist" in message[1]
    ]


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("exit_type,price", [("SL", 98.0), ("TP", 102.0)])
def test_protective_exit_precedes_missing_signal_gate(once, exit_type, price):
    class Probe(_strategy_class()):
        def next(self):
            super().next()
            if len(self.signal_data) - 1 == 10:
                self.buy(size=0.1)

    base = _frame()
    for column, value in (("open", 100.0), ("high", 101.0), ("low", 99.0), ("close", 100.0)):
        base[column] = value
    base.loc[base.index[12], "close"] = price
    base.loc[base.index[12], "high"] = max(101.0, price)
    base.loc[base.index[12], "low"] = min(99.0, price)
    signal = base.copy()
    signal.loc[signal.index[12], "high"] = math.nan
    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=base))
    engine.adddata(bt.feeds.PandasData(dataname=signal))
    engine.addstrategy(
        Probe,
        aroon_period=3,
        atr_period=1,
        point=1.0,
        stop_loss_points=1,
        take_profit_points=1,
        buy_pos_open=False,
        sell_pos_open=False,
        buy_pos_close=False,
        sell_pos_close=False,
    )
    strategy = engine.run(preload=True)[0]
    assert math.isnan(strategy.indicator.bears_aroon.array[12])
    assert math.isnan(strategy.indicator.bulls_aroon.array[12])
    assert ("sell", 12) in strategy.actions
    assert any(
        index == 12 and f"close long {exit_type}" in text for index, text in strategy.messages
    )


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("exit_type,price", [("SL", 102.0), ("TP", 98.0)])
def test_short_protective_exit_precedes_missing_signal_gate(once, exit_type, price):
    class Probe(_strategy_class()):
        def next(self):
            super().next()
            if len(self.signal_data) - 1 == 10:
                self.sell(size=0.1)

    base = _frame()
    for column, value in (("open", 100.0), ("high", 101.0), ("low", 99.0), ("close", 100.0)):
        base[column] = value
    base.loc[base.index[12], "close"] = price
    base.loc[base.index[12], "high"] = max(101.0, price)
    base.loc[base.index[12], "low"] = min(99.0, price)
    signal = base.copy()
    signal.loc[signal.index[12], "high"] = math.nan
    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=base))
    engine.adddata(bt.feeds.PandasData(dataname=signal))
    engine.addstrategy(
        Probe,
        aroon_period=3,
        atr_period=1,
        point=1.0,
        stop_loss_points=1,
        take_profit_points=1,
        buy_pos_open=False,
        sell_pos_open=False,
        buy_pos_close=False,
        sell_pos_close=False,
    )
    strategy = engine.run(preload=True)[0]
    assert math.isnan(strategy.indicator.bears_aroon.array[12])
    assert math.isnan(strategy.indicator.bulls_aroon.array[12])
    assert ("buy", 12) in strategy.actions
    assert any(
        index == 12 and f"close short {exit_type}" in text for index, text in strategy.messages
    )
