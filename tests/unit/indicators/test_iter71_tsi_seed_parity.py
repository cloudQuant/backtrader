"""Regression coverage for TSI EMA seeding and runonce parity (R71-153)."""

import math

import backtrader as bt
import pandas as pd
import pytest


_DEFAULT_CLOSES = tuple(
    100.0 + ((index * 7) % 13) - 6.0 for index in range(45)
)


def _reference_tsi(closes, period1, period2, pchange, source_minperiod=1):
    """Calculate nested SMA-seeded EMAs without using Backtrader helpers."""
    values = [float("nan")] * len(closes)
    first_pc = source_minperiod - 1 + pchange
    first_ema1 = first_pc + period1 - 1
    first_tsi = first_ema1 + period2 - 1
    if first_tsi >= len(closes):
        return values, first_tsi + 1

    alpha1 = 2.0 / (period1 + 1.0)
    alpha2 = 2.0 / (period2 + 1.0)
    ema1 = sum(
        closes[index] - closes[index - pchange]
        for index in range(first_pc, first_ema1 + 1)
    ) / period1
    abs_ema1 = sum(
        abs(closes[index] - closes[index - pchange])
        for index in range(first_pc, first_ema1 + 1)
    ) / period1

    ema1_values = [ema1]
    abs_ema1_values = [abs_ema1]
    for index in range(first_ema1 + 1, len(closes)):
        change = closes[index] - closes[index - pchange]
        ema1 = ema1 * (1.0 - alpha1) + change * alpha1
        abs_ema1 = abs_ema1 * (1.0 - alpha1) + abs(change) * alpha1
        ema1_values.append(ema1)
        abs_ema1_values.append(abs_ema1)

    ema2 = sum(ema1_values[:period2]) / period2
    abs_ema2 = sum(abs_ema1_values[:period2]) / period2
    values[first_tsi] = 0.0 if abs_ema2 == 0.0 else 100.0 * ema2 / abs_ema2

    for offset, index in enumerate(range(first_tsi + 1, len(closes)), start=period2):
        ema2 = ema2 * (1.0 - alpha2) + ema1_values[offset] * alpha2
        abs_ema2 = abs_ema2 * (1.0 - alpha2) + abs_ema1_values[offset] * alpha2
        values[index] = 0.0 if abs_ema2 == 0.0 else 100.0 * ema2 / abs_ema2

    return values, first_tsi + 1


def _run_tsi(
    closes,
    period1,
    period2,
    pchange,
    runonce,
    source_sma_period=None,
    movav=None,
):
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )
    result = {}

    class TsiProbe(bt.Strategy):
        def __init__(self):
            source = self.data.close
            if source_sma_period is not None:
                source = bt.indicators.SMA(source, period=source_sma_period)
            params = {"period1": period1, "period2": period2, "pchange": pchange}
            if movav is not None:
                params["_movav"] = movav
            self.tsi = bt.indicators.TSI(source, **params)

        def stop(self):
            result["minperiod"] = self.tsi._minperiod
            result["values"] = list(self.tsi.tsi.array)
            result["indicator"] = self.tsi

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(TsiProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _reference_sma_tsi(closes, period1, period2, pchange):
    """Calculate TSI with two nested simple moving averages."""
    values = [float("nan")] * len(closes)
    first_ema1 = pchange + period1 - 1
    first_tsi = first_ema1 + period2 - 1
    if first_tsi >= len(closes):
        return values, first_tsi + 1

    momentum = [float("nan")] * len(closes)
    abs_momentum = [float("nan")] * len(closes)
    for index in range(pchange, len(closes)):
        change = closes[index] - closes[index - pchange]
        momentum[index] = change
        abs_momentum[index] = abs(change)

    sm1 = [float("nan")] * len(closes)
    sm2 = [float("nan")] * len(closes)
    for index in range(first_ema1, len(closes)):
        start = index - period1 + 1
        sm1[index] = sum(momentum[start : index + 1]) / period1
        sm2[index] = sum(abs_momentum[start : index + 1]) / period1

    for index in range(first_tsi, len(closes)):
        start = index - period2 + 1
        numerator = sum(sm1[start : index + 1]) / period2
        denominator = sum(sm2[start : index + 1]) / period2
        values[index] = 0.0 if denominator == 0.0 else 100.0 * numerator / denominator

    return values, first_tsi + 1


@pytest.mark.parametrize(
    "closes, period1, period2, pchange",
    [
        ([100.0, 103.0, 101.0, 106.0, 107.0, 102.0, 108.0, 105.0, 111.0, 110.0], 3, 2, 1),
        ([10.0, 12.0, 11.0, 16.0, 15.0, 18.0, 14.0, 20.0, 19.0, 23.0], 3, 2, 2),
        ([7.0] * 9, 1, 1, 1),
        ([5.0, 8.0, 6.0, 9.0, 7.0, 11.0, 10.0], 1, 3, 1),
    ],
)
def test_tsi_full_sequence_matches_nested_ema_reference(
    closes, period1, period2, pchange
):
    """Both execution modes match the SMA-seeded EMA formula at every bar."""
    expected, minperiod = _reference_tsi(closes, period1, period2, pchange)
    runnext = _run_tsi(closes, period1, period2, pchange, runonce=False)
    runonce = _run_tsi(closes, period1, period2, pchange, runonce=True)

    assert runnext["minperiod"] == runonce["minperiod"] == minperiod
    for actual in (runnext["values"], runonce["values"]):
        assert len(actual) == len(expected) == len(closes)
        assert all(math.isnan(value) for value in actual[: minperiod - 1])
        assert actual[minperiod - 1 :] == pytest.approx(expected[minperiod - 1 :])


@pytest.mark.parametrize("runonce", (False, True))
@pytest.mark.parametrize("length, expected_valid", ((5, False), (6, True), (7, True)))
def test_tsi_minimum_period_boundary(runonce, length, expected_valid):
    """The first output appears exactly after both EMA windows are seeded."""
    closes = [10.0, 12.0, 11.0, 16.0, 15.0, 18.0, 14.0][:length]
    result = _run_tsi(closes, period1=3, period2=2, pchange=2, runonce=runonce)

    assert result["minperiod"] == 6
    if expected_valid:
        assert math.isnan(result["values"][4])
        assert math.isfinite(result["values"][5])
    else:
        assert all(math.isnan(value) for value in result["values"])


def test_tsi_default_warmup_contract_and_full_sequence():
    """The default 25/13/1 configuration first yields a value at bar 38."""
    expected, minperiod = _reference_tsi(
        _DEFAULT_CLOSES, period1=25, period2=13, pchange=1
    )
    assert minperiod == 38

    for runonce in (False, True):
        result = _run_tsi(
            _DEFAULT_CLOSES, period1=25, period2=13, pchange=1, runonce=runonce
        )
        assert result["minperiod"] == 38
        assert all(math.isnan(value) for value in result["values"][:37])
        assert result["values"][37:] == pytest.approx(expected[37:])


def test_tsi_preserves_source_minperiod_and_warms_from_first_valid_input():
    """A line input's own warmup precedes the TSI price-change windows."""
    closes = [10.0, 12.0, 11.0, 16.0, 15.0, 18.0, 14.0, 20.0, 19.0]
    source_period = 3
    source = [float("nan")] * (source_period - 1)
    source.extend(
        sum(closes[index - source_period + 1 : index + 1]) / source_period
        for index in range(source_period - 1, len(closes))
    )
    expected, minperiod = _reference_tsi(
        source, period1=2, period2=2, pchange=1, source_minperiod=source_period
    )

    for runonce in (False, True):
        result = _run_tsi(
            closes,
            period1=2,
            period2=2,
            pchange=1,
            runonce=runonce,
            source_sma_period=source_period,
        )
        assert result["minperiod"] == minperiod == 6
        assert all(math.isnan(value) for value in result["values"][:5])
        assert result["values"][5:] == pytest.approx(expected[5:])


def test_tsi_once_segments_only_write_the_requested_range():
    """Disjoint once calls preserve sentinels outside each requested slice."""
    closes = [100.0, 103.0, 101.0, 106.0, 107.0, 102.0, 108.0, 105.0, 111.0, 110.0]
    expected, _ = _reference_tsi(closes, period1=3, period2=2, pchange=1)
    result = _run_tsi(closes, 3, 2, 1, runonce=False)
    indicator = result["indicator"]
    line = indicator.lines.tsi.array
    sentinel = -987654.321
    for index in range(len(line)):
        line[index] = sentinel

    for start, end in ((0, 3), (3, 6), (6, len(closes))):
        before = list(line)
        indicator.once(start, end)
        for index, old_value in enumerate(before):
            if not start <= index < end:
                    new_value = line[index]
                    assert new_value == old_value or (
                        math.isnan(new_value) and math.isnan(old_value)
                    )

    assert all(math.isnan(value) for value in line[:4])
    assert line[4:] == pytest.approx(expected[4:])


def test_tsi_honors_nondefault_moving_average_parameter():
    """A custom _movav uses nested moving averages instead of the EMA path."""
    closes = [100.0, 103.0, 101.0, 106.0, 107.0, 102.0, 108.0, 105.0, 111.0, 110.0]
    expected, minperiod = _reference_sma_tsi(
        closes, period1=3, period2=2, pchange=1
    )

    for runonce in (False, True):
        result = _run_tsi(
            closes,
            period1=3,
            period2=2,
            pchange=1,
            runonce=runonce,
            movav=bt.indicators.SMA,
        )
        assert result["minperiod"] == minperiod == 5
        assert result["values"][4:] == pytest.approx(expected[4:])


def test_tsi_nan_gap_keeps_both_execution_modes_poisoned():
    """The default TSI recurrence propagates a missing price in both modes."""
    closes = [
        100.0,
        103.0,
        101.0,
        106.0,
        107.0,
        102.0,
        108.0,
        105.0,
        float("nan"),
        110.0,
        112.0,
        109.0,
        115.0,
        113.0,
        117.0,
        116.0,
    ]
    gap_index = 8
    expected, minperiod = _reference_tsi(
        closes, period1=3, period2=2, pchange=1
    )

    for runonce in (False, True):
        result = _run_tsi(
            closes, period1=3, period2=2, pchange=1, runonce=runonce
        )
        assert result["minperiod"] == minperiod == 5
        assert all(math.isnan(value) for value in result["values"][:4])
        assert result["values"][4:gap_index] == pytest.approx(
            expected[4:gap_index]
        )
        assert all(math.isnan(value) for value in result["values"][gap_index:])
