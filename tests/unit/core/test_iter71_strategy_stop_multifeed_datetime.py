"""Keep per-feed bar timestamps intact when Strategy stops."""

import datetime

import pandas as pd
import pytest

import backtrader as bt


def _ohlcv(index, base):
    close = [base + offset for offset in range(len(index))]
    return pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
            "volume": [1000.0] * len(close),
            "openinterest": [0.0] * len(close),
        },
        index=index,
    )


class _StopClockStrategy(bt.Strategy):
    def stop(self):
        self.stop_snapshot = (
            self.datetime.datetime(),
            len(self),
            {
                data._name: (
                    data.datetime.datetime(),
                    float(data.close[0]),
                    len(data),
                )
                for data in self.datas
            },
        )


def _current_snapshot(strategy):
    return (
        strategy.datetime.datetime(),
        len(strategy),
        {
            data._name: (
                data.datetime.datetime(),
                float(data.close[0]),
                len(data),
            )
            for data in strategy.datas
        },
    )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("fast_first", (True, False), ids=("fast-first", "slow-first"))
def test_stop_preserves_each_feed_last_bar_datetime(runonce, fast_first):
    fast_index = pd.date_range("2024-01-01 00:00", periods=11, freq="h")
    slow_index = pd.date_range("2024-01-01 01:00", periods=3, freq="4h")
    fast = bt.feeds.PandasData(
        dataname=_ohlcv(fast_index, 100.0), name="fast"
    )
    slow = bt.feeds.PandasData(
        dataname=_ohlcv(slow_index, 200.0), name="slow"
    )

    cerebro = bt.Cerebro(
        stdstats=False,
        runonce=runonce,
        preload=runonce,
    )
    for data in ((fast, slow) if fast_first else (slow, fast)):
        cerebro.adddata(data)
    cerebro.addstrategy(_StopClockStrategy)

    strategy = cerebro.run()[0]

    expected = (
        datetime.datetime(2024, 1, 1, 10),
        11,
        {
            "fast": (datetime.datetime(2024, 1, 1, 10), 110.0, 11),
            "slow": (datetime.datetime(2024, 1, 1, 9), 202.0, 3),
        },
    )
    assert strategy.stop_snapshot == expected
    assert _current_snapshot(strategy) == expected
