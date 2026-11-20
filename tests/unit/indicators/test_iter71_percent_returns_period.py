"""The percentage-return window needs the current bar plus its history."""

import math
from pathlib import Path

import pytest

import backtrader as bt


@pytest.mark.parametrize("preload,runonce", [(False, False), (True, False), (True, True)])
def test_first_return_waits_for_period_plus_one_bars(preload, runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.returns = bt.indicators.PercentReturnsPeriod(self.data, period=3)
            self.records = []

        def prenext(self):
            self.record()

        def next(self):
            self.record()
            if len(self) == 4:
                self.env.runstop()

        def record(self):
            self.records.append((float(self.data.close[0]), float(self.returns[0])))

    data = Path(__file__).resolve().parents[2] / "datas" / "2006-day-001.txt"
    cerebro = bt.Cerebro(stdstats=False, preload=preload, runonce=runonce)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(data)))
    cerebro.addstrategy(Probe)

    result = cerebro.run()[0]
    assert result.returns._minperiod == 4
    assert len(result.records) == 4
    assert all(math.isnan(value) for _, value in result.records[:3])
    assert result.records[3][1] == pytest.approx(
        (result.records[3][0] - result.records[0][0]) / result.records[0][0]
    )


@pytest.mark.parametrize("runonce", [False, True])
def test_short_history_never_emits_return(tmp_path, runonce):
    path = tmp_path / "short.csv"
    path.write_text(
        "Date,Open,High,Low,Close,Volume,OpenInterest\n"
        "2025-01-01,10,10,10,10,1,0\n"
        "2025-01-02,11,11,11,11,1,0\n"
        "2025-01-03,12,12,12,12,1,0\n",
        encoding="utf-8",
    )

    class Probe(bt.Strategy):
        def __init__(self):
            self.returns = bt.indicators.PercentReturnsPeriod(self.data, period=3)

    cerebro = bt.Cerebro(stdstats=False, preload=True, runonce=runonce)
    cerebro.adddata(bt.feeds.BacktraderCSVData(dataname=str(path)))
    cerebro.addstrategy(Probe)
    result = cerebro.run()[0]

    assert result.returns._minperiod == 4
    assert all(math.isnan(value) for value in result.returns.array)
