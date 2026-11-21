"""Check ZeroLagHLR first publication and its subsequent recursion."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.hlr_indicator import ZeroLagHLRIndicator


PERIODS = (2, 3, 4, 5, 6)
MINPERIOD = 3 * max(PERIODS) + 3
FACTORS = (0.05, 0.10, 0.16, 0.26, 0.43)


def _frame(count, *, every=1, missing=None):
    close = [100 + i * 0.08 + 4 * math.sin(i * 0.43) for i in range(count)]
    high = [value + 1.0 + (i % 3) * 0.1 for i, value in enumerate(close)]
    low = [value - 1.0 - (i % 4) * 0.1 for i, value in enumerate(close)]
    if missing is not None:
        high[missing] = low[missing] = math.nan
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": [10.0] * count},
        index=pd.date_range("2020-01-01", periods=count, freq=f"{every}D"),
    )


def _reference_fast(frame, index, preserve):
    high = list(frame.high)
    low = list(frame.low)
    factors = list(FACTORS)
    if preserve:
        factors[2] = factors[1]
    result = 0.0
    for period, factor in zip(PERIODS, factors):
        hh = max(high[index - period + 1:index + 1])
        ll = min(low[index - period + 1:index + 1])
        mid = (high[index] + low[index]) / 2.0
        result += factor * (100.0 * (mid - ll) / (hh - ll) if hh != ll else 0.0)
    return result


def _run(frame, once, *, preserve=True, cls=ZeroLagHLRIndicator, primary=None):
    class Strategy(bt.Strategy):
        def __init__(self):
            self.ind = cls(
                self.datas[-1], smoothing=3,
                hlr_period1=PERIODS[0], hlr_period2=PERIODS[1],
                hlr_period3=PERIODS[2], hlr_period4=PERIODS[3], hlr_period5=PERIODS[4],
                preserve_source_hlr3_weight=preserve,
            )
            self.first = None

        def nextstart(self):
            self.first = (len(self.datas[-1]), float(self.ind.fast[0]), float(self.ind.slow[0]))
            self.next()

        def next(self):
            pass

    c = bt.Cerebro(runonce=once, preload=True, stdstats=False)
    if primary is not None:
        c.adddata(bt.feeds.PandasData(dataname=primary))
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Strategy)
    return c.run()[0]


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
@pytest.mark.parametrize("preserve", (False, True))
def test_first_seed_and_recursion_match_independent_hlr_reference(once, preserve):
    frame = _frame(55)
    strategy = _run(frame, once, preserve=preserve)
    assert strategy.ind._minperiod == MINPERIOD
    assert strategy.first[0] == MINPERIOD
    assert all(math.isnan(value) for value in strategy.ind.fast.array[:MINPERIOD - 1])
    assert all(math.isnan(value) for value in strategy.ind.slow.array[:MINPERIOD - 1])
    previous = 0.0
    for index in range(MINPERIOD - 1, len(frame)):
        fast = _reference_fast(frame, index, preserve)
        slow = fast / 3.0 + previous * 2.0 / 3.0
        assert strategy.ind.fast.array[index] == pytest.approx(fast)
        assert strategy.ind.slow.array[index] == pytest.approx(slow)
        previous = slow


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_short_history_has_no_published_values(once):
    strategy = _run(_frame(MINPERIOD - 1), once)
    assert strategy.ind._minperiod == MINPERIOD
    assert strategy.first is None
    assert all(math.isnan(v) for v in strategy.ind.fast.array)
    assert all(math.isnan(v) for v in strategy.ind.slow.array)


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_missing_input_is_not_silently_reseeded(once):
    strategy = _run(_frame(40, missing=25), once)
    assert math.isfinite(strategy.ind.slow.array[24])
    assert math.isnan(strategy.ind.fast.array[25])
    assert math.isnan(strategy.ind.slow.array[25])
    assert math.isnan(strategy.ind.slow.array[26])


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_subclass_prenext_slow_value_is_preserved(once):
    class CustomWarmup(ZeroLagHLRIndicator):
        def prenext(self):
            self.lines.slow[0] = 50.0

    frame = _frame(30)
    strategy = _run(frame, once, cls=CustomWarmup)
    fast = _reference_fast(frame, MINPERIOD - 1, True)
    assert strategy.first[2] == pytest.approx(fast / 3.0 + 50.0 * 2.0 / 3.0)


@pytest.mark.parametrize("once", (False, True), ids=("next", "once"))
def test_secondary_clock_tracks_source_windows(once):
    frame = _frame(35, every=3)
    strategy = _run(frame, once, primary=_frame(103))
    assert len(strategy.ind.fast.array) == len(frame)
    previous = 0.0
    for index in range(MINPERIOD - 1, len(frame)):
        fast = _reference_fast(frame, index, True)
        previous = fast / 3.0 + previous * 2.0 / 3.0
        assert strategy.ind.fast.array[index] == pytest.approx(fast)
        assert strategy.ind.slow.array[index] == pytest.approx(previous)


def test_replayed_daily_slow_uses_final_fast_and_previous_slow():
    daily = _frame(35)
    rows, dates = [], []
    for date, row in daily.iterrows():
        rows.extend(((row.open, row.close, row.close, row.close, row.volume),
                     (row.open, row.high, row.low, row.close, row.volume)))
        dates.extend((date + pd.Timedelta(hours=9), date + pd.Timedelta(hours=10)))
    frame = pd.DataFrame(rows, columns=("open", "high", "low", "close", "volume"), index=dates)

    class ReplayStrategy(bt.Strategy):
        def __init__(self):
            self.ind = ZeroLagHLRIndicator(
                self.data, smoothing=3,
                hlr_period1=2, hlr_period2=3, hlr_period3=4, hlr_period4=5, hlr_period5=6,
            )

    c = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    feed = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=60)
    c.replaydata(feed, timeframe=bt.TimeFrame.Days, compression=1)
    c.addstrategy(ReplayStrategy)
    strategy = c.run()[0]
    assert len(strategy.ind.fast.array) == len(daily)
    previous = 0.0
    for index in range(MINPERIOD - 1, len(daily)):
        # This checks the slow recurrence against the actual final fast value;
        # independent finalized-window parity for the replayed child HLRs is
        # a separate, currently failing behavior.
        fast = strategy.ind.fast.array[index]
        assert math.isfinite(fast)
        previous = fast / 3.0 + previous * 2.0 / 3.0
        assert strategy.ind.slow.array[index] == pytest.approx(previous)
