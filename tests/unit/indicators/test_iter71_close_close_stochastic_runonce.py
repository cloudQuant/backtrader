"""Close-based Stochastic smoothing agrees in both Cerebro modes."""

import importlib
import math

import backtrader as bt
import pandas as pd
import pytest


def _prices(count, *, flat=False):
    if flat:
        return [100.0] * count
    return [
        100.0 + i * 0.13 + (i * 7 % 13) * 0.47 + math.sin(i * 0.3) * 2.2
        for i in range(count)
    ]


def _run(runonce, *, count=240, flat=False, **params):
    close = _prices(count, flat=flat)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
            "volume": [1000.0] * count,
        },
        index=pd.date_range("2020-01-01", periods=count),
    )

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.CloseCloseEmaStochastic(self.data, **params)
            self.downstream = bt.indicators.SMA(self.indicator.percD, period=3)

        def stop(self):
            self.result = (
                self.indicator._minperiod,
                list(self.indicator.percK.array),
                list(self.indicator.percD.array),
                list(self.downstream.array),
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


def _ema(values, period, source_start):
    output = [math.nan] * len(values)
    seed = source_start + period - 1
    if seed >= len(values):
        return output
    previous = math.fsum(values[source_start : seed + 1]) / period
    output[seed] = previous
    alpha = 2.0 / (period + 1.0)
    for index in range(seed + 1, len(values)):
        previous = previous * (1.0 - alpha) + values[index] * alpha
        output[index] = previous
    return output


def _assert_equal(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        if math.isnan(want):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


def test_k_binding_precedes_d_registration(monkeypatch):
    module = importlib.import_module("backtrader.indicators.contrib.raw_close_close_stochastic")
    original_ema = module.ExponentialMovingAverage
    observed = {}

    def capture_ema(*args, **kwargs):
        perc_k = observed.get("perc_k")
        if perc_k is None:
            perc_k = original_ema(*args, **kwargs)
            observed["perc_k"] = perc_k
            return perc_k
        if args[0] is perc_k:
            owner = perc_k._owner
            assert any(line is owner.l.percK for line in perc_k.lines[0].bindings)
            assert any(child is perc_k for child in owner._lineiterators[0])
            perc_d = original_ema(*args, **kwargs)
            observed["perc_d"] = perc_d
            assert perc_d.data is perc_k
            assert perc_d._owner is owner
            return perc_d
        return original_ema(*args, **kwargs)

    monkeypatch.setattr(module, "ExponentialMovingAverage", capture_ema)
    _run(False, count=20)
    perc_k, perc_d = observed["perc_k"], observed["perc_d"]
    owner = perc_k._owner
    children = owner._lineiterators[0]
    assert next(i for i, child in enumerate(children) if child is perc_k) < next(
        i for i, child in enumerate(children) if child is perc_d
    )
    assert any(line is owner.l.percD for line in perc_d.lines[0].bindings)


@pytest.mark.parametrize(
    "period,slowing,dperiod,flat",
    [(5, 3, 3, False), (7, 2, 5, False), (1, 1, 1, False), (5, 3, 3, True)],
)
def test_formula_and_smoothing_match_next_and_once(period, slowing, dperiod, flat):
    params = {"period": period, "slowing": slowing, "dperiod": dperiod}
    runnext = _run(False, flat=flat, **params)
    runonce = _run(True, flat=flat, **params)
    first_raw = period - 1
    first_k = first_raw + slowing - 1
    first_d = first_k + dperiod - 1
    assert runnext[0] == runonce[0] == first_d + 1
    for actual, expected in zip(runonce[1:], runnext[1:]):
        _assert_equal(actual, expected)

    prices = _prices(240, flat=flat)
    raw = [math.nan] * first_raw
    for i in range(first_raw, len(prices)):
        window = prices[i - period + 1 : i + 1]
        low, high = min(window), max(window)
        raw.append(100.0 * (prices[i] - low) / (high - low) if high != low else 0.0)
    expected_k = _ema(raw, slowing, first_raw)
    expected_d = _ema(expected_k, dperiod, first_k)
    _assert_equal(runnext[1], expected_k)
    _assert_equal(runnext[2], expected_d)


@pytest.mark.parametrize("runonce", [False, True])
def test_short_history_keeps_d_unavailable(runonce):
    minperiod, _perc_k, perc_d, downstream = _run(runonce, count=7)
    assert minperiod == 9
    assert all(math.isnan(value) for value in perc_d)
    assert all(math.isnan(value) for value in downstream)
