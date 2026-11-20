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

"""Test module for the Awesome Oscillator (AO) indicator.

This module contains test cases for the Backtrader Awesome Oscillator indicator,
which is a momentum indicator that measures the difference between a 34-period
and a 5-period simple moving average of the median price (high + low) / 2.

The test validates that the AO indicator produces expected values when applied
to historical price data, ensuring the implementation matches the reference
calculation.

Module Variables:
    chkdatas (int): Number of data feeds to load for testing (default: 1).
    chkvals (list): List of expected indicator values at specific bars for
        validation. Contains three string representations of float values:
        ["50.804206", "72.983735", "33.655941"].
    chkmin (int): Minimum period required before the indicator produces valid
        values (default: 34).
    chkind (type): The indicator class being tested (bt.ind.AO - Awesome
        Oscillator).
"""

import math

import backtrader as bt
import backtrader.indicators as btind
import pandas as pd
import pytest

import testcommon


chkdatas = 1
chkvals = [["50.804206", "72.983735", "33.655941"]]

chkmin = 34
chkind = bt.ind.AO


def test_run(main=False):
    """Execute the Awesome Oscillator indicator test.

    This function loads test data, runs the indicator through the standard
    test strategy, and validates that the calculated values match the expected
    results. The test can optionally plot the results for visual inspection
    when run directly as a script.

    Args:
        main (bool, optional): Whether the test is being run as the main
            script. When True, enables plotting of the results. Defaults to
            False.

    Returns:
        None: The function executes the test and raises assertions if
            validation fails, otherwise returns silently.

    Raises:
        AssertionError: If the calculated indicator values do not match the
            expected values in chkvals, or if the minimum period does not
            match chkmin.

    Example:
        >>> test_run(main=False)  # Run test without plotting
        >>> test_run(main=True)   # Run test with plotting (typically in __main__)
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkvals=chkvals,
    )


def _run_ao_sequence(runonce, fast, slow, movav):
    """Return AO and moving-average reference arrays for synthetic OHLC data."""
    count = 48
    close = [100.0 + i * 0.73 + ((i * 7) % 9) * 0.41 for i in range(count)]
    frame = pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 + i % 4 for i, value in enumerate(close)],
            "low": [value - 0.5 - i % 3 for i, value in enumerate(close)],
            "close": close,
            "volume": [1000.0] * count,
            "openinterest": [0.0] * count,
        },
        index=pd.date_range("2026-01-01", periods=count, freq="D"),
    )

    class AOProbeStrategy(bt.Strategy):
        def __init__(self):
            median = (self.data.high + self.data.low) / 2.0
            self.ao = btind.AwesomeOscillator(
                self.data, fast=fast, slow=slow, movav=movav
            )
            self.reference_fast = movav(median, period=fast)
            self.reference_slow = movav(median, period=slow)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(AOProbeStrategy)
    strategy = cerebro.run()[0]

    return (
        strategy.ao._minperiod,
        list(strategy.ao.lines.ao.array[:count]),
        list(strategy.reference_fast.lines[0].array),
        list(strategy.reference_slow.lines[0].array),
    )


def _assert_same_series(actual, expected):
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        if math.isnan(want):
            assert math.isnan(got)
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12)


@pytest.mark.parametrize(
    ("fast", "slow", "movav"),
    [
        (5, 34, btind.SMA),
        (3, 7, btind.EMA),
        (8, 3, btind.SMA),
    ],
    ids=("default-sma", "custom-ema", "fast-greater-than-slow"),
)
def test_awesome_oscillator_movav_minperiod_and_run_mode_parity(fast, slow, movav):
    """AO uses its configured MA and waits for both windows in either mode."""
    expected_minperiod = max(fast, slow)
    sequences = {
        runonce: _run_ao_sequence(runonce, fast, slow, movav)
        for runonce in (False, True)
    }

    for minperiod, actual, fast_ma, slow_ma in sequences.values():
        assert minperiod == expected_minperiod
        reference = [
            fast_value - slow_value
            for fast_value, slow_value in zip(fast_ma, slow_ma)
        ]
        _assert_same_series(actual, reference)

    _assert_same_series(sequences[False][1], sequences[True][1])


def _run_multitimeframe_ao(runonce):
    """Run AO on a weekly feed while the strategy clock advances daily."""
    count = 84
    dates = pd.date_range("2026-01-05", periods=count, freq="D")
    close = [100.0 + i * 0.53 + ((i * 5) % 11) * 0.37 for i in range(count)]
    daily = pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 + i % 4 for i, value in enumerate(close)],
            "low": [value - 0.5 - i % 3 for i, value in enumerate(close)],
            "close": close,
            "volume": [1000.0] * count,
            "openinterest": [0.0] * count,
        },
        index=dates,
    )
    week_ids = pd.Series(range(count), index=dates) // 7
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
    weekly["median"] = (weekly["high"] + weekly["low"]) / 2.0

    class WeeklyMedianData(bt.feeds.PandasData):
        lines = ("median",)
        params = (("median", -1),)

    class MultiTimeframeAOProbe(bt.Strategy):
        def __init__(self):
            # The explicit median field gives the reference MAs the same OHLC
            # midpoint without adding another LineOperation to the slow feed.
            self.reference_fast = btind.SMA(self.data1.median, period=2)
            self.reference_slow = btind.SMA(self.data1.median, period=3)
            self.ao = btind.AwesomeOscillator(self.data1, fast=2, slow=3)
            self.records = []

        def next(self):
            self.records.append(
                (
                    len(self.data0),
                    len(self.data1),
                    len(self.ao),
                    float(self.data0.datetime[0]),
                    float(self.data1.datetime[0]),
                    float(self.ao.data.datetime[0]),
                    float(self.ao[0]),
                    float(self.reference_fast[0] - self.reference_slow[0]),
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
        WeeklyMedianData(
            dataname=weekly,
            timeframe=bt.TimeFrame.Weeks,
            compression=1,
        ),
        name="weekly",
    )
    cerebro.addstrategy(MultiTimeframeAOProbe)
    strategy = cerebro.run()[0]
    return strategy.ao._minperiod, strategy.records


def test_awesome_oscillator_slow_data_multitimeframe_clock_and_parity():
    """AO follows the weekly feed clock and matches its reference on each call."""
    sequences = {
        runonce: _run_multitimeframe_ao(runonce)
        for runonce in (False, True)
    }
    assert sequences[False][0] == sequences[True][0] == 3

    next_records = sequences[False][1]
    once_records = sequences[True][1]
    assert len(next_records) == len(once_records) == 64

    for records in (next_records, once_records):
        assert records[0][:3] == (21, 3, 3)
        assert records[-1][:3] == (84, 12, 12)
        assert all(record[2] == record[1] for record in records)
        assert all(record[4] == record[5] for record in records)
        assert all(
            record[6] == pytest.approx(record[7], rel=1e-12, abs=1e-12)
            for record in records
        )
        assert all(left[3] < right[3] for left, right in zip(records, records[1:]))
        assert all(left[4] <= right[4] for left, right in zip(records, records[1:]))
        assert any(left[4] == right[4] for left, right in zip(records, records[1:]))

    for next_record, once_record in zip(next_records, once_records):
        assert next_record[:6] == once_record[:6]
        assert next_record[6:] == pytest.approx(
            once_record[6:], rel=1e-12, abs=1e-12
        )


if __name__ == "__main__":
    test_run(main=True)
