"""BlauErgodic signal and spread agree with a triple-EMA reference."""

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


def _run(runonce, *, count=350, flat=False, **params):
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
            self.indicator = bt.indicators.BlauErgodic(self.data, **params)
            self.downstream = bt.indicators.SMA(self.indicator.spread, period=3)

        def stop(self):
            self.result = (
                self.indicator._minperiod,
                list(self.indicator.main.array),
                list(self.indicator.signal.array),
                list(self.indicator.spread.array),
                list(self.downstream.array),
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].result


def _ema(values, period, source_start):
    """Calculate EMA from a known first valid input using an SMA seed."""
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


def test_main_binding_precedes_signal_registration(monkeypatch):
    module = importlib.import_module("backtrader.indicators.contrib.blau_ergodic")
    original_divide = module.btfunc.DivByZero
    original_ema = module.EMA
    observed = {}

    def capture_main(*args, **kwargs):
        main = original_divide(*args, **kwargs)
        observed["main"] = main
        return main

    def capture_ema(*args, **kwargs):
        main = observed.get("main")
        if main is not None and args[0] is main:
            owner = main._owner
            # The public main binding and its owner registration must already
            # exist before the signal EMA is constructed and registered.
            assert any(line is owner.l.main for line in main.bindings)
            assert any(child is main for child in owner._lineiterators[0])
            signal = original_ema(*args, **kwargs)
            observed["signal"] = signal
            assert signal.data is main
            assert signal._owner is owner
            return signal
        return original_ema(*args, **kwargs)

    monkeypatch.setattr(module.btfunc, "DivByZero", capture_main)
    monkeypatch.setattr(module, "EMA", capture_ema)
    _run(False, count=40)

    main = observed["main"]
    signal = observed["signal"]
    owner = main._owner
    children = owner._lineiterators[0]
    assert next(i for i, child in enumerate(children) if child is main) < next(
        i for i, child in enumerate(children) if child is signal
    )
    assert any(line is owner.l.signal for line in signal.lines[0].bindings)


@pytest.mark.parametrize(
    "shift,periods,signal_period,flat",
    [(1, (20, 5, 3), 3, False), (3, (5, 3, 2), 4, False),
     (1, (1, 2, 1), 1, False), (1, (20, 5, 3), 3, True)],
)
def test_formula_signal_and_spread_match_next_and_once(shift, periods, signal_period, flat):
    params = {
        "xlength": shift + 1,
        "xlength1": periods[0],
        "xlength2": periods[1],
        "xlength3": periods[2],
        "xlength4": signal_period,
    }
    runnext = _run(False, flat=flat, **params)
    runonce = _run(True, flat=flat, **params)
    first_main = shift + sum(period - 1 for period in periods)
    first_signal = first_main + signal_period - 1
    assert runnext[0] == runonce[0] == first_signal + 1
    for actual, expected in zip(runonce[1:], runnext[1:]):
        _assert_equal(actual, expected)

    prices = _prices(350, flat=flat)
    momentum = [math.nan] * shift + [
        prices[i] - prices[i - shift] for i in range(shift, len(prices))
    ]
    absolute = [abs(value) for value in momentum]
    first = shift
    for period in periods:
        momentum = _ema(momentum, period, first)
        absolute = _ema(absolute, period, first)
        first += period - 1
    expected_main = [math.nan] * first_main + [
        100.0 * momentum[i] / absolute[i] if absolute[i] else 0.0
        for i in range(first_main, len(prices))
    ]
    expected_signal = _ema(expected_main, signal_period, first_main)
    expected_spread = [math.nan] * first_signal + [
        expected_main[i] - expected_signal[i] for i in range(first_signal, len(prices))
    ]
    # main's pre-warmup projection is existing behavior; check the formula
    # only where all three smoothing stages have a complete input history.
    _assert_equal(runnext[1][first_main:], expected_main[first_main:])
    _assert_equal(runnext[2], expected_signal)
    _assert_equal(runnext[3], expected_spread)


@pytest.mark.parametrize("runonce", [False, True])
def test_short_history_keeps_signal_and_spread_unavailable(runonce):
    minperiod, _main, signal, spread, downstream = _run(runonce, count=25)
    assert minperiod == 29
    assert all(math.isnan(value) for value in signal)
    assert all(math.isnan(value) for value in spread)
    assert all(math.isnan(value) for value in downstream)
