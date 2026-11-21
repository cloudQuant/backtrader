"""Previous-close indicators respect their warmup in both execution modes."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest


CLASSES = (bt.indicators.TrueHigh, bt.indicators.TrueLow, bt.indicators.TrueRange)


def _frame(n, freq="D"):
    close = [100.0 + (i % 4 - 2) * 2 + i * .2 for i in range(n)]
    return pd.DataFrame({"open": close, "high": [v + 1 for v in close],
                         "low": [v - 1.5 for v in close], "close": close,
                         "volume": [10.0] * n},
                        index=pd.date_range("2020-01-01", periods=n, freq=freq))


def _expected(high, low, previous_close):
    high = max(high, previous_close)
    low = min(low, previous_close)
    return high, low, high - low


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("count", [1, 2, 20])
def test_full_history_has_no_value_before_previous_close(runonce, count):
    frame = _frame(count)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicators = [cls(self.data) for cls in CLASSES]

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe)
    result = engine.run()[0]
    for indicator in result.indicators:
        assert indicator._minperiod == 2
        assert math.isnan(indicator.lines[0].array[0])
        assert len(indicator.lines[0].array) == count
    for i in range(1, count):
        expected = _expected(frame.high.iloc[i], frame.low.iloc[i], frame.close.iloc[i - 1])
        assert tuple(ind.lines[0].array[i] for ind in result.indicators) == pytest.approx(expected)


@pytest.mark.parametrize("cls,output", zip(CLASSES, ("truehigh", "truelow", "tr")))
def test_once_only_writes_requested_slice(cls, output):
    class Line:
        def __init__(self, values):
            self.array = values

    data = SimpleNamespace(high=Line([4., 8., 5., 9.]), low=Line([2., 3., 1., 4.]),
                           close=Line([3., 6., 2., 7.]))
    target = Line([float("nan"), -10., -11., -12.])
    instance = SimpleNamespace(data=data, lines=SimpleNamespace(**{output: target}))
    cls.once(instance, 2, 3)
    assert math.isnan(target.array[0])
    assert target.array[1] == -10. and target.array[3] == -12.
    assert target.array[2] == _expected(5., 1., 6.)[CLASSES.index(cls)]


@pytest.mark.parametrize("cls,output", zip(CLASSES, ("truehigh", "truelow", "tr")))
def test_once_clears_reused_first_slot_only_when_requested(cls, output):
    class Line:
        def __init__(self, values):
            self.array = values

    data = SimpleNamespace(high=Line([4., 8.]), low=Line([2., 3.]),
                           close=Line([3., 6.]))
    target = Line([42., 43.])
    instance = SimpleNamespace(data=data, lines=SimpleNamespace(**{output: target}))

    cls.once(instance, 0, 0)
    assert target.array == [42., 43.]
    cls.once(instance, 1, 2)
    assert target.array[0] == 42.
    expected_second = _expected(8., 3., 3.)[CLASSES.index(cls)]
    assert target.array[1] == expected_second
    cls.once(instance, 0, 1)
    assert math.isnan(target.array[0])
    assert target.array[1] == expected_second


def test_actual_indicator_buffers_clear_reused_first_slot():
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicators = [cls(self.data) for cls in CLASSES]

    engine = bt.Cerebro(runonce=True, preload=True, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=_frame(10)))
    engine.addstrategy(Probe)
    for ind in engine.run()[0].indicators:
        line = ind.lines[0].array
        line[0] = 123.0
        ind.once(1, 10)
        assert line[0] == 123.0
        second = line[1]
        ind.once(0, 1)
        assert math.isnan(line[0])
        assert line[1] == second


@pytest.mark.parametrize("runonce", [False, True])
def test_slow_second_feed_uses_its_previous_close(runonce):
    slow = _frame(12, "3D")

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicators = [cls(self.datas[1]) for cls in CLASSES]

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=_frame(36)))
    engine.adddata(bt.feeds.PandasData(dataname=slow))
    engine.addstrategy(Probe)
    indicators = engine.run()[0].indicators
    for ind in indicators:
        assert math.isnan(ind.lines[0].array[0])
    for i in range(1, len(slow)):
        actual = tuple(ind.lines[0].array[i] for ind in indicators)
        assert actual == pytest.approx(_expected(slow.high.iloc[i], slow.low.iloc[i], slow.close.iloc[i - 1]))


def test_replay_revisions_use_previous_completed_bar():
    rows, dates = [], []
    for i in range(8):
        for hour, offset in ((9, 0.), (10, 3.), (11, -2.)):
            close = 100 + i + offset
            rows.append({"open": close, "high": close + 1, "low": close - 1,
                         "close": close, "volume": 1.})
            dates.append(pd.Timestamp("2020-01-01") + pd.Timedelta(days=i, hours=hour))
    frame = pd.DataFrame(rows, index=pd.DatetimeIndex(dates))

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicators = [cls(self.data) for cls in CLASSES]
            self.seen = []

        def next(self):
            expected = _expected(self.data.high[0], self.data.low[0], self.data.close[-1])
            self.seen.append((len(self.data), tuple(ind[0] for ind in self.indicators), expected))

    engine = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    feed = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=60)
    engine.replaydata(feed, timeframe=bt.TimeFrame.Days)
    engine.addstrategy(Probe)
    seen = engine.run()[0].seen
    assert len(seen) >= 20
    assert len({n for n, _, _ in seen}) >= 7
    for _, actual, expected in seen:
        assert actual == pytest.approx(expected)
