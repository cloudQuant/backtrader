"""Regression coverage for TradeAnalyzer-backed performance metrics."""

import pandas as pd
import pytest

import backtrader as bt
from backtrader.reports.performance import PerformanceCalculator


@pytest.mark.parametrize("runonce", [True, False])
def test_avg_trade_duration_uses_trade_analyzer_average(runonce):
    """Report the average of closed-trade bar lengths from TradeAnalyzer."""
    prices = [100, 101, 102, 103, 102, 101, 100, 99, 100, 101, 102, 103]
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1 for price in prices],
            "low": [price - 1 for price in prices],
            "close": prices,
            "volume": [100] * len(prices),
            "openinterest": [0] * len(prices),
        },
        index=pd.date_range("2024-01-01", periods=len(prices), freq="D"),
    )

    class TwoTrades(bt.Strategy):
        def next(self):
            bar = len(self)
            if not self.position and bar in (1, 7):
                self.buy(size=1)
            elif self.position and bar in (4, 10):
                self.close()

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(TwoTrades)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="tradeanalyzer")
    strategy = cerebro.run(runonce=runonce)[0]

    analysis = strategy.analyzers.tradeanalyzer.get_analysis()
    assert analysis.total.closed == 2
    assert analysis.len.total == 6
    assert analysis.len.average == pytest.approx(3.0)
    assert PerformanceCalculator(strategy).get_trade_metrics()[
        "avg_trade_duration"
    ] == pytest.approx(3.0)
