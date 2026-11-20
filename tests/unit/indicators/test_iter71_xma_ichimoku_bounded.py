"""Bounded XMA smoothing state and historical window behavior."""

import math
import random

import pytest

pd = pytest.importorskip("pandas")

import backtrader as bt
from backtrader.indicators.contrib.xma_ichimoku import (
    TwoXmaIchimokuOscillator,
    XmaIchimoku,
)


class _CaptureXmaStrategy(bt.Strategy):
    params = (
        ("x_length", 25),
        ("method", "SMA"),
        ("price_shift", 0.25),
        ("run_oscillator", False),
    )

    def __init__(self):
        self.xma = XmaIchimoku(
            self.data,
            up_period=1,
            dn_period=1,
            xma_method=self.p.method,
            x_length=self.p.x_length,
            price_shift=self.p.price_shift,
        )
        if self.p.run_oscillator:
            self.oscillator = TwoXmaIchimokuOscillator(
                self.data,
                up_period1=1,
                dn_period1=1,
                up_period2=1,
                dn_period2=1,
                x_length1=self.p.x_length,
                x_length2=self.p.x_length + 3,
            )
        self.raw_values = []
        self.values = []

    def next(self):
        self.raw_values.append((float(self.data.high[0]) + float(self.data.low[0])) / 2.0)
        self.values.append(float(self.xma.lines.value[0]))


class _DynamicXmaStrategy(bt.Strategy):
    def __init__(self):
        self.xma = XmaIchimoku(
            self.data,
            up_period=1,
            dn_period=1,
            xma_method="SMA",
            x_length=6,
            price_shift=0.25,
        )
        self.raw_values = []
        self.values = []
        self.periods = []
        self.methods = []

    def next(self):
        index = len(self.values)
        self.raw_values.append((float(self.data.high[0]) + float(self.data.low[0])) / 2.0)
        self.values.append(float(self.xma.lines.value[0]))
        self.periods.append(int(self.xma.p.x_length))
        self.methods.append(str(self.xma.p.xma_method).upper())

        # Expand before the initial six-item buffer has evicted history, then
        # exercise decreases, increases within retained capacity, and mode
        # changes through real Cerebro callbacks.
        if index == 0:
            self.xma.p.x_length = 8
        elif index == 8:
            self.xma.p.x_length = 3
        elif index == 16:
            self.xma.p.x_length = 8
        elif index == 24:
            self.xma.p.xma_method = "EMA"
        elif index == 32:
            self.xma.p.x_length = 4
        elif index == 40:
            self.xma.p.xma_method = "SMA"
        elif index == 48:
            self.xma.p.x_length = 2
        elif index == 56:
            self.xma.p.x_length = 5


class _GrowPastRetainedXmaStrategy(bt.Strategy):
    def __init__(self):
        self.xma = XmaIchimoku(
            self.data,
            up_period=1,
            dn_period=1,
            xma_method="SMA",
            x_length=3,
        )
        self.callbacks = 0

    def next(self):
        self.callbacks += 1
        if self.callbacks == 5:
            # The three-item window has already evicted older raw values.
            self.xma.p.x_length = 5


def _run(values, *, period, method="SMA", runonce=False, run_oscillator=False):
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=pd.date_range("2020-01-01", periods=len(values), freq="min"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(
        _CaptureXmaStrategy,
        x_length=period,
        method=method,
        run_oscillator=run_oscillator,
    )
    return cerebro.run(runonce=runonce, preload=True)[0]


def _run_strategy(values, strategy, *, runonce=False):
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=pd.date_range("2020-01-01", periods=len(values), freq="min"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(strategy)
    return cerebro.run(runonce=runonce, preload=True)[0]


def _expected_smoothing(raw_values, period, method, price_shift):
    result = []
    history = []
    smooth_previous = None
    alpha = 2.0 / (period + 1.0)
    alpha *= 1.0 + 0.35 * (15 / 100.0)
    alpha = max(0.01, min(0.99, alpha))
    for raw_value in raw_values:
        history.append(raw_value)
        if method in ("SMA", "MODE_SMA_"):
            smooth = (
                raw_value
                if len(history) < period
                else sum(history[-period:]) / float(period)
            )
        elif smooth_previous is None or not math.isfinite(smooth_previous):
            smooth = raw_value
            smooth_previous = smooth
        else:
            smooth = smooth_previous + alpha * (raw_value - smooth_previous)
            smooth_previous = smooth
        result.append(smooth + price_shift)
    return result


def _expected_dynamic_smoothing(raw_values, periods, methods, price_shift):
    result = []
    history = []
    smooth_previous = None
    for raw_value, period, method in zip(raw_values, periods, methods):
        history.append(raw_value)
        if method in ("SMA", "MODE_SMA_"):
            smooth = (
                raw_value
                if len(history) < period
                else sum(history[-period:]) / float(period)
            )
        else:
            alpha = 2.0 / (period + 1.0)
            alpha *= 1.0 + 0.35 * (15 / 100.0)
            alpha = max(0.01, min(0.99, alpha))
            if smooth_previous is None or not math.isfinite(smooth_previous):
                smooth = raw_value
            else:
                smooth = smooth_previous + alpha * (raw_value - smooth_previous)
            smooth_previous = smooth
        result.append(smooth + price_shift)
    return result


def _assert_same_float(actual, expected):
    if math.isnan(expected):
        assert math.isnan(actual)
    elif math.isinf(expected):
        # LineBuffer maps indicator infinities to its NaN default.
        assert math.isnan(actual)
    else:
        assert actual == expected


@pytest.mark.parametrize("method", ["SMA", "MODE_SMA_", "EMA"])
@pytest.mark.parametrize("runonce", [False, True], ids=["next", "runonce"])
def test_xma_smoothing_history_is_bounded_and_matches_window_formula(method, runonce):
    rng = random.Random(71)
    values = [100.0 + rng.uniform(-0.5, 0.5) for _ in range(5000)]
    strategy = _run(values, period=25, method=method, runonce=runonce)

    assert len(strategy.raw_values) > 4000
    assert len(strategy.xma._raw_buf) == 25
    assert strategy.xma._raw_buf.maxlen == 25
    expected = _expected_smoothing(strategy.raw_values, 25, method, 0.25)
    for actual, reference in zip(strategy.values, expected):
        _assert_same_float(actual, reference)


@pytest.mark.parametrize("value_kind", ["large-offset", "near-zero-cancellation"])
def test_xma_sma_matches_historical_sum_for_different_float_scales(value_kind):
    rng = random.Random(157)
    if value_kind == "large-offset":
        values = [1e12 + rng.random() for _ in range(5000)]
    else:
        values = [
            (1e8 if index % 2 else -1e8) + rng.random()
            for index in range(5000)
        ]
    strategy = _run(values, period=80, method="SMA", runonce=False)
    expected = _expected_smoothing(strategy.raw_values, 80, "SMA", 0.25)

    # The first full window still uses the original left-to-right sum order.
    assert strategy.values[79] == expected[79]
    for actual, reference in zip(strategy.values, expected):
        _assert_same_float(actual, reference)


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "runonce"])
def test_xma_sma_recomputes_after_non_finite_values_leave_window(runonce):
    values = [100.0 + index / 10.0 for index in range(80)]
    values[20] = math.nan
    # Finite inputs can overflow the midpoint expression to +/-inf while the
    # line buffer still accepts the original bar values.
    values[27] = 1e308
    values[28] = -1e308
    values[31] = 1e308
    values[45] = math.nan
    strategy = _run(values, period=3, method="SMA", runonce=runonce)

    expected = _expected_smoothing(strategy.raw_values, 3, "SMA", 0.25)
    for actual, reference in zip(strategy.values, expected):
        _assert_same_float(actual, reference)
    assert any(math.isnan(value) for value in strategy.values)
    assert any(math.isinf(value) for value in strategy.raw_values)
    assert math.isfinite(strategy.values[-1])
    assert len(strategy.xma._raw_buf) == 3
    assert strategy.xma._raw_buf.maxlen == 3


def test_xma_tracks_runtime_length_and_method_changes_with_cerebro():
    values = [100.0 + ((index * 37) % 101) / 10.0 for index in range(100)]
    strategy = _run_strategy(values, _DynamicXmaStrategy)

    assert strategy.periods[0] == 6
    assert 8 in strategy.periods and 3 in strategy.periods and 2 in strategy.periods
    assert "EMA" in strategy.methods
    assert strategy.methods[-1] == "SMA"
    assert strategy.xma._raw_buf.maxlen == 8
    expected = _expected_dynamic_smoothing(
        strategy.raw_values, strategy.periods, strategy.methods, 0.25
    )
    for actual, reference in zip(strategy.values, expected):
        _assert_same_float(actual, reference)


def test_xma_fails_closed_when_runtime_sma_length_exceeds_retained_history():
    values = [100.0 + index / 10.0 for index in range(40)]
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=pd.date_range("2020-01-01", periods=len(values), freq="min"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(_GrowPastRetainedXmaStrategy)

    with pytest.raises(ValueError, match="older raw values were discarded"):
        cerebro.run(runonce=False, preload=True)


def test_two_xma_oscillator_children_keep_only_their_smoothing_windows():
    values = [100.0 + ((index * 19) % 89) / 100.0 for index in range(5000)]
    strategy = _run(
        values,
        period=25,
        method="SMA",
        runonce=False,
        run_oscillator=True,
    )

    assert strategy.oscillator.xma1._raw_buf.maxlen == 25
    assert strategy.oscillator.xma2._raw_buf.maxlen == 28
    assert len(strategy.oscillator.xma1._raw_buf) == 25
    assert len(strategy.oscillator.xma2._raw_buf) == 28
