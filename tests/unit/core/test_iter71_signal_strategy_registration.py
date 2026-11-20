"""Signals coexist with ordinary and explicitly registered signal strategies."""

from pathlib import Path

import pytest

import backtrader as bt


class NeutralSignal(bt.Indicator):
    lines = ("signal",)

    def next(self):
        self.lines.signal[0] = 0.0


class OrdinaryStrategy(bt.Strategy):
    params = (("period", 1),)


class CustomSignalStrategy(bt.SignalStrategy):
    pass


def make_cerebro():
    data = Path(__file__).resolve().parents[2] / "datas" / "2006-day-001.txt"
    cerebro = bt.Cerebro(stdstats=False, maxcpus=1)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(data)))
    cerebro.add_signal(bt.SIGNAL_LONG, NeutralSignal)
    return cerebro


@pytest.mark.parametrize("strategy", [OrdinaryStrategy, CustomSignalStrategy])
def test_registered_strategy_can_run_with_signal(strategy):
    cerebro = make_cerebro()
    cerebro.addstrategy(strategy)

    strategies = cerebro.run()

    assert sum(type(item) is strategy for item in strategies) == 1
    assert sum(isinstance(item, bt.SignalStrategy) for item in strategies) == 1


def test_signal_does_not_consume_optimization_combinations():
    cerebro = make_cerebro()
    cerebro.optstrategy(OrdinaryStrategy, period=(2, 3))

    results = cerebro.run(optreturn=False)

    assert len(results) == 2
    assert [result[0].p.period for result in results] == [2, 3]
    assert all(any(isinstance(item, bt.SignalStrategy) for item in result) for result in results)


def test_repeated_run_does_not_add_duplicate_signal_strategies():
    cerebro = make_cerebro()
    cerebro.addstrategy(OrdinaryStrategy)

    for _ in range(2):
        strategies = cerebro.run()
        assert len(strategies) == 2
        assert sum(isinstance(item, bt.SignalStrategy) for item in strategies) == 1


def test_registered_signal_strategy_keeps_its_position():
    cerebro = make_cerebro()
    cerebro.addstrategy(CustomSignalStrategy)
    cerebro.addstrategy(OrdinaryStrategy)

    strategies = cerebro.run()

    assert [type(strategy) for strategy in strategies] == [CustomSignalStrategy, OrdinaryStrategy]
