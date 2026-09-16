"""Preserve master's moving-average aliases without adding MACD output lines."""

import pandas as pd
import pytest

import backtrader as bt


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("indicator_type", [bt.ind.MACD, bt.ind.MACDHisto])
def test_master_moving_average_aliases_preserve_macd_values(runonce, indicator_type):
    """Exercise alias identity and independently calculated EMA values in Cerebro."""
    prices = [10, 11, 13, 12, 15, 14, 16, 13, 17, 18, 16, 19]
    frame = pd.DataFrame(
        dict.fromkeys(("open", "high", "low", "close"), prices),
        index=pd.date_range("2026-01-01", periods=len(prices)),
    )
    frame["volume"] = 100

    class AliasConsumer(bt.Strategy):
        def __init__(self):
            self.macd = indicator_type(self.data, period_me1=3, period_me2=5, period_signal=3)
            assert self.macd.lines.me1 is self.macd.me1
            assert self.macd.lines.me2 is self.macd.me2
            expected_lines = ("macd", "signal")
            if indicator_type is bt.ind.MACDHisto:
                expected_lines += ("histo",)
            assert self.macd.lines.getlinealiases() == expected_lines
            self.samples = []
            self.histograms = []

        def next(self):
            self.samples.append(
                (
                    self.macd.lines.me1[0],
                    self.macd.lines.me2[0],
                    self.macd.macd[0],
                    self.macd.signal[0],
                )
            )
            if indicator_type is bt.ind.MACDHisto:
                self.histograms.append(self.macd.histo[0])

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(AliasConsumer)
    strategy = cerebro.run(runonce=runonce, preload=True)[0]

    # SMA-seeded EMA(3), EMA(5), their difference, and EMA(3) of that difference.
    # These values are derived from the fixed input above, not another MACD run.
    expected = [
        (14.833333333333334, 13.866666666666667, 0.9666666666666667, 0.9888888888888889),
        (13.916666666666666, 13.577777777777778, 0.3388888888888889, 0.6638888888888889),
        (15.458333333333334, 14.718518518518518, 0.7398148148148148, 0.7018518518518518),
        (16.729166666666668, 15.812345679012345, 0.916820987654321, 0.8093364197530864),
        (16.364583333333332, 15.874897119341564, 0.48968621399176954, 0.6495113168724279),
        (17.682291666666668, 16.916598079561042, 0.7656935871056241, 0.707602451989026),
    ]
    assert len(strategy.samples) == len(expected)
    for actual, reference in zip(strategy.samples, expected):
        assert actual == pytest.approx(reference, abs=1e-12)
    if indicator_type is bt.ind.MACDHisto:
        assert strategy.histograms == pytest.approx([row[2] - row[3] for row in expected])
