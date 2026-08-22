#!/usr/bin/env python
"""Tests for the On-Balance Volume indicator."""

import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators as btind


def _run_obv(close, volume, runonce):
    """Run OBV over synthetic OHLCV data and return calculated values."""
    index = pd.date_range("2020-01-01", periods=len(close), freq="D")
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": volume,
            "openinterest": 0.0,
        },
        index=index,
    )
    values = []
    lengths = {}

    class OBVStrategy(bt.Strategy):
        def __init__(self):
            self.obv = btind.OBV(self.data)

        def next(self):
            values.append(float(self.obv[0]))

        def stop(self):
            lengths["data"] = self.data.buflen()
            lengths["indicator"] = self.obv.buflen()
            lengths["line"] = len(self.obv.lines.obv.array)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(OBVStrategy)
    cerebro.run()
    return values, lengths


def test_obv_public_names_and_lifecycle_methods():
    """OBV is exported under both names and explicitly implements both modes."""
    assert btind.OBV is btind.OnBalanceVolume

    from backtrader.indicators.obv import OBV, OnBalanceVolume

    assert OBV is OnBalanceVolume

    lifecycle_methods = {"nextstart", "next", "oncestart", "once"}
    assert lifecycle_methods <= btind.OnBalanceVolume.__dict__.keys()


@pytest.mark.parametrize("runonce", [False, True])
def test_obv_calculation(runonce):
    """OBV follows price direction and seeds with the first volume."""
    values, lengths = _run_obv(
        close=[10.0, 11.0, 11.0, 9.0, 10.0],
        volume=[100.0, 200.0, 300.0, 400.0, 500.0],
        runonce=runonce,
    )

    assert values == pytest.approx([100.0, 300.0, 300.0, -100.0, 400.0])
    assert lengths == {"data": 5, "indicator": 5, "line": 5}


@pytest.mark.parametrize("runonce", [False, True])
def test_obv_flat_prices_and_zero_volume(runonce):
    """Unchanged prices preserve OBV and zero volume changes nothing."""
    values, lengths = _run_obv(
        close=[10.0, 10.0, 11.0, 9.0],
        volume=[100.0, 200.0, 0.0, 0.0],
        runonce=runonce,
    )

    assert values == pytest.approx([100.0, 100.0, 100.0, 100.0])
    assert lengths == {"data": 4, "indicator": 4, "line": 4}


def test_obv_runonce_runnext_parity():
    """Batch and event-driven execution produce identical OBV output."""
    close = [10.0, 11.0, 9.0, 9.0, 12.0, 8.0, 13.0]
    volume = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0]

    runnext_values, _ = _run_obv(close, volume, runonce=False)
    runonce_values, _ = _run_obv(close, volume, runonce=True)

    assert runonce_values == pytest.approx(runnext_values)