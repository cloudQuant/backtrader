"""Short QBuffer windows return the available prefix instead of failing."""

from pathlib import Path

import pytest

import backtrader as bt
from backtrader.linebuffer import LineBuffer


@pytest.mark.parametrize("queued", [False, True])
def test_window_longer_than_available_history(queued):
    line = LineBuffer()
    if queued:
        line._minperiod = 4
        line.qbuffer()
    line.forward(value=1.0)

    assert list(line.get(size=3)) == [1.0]
    line.forward(value=2.0)
    assert list(line.get(size=3)) == [1.0, 2.0]
    line.forward(value=3.0)
    assert list(line.get(size=3)) == [1.0, 2.0, 3.0]
    assert list(line.get(ago=-1, size=3)) == [1.0, 2.0]
    assert list(line.get(ago=-5, size=1)) == []


def test_qbuffer_window_preserves_explicit_lookahead():
    line = LineBuffer()
    line._minperiod = 3
    line.qbuffer(extrasize=1)
    line.forward(value=1.0)
    line.forward(value=2.0)
    line.rewind()

    assert list(line.get(ago=1, size=1)) == [2.0]


@pytest.mark.parametrize("exactbars", [0, 1, -1])
def test_strategy_window_during_warmup(exactbars):
    class Probe(bt.Strategy):
        def __init__(self):
            self.average = bt.indicators.SMA(self.data, period=3)
            self.closes = []
            self.windows = []

        def prenext(self):
            self.record()

        def next(self):
            self.record()
            if len(self) == 3:
                self.env.runstop()

        def record(self):
            self.closes.append(self.data.close[0])
            self.windows.append(list(self.data.close.get(size=3)))

    data = Path(__file__).resolve().parents[2] / "datas" / "2006-day-001.txt"
    cerebro = bt.Cerebro(stdstats=False, exactbars=exactbars, runonce=False)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(data)))
    cerebro.addstrategy(Probe)

    result = cerebro.run()[0]
    assert result.windows == [result.closes[:1], result.closes[:2], result.closes[:3]]
