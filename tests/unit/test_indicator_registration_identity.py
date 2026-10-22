from __future__ import annotations

import pandas as pd

import backtrader as bt


class _EqualIndicators(bt.Indicator):
    lines = ("value",)
    __hash__ = object.__hash__

    def __init__(self):
        self.equality_calls = 0
        super().__init__()

    def __eq__(self, other):
        self.equality_calls += 1
        return isinstance(other, _EqualIndicators)

    def next(self):
        self.lines.value[0] = self.data.close[0]


class _TwoEqualIndicators(bt.Strategy):
    def __init__(self):
        self.first = _EqualIndicators(self.data)
        self.second = _EqualIndicators(self.data)


def test_registration_uses_identity_for_duplicates_and_equal_indicators():
    index = pd.date_range("2026-01-01", periods=3, freq="D")
    frame = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.5, 11.5, 12.5],
            "volume": [100.0, 110.0, 120.0],
            "openinterest": [0.0, 0.0, 0.0],
        },
        index=index,
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="AAA")
    cerebro.addstrategy(_TwoEqualIndicators)

    strategy = cerebro.run()[0]
    indicators = strategy.getindicators()

    assert strategy.first is not strategy.second
    assert sum(item is strategy.first for item in indicators) == 1
    assert sum(item is strategy.second for item in indicators) == 1
    assert strategy.first.equality_calls == 0
    assert strategy.second.equality_calls == 0

    registered_count = len(indicators)
    strategy.addindicator(strategy.first)

    assert len(strategy.getindicators()) == registered_count
    assert sum(item is strategy.first for item in strategy.getindicators()) == 1
    assert strategy.first.equality_calls == 0
    assert strategy.second.equality_calls == 0
