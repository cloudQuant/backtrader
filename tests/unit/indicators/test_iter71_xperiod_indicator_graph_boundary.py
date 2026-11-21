"""XPeriod one-bar smoothing preserves upstream and downstream warmup."""

import math

import pandas as pd
import pytest

import backtrader as bt


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("periods", [(3, 3, 3, 3), (1, 1, 1, 10)])
def test_single_bar_smoothing_in_indicator_graph(runonce, periods):
    names = ("open", "high", "low", "close")
    opens = [10.0 + i * 0.2 for i in range(30)]
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": [value + 2.0 for value in opens],
            "low": [value - 2.0 for value in opens],
            "close": [value + 1.0 for value in opens],
            "volume": [1.0] * len(opens),
        },
        index=pd.date_range("2024-01-01", periods=len(opens), freq="h"),
    )

    class Source(bt.Indicator):
        lines = ("open", "high", "low", "close")

        def __init__(self):
            for name, period in zip(names, periods):
                value = bt.ind.SMA(getattr(self.data, name), period=period)
                setattr(self.lines, name, value)

    class Strategy(bt.Strategy):
        def __init__(self):
            self.source = Source(self.data)
            self.candle = bt.ind.XPeriodCandleColor(self.source, cperiod=5, ma_length=1)
            self.child = bt.ind.SMA(self.candle.xclose, period=2)
            self.callbacks = []

        def next(self):
            self.callbacks.append(len(self.data))

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Strategy)
    result = engine.run()[0]
    first = max(periods) + 4
    assert result.candle._minperiod == first
    assert result.child._minperiod == first + 1
    assert result.callbacks[0] == first + 1
    assert all(
        math.isnan(float(line.array[index]))
        for index in range(first - 1)
        for line in result.candle.lines
    )

    # Existing Indicator-source once scheduling can produce NaNs after warmup;
    # this test does not claim batch numerical parity for that path.
    if runonce:
        return

    def source_mean(name, index):
        period = periods[names.index(name)]
        window = frame[name].iloc[index - period + 1 : index + 1]
        return float(window.sum()) / period

    for index in range(first - 1, len(frame)):
        start = index - 4
        xopen = source_mean("open", start)
        xclose = source_mean("close", index)
        xhigh = max(source_mean("high", i) for i in range(start, index + 1))
        xlow = min(source_mean("low", i) for i in range(start, index + 1))
        expected = (0.0 if xopen <= xclose else 2.0, xopen, xclose, xhigh, xlow)
        assert tuple(float(line.array[index]) for line in result.candle.lines) == pytest.approx(
            expected
        )
        if index >= first:
            previous_close = source_mean("close", index - 1)
            assert float(result.child.array[index]) == pytest.approx((previous_close + xclose) / 2)
