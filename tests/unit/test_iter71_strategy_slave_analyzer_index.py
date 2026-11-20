"""R71-089: strategy slave-analyzer lookup must use the stored index."""

from __future__ import annotations

import pandas as pd
import pytest

import backtrader as bt
from backtrader.analyzer import Analyzer


class _CountingSlaveAnalyzer(Analyzer):
    def __init__(self):
        super().__init__()
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _SlaveAnalyzerLookupStrategy(bt.Strategy):
    params = (("label", ""),)

    def __init__(self):
        prefix = self.p.label
        first = self._addanalyzer_slave(_CountingSlaveAnalyzer)
        first.label = prefix + "-first"
        second = self._addanalyzer_slave(_CountingSlaveAnalyzer)
        second.label = prefix + "-second"
        self.lookup = (self._getanalyzer_slave(0), self._getanalyzer_slave(1))
        self.created = (first, second)


@pytest.mark.parametrize("runonce", (True, False))
def test_slave_analyzer_indices_are_isolated_for_strategies_on_one_cerebro(runonce):
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    prices = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0, 13.0],
            "high": [11.0, 12.0, 13.0, 14.0],
            "low": [9.0, 10.0, 11.0, 12.0],
            "close": [10.5, 11.5, 12.5, 13.5],
            "volume": [100.0, 100.0, 100.0, 100.0],
            "openinterest": [0.0, 0.0, 0.0, 0.0],
        },
        index=index,
    )

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=prices))
    cerebro.addstrategy(_SlaveAnalyzerLookupStrategy, label="left")
    cerebro.addstrategy(_SlaveAnalyzerLookupStrategy, label="right")
    strategies = cerebro.run(runonce=runonce)

    assert len(strategies) == 2
    assert strategies[0] is not strategies[1]
    assert strategies[0]._slave_analyzers is not strategies[1]._slave_analyzers
    for strategy, prefix in zip(strategies, ("left", "right")):
        assert len(strategy._slave_analyzers) == 2
        assert strategy.lookup == strategy.created
        assert strategy.lookup[0] is strategy._slave_analyzers[0]
        assert strategy.lookup[1] is strategy._slave_analyzers[1]
        assert strategy.lookup[0] is not strategy.lookup[1]
        assert strategy.lookup[0].label == prefix + "-first"
        assert strategy.lookup[1].label == prefix + "-second"
        assert strategy.lookup[0].started and strategy.lookup[0].stopped
        assert strategy.lookup[1].started and strategy.lookup[1].stopped
