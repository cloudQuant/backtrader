"""Close-only CCI preserves an undefined result for zero deviation."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.close_line_cci import CloseLineCCI


def _frame(values, *, frequency="D"):
    return pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values,
         "volume": [100.0] * len(values)},
        index=pd.date_range("2024-01-01", periods=len(values), freq=frequency),
    )


def _reference(values, period=5, factor=0.015):
    """Use the existing moving-average-of-absolute-deviations CCI definition."""
    means = [math.nan] * len(values)
    deviations = [math.nan] * len(values)
    result = [math.nan] * len(values)
    for index in range(period - 1, len(values)):
        means[index] = sum(values[index - period + 1:index + 1]) / period
        deviations[index] = abs(values[index] - means[index])
    for index in range(2 * period - 2, len(values)):
        deviation = sum(deviations[index - period + 1:index + 1]) / period
        denominator = factor * deviation
        if math.isfinite(denominator) and denominator != 0:
            result[index] = (values[index] - means[index]) / denominator
    return result


def _same(actual, expected):
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), (index, got, want)
        else:
            assert got == pytest.approx(want, rel=1e-11, abs=1e-11), index


def _run(values, runonce, *, factor=0.015, primary=None):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = CloseLineCCI(self.datas[-1].close, period=5, factor=factor)

        def stop(self):
            self.output = list(self.indicator.cci.array)
            self.minimum = self.indicator._minperiod

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    if primary is not None:
        engine.adddata(bt.feeds.PandasData(dataname=primary))
    engine.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    engine.addstrategy(Probe)
    return engine.run()[0]


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_flat_price_has_undefined_cci_without_division_error(runonce):
    values = [100.0] * 50
    result = _run(values, runonce)
    assert result.minimum == 9
    assert len(result.output) == len(values)
    assert all(math.isnan(value) for value in result.output)


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("gap", [False, True], ids=["finite", "missing-close"])
def test_flat_then_movement_and_missing_data_recover_against_reference(runonce, gap):
    values = [100.0] * 25 + [100.0 + i * 0.08 + math.sin(i * 0.29) for i in range(90)]
    if gap:
        values[55] = math.nan
    result = _run(values, runonce)
    _same(result.output, _reference(values))
    assert all(math.isnan(value) for value in result.output[:25])
    assert any(math.isfinite(value) for value in result.output[-20:])
    if gap:
        assert math.isnan(result.output[55])
        assert any(math.isfinite(value) for value in result.output[65:])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_zero_factor_remains_undefined(runonce):
    values = [100.0 + math.sin(i * 0.3) for i in range(50)]
    result = _run(values, runonce, factor=0.0)
    assert all(math.isnan(value) for value in result.output)


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_secondary_data_clock_retains_flat_and_recovery_semantics(runonce):
    values = [100.0] * 20 + [100.0 + math.sin(i * 0.2) for i in range(40)]
    primary = _frame([100.0 + i * 0.1 for i in range(len(values) * 3)])
    signal = _frame(values)
    signal.index = pd.date_range("2024-01-01", periods=len(values), freq="3D")

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = CloseLineCCI(self.datas[1].close, period=5)

        def stop(self):
            self.output = list(self.indicator.cci.array)

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=primary))
    engine.adddata(bt.feeds.PandasData(dataname=signal))
    engine.addstrategy(Probe)
    _same(engine.run()[0].output, _reference(values))
