"""Regression tests for ZLEMA warmup and execution-mode parity."""

import math

import backtrader as bt
import backtrader.indicators as btind
import pandas as pd
import pytest


def _prices(count):
    return [
        100.0 + index * 0.37 + math.sin(index / 3.0) * 4.0
        + ((index * 7) % 11) * 0.2
        for index in range(count)
    ]


def _sma_reference(values, period):
    result = [float("nan")] * len(values)
    for index in range(period - 1, len(values)):
        result[index] = sum(values[index - period + 1 : index + 1]) / period
    return result


def _zlema_reference(values, period, source_minperiod=1):
    """Independently calculate the SMA-seeded EMA of lag-adjusted inputs."""
    lag = (period - 1) // 2
    source_start = source_minperiod - 1
    first = source_start + lag + period - 1
    result = [float("nan")] * len(values)
    if first >= len(values):
        return result

    adjusted = [
        2.0 * values[index] - values[index - lag]
        for index in range(source_start + lag, len(values))
    ]
    seed_offset = source_start + lag
    seed_values = adjusted[:period]
    previous = sum(seed_values) / period
    result[first] = previous

    alpha = 2.0 / (period + 1.0)
    alpha1 = 1.0 - alpha
    for index in range(first + 1, len(values)):
        previous = previous * alpha1 + adjusted[index - seed_offset] * alpha
        result[index] = previous

    return result


class _ZlemaProbe(bt.Strategy):
    params = (
        ("period", 30),
        ("source_period", None),
    )

    def __init__(self):
        if self.p.source_period is None:
            source = self.data.close
        else:
            self.source = btind.SMA(self.data.close, period=self.p.source_period)
            source = self.source

        self.zlema = btind.ZLEMA(source, period=self.p.period)


def _run_zlema(runonce, count, period=30, source_period=None, prices=None):
    prices = _prices(count) if prices is None else list(prices)
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1.0 for price in prices],
            "low": [price - 1.0 for price in prices],
            "close": prices,
            "volume": [1000.0] * count,
            "openinterest": [0.0] * count,
        },
        index=pd.date_range("2026-01-01", periods=count, freq="D"),
    )
    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(
        _ZlemaProbe,
        period=period,
        source_period=source_period,
    )
    strategy = cerebro.run()[0]

    raw_reference = prices
    source_minperiod = 1
    if source_period is not None:
        raw_reference = _sma_reference(prices, source_period)
        source_minperiod = source_period

    return (
        prices,
        strategy.zlema._minperiod,
        list(strategy.zlema.lines.zlema.array[:count]),
        _zlema_reference(raw_reference, period, source_minperiod),
        strategy.zlema,
    )


def _assert_series_equal(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        if math.isnan(want):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize(
    ("period", "source_period"),
    [
        (30, None),  # Existing default-period regression: 30 + lag(14) = 44.
        (6, None),  # Even period uses lag 2.
        (1, None),  # Zero lag must not add a warmup bar.
        (7, 4),  # Upstream SMA warmup composes once with ZLEMA's own lookback.
    ],
    ids=("default-raw", "even-raw", "period-one-raw", "upstream-sma"),
)
def test_zlema_minperiod_and_full_output_match_reference(period, source_period):
    lag = (period - 1) // 2
    expected_minperiod = period + lag
    if source_period is not None:
        expected_minperiod += source_period - 1

    sequences = {
        runonce: _run_zlema(
            runonce,
            count=expected_minperiod + 35,
            period=period,
            source_period=source_period,
        )
        for runonce in (False, True)
    }

    for prices, minperiod, actual, expected, _ in sequences.values():
        assert minperiod == expected_minperiod
        _assert_series_equal(actual, expected)

        actual_signals = [
            1 if price > value else -1 if price < value else 0
            for price, value in zip(prices, actual)
            if math.isfinite(value)
        ]
        expected_signals = [
            1 if price > value else -1 if price < value else 0
            for price, value in zip(prices, expected)
            if math.isfinite(value)
        ]
        assert actual_signals == expected_signals

    _assert_series_equal(sequences[False][2], sequences[True][2])


@pytest.mark.parametrize(
    ("period", "source_period"),
    [(30, None), (7, 4)],
    ids=("raw", "upstream-sma"),
)
@pytest.mark.parametrize("runonce", [False, True], ids=("runnext", "runonce"))
def test_zlema_short_history_stays_warmup_nan(period, source_period, runonce):
    lag = (period - 1) // 2
    expected_minperiod = period + lag
    if source_period is not None:
        expected_minperiod += source_period - 1

    _, minperiod, actual, _, _ = _run_zlema(
        runonce,
        count=expected_minperiod - 1,
        period=period,
        source_period=source_period,
    )

    assert minperiod == expected_minperiod
    assert len(actual) == expected_minperiod - 1
    assert all(math.isnan(value) for value in actual)


@pytest.mark.parametrize(
    ("period", "source_period"),
    [(7, None), (7, 4)],
    ids=("raw", "upstream-sma"),
)
def test_zlema_once_segments_only_write_their_range_and_continue(
    period, source_period
):
    count = 48
    prices, _, _, expected, zlema = _run_zlema(
        runonce=False,
        count=count,
        period=period,
        source_period=source_period,
    )
    output = zlema.lines.zlema.array
    canary = 1.0e100
    for index in range(count):
        output[index] = canary

    source_start = (source_period or 1) - 1
    seed_idx = source_start + (period - 1) // 2 + period - 1
    first_end = seed_idx - 2
    second_end = seed_idx + 5

    zlema.once(0, first_end)
    _assert_series_equal(list(output[:first_end]), expected[:first_end])
    assert all(value == canary for value in output[first_end:])

    first_segment = list(output[:first_end])
    zlema.once(first_end, second_end)
    _assert_series_equal(list(output[:first_end]), first_segment)
    _assert_series_equal(list(output[first_end:second_end]), expected[first_end:second_end])
    assert all(value == canary for value in output[second_end:])

    second_segment = list(output[:second_end])
    zlema.once(second_end, count)
    _assert_series_equal(list(output[:second_end]), second_segment)
    _assert_series_equal(list(output[second_end:count]), expected[second_end:count])


@pytest.mark.parametrize("runonce", [False, True], ids=("runnext", "runonce"))
@pytest.mark.parametrize("nan_index", [0, 20], ids=("initial-nan", "midstream-nan"))
def test_zlema_nan_state_matches_between_execution_modes(runonce, nan_index):
    period = 7
    count = 48
    prices = _prices(count)
    prices[nan_index] = float("nan")

    _, minperiod, actual, expected, _ = _run_zlema(
        runonce=runonce,
        count=count,
        period=period,
        prices=prices,
    )

    assert minperiod == period + (period - 1) // 2
    _assert_series_equal(actual, expected)
