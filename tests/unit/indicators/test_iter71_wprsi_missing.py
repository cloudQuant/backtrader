"""Real Cerebro checks for unavailable WPR/RSI signal inputs."""

import math
import random

import backtrader as bt
import pandas as pd
import pytest


def _bars(count=300):
    rng = random.Random(731)
    price = 100.0
    bars = []
    for _ in range(count):
        price += rng.uniform(-4, 4)
        bars.append(
            {
                "open": price - 0.1,
                "high": price + rng.uniform(0.1, 2),
                "low": price - rng.uniform(0.1, 2),
                "close": price,
                "volume": 1.0,
            }
        )
    return bars


def _reference(bars, index):
    period = 5

    def wpr(ago):
        window = bars[index - ago - period + 1 : index - ago + 1]
        source = [bar[field] for bar in window for field in ("high", "low")]
        close = bars[index - ago]["close"]
        if any(math.isnan(value) for value in (*source, close)):
            return math.nan
        high = max(bar["high"] for bar in window)
        low = min(bar["low"] for bar in window)
        return -50.0 if high == low else -100.0 * (high - close) / (high - low)

    diffs = [bars[index - i]["close"] - bars[index - i - 1]["close"] for i in range(period)]
    if any(math.isnan(value) for value in diffs):
        return (math.nan, math.nan)
    gains = sum(value for value in diffs if value > 0) / period
    losses = -sum(value for value in diffs if value <= 0) / period
    rsi = 100.0 if losses == 0 else 100.0 - 100.0 / (1.0 + gains / losses)
    now, prev = wpr(0), wpr(1)
    if math.isnan(now) or math.isnan(prev):
        return (math.nan, math.nan)
    high, low = bars[index]["high"], bars[index]["low"]
    spread = high - low
    buy = sell = 0.0
    if now > -20 and prev < -20 and rsi > 50:
        filtered = [wpr(k) for k in range(2, 5)]
        if not any(value > -20 for value in filtered if not math.isnan(value)):
            buy = math.nan if any(math.isnan(value) for value in filtered) else low - spread / 2
    if prev > -80 and now < -80 and rsi < 50:
        filtered = [wpr(k) for k in range(2, 5)]
        if not any(value < -80 for value in filtered if not math.isnan(value)):
            sell = math.nan if any(math.isnan(value) for value in filtered) else high + spread / 2
    return (buy, sell)


def _run(bars, runonce):
    frame = pd.DataFrame(bars, index=pd.date_range("2025-01-01", periods=len(bars)))

    class Strategy(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.WPRSISignalIndicator(
                self.data, wprsi_period=5, filter_up=2, filter_dn=2
            )
            self.signals = []
            self.submitted = []

        def next(self):
            buy = float(self.indicator.buy_arrow[0])
            if not math.isnan(buy) and buy != 0.0:
                self.signals.append(len(self.data) - 1)
                if len(self.data) - 1 == 26:
                    self.buy()
                    self.submitted.append(26)

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Strategy)
    result = engine.run()[0]
    return (
        list(result.indicator.buy_arrow.array),
        list(result.indicator.sell_arrow.array),
        result.signals,
        result.submitted,
    )


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("field", [None, "high", "low", "close"])
def test_missing_and_finite_match_independent_reference(runonce, field):
    bars = _bars()
    if field is not None:
        bars[24][field] = math.nan
    buy, sell, _, _ = _run(bars, runonce)
    for index in range(9, len(bars)):
        expected = _reference(bars, index)
        for actual, want in zip((buy[index], sell[index]), expected):
            if math.isnan(want):
                assert math.isnan(actual), (field, index, actual)
            else:
                assert actual == pytest.approx(want, rel=1e-12, abs=1e-12), (field, index)
    assert all(math.isfinite(buy[i]) and math.isfinite(sell[i]) for i in range(35, len(bars)))


@pytest.mark.parametrize("runonce", [False, True])
def test_missing_historical_high_does_not_create_buy_signal(runonce):
    bars = _bars()
    assert _reference(bars, 26)[0] != 0.0
    bars[24]["high"] = math.nan
    buy, sell, signals, submitted = _run(bars, runonce)
    assert math.isnan(buy[26])
    assert math.isnan(sell[26])
    assert 26 not in signals
    assert 26 not in submitted


@pytest.mark.parametrize("runonce", [False, True])
def test_filter_only_missing_makes_only_sell_unknown(runonce):
    bars = _bars()
    assert _reference(bars, 19)[1] != 0.0
    bars[13]["high"] = math.nan
    buy, sell, _, _ = _run(bars, runonce)
    assert buy[19] == 0.0
    assert math.isnan(sell[19])
    assert all(math.isfinite(buy[i]) and math.isfinite(sell[i]) for i in range(25, len(bars)))


@pytest.mark.parametrize("runonce", [False, True])
def test_flat_prices_keep_zero_loss_and_flat_wpr_behavior(runonce):
    bars = [
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0}
        for _ in range(40)
    ]
    buy, sell, _, _ = _run(bars, runonce)
    assert all(value == 0.0 for value in buy[9:])
    assert all(value == 0.0 for value in sell[9:])
