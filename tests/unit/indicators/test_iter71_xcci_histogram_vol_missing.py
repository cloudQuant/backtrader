"""Regression coverage for missing inputs in XCCIHistogramVolIndicator."""

from __future__ import annotations

import math

import backtrader as bt
import pandas as pd
import pytest


class _XCCIStateProbe(bt.Strategy):
    """Capture the public color state and its consumer's transition guard."""

    def __init__(self):
        self.indicator = bt.indicators.XCCIHistogramVolIndicator(
            self.data,
            cci_period=2,
            high_level2=60,
            high_level1=50,
            low_level1=-50,
            low_level2=-60,
            ma_length=1,
        )
        self.rows = []

    def prenext(self):
        self._capture()

    def nextstart(self):
        self._capture()

    def next(self):
        self._capture()

    def _capture(self):
        previous = float(self.indicator.color_state[-1])
        current = float(self.indicator.color_state[0])
        signal = None
        if math.isfinite(previous) and math.isfinite(current):
            if previous == 1.0 and current > 1.0:
                signal = ("buy", "mm1")
            elif previous == 0.0 and current > 0.0:
                signal = ("buy", "mm2")
            elif previous == 3.0 and current < 3.0:
                signal = ("sell", "mm1")
            elif previous == 4.0 and current < 4.0:
                signal = ("sell", "mm2")
        self.rows.append(
            (
                len(self.data),
                float(self.indicator.value[0]),
                current,
                signal,
            )
        )


def _run_probe(*, runonce: bool, missing_field: str | None):
    closes = [100.0 + index for index in range(14)]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range("2020-01-01", periods=len(closes)),
    )
    if missing_field is not None:
        frame.loc[frame.index[8], missing_field] = math.nan

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(_XCCIStateProbe)
    strategy = cerebro.run(runonce=runonce)[0]
    return strategy.indicator._minperiod, strategy.rows


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("missing_field", ["high", "low", "close", "volume"])
def test_missing_inputs_do_not_publish_a_valid_neutral_color_or_signal(
    runonce: bool,
    missing_field: str,
) -> None:
    minperiod, rows = _run_probe(runonce=runonce, missing_field=missing_field)

    assert minperiod == 5
    baseline_rows = [row for row in rows if minperiod <= row[0] < 9]
    assert baseline_rows
    assert all(row[2] == 0.0 for row in baseline_rows)

    invalid_rows = [row for row in rows if not math.isfinite(row[1])]
    assert invalid_rows
    expected_invalid_lengths = {9} if missing_field == "volume" else {9, 10}
    assert {row[0] for row in invalid_rows if row[0] >= minperiod} == expected_invalid_lengths
    assert all(math.isnan(row[2]) for row in invalid_rows)
    assert all(row[3] is None for row in rows)
