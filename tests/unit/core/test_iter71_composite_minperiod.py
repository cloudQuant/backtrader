"""Composite indicators must expose their calculated warmup to consumers."""

from pathlib import Path

import pytest

import backtrader as bt


class CompositeAverage(bt.Indicator):
    lines = ("value",)

    def __init__(self):
        self.child = bt.indicators.SMA(self.data, period=5)

    def next(self):
        self.lines.value[0] = self.child[0]


@pytest.mark.parametrize("runonce", [False, True])
def test_composite_line_propagates_child_warmup_to_downstream(runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.composite = CompositeAverage(self.data)
            self.downstream = bt.indicators.SMA(self.composite, period=3)
            self.expression = self.composite + 1
            self.conditional = bt.If(self.composite > 0, self.composite, 0)
            self.reference = bt.indicators.SMA(bt.indicators.SMA(self.data, period=5), period=3)
            self.first_next = None
            self.first_values = None

        def next(self):
            if self.first_next is None:
                self.first_next = len(self)
                self.first_values = (float(self.downstream[0]), float(self.reference[0]))
            self.env.runstop()

    path = Path(__file__).resolve().parents[2] / "datas" / "2006-day-001.txt"
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(path)))
    cerebro.addstrategy(Probe)

    result = cerebro.run()[0]
    assert result.composite._minperiod == 5
    assert result.composite.lines.value._minperiod == 5
    assert result.downstream._minperiod == 7
    assert result.expression._minperiod == 5
    assert result.conditional._minperiod == 5
    assert result.first_next == 7
    assert result.first_values[0] == pytest.approx(result.first_values[1])


@pytest.mark.parametrize(
    "indicator",
    [bt.indicators.RSI_Safe, bt.indicators.DPO, bt.indicators.Trix, bt.indicators.PPO],
)
def test_builtin_composite_lines_expose_their_warmup(indicator):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = indicator(self.data)
            self.downstream = bt.indicators.SMA(self.indicator.lines[0], period=3)

    path = Path(__file__).resolve().parents[2] / "datas" / "2006-day-001.txt"
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(path)))
    cerebro.addstrategy(Probe)

    result = cerebro.run()[0]
    assert result.indicator._minperiod > 1
    assert all(line._minperiod >= result.indicator._minperiod for line in result.indicator.lines)
    assert result.downstream._minperiod >= result.indicator._minperiod + 2
