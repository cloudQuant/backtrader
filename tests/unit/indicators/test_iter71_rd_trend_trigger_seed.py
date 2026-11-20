"""R71-033 regression coverage for the RD trend-trigger EMA seed."""

import math
from pathlib import Path

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.rd_trend_trigger_indicator import (
    RDTrendTriggerIndicator,
)
from backtrader.utils.load_data import load_mt5_csv


REGRESS = 15
T3_LENGTH = 5
BAR_COUNT = 171
MINPERIOD = REGRESS * 2 + T3_LENGTH + 3
FROMDATE = pd.Timestamp("2025-12-03 01:15:00")
TODATE = pd.Timestamp("2026-03-10 09:00:00")


def _load_real_bars(length=BAR_COUNT):
    """Load the same XAUUSD M15 source window used by the functional case."""
    repo = Path(__file__).resolve().parents[3]
    source = repo / "tests" / "datas" / "XAUUSD_M15.csv"
    assert source.is_file(), "required XAUUSD M15 input is missing"

    frame = load_mt5_csv(
        source,
        fromdate=FROMDATE,
        todate=TODATE,
        bar_shift_minutes=15,
    )
    assert len(frame) >= length, (
        f"required {length} XAUUSD M15 bars, received {len(frame)}"
    )
    frame = frame.iloc[:length].copy()
    for name in ("open", "high", "low", "close"):
        assert all(math.isfinite(float(value)) for value in frame[name]), (
            f"required finite source values in {name}"
        )
    return frame


def _reference_values(highs, lows):
    """Calculate the trigger sequence, seeding its EMA from the first TTF."""
    values = [float("nan")] * len(highs)
    first_index = MINPERIOD - 1
    if first_index >= len(highs):
        return values

    alpha = 2.0 / (T3_LENGTH + 1.0)
    previous = None
    for index in range(first_index, len(highs)):
        recent_start = index - REGRESS + 1
        older_start = index - REGRESS * 2 + 1
        highest_high_recent = max(highs[recent_start : index + 1])
        highest_high_older = max(highs[older_start:recent_start])
        lowest_low_recent = min(lows[recent_start : index + 1])
        lowest_low_older = min(lows[older_start:recent_start])
        buy_power = highest_high_recent - lowest_low_older
        sell_power = highest_high_older - lowest_low_recent
        denominator = buy_power + sell_power
        ttf = (
            (buy_power - sell_power) / (0.5 * denominator) * 100.0
            if denominator
            else 0.0
        )
        value = (
            ttf
            if previous is None
            else alpha * ttf + (1.0 - alpha) * previous
        )
        values[index] = value
        previous = value

    return values


def _run_cerebro(frame, runonce):
    """Run the actual contributed indicator in a Backtrader Cerebro engine."""
    result = {}

    class RDTrendTriggerProbe(bt.Strategy):
        def __init__(self):
            self.indicator = RDTrendTriggerIndicator(
                self.data, regress=REGRESS, t3_length=T3_LENGTH
            )

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            result["values"] = [
                float(value) for value in self.indicator.lines.value.array
            ]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(
        bt.feeds.PandasData(
            dataname=frame,
            timeframe=bt.TimeFrame.Minutes,
            compression=15,
        )
    )
    cerebro.addstrategy(RDTrendTriggerProbe)
    cerebro.run(runonce=runonce, preload=True)
    return result


@pytest.mark.parametrize("runonce", (False, True))
def test_rd_trend_trigger_seeds_from_first_valid_ttf_for_171_real_bars(runonce):
    """The first valid TTF seeds the EMA and subsequent bars stay finite."""
    frame = _load_real_bars()
    result = _run_cerebro(frame, runonce)
    expected = _reference_values(
        [float(value) for value in frame["high"]],
        [float(value) for value in frame["low"]],
    )

    assert result["minperiod"] == MINPERIOD
    assert len(result["values"]) == BAR_COUNT
    assert all(math.isnan(value) for value in result["values"][: MINPERIOD - 1])
    assert result["values"][MINPERIOD - 1 :] == pytest.approx(
        expected[MINPERIOD - 1 :]
    )
    assert all(math.isfinite(value) for value in result["values"][MINPERIOD - 1 :])


@pytest.mark.parametrize("runonce", (False, True))
@pytest.mark.parametrize(
    "length, has_seed",
    ((MINPERIOD - 1, False), (MINPERIOD, True)),
)
def test_rd_trend_trigger_first_value_respects_minperiod_boundary(
    runonce, length, has_seed
):
    """The first finite output appears only when the warmup bar is present."""
    frame = _load_real_bars(length)
    result = _run_cerebro(frame, runonce)

    assert result["minperiod"] == MINPERIOD
    assert len(result["values"]) == length
    if has_seed:
        expected = _reference_values(
            [float(value) for value in frame["high"]],
            [float(value) for value in frame["low"]],
        )
        assert all(math.isnan(value) for value in result["values"][:-1])
        assert result["values"][-1] == pytest.approx(expected[-1])
        assert math.isfinite(result["values"][-1])
    else:
        assert all(math.isnan(value) for value in result["values"])


@pytest.mark.parametrize("runonce", (False, True))
def test_rd_trend_trigger_does_not_reseed_after_real_input_nan_gap(runonce):
    """A missing source bar cannot be hidden by reseeding the recursive EMA."""
    frame = _load_real_bars()
    gap_index = MINPERIOD + 20
    frame.iloc[gap_index, frame.columns.get_loc("high")] = float("nan")

    result = _run_cerebro(frame, runonce)

    assert math.isnan(result["values"][gap_index])
    assert all(math.isnan(value) for value in result["values"][gap_index:])
