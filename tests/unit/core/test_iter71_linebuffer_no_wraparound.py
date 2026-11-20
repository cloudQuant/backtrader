"""Out-of-history reads must not wrap into preloaded future data."""

import math
from pathlib import Path

import pytest

import backtrader as bt
from backtrader.linebuffer import LineBuffer, _raw_linebuffer_value


@pytest.mark.parametrize("read", [lambda line, ago: line[ago], _raw_linebuffer_value])
def test_preloaded_feed_read_before_first_bar_does_not_wrap(read):
    line = LineBuffer()
    line._is_data_feed_line = True
    for value in range(1, 41):
        line.forward(value=float(value))
    line.home()

    with pytest.raises(IndexError):
        read(line, 0)

    line.advance(3)
    assert read(line, 0) == 3
    assert read(line, -2) == 1
    assert read(line, 1) == 4  # Explicit lookahead still works.
    with pytest.raises(IndexError):
        read(line, -20)


@pytest.mark.parametrize("read", [lambda line, ago: line[ago], _raw_linebuffer_value])
def test_non_feed_history_underflow_is_missing_not_future(read):
    line = LineBuffer()
    for value in range(1, 41):
        line.forward(value=float(value))
    line.home()
    assert math.isnan(read(line, 0))
    line.advance(3)
    assert math.isnan(read(line, -20))


@pytest.mark.parametrize("read", [lambda line, ago: line[ago], _raw_linebuffer_value])
def test_underflow_check_uses_effective_clamped_index(read):
    line = LineBuffer()
    line._is_data_feed_line = True
    for value in range(1, 41):
        line.forward(value=float(value))
    line.lencount = 3
    line._idx = 10

    with pytest.raises(IndexError):
        read(line, -5)


@pytest.mark.parametrize("read", [lambda line, ago: line[ago], _raw_linebuffer_value])
def test_qbuffer_history_cannot_wrap(read):
    line = LineBuffer()
    line._is_data_feed_line = True
    line._minperiod = 4
    line.qbuffer()
    for value in range(1, 7):
        line.forward(value=float(value))

    assert read(line, -3) == 3
    with pytest.raises(IndexError):
        read(line, -4)


@pytest.mark.parametrize("preload", [False, True])
def test_strategy_cannot_read_preloaded_future_as_early_history(preload):
    class Probe(bt.Strategy):
        def __init__(self):
            self.probe = None

        def next(self):
            if len(self) == 3:
                try:
                    self.probe = self.data.close[-20]
                except IndexError:
                    self.probe = "out of range"
                self.env.runstop()

    data = Path(__file__).resolve().parents[2] / "datas" / "2006-day-001.txt"
    cerebro = bt.Cerebro(stdstats=False, preload=preload, runonce=False)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(data)))
    cerebro.addstrategy(Probe)

    assert cerebro.run()[0].probe == "out of range"
