"""TriggerLine's first published signal uses the preceding price window."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.trigger_line import TriggerLine


def _frame(count, *, every=1, missing=None):
    close = [100.0 + i * 2.0 + i * i * 0.05 for i in range(count)]
    if missing is not None:
        close[missing] = math.nan
    return pd.DataFrame(
        {
            "open": [v - 0.4 for v in close],
            "high": [v + 1.0 for v in close],
            "low": [v - 1.5 for v in close],
            "close": close,
            "volume": [100.0] * count,
        },
        index=pd.date_range("2020-01-01", periods=count, freq=f"{every}D"),
    )


def _reference(frame, index, period, signal_period, price):
    def price_at(i):
        row = frame.iloc[i]
        if price == "typical":
            return (row.high + row.low + row.close) / 3.0
        return row[price]

    def main_at(i):
        return 6.0 / (period * (period + 1.0)) * sum(
            (period - lag - (period + 1.0) / 3.0) * price_at(i - lag)
            for lag in range(period)
        )

    previous, current = main_at(index - 1), main_at(index)
    alpha = 2.0 / (signal_period + 1.0)
    return current, (1.0 - alpha) * previous + alpha * current


def _run(frame, runonce, *, period=24, signal_period=6, price="close", cls=TriggerLine,
         primary=None):
    class Strategy(bt.Strategy):
        def __init__(self):
            data = self.datas[-1]
            self.ind = cls(data, rperiod=period, lsma_period=signal_period, price=price)
            self.first = None

        def nextstart(self):
            self.first = (len(self.datas[-1]), float(self.ind.main[0]), float(self.ind.signal[0]))
            self.next()

        def next(self):
            pass

    c = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    if primary is not None:
        c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Strategy)
    return c.run()[0]


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "once"))
@pytest.mark.parametrize("period,signal_period,price", [(1, 1, "close"), (4, 3, "open"),
                                                         (24, 6, "typical")])
def test_first_callback_and_following_match_independent_price_reference(
    runonce, period, signal_period, price
):
    frame = _frame(period + 12)
    strategy = _run(frame, runonce, period=period, signal_period=signal_period, price=price)
    minperiod = period + 3
    assert strategy.ind._minperiod == minperiod
    assert strategy.first[0] == minperiod
    main, signal = _reference(frame, minperiod - 1, period, signal_period, price)
    assert strategy.first[1:] == pytest.approx((main, signal))
    assert all(math.isnan(v) for v in strategy.ind.main.array[:minperiod - 1])
    assert all(math.isnan(v) for v in strategy.ind.signal.array[:minperiod - 1])
    for index in range(minperiod - 1, len(frame)):
        main, signal = _reference(frame, index, period, signal_period, price)
        assert strategy.ind.main.array[index] == pytest.approx(main)
        assert strategy.ind.signal.array[index] == pytest.approx(signal)


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "once"))
def test_short_history_stays_in_warmup(runonce):
    strategy = _run(_frame(26), runonce)
    assert strategy.ind._minperiod == 27
    assert strategy.first is None
    assert all(math.isnan(v) for v in strategy.ind.main.array)
    assert all(math.isnan(v) for v in strategy.ind.signal.array)


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "once"))
def test_missing_price_does_not_get_fabricated_or_reseeded(runonce):
    frame = _frame(45, missing=26)
    strategy = _run(frame, runonce)
    assert math.isnan(strategy.ind.main.array[26])
    assert math.isnan(strategy.ind.signal.array[26])
    assert math.isnan(strategy.ind.signal.array[27])


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "once"))
def test_subclass_prenext_previous_main_is_preserved(runonce):
    class CustomWarmup(TriggerLine):
        def prenext(self):
            self.lines.main[0] = 500.0

    frame = _frame(30)
    strategy = _run(frame, runonce, cls=CustomWarmup)
    main, _ = _reference(frame, 26, 24, 6, "close")
    assert strategy.first[1] == pytest.approx(main)
    assert strategy.first[2] == pytest.approx(500.0 + (main - 500.0) * 2.0 / 7.0)


@pytest.mark.parametrize("runonce", (False, True), ids=("next", "once"))
def test_secondary_feed_clock_uses_its_own_preceding_price_window(runonce):
    frame = _frame(34, every=3)
    primary = _frame(100)
    strategy = _run(frame, runonce, primary=primary)
    assert strategy.ind._minperiod == 27
    assert len(strategy.ind.main.array) == len(frame)
    for index in range(26, len(frame)):
        main, signal = _reference(frame, index, 24, 6, "close")
        assert strategy.ind.main.array[index] == pytest.approx(main)
        assert strategy.ind.signal.array[index] == pytest.approx(signal)
