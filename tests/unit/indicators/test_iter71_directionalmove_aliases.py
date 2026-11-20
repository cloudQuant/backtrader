"""Public aliases and execution-mode parity for directional indicators."""

import math

import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators as btind
from backtrader.indicators.directionalmove import (
    MinusDirectionalIndicator,
    PlusDirectionalIndicator,
)


def test_directional_indicator_public_aliases_preserve_class_identity():
    """Short and symbolic historical names resolve to the canonical classes."""
    from backtrader.indicators import MinusDI, PlusDI

    assert btind.PlusDirectionalIndicator is PlusDirectionalIndicator
    assert btind.MinusDirectionalIndicator is MinusDirectionalIndicator
    assert PlusDI is bt.indicators.PlusDI is PlusDirectionalIndicator
    assert MinusDI is bt.indicators.MinusDI is MinusDirectionalIndicator
    assert getattr(bt.indicators, "+DI") is PlusDirectionalIndicator
    assert getattr(bt.indicators, "-DI") is MinusDirectionalIndicator


def _run_directional_aliases(runonce):
    """Run both short aliases over a small series with known Wilder values."""
    highs = [10.0, 12.0, 13.0, 11.0, 10.0, 14.0]
    lows = [8.0, 9.0, 8.0, 6.0, 5.0, 8.0]
    closes = [9.0, 11.0, 9.0, 7.0, 6.0, 13.0]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D"),
    )
    values = {}

    class DirectionalProbeStrategy(bt.Strategy):
        def __init__(self):
            self.plus_di = bt.indicators.PlusDI(self.data, period=2)
            self.minus_di = bt.indicators.MinusDI(self.data, period=2)

        def stop(self):
            values["plus"] = list(self.plus_di.lines.plusDI.array)
            values["minus"] = list(self.minus_di.lines.minusDI.array)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(DirectionalProbeStrategy)
    cerebro.run()
    return values


@pytest.mark.parametrize("runonce", [False, True])
def test_short_directional_aliases_produce_expected_wilder_values(runonce):
    """The public aliases calculate the same concrete DI series in both modes."""
    values = _run_directional_aliases(runonce)

    expected = {
        "plus": [
            math.nan,
            math.nan,
            25.0,
            100.0 / 9.0,
            100.0 / 19.0,
            100.0 / 3.0,
        ],
        "minus": [
            math.nan,
            math.nan,
            0.0,
            200.0 / 9.0,
            400.0 / 19.0,
            100.0 / 12.75,
        ],
    }

    for name, expected_values in expected.items():
        actual_values = values[name]
        assert len(actual_values) == len(expected_values)
        assert math.isnan(actual_values[0])
        assert math.isnan(actual_values[1])
        assert actual_values[2:] == pytest.approx(expected_values[2:])
