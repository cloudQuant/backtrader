"""Regression coverage for KAMA's runonce seed alignment."""

import math
from types import SimpleNamespace

import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators as btind
from backtrader.indicators.kama import AdaptiveMovingAverage


PERIOD = 4
FAST = 2
SLOW = 6
CLOSE = [100.0, 102.0, 101.0, 105.0, 108.0, 106.0, 111.0, 112.0, 109.0, 115.0]
NAN_IN_SEED = [100.0, 102.0, float("nan"), 105.0, 108.0, 106.0, 111.0]
NAN_AFTER_SEED = [
    100.0,
    102.0,
    101.0,
    105.0,
    108.0,
    float("nan"),
    111.0,
    112.0,
    109.0,
    115.0,
    118.0,
    117.0,
    120.0,
]


def _run_kama(prices, runonce):
    """Return the complete KAMA line from a synthetic feed."""
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1.0] * len(prices),
            "openinterest": [0.0] * len(prices),
        },
        index=pd.date_range("2020-01-01", periods=len(prices), freq="D"),
    )
    result = {}

    class KAMAProbeStrategy(bt.Strategy):
        def __init__(self):
            self.kama = btind.KAMA(
                self.data.close, period=PERIOD, fast=FAST, slow=SLOW
            )

        def stop(self):
            result["kama"] = [float(value) for value in self.kama.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(KAMAProbeStrategy)
    cerebro.run(runonce=runonce, preload=True)
    return result["kama"]


def _run_kama_on_sma(prices, runonce):
    """Return KAMA over a real SMA indicator input in either engine mode."""
    source_period = 3
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1.0] * len(prices),
            "openinterest": [0.0] * len(prices),
        },
        index=pd.date_range("2020-01-01", periods=len(prices), freq="D"),
    )
    result = {}

    class KAMAOnSMAProbeStrategy(bt.Strategy):
        def __init__(self):
            self.source = btind.SMA(self.data.close, period=source_period)
            self.kama = btind.KAMA(
                self.source, period=PERIOD, fast=FAST, slow=SLOW
            )

        def stop(self):
            result["source"] = [float(value) for value in self.source.array]
            result["kama"] = [float(value) for value in self.kama.array]
            result["source_minperiod"] = self.source._minperiod
            result["kama_input_minperiod"] = self.kama.data._minperiod
            result["kama_minperiod"] = self.kama._minperiod

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(KAMAOnSMAProbeStrategy)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _run_kama_in_chunks(prices, input_minperiod=1):
    """Call once over adjacent ranges and retain per-call outside sentinels."""
    sentinel = -999999.0
    output = [sentinel - index for index in range(len(prices))]
    seed_index = input_minperiod + PERIOD - 2
    indicator = SimpleNamespace(
        data=SimpleNamespace(array=prices, _minperiod=input_minperiod),
        lines=SimpleNamespace(kama=SimpleNamespace(array=output)),
        p=SimpleNamespace(period=PERIOD),
        fast_sc=2.0 / (FAST + 1.0),
        slow_sc=2.0 / (SLOW + 1.0),
    )
    boundaries = {0, len(prices)}
    for boundary in (seed_index, seed_index + 1, seed_index + 2):
        if 0 < boundary < len(prices):
            boundaries.add(boundary)
    for index, value in enumerate(prices):
        if math.isnan(value):
            for boundary in (index, index + 1, index + PERIOD + 1):
                if 0 < boundary < len(prices):
                    boundaries.add(boundary)

    points = sorted(boundaries)
    for start, end in zip(points, points[1:]):
        previous = output[:]
        AdaptiveMovingAverage.once(indicator, start, end)
        for index, (before, after) in enumerate(zip(previous, output)):
            if not start <= index < end:
                assert after == before or (math.isnan(after) and math.isnan(before))

    return output


def _reference_kama(prices, source_start=0):
    """Compute KAMA from its SMA seed and period-sized price-change window."""
    result = [float("nan")] * len(prices)
    seed_index = source_start + PERIOD - 1
    if seed_index >= len(prices):
        return result

    previous = sum(prices[source_start : seed_index + 1]) / PERIOD
    result[seed_index] = previous
    fast_sc = 2.0 / (FAST + 1.0)
    slow_sc = 2.0 / (SLOW + 1.0)

    for index in range(seed_index + 1, len(prices)):
        direction = prices[index] - prices[index - PERIOD]
        volatility = sum(
            abs(prices[current] - prices[current - 1])
            for current in range(index - PERIOD + 1, index + 1)
        )
        efficiency_ratio = abs(direction / volatility) if volatility else 0.0
        smoothing = (
            efficiency_ratio * (fast_sc - slow_sc) + slow_sc
        ) ** 2
        previous += smoothing * (prices[index] - previous)
        result[index] = previous

    return result


def _assert_matches_reference(actual, expected):
    assert len(actual) == len(expected)
    assert [math.isnan(value) for value in actual] == [
        math.isnan(value) for value in expected
    ]
    for actual_value, expected_value in zip(actual, expected):
        if not math.isnan(expected_value):
            assert actual_value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            )


def test_kama_runonce_matches_runnext_and_independent_reference():
    """Runonce seeds on bar period-1 and matches every recursive value."""
    expected = _reference_kama(CLOSE)
    runnext = _run_kama(CLOSE, runonce=False)
    runonce = _run_kama(CLOSE, runonce=True)

    assert math.isnan(runnext[PERIOD - 2])
    assert math.isnan(runonce[PERIOD - 2])
    assert runnext[PERIOD - 1] == pytest.approx(sum(CLOSE[:PERIOD]) / PERIOD)
    assert runonce[PERIOD - 1] == pytest.approx(sum(CLOSE[:PERIOD]) / PERIOD)
    _assert_matches_reference(runnext, expected)
    _assert_matches_reference(runonce, expected)


@pytest.mark.parametrize("length", [5, 6, 7, len(CLOSE)])
def test_kama_runonce_respects_upstream_sma_minperiod(length):
    """KAMA seeds after the full SMA input window becomes available."""
    prices = CLOSE[:length]
    source_period = 3
    source_start = source_period - 1
    source_expected = [float("nan")] * source_start + [
        sum(prices[index - source_period + 1 : index + 1]) / source_period
        for index in range(source_start, len(prices))
    ]
    expected = _reference_kama(source_expected, source_start=source_start)
    runnext = _run_kama_on_sma(prices, runonce=False)
    runonce = _run_kama_on_sma(prices, runonce=True)

    assert runnext["source_minperiod"] == runonce["source_minperiod"] == source_period
    assert runnext["kama_input_minperiod"] == runonce["kama_input_minperiod"] == (
        source_period
    )
    assert runnext["kama_minperiod"] == runonce["kama_minperiod"] == (
        source_period + PERIOD - 1
    )
    _assert_matches_reference(runnext["source"], source_expected)
    _assert_matches_reference(runonce["source"], source_expected)
    _assert_matches_reference(runnext["kama"], expected)
    _assert_matches_reference(runonce["kama"], expected)
    _assert_matches_reference(
        _run_kama_in_chunks(source_expected, input_minperiod=source_period), expected
    )


@pytest.mark.parametrize("length", [1, PERIOD - 1, PERIOD, PERIOD + 1])
def test_kama_short_history_seed_and_warmup_match_runnext(length):
    """Short inputs stay warmup-only until the exact SMA seed bar."""
    prices = CLOSE[:length]
    expected = _reference_kama(prices)
    runnext = _run_kama(prices, runonce=False)
    runonce = _run_kama(prices, runonce=True)

    _assert_matches_reference(runnext, expected)
    _assert_matches_reference(runonce, expected)


@pytest.mark.parametrize(
    "prices",
    [
        pytest.param(CLOSE, id="full-history"),
        pytest.param(CLOSE[: PERIOD - 1], id="short-before-seed"),
        pytest.param(CLOSE[:PERIOD], id="exact-seed-length"),
        pytest.param(CLOSE[: PERIOD + 1], id="first-recursive-value"),
        pytest.param(NAN_IN_SEED, id="nan-in-seed-window"),
        pytest.param(NAN_AFTER_SEED, id="nan-after-seed"),
    ],
)
def test_kama_once_chunks_match_full_run_and_runnext(prices):
    """Chunked once respects each range and matches full calculation and NaNs."""
    expected = _reference_kama(prices)
    runnext = _run_kama(prices, runonce=False)
    full_once = _run_kama(prices, runonce=True)
    chunked_once = _run_kama_in_chunks(prices)

    _assert_matches_reference(runnext, expected)
    _assert_matches_reference(full_once, expected)
    _assert_matches_reference(chunked_once, expected)


def test_kama_once_empty_slice_is_a_noop():
    """An empty [start, end) range cannot extend or rewrite the output line."""
    output = []
    indicator = SimpleNamespace(
        data=SimpleNamespace(array=CLOSE),
        lines=SimpleNamespace(kama=SimpleNamespace(array=output)),
        p=SimpleNamespace(period=PERIOD),
        fast_sc=2.0 / (FAST + 1.0),
        slow_sc=2.0 / (SLOW + 1.0),
    )

    AdaptiveMovingAverage.once(indicator, PERIOD, PERIOD)

    assert output == []
