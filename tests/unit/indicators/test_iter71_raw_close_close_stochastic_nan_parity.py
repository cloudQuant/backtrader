"""Raw close stochastic next/once use the same NaN window ordering."""

import datetime as dt
import math

import backtrader as bt
import pytest


class _CloseValues(bt.feed.DataBase):
    params = (("close_values", ()),)

    def __init__(self):
        super().__init__()
        self._index = 0

    def _load(self):
        if self._index >= len(self.p.close_values):
            return False

        value = float(self.p.close_values[self._index])
        moment = dt.datetime(2026, 1, 1) + dt.timedelta(days=self._index)
        self.lines.datetime[0] = bt.date2num(moment)
        self.lines.open[0] = value
        self.lines.high[0] = value
        self.lines.low[0] = value
        self.lines.close[0] = value
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        self._index += 1
        return True


def _prices(count):
    return [
        100.0 + i * 0.13 + (i * 7 % 13) * 0.47 + math.sin(i * 0.3) * 2.2
        for i in range(count)
    ]


def _run(runonce, values, *, period=5, slowing=3, dperiod=3):
    class Probe(bt.Strategy):
        def __init__(self):
            self.raw = bt.indicators.RawCloseCloseStochastic(
                self.data, period=period
            )
            self.highest = bt.indicators.Highest(self.data.close, period=period)
            self.lowest = bt.indicators.Lowest(self.data.close, period=period)
            self.smoothed = bt.indicators.CloseCloseEmaStochastic(
                self.data,
                period=period,
                slowing=slowing,
                dperiod=dperiod,
            )

        def stop(self):
            self.result = {
                "raw": list(self.raw.raw.array),
                "minperiod": self.raw._minperiod,
                "highest": list(self.highest.highest.array),
                "lowest": list(self.lowest.lowest.array),
                "k": list(self.smoothed.percK.array),
                "d": list(self.smoothed.percD.array),
            }

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(_CloseValues(close_values=values))
    cerebro.addstrategy(Probe)
    return cerebro.run(runonce=runonce, preload=True)[0].result


def _reference(values, period):
    result = [math.nan] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        highest = max(window)
        lowest = min(window)
        denominator = highest - lowest
        result[index] = (
            0.0
            if denominator == 0.0
            else 100.0 * (values[index] - lowest) / denominator
        )
    return result


def _extreme_reference(values, period, func):
    result = [math.nan] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        result[index] = func(window)
    return result


def _assert_same(actual, expected):
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), index
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), index


@pytest.mark.parametrize(
    "missing_indices",
    ((70,), (70, 71, 72)),
    ids=("single-gap", "three-bar-gap"),
)
def test_raw_and_smoothed_lines_match_reference_after_nan_window(missing_indices):
    values = _prices(110)
    for index in missing_indices:
        values[index] = math.nan

    runnext = _run(False, values)
    runonce = _run(True, values)
    expected_raw = _reference(values, 5)
    expected_high = _extreme_reference(values, 5, max)
    expected_low = _extreme_reference(values, 5, min)

    assert runnext["minperiod"] == runonce["minperiod"] == 5
    assert all(math.isnan(value) for value in runnext["raw"][:4])
    assert any(math.isfinite(value) for value in runnext["raw"][4:])
    _assert_same(runnext["raw"], expected_raw)
    _assert_same(runonce["raw"], expected_raw)
    _assert_same(runnext["highest"], expected_high)
    _assert_same(runonce["highest"], expected_high)
    _assert_same(runnext["lowest"], expected_low)
    _assert_same(runonce["lowest"], expected_low)
    _assert_same(runonce["k"], runnext["k"])
    _assert_same(runonce["d"], runnext["d"])

    if missing_indices == (70,):
        # The NaN is newest at 70, internal to the window at 71-73, oldest at
        # 74, and outside the window at 75. Preserve chronological max/min.
        assert math.isnan(expected_raw[70])
        assert math.isfinite(expected_raw[71])
        assert math.isfinite(expected_raw[72])
        assert math.isfinite(expected_raw[73])
        assert math.isnan(expected_raw[74])
        assert math.isfinite(expected_raw[75])
        assert all(math.isnan(value) for value in runnext["k"][70:])
        assert all(math.isnan(value) for value in runnext["d"][70:])
