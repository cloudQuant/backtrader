"""Negative ROC periods must not become future-data lookups."""

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.roc2_vg_indicator import ROC2VGIndicator


def _frame():
    values = [float(v) for v in range(10, 30)]
    return pd.DataFrame({name: values for name in ("open", "high", "low", "close")},
                        index=pd.date_range("2024-01-01", periods=len(values)))


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("preload", [False, True])
@pytest.mark.parametrize("which", ["roc_period1", "roc_period2"])
@pytest.mark.parametrize("negative", [-1, -2, "-1"])
def test_negative_period_is_rejected_before_strategy_callbacks(runonce, preload, which, negative):
    callbacks = []

    class Probe(bt.Strategy):
        def __init__(self):
            params = {"roc_period1": 2, "roc_period2": 3, which: negative}
            self.ind = ROC2VGIndicator(self.data, **params)

        def next(self):
            callbacks.append(len(self.data))

    engine = bt.Cerebro(runonce=runonce, preload=preload, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=_frame()))
    engine.addstrategy(Probe)
    with pytest.raises(ValueError, match="ROC periods must not be negative"):
        engine.run()
    assert callbacks == []


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("period", [0, -0.5])
def test_zero_and_existing_integer_coercion_remain_supported(runonce, period):
    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = ROC2VGIndicator(self.data, roc_period1=period, roc_type1=1,
                                       roc_period2=3, roc_type2=1)

    engine = bt.Cerebro(runonce=runonce, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=_frame()))
    engine.addstrategy(Probe)
    ind = engine.run()[0].ind
    assert ind._p1 == 0
    assert all(value == 0.0 for value in ind.roc1.array[ind._minperiod - 1:])
