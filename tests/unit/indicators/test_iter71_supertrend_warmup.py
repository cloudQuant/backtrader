"""Regression coverage for SuperTrend's ATR warmup state."""

import math

import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators as btind


def _run_supertrend(period, length, runonce, missing=None):
    """Run SuperTrend on synthetic history and return lines/callback facts."""
    close = [100.0] * length
    high = [value + 1.0 for value in close]
    low = [value - 1.0 for value in close]
    open_ = list(close)
    if missing is not None:
        missing_values = [missing] if isinstance(missing[0], str) else missing
        for field, index in missing_values:
            {"open": open_, "high": high, "low": low, "close": close}[
                field
            ][index] = float("nan")
    frame = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1.0] * length,
            "openinterest": [0.0] * length,
        },
        index=pd.date_range("2020-01-01", periods=length, freq="D"),
    )
    result = {}

    class SuperTrendProbe(bt.Strategy):
        def __init__(self):
            self.supertrend = btind.SuperTrendIndicator(
                self.data, period=period, multiplier=3.0
            )

        def prenext(self):
            result.setdefault("strategy_prenext", []).append(
                (
                    len(self),
                    float(self.supertrend.supertrend[0]),
                    float(self.supertrend.direction[0]),
                )
            )

        def stop(self):
            result["minperiod"] = self.supertrend._minperiod
            result["supertrend"] = [
                float(value) for value in self.supertrend.supertrend.array
            ]
            result["direction"] = [
                float(value) for value in self.supertrend.direction.array
            ]
            result["atr"] = [float(value) for value in self.supertrend.atr.atr.array]
            result["high"] = [float(value) for value in self.data.high.array]
            result["low"] = [float(value) for value in self.data.low.array]
            result["close"] = [float(value) for value in self.data.close.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(SuperTrendProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


@pytest.mark.parametrize("runonce", [True, False])
@pytest.mark.parametrize(
    ("period", "length"),
    [
        (1, 1),
        (1, 2),
        (3, 1),
        (3, 3),
        (3, 4),
        (3, 5),
    ],
)
def test_supertrend_warmup_stays_nan_and_ready_state_is_seeded(
    period, length, runonce
):
    """Warmup stays unpublished and the first ATR-ready state is bullish."""
    result = _run_supertrend(period, length, runonce)

    assert result["minperiod"] == period + 1
    assert len(result["supertrend"]) == length
    assert len(result["direction"]) == length
    warmup_length = min(period, length)
    assert all(math.isnan(value) for value in result["supertrend"][:warmup_length])
    assert all(math.isnan(value) for value in result["direction"][:warmup_length])
    if length > period:
        assert result["supertrend"][period:] == pytest.approx(
            [100.0] * (length - period)
        )
        assert result["direction"][period:] == pytest.approx(
            [1.0] * (length - period)
        )


@pytest.mark.parametrize("runonce", [True, False])
def test_strategy_prenext_cannot_observe_supertrend_warmup_state(runonce):
    """A real Strategy.prenext callback sees no pre-ATR public state."""
    result = _run_supertrend(period=3, length=3, runonce=runonce)

    assert [event[0] for event in result["strategy_prenext"]] == [1, 2, 3]
    assert all(
        math.isnan(supertrend) and math.isnan(direction)
        for _length, supertrend, direction in result["strategy_prenext"]
    )


@pytest.mark.parametrize("runonce", [True, False])
@pytest.mark.parametrize("field", ["high", "low", "close"])
def test_supertrend_missing_required_ohlc_does_not_publish_state(field, runonce):
    """A missing required OHLC value cannot produce a valid trend state."""
    period = 3
    missing_index = period + 1
    result = _run_supertrend(
        period=period,
        length=period + 2,
        runonce=runonce,
        missing=(field, missing_index),
    )

    assert math.isnan(result["supertrend"][missing_index])
    assert math.isnan(result["direction"][missing_index])


@pytest.mark.parametrize("runonce", [True, False])
def test_supertrend_does_not_publish_when_atr_is_nan_after_prior_missing_hlc(
    runonce,
):
    """Finite current HLC is insufficient when prior data left ATR nonfinite."""
    period = 3
    current_index = period
    result = _run_supertrend(
        period=period,
        length=period + 1,
        runonce=runonce,
        missing=("high", 1),
    )

    assert all(
        math.isfinite(result[field][current_index])
        for field in ("high", "low", "close")
    )
    assert math.isnan(result["atr"][current_index])
    assert math.isnan(result["supertrend"][current_index])
    assert math.isnan(result["direction"][current_index])
