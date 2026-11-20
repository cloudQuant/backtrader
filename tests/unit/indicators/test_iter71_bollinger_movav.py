"""Regression tests for BollingerBands' configurable middle-band average."""

import math

import backtrader as bt
import pandas as pd
import pytest


_CLOSES = [10.0, 12.0, 11.0, 14.0, 10.0, 16.0, 13.0, 18.0]
_PERIOD = 3
_DEVFACTOR = 1.5


def _run_bollinger(runonce, movav):
    frame = pd.DataFrame(
        {
            "open": _CLOSES,
            "high": [value + 1.0 for value in _CLOSES],
            "low": [value - 1.0 for value in _CLOSES],
            "close": _CLOSES,
            "volume": [1] * len(_CLOSES),
            "openinterest": [0] * len(_CLOSES),
        },
        index=pd.date_range("2024-01-01", periods=len(_CLOSES)),
    )
    configured_movav = movav or bt.ind.MovAv.Simple

    class CaptureStrategy(bt.Strategy):
        def __init__(self):
            kwargs = {} if movav is None else {"movav": movav}
            self.bbands = bt.ind.BollingerBands(
                self.data.close,
                period=_PERIOD,
                devfactor=_DEVFACTOR,
                **kwargs
            )
            self.reference = configured_movav(self.data.close, period=_PERIOD)
            self.next_bars = []

        def next(self):
            self.next_bars.append(len(self))

    cerebro = bt.Cerebro(runonce=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(CaptureStrategy)
    strategy = cerebro.run()[0]

    return {
        "minperiod": strategy.bbands._minperiod,
        "next_bars": strategy.next_bars,
        "mid": list(strategy.bbands.lines.mid.array),
        "top": list(strategy.bbands.lines.top.array),
        "bot": list(strategy.bbands.lines.bot.array),
        "reference": list(strategy.reference.lines[0].array),
    }


def _assert_same_series(left, right):
    assert len(left) == len(right)
    for actual, expected in zip(left, right):
        if math.isnan(actual):
            assert math.isnan(expected)
        else:
            assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


@pytest.mark.parametrize(
    "movav",
    [None, bt.ind.MovAv.Simple, bt.ind.MovAv.EMA, bt.ind.MovAv.WMA],
    ids=["default-simple", "explicit-simple", "ema", "wma"],
)
def test_bollinger_middle_band_uses_configured_movav_in_both_modes(movav):
    next_result = _run_bollinger(runonce=False, movav=movav)
    once_result = _run_bollinger(runonce=True, movav=movav)

    for result in (next_result, once_result):
        assert result["minperiod"] == _PERIOD
        assert result["next_bars"] == list(range(_PERIOD, len(_CLOSES) + 1))
        assert len(result["mid"]) == len(_CLOSES)

        _assert_same_series(result["mid"], result["reference"])

        for index in range(_PERIOD - 1):
            assert math.isnan(result["mid"][index])
            assert math.isnan(result["top"][index])
            assert math.isnan(result["bot"][index])

        for index in range(_PERIOD - 1, len(_CLOSES)):
            window = _CLOSES[index - _PERIOD + 1 : index + 1]
            mean = sum(window) / _PERIOD
            meansq = sum(value * value for value in window) / _PERIOD
            stddev = math.sqrt(max(0.0, meansq - mean * mean))
            mid = result["reference"][index]
            assert math.isclose(
                result["top"][index],
                mid + _DEVFACTOR * stddev,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            assert math.isclose(
                result["bot"][index],
                mid - _DEVFACTOR * stddev,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )

    for line in ("mid", "top", "bot"):
        _assert_same_series(next_result[line], once_result[line])

    if movav in (None, bt.ind.MovAv.Simple):
        for index in range(_PERIOD - 1, len(_CLOSES)):
            expected_simple = (
                sum(_CLOSES[index - _PERIOD + 1 : index + 1]) / _PERIOD
            )
            assert math.isclose(
                next_result["mid"][index],
                expected_simple,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
    else:
        simple_values = [
            sum(_CLOSES[index - _PERIOD + 1 : index + 1]) / _PERIOD
            for index in range(_PERIOD - 1, len(_CLOSES))
        ]
        selected_values = next_result["mid"][_PERIOD - 1 :]
        assert any(
            not math.isclose(selected, simple, rel_tol=1e-12, abs_tol=1e-12)
            for selected, simple in zip(selected_values, simple_values)
        )
