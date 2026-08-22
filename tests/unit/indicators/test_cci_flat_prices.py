"""Regression coverage for CCI when its mean-deviation denominator is zero."""

import math

import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators as btind


def _run_flat_cci(runonce):
    """Run CCI over a flat OHLC series and collect every valid output."""
    prices = [100.0] * 8
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1.0] * len(prices),
            "openinterest": [0.0] * len(prices),
        },
        index=pd.date_range("2026-01-01", periods=len(prices), freq="D"),
    )
    values = []

    class CCIProbeStrategy(bt.Strategy):
        def __init__(self):
            self.cci = btind.CCI(self.data, period=3)

        def next(self):
            values.append(float(self.cci[0]))

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(CCIProbeStrategy)
    cerebro.run()
    return values


@pytest.mark.parametrize("runonce", [False, True])
def test_cci_flat_prices_are_undefined_not_neutral(runonce):
    """Flat prices do not raise and produce undefined, rather than neutral, CCI."""
    values = _run_flat_cci(runonce)

    assert values
    assert all(math.isnan(value) for value in values)


def test_cci_flat_price_runonce_runnext_parity():
    """Batch and event-driven calculation preserve the same undefined values."""
    runnext_values = _run_flat_cci(runonce=False)
    runonce_values = _run_flat_cci(runonce=True)

    assert len(runonce_values) == len(runnext_values)
    assert all(math.isnan(value) for value in runnext_values)
    assert all(math.isnan(value) for value in runonce_values)
