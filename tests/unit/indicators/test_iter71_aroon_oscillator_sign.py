"""R71-036 coverage for Aroon bars-ago sign and threshold crossings."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.aroon_oscillator_sign_alert import (
    AroonOscillatorSignAlert,
)


AROON_PERIOD = 4
ATR_PERIOD = 3
UP_LEVEL = 50.0
DN_LEVEL = -50.0
MINPERIOD = max(AROON_PERIOD, ATR_PERIOD) + 3


def _frame_from_closes(closes):
    """Create finite, deterministic OHLC bars for the real Cerebro probe."""
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D"),
    )


def _tie_frame(highs, lows):
    """Put a four-bar extreme-tie vector at the first valid Aroon bar."""
    highs = [105.0, 105.0, 105.0] + list(highs)
    lows = [95.0, 95.0, 95.0] + list(lows)
    centers = [100.0] * len(highs)
    return pd.DataFrame(
        {
            "open": centers,
            "high": highs,
            "low": lows,
            "close": centers,
            "volume": [1.0] * len(highs),
            "openinterest": [0.0] * len(highs),
        },
        index=pd.date_range("2026-02-01", periods=len(highs), freq="D"),
    )


def _run_cerebro(frame, runonce):
    """Return every Aroon oscillator and trigger line from actual Cerebro."""
    result = {}

    class AroonSignProbe(bt.Strategy):
        def __init__(self):
            self.indicator = AroonOscillatorSignAlert(
                self.data,
                atr_period=ATR_PERIOD,
                aroon_period=AROON_PERIOD,
                up_level=UP_LEVEL,
                dn_level=DN_LEVEL,
            )

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            for name in ("osc", "buy", "sell"):
                result[name] = [
                    float(value) for value in getattr(self.indicator.lines, name).array
                ]
            result["atr"] = [float(value) for value in self.indicator.atr.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(
        bt.feeds.PandasData(
            dataname=frame,
            timeframe=bt.TimeFrame.Days,
            compression=1,
        )
    )
    cerebro.addstrategy(AroonSignProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _reference(frame, atr):
    """Compute bars-ago Aroon sign and level-cross alerts independently."""
    highs = [float(value) for value in frame["high"]]
    lows = [float(value) for value in frame["low"]]
    oscillator = [float("nan")] * len(frame)
    buy = [float("nan")] * len(frame)
    sell = [float("nan")] * len(frame)

    for index in range(MINPERIOD - 1, len(frame)):
        high_bars_ago = [highs[index - age] for age in range(AROON_PERIOD)]
        low_bars_ago = [lows[index - age] for age in range(AROON_PERIOD)]
        highest = high_bars_ago.index(max(high_bars_ago))
        lowest = low_bars_ago.index(min(low_bars_ago))
        value = 100.0 * (lowest - highest) / AROON_PERIOD
        oscillator[index] = value

        previous = oscillator[index - 1]
        if value > DN_LEVEL and previous <= DN_LEVEL:
            buy[index] = float(frame["low"].iloc[index]) - float(atr[index]) * 3.0 / 8.0
        if value < UP_LEVEL and previous >= UP_LEVEL:
            sell[index] = (
                float(frame["high"].iloc[index]) + float(atr[index]) * 3.0 / 8.0
            )

    return oscillator, buy, sell


def _assert_same_line(actual, expected):
    assert len(actual) == len(expected)
    assert [math.isnan(value) for value in actual] == [
        math.isnan(value) for value in expected
    ]
    for actual_value, expected_value in zip(actual, expected):
        if not math.isnan(expected_value):
            assert actual_value == pytest.approx(expected_value, rel=1e-12, abs=1e-12)


_FULL_CLOSES = [
    110.0,
    109.0,
    108.0,
    107.0,
    106.0,
    105.0,
    104.0,
    105.0,
    106.0,
    107.0,
    108.0,
    109.0,
    110.0,
    109.0,
    108.0,
    107.0,
    106.0,
    105.0,
    104.0,
    103.0,
    104.0,
    105.0,
    106.0,
    107.0,
    108.0,
    107.0,
    106.0,
    105.0,
    104.0,
    103.0,
    102.0,
    101.0,
    102.0,
    103.0,
    104.0,
    105.0,
]


@pytest.mark.parametrize("runonce", (False, True))
def test_aroon_oscillator_sign_and_crosses_match_bars_ago_reference(runonce):
    """Both execution modes match the full independent oscillator/alert series."""
    frame = _frame_from_closes(_FULL_CLOSES)
    result = _run_cerebro(frame, runonce)
    expected_osc, expected_buy, expected_sell = _reference(frame, result["atr"])

    assert result["minperiod"] == MINPERIOD
    assert len(result["osc"]) == len(frame)
    assert all(math.isnan(value) for value in result["osc"][: MINPERIOD - 1])
    _assert_same_line(result["osc"], expected_osc)
    _assert_same_line(result["buy"], expected_buy)
    _assert_same_line(result["sell"], expected_sell)
    buy_indices = [
        index for index, value in enumerate(expected_buy) if math.isfinite(value)
    ]
    sell_indices = [
        index for index, value in enumerate(expected_sell) if math.isfinite(value)
    ]
    assert buy_indices
    assert sell_indices
    assert all(
        expected_osc[index - 1] <= DN_LEVEL < expected_osc[index]
        for index in buy_indices
    )
    assert all(
        expected_osc[index - 1] >= UP_LEVEL > expected_osc[index]
        for index in sell_indices
    )


@pytest.mark.parametrize("runonce", (False, True))
@pytest.mark.parametrize(
    "highs, lows, expected_osc",
    (
        ((110.0, 112.0, 111.0, 112.0), (90.0, 91.0, 92.0, 93.0), 75.0),
        ((112.0, 111.0, 110.0, 109.0), (100.0, 98.0, 99.0, 98.0), -75.0),
    ),
)
def test_aroon_oscillator_ties_choose_nearest_bars_ago_extreme(
    runonce, highs, lows, expected_osc
):
    """Equal extremes select the nearest bar, with a valid first boundary value."""
    frame = _tie_frame(highs, lows)
    result = _run_cerebro(frame, runonce)

    assert result["minperiod"] == MINPERIOD
    assert len(frame) == MINPERIOD
    assert all(math.isnan(value) for value in result["osc"][:-1])
    assert result["osc"][-1] == pytest.approx(expected_osc)


@pytest.mark.parametrize("runonce", (False, True))
@pytest.mark.parametrize("length, has_value", ((MINPERIOD - 1, False), (MINPERIOD, True)))
def test_aroon_oscillator_first_value_obeys_minperiod_boundary(
    runonce, length, has_value
):
    """The Aroon line is empty just before and finite at its warmup boundary."""
    frame = _frame_from_closes(_FULL_CLOSES[:length])
    result = _run_cerebro(frame, runonce)

    assert result["minperiod"] == MINPERIOD
    assert len(result["osc"]) == length
    if has_value:
        assert all(math.isnan(value) for value in result["osc"][:-1])
        assert math.isfinite(result["osc"][-1])
    else:
        assert all(math.isnan(value) for value in result["osc"])
