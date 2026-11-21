"""Bounded asynchronous feeds retain, but do not deliver, a future bar."""

import math

import pandas as pd
import pytest

import backtrader as bt


def _frames(pattern):
    times = pd.date_range("2024-01-01", periods=48, freq="min")
    primary = [100.0 + i * 0.17 for i in range(len(times))]
    secondary = [200.0 + i * 0.07 for i in range(len(times))]

    def make(indexes, values):
        close = [values[i] for i in indexes]
        return pd.DataFrame(
            {
                "open": close,
                "high": [x + 1 for x in close],
                "low": [x - 1 for x in close],
                "close": close,
                "volume": [1.0] * len(close),
            },
            index=times[indexes],
        )

    if pattern == "gaps":
        chosen = [i for i in range(len(times)) if i % 3 != 0]
    elif pattern == "slower":
        chosen = list(range(0, len(times), 4))
    else:
        chosen = list(range(2, len(times), 3))
    return make(list(range(len(times))), primary), make(chosen, secondary), chosen


@pytest.mark.parametrize("feed_type", ["pandas", "generic_csv"])
@pytest.mark.parametrize("pattern", ["gaps", "slower", "delayed"])
@pytest.mark.parametrize("exactbars,request_once", [(0, False), (1, False), (1, True)])
def test_bounded_secondary_feed_never_exposes_future_bar(
    pattern, exactbars, request_once, feed_type, tmp_path
):
    primary, secondary, chosen = _frames(pattern)

    class Strategy(bt.Strategy):
        def __init__(self):
            self.expression = (self.data0.close + 1.0) / (self.data1.close + 2.0)
            self.average = bt.ind.SMA(self.expression, period=5)
            self.rows = []

        def next(self):
            self.rows.append(
                (
                    len(self.data0) - 1,
                    len(self.data1),
                    float(self.data0.datetime[0]),
                    float(self.data1.datetime[0]),
                    float(self.data1.close[0]),
                    float(self.expression[0]),
                    float(self.average[0]),
                )
            )

    c = bt.Cerebro(stdstats=False, runonce=request_once, preload=False, exactbars=exactbars)
    for number, frame in enumerate((primary, secondary)):
        if feed_type == "pandas":
            feed = bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes)
        else:
            path = tmp_path / (str(number) + ".csv")
            frame.to_csv(path, date_format="%Y-%m-%d %H:%M:%S")
            feed = bt.feeds.GenericCSVData(
                dataname=str(path), timeframe=bt.TimeFrame.Minutes,
                dtformat="%Y-%m-%d %H:%M:%S", datetime=0, time=-1,
                open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
            )
        c.adddata(feed)
    c.addstrategy(Strategy)
    strategy = c.run()[0]
    assert strategy.rows
    if exactbars:
        assert not c._dorunonce
    ratios = []
    for index in range(len(primary)):
        previous = [j for j in chosen if j <= index]
        if not previous:
            ratios.append(math.nan)
        else:
            price = float(secondary.close.iloc[len(previous) - 1])
            ratios.append((float(primary.close.iloc[index]) + 1.0) / (price + 2.0))
    for index, count, master_dt, source_dt, price, expression, average in strategy.rows:
        previous = [j for j in chosen if j <= index]
        assert previous
        assert source_dt <= master_dt
        assert count == len(previous)
        assert price == pytest.approx(float(secondary.close.iloc[count - 1]))
        assert expression == pytest.approx(ratios[index])
        window = ratios[index - 4 : index + 1]
        expected = sum(window) / 5.0
        if math.isnan(expected):
            assert math.isnan(average)
        else:
            assert average == pytest.approx(expected)
