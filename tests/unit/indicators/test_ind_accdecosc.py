#!/usr/bin/env python
###############################################################################
#
# Copyright (C) 2015-2023 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

"""Test module for AccelerationDecelerationOscillator indicator.

This module tests the AccelerationDecelerationOscillator (AC) indicator implementation
in backtrader. The AC indicator is a momentum oscillator developed by Bill Williams
that measures the acceleration and deceleration of the driving force in the market.

The test validates:
1. Indicator calculation accuracy against expected values
2. Minimum period requirements
3. Multiple execution modes (runonce, preload, exactbars combinations)

Example:
    To run the test directly:
        python test_ind_accdecosc.py

    To run as part of pytest:
        pytest tests/original_tests/test_ind_accdecosc.py
"""

import math

import backtrader as bt
import backtrader.indicators as btind
import pandas as pd
import pytest

import testcommon


# Number of data feeds to use for testing
chkdatas = 1

# Expected indicator values at specific checkpoints
# These values are validated against the computed AC indicator values
chkvals = [["-2.097441", "14.156647", "30.408335"]]

# Minimum period required for the indicator to produce valid values
chkmin = 38

# The indicator class being tested
chkind = bt.ind.AccelerationDecelerationOscillator


def test_run(main=False):
    """Run the AccelerationDecelerationOscillator indicator test.

    This function executes the test by loading test data, running the test strategy
    with the indicator, and validating the results against expected values.

    Args:
        main (bool, optional): If True, enables plot output for manual inspection.
            Defaults to False.

    Returns:
        None. The function runs the test and raises exceptions if validation fails.

    Raises:
        AssertionError: If computed indicator values do not match expected values.
        Exception: For any other errors during test execution.

    Example:
        Run test with plotting for manual inspection:
            test_run(main=True)

        Run test in automated mode:
            test_run(main=False)
    """
    # Load test data feeds
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with multiple configuration combinations
    # Tests various combinations of runonce, preload, and exactbars settings
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkvals=chkvals,
    )


def _simple_average(values, period):
    result = [float("nan")] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        if not any(math.isnan(value) for value in window):
            result[index] = math.fsum(window) / period
    return result


def _reference_ao(high, low):
    median = [(high_value + low_value) / 2.0 for high_value, low_value in zip(high, low)]
    fast = _simple_average(median, 5)
    slow = _simple_average(median, 34)
    return [
        fast_value - slow_value
        if not math.isnan(fast_value) and not math.isnan(slow_value)
        else float("nan")
        for fast_value, slow_value in zip(fast, slow)
    ]


def _reference_movav(values, period, movav):
    if movav in (None, btind.SMA):
        return _simple_average(values, period)

    result = [float("nan")] * len(values)
    first_valid = next(
        (index for index, value in enumerate(values) if not math.isnan(value)),
        None,
    )
    if first_valid is None:
        return result

    if movav is btind.EMA:
        seed = first_valid + period - 1
        if seed >= len(values):
            return result
        window = values[first_valid : seed + 1]
        if any(math.isnan(value) for value in window):
            return result

        previous = math.fsum(window) / period
        result[seed] = previous
        alpha = 2.0 / (period + 1.0)
        for index in range(seed + 1, len(values)):
            value = values[index]
            if math.isnan(value):
                previous = float("nan")
            else:
                previous = previous * (1.0 - alpha) + value * alpha
            result[index] = previous
        return result

    if movav is btind.WMA:
        weights = tuple(range(1, period + 1))
        coefficient = 2.0 / (period * (period + 1.0))
        for index in range(first_valid + period - 1, len(values)):
            window = values[index - period + 1 : index + 1]
            if not any(math.isnan(value) for value in window):
                result[index] = coefficient * math.fsum(
                    weight * value for weight, value in zip(weights, window)
                )
        return result

    raise AssertionError("Add an independent reference for this moving average")


def _run_accde_sequence(runonce, period, movav):
    count = 48
    close = [100.0 + i * 0.73 + ((i * 7) % 9) * 0.41 for i in range(count)]
    high = [value + 1.0 + i % 4 for i, value in enumerate(close)]
    low = [value - 0.5 - i % 3 for i, value in enumerate(close)]
    frame = pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000.0] * count,
            "openinterest": [0.0] * count,
        },
        index=pd.date_range("2026-01-01", periods=count, freq="D"),
    )

    class AccDeProbeStrategy(bt.Strategy):
        def __init__(self):
            kwargs = {} if movav is None else {"movav": movav}
            self.accde = btind.AccelerationDecelerationOscillator(
                self.data, period=period, **kwargs
            )
            self.next_bars = []

        def next(self):
            self.next_bars.append(len(self))

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(AccDeProbeStrategy)
    strategy = cerebro.run()[0]

    return {
        "minperiod": strategy.accde._minperiod,
        "ao_minperiod": strategy.accde.ao._minperiod,
        "values": list(strategy.accde.lines.accde.array[:count]),
        "next_bars": strategy.next_bars,
        "high": high,
        "low": low,
    }


def _assert_same_series(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        if math.isnan(want):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize(
    ("period", "movav"),
    [
        (5, None),
        (1, btind.SMA),
        (4, btind.EMA),
        (6, btind.WMA),
    ],
    ids=("default-sma", "period-one-sma", "ema", "wma"),
)
def test_accde_movav_minperiod_and_run_mode_parity(period, movav):
    """AC waits for AO plus its smoothing window and honors the selected MA."""
    runnext = _run_accde_sequence(runonce=False, period=period, movav=movav)
    runonce = _run_accde_sequence(runonce=True, period=period, movav=movav)

    expected_minperiod = 34 + period - 1
    expected_ao = _reference_ao(runnext["high"], runnext["low"])
    average = _reference_movav(expected_ao, period, movav)
    expected = [
        ao_value - average_value
        if not math.isnan(ao_value) and not math.isnan(average_value)
        else float("nan")
        for ao_value, average_value in zip(expected_ao, average)
    ]

    for result in (runnext, runonce):
        assert result["ao_minperiod"] == 34
        assert result["minperiod"] == expected_minperiod
        assert result["next_bars"] == list(
            range(expected_minperiod, len(result["values"]) + 1)
        )
        _assert_same_series(result["values"], expected)

    _assert_same_series(runnext["values"], runonce["values"])


def _run_multitimeframe_accde(runonce, period, movav):
    """Run AC on weekly bars while the strategy clock advances daily."""
    daily_count = 42 * 7
    dates = pd.date_range("2026-01-05", periods=daily_count, freq="D")
    close = [100.0 + i * 0.53 + ((i * 5) % 11) * 0.37 for i in range(daily_count)]
    daily = pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 + i % 4 for i, value in enumerate(close)],
            "low": [value - 0.5 - i % 3 for i, value in enumerate(close)],
            "close": close,
            "volume": [1000.0] * daily_count,
            "openinterest": [0.0] * daily_count,
        },
        index=dates,
    )
    week_ids = pd.Series(range(daily_count), index=dates) // 7
    weekly = daily.groupby(week_ids).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "openinterest": "last",
        }
    )
    weekly.index = dates[6::7]

    class MultiTimeframeAccDeProbe(bt.Strategy):
        def __init__(self):
            self.accde = btind.AccelerationDecelerationOscillator(
                self.data1, period=period, movav=movav
            )
            self.records = []

        def next(self):
            self.records.append(
                (
                    len(self.data0),
                    len(self.data1),
                    len(self.accde),
                    float(self.data0.datetime[0]),
                    float(self.data1.datetime[0]),
                    float(self.accde.data.datetime[0]),
                    float(self.accde[0]),
                )
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(
        bt.feeds.PandasData(
            dataname=daily,
            timeframe=bt.TimeFrame.Days,
            compression=1,
        ),
        name="daily",
    )
    cerebro.adddata(
        bt.feeds.PandasData(
            dataname=weekly,
            timeframe=bt.TimeFrame.Weeks,
            compression=1,
        ),
        name="weekly",
    )
    cerebro.addstrategy(MultiTimeframeAccDeProbe)
    strategy = cerebro.run()[0]

    return {
        "minperiod": strategy.accde._minperiod,
        "ao_minperiod": strategy.accde.ao._minperiod,
        "values": list(strategy.accde.lines.accde.array[: len(weekly)]),
        "records": strategy.records,
        "weekly_high": list(weekly["high"]),
        "weekly_low": list(weekly["low"]),
        "daily_count": daily_count,
    }


def test_accde_slow_secondary_data_multitimeframe_clock_and_full_sequence_parity():
    """AC follows its slow feed clock and matches the independent full sequence."""
    period = 4
    movav = btind.EMA
    sequences = {
        runonce: _run_multitimeframe_accde(runonce, period, movav)
        for runonce in (False, True)
    }
    expected_minperiod = 34 + period - 1
    next_result = sequences[False]
    expected_ao = _reference_ao(
        next_result["weekly_high"], next_result["weekly_low"]
    )
    average = _reference_movav(expected_ao, period, movav)
    expected = [
        ao_value - average_value
        if not math.isnan(ao_value) and not math.isnan(average_value)
        else float("nan")
        for ao_value, average_value in zip(expected_ao, average)
    ]

    for result in sequences.values():
        assert result["ao_minperiod"] == 34
        assert result["minperiod"] == expected_minperiod
        assert len(result["values"]) == 42
        _assert_same_series(result["values"], expected)

        records = result["records"]
        first_daily_bar = expected_minperiod * 7
        assert len(records) == result["daily_count"] - first_daily_bar + 1
        assert records[0][:3] == (first_daily_bar, expected_minperiod, expected_minperiod)
        assert records[-1][:3] == (result["daily_count"], 42, 42)
        assert all(record[2] == record[1] for record in records)
        assert all(record[4] == record[5] for record in records)
        assert all(
            record[6] == pytest.approx(
                expected[record[1] - 1], rel=1e-12, abs=1e-12
            )
            for record in records
        )
        assert all(left[3] < right[3] for left, right in zip(records, records[1:]))
        assert all(left[4] <= right[4] for left, right in zip(records, records[1:]))
        assert any(left[4] == right[4] for left, right in zip(records, records[1:]))

    next_records = sequences[False]["records"]
    once_records = sequences[True]["records"]
    assert len(next_records) == len(once_records)
    for next_record, once_record in zip(next_records, once_records):
        assert next_record[:6] == once_record[:6]
        assert next_record[6:] == pytest.approx(
            once_record[6:], rel=1e-12, abs=1e-12
        )
    _assert_same_series(sequences[False]["values"], sequences[True]["values"])


if __name__ == "__main__":
    test_run(main=True)
