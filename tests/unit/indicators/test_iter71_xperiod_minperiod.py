"""XPeriod candle starts on the first complete smoothed candle window."""

import math

import pandas as pd
import pytest

import backtrader as bt


def _frame(size):
    opens = [10.0 + i * 0.4 + (i % 5) * 0.2 for i in range(size)]
    return pd.DataFrame(
        {
            "open": opens,
            "high": [x + 2.0 + (i % 2) * 0.2 for i, x in enumerate(opens)],
            "low": [x - 2.0 - (i % 3) * 0.1 for i, x in enumerate(opens)],
            "close": [x + (i % 4) * 0.3 for i, x in enumerate(opens)],
            "volume": [1.0] * size,
        },
        index=pd.date_range("2024-01-01", periods=size, freq="h"),
    )


def _reference(frame, period, length, index):
    def mean(field, end):
        return sum(float(v) for v in frame[field].iloc[end - length + 1 : end + 1]) / length

    start = index - period + 1
    xopen = mean("open", start)
    xclose = mean("close", index)
    xhigh = max(mean("high", i) for i in range(start, index + 1))
    xlow = min(mean("low", i) for i in range(start, index + 1))
    return (0.0 if xopen <= xclose else 2.0, xopen, xclose, xhigh, xlow)


def _run(frame, period, length, once):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.XPeriodCandleColor(self.data, cperiod=period, ma_length=length)
            self.downstream = bt.ind.SMA(self.indicator.xclose, period=2)
            self.callbacks = []

        def next(self):
            self.callbacks.append(len(self.data))

    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe)
    return engine.run()[0]


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("period,length", [(1, 1), (5, 3), (2, 5), (7, 7)])
def test_first_full_window_and_all_later_values(once, period, length):
    frame = _frame(32)
    strategy = _run(frame, period, length, once)
    indicator = strategy.indicator
    first = period + length - 1
    assert indicator._minperiod == first
    assert strategy.downstream._minperiod == first + 1
    assert strategy.callbacks[0] == first + 1
    for index in range(len(frame)):
        values = tuple(float(line.array[index]) for line in indicator.lines)
        if index < first - 1:
            assert all(math.isnan(value) for value in values)
        else:
            assert values == pytest.approx(_reference(frame, period, length, index))


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("period", [0, -2])
def test_nonpositive_cperiod_uses_existing_one_bar_lookback(once, period):
    frame = _frame(20)
    strategy = _run(frame, period, length=3, once=once)
    assert strategy.indicator._minperiod == 3
    for index in range(2, len(frame)):
        values = tuple(float(line.array[index]) for line in strategy.indicator.lines)
        assert values == pytest.approx(_reference(frame, 1, 3, index))


@pytest.mark.parametrize("once", [False, True])
def test_noninteger_cperiod_keeps_existing_conversion_order(once):
    class Period:
        def __init__(self):
            self.calls = []

        def __radd__(self, value):
            self.calls.append("radd")
            return value + 5

        def __int__(self):
            self.calls.append("int")
            return 5

    period = Period()
    result = _run(_frame(18), period, 3, once)
    assert result.indicator._minperiod == 8
    assert period.calls == ["radd"] + ["int"] * 11
    with pytest.raises(TypeError, match="unsupported operand"):
        _run(_frame(18), "5", 3, once)
    if once:
        with pytest.raises(TypeError, match="cannot be interpreted as an integer"):
            _run(_frame(18), 5.5, 3, once)
    else:
        assert _run(_frame(18), 5.5, 3, once).indicator._minperiod == 8.5


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("size", [0, 1, 5, 6, 7])
def test_short_histories_and_exact_boundary(once, size):
    strategy = _run(_frame(size), period=5, length=3, once=once)
    for index in range(size):
        values = tuple(float(line.array[index]) for line in strategy.indicator.lines)
        if index < 6:
            assert all(math.isnan(value) for value in values)
        else:
            assert values == pytest.approx(_reference(_frame(size), 5, 3, index))


@pytest.mark.parametrize("once", [False, True])
def test_slower_secondary_feed_uses_its_own_complete_windows(once):
    slow = _frame(20)
    slow.index = pd.date_range("2024-01-01", periods=len(slow), freq="D")
    fast = _frame(80)
    fast.index = pd.date_range("2024-01-01", periods=len(fast), freq="6h")

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.XPeriodCandleColor(self.datas[1], cperiod=5, ma_length=3)
            self.observed = []

        def next(self):
            self.observed.append((len(self.data0), len(self.data1)))

    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=fast))
    engine.adddata(bt.feeds.PandasData(dataname=slow))
    engine.addstrategy(Probe)
    result = engine.run()[0]
    assert result.observed
    assert result.indicator._minperiod == 7
    for index in range(6, len(slow)):
        values = tuple(float(line.array[index]) for line in result.indicator.lines)
        assert values == pytest.approx(_reference(slow, 5, 3, index))


@pytest.mark.parametrize("once", [False, True])
@pytest.mark.parametrize("up_periods", [(3, 3, 3, 3), (5, 3, 2, 4)])
def test_indicator_source_adds_longest_input_period(once, up_periods):
    names = ("open", "high", "low", "close")
    frame = _frame(30)

    class SmoothedOHLC(bt.Indicator):
        lines = ("open", "high", "low", "close")

        def __init__(self):
            for name, period in zip(names, up_periods):
                setattr(self.lines, name, bt.ind.SMA(getattr(self.data, name), period=period))

    class Probe(bt.Strategy):
        def __init__(self):
            self.source = SmoothedOHLC(self.data)
            self.indicator = bt.ind.XPeriodCandleColor(self.source, cperiod=5, ma_length=3)
            self.first = None

        def next(self):
            if self.first is None:
                self.first = len(self.data)

    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe)
    result = engine.run()[0]
    required = max(up_periods) + 3 + 5 - 2
    assert result.indicator._minperiod == required
    assert result.first == required
    for index in range(required - 1):
        assert all(math.isnan(float(line.array[index])) for line in result.indicator.lines)
    if not once:

        def smooth(name, index):
            period = up_periods[names.index(name)]
            return (
                sum(
                    sum(frame[name].iloc[i - period + 1 : i + 1]) / period
                    for i in range(index - 2, index + 1)
                )
                / 3
            )

        for index in range(required - 1, len(frame)):
            start = index - 4
            xopen = smooth("open", start)
            xclose = smooth("close", index)
            xhigh = max(smooth("high", i) for i in range(start, index + 1))
            xlow = min(smooth("low", i) for i in range(start, index + 1))
            expected = (0.0 if xopen <= xclose else 2.0, xopen, xclose, xhigh, xlow)
            actual = tuple(float(line.array[index]) for line in result.indicator.lines)
            assert actual == pytest.approx(expected)
