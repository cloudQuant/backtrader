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

"""Test module for data resampling functionality in backtrader.

This module tests the resampling of data from daily timeframe to weekly timeframe.
It validates that indicators (specifically SMA) produce correct values when applied
to resampled data.

The test loads daily price data, resamples it to weekly bars, and then verifies
that the SMA indicator calculates expected values at specific checkpoints.
"""

import datetime

import pandas as pd

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Module-level constants for test validation
chkdatas = 1  # Number of data feeds to use
chkvals = [["3836.453333", "3703.962333", "3741.802000"]]  # Expected SMA values

chkmin = 30  # Expected minimum period (will be in weeks)
chkind = [btind.SMA]  # Indicator class to test
chkargs = dict()  # Additional arguments for indicator creation


def test_run(main=False):
    """Run the data resampling test with multiple execution modes.

    This function tests data resampling from daily to weekly timeframe with
    both runonce=True and runonce=False modes to ensure compatibility
    across different execution strategies.

    Args:
        main (bool, optional): If True, enables plotting for visual inspection.
            Defaults to False (automated test mode).

    Returns:
        None: The function executes tests and validates results through
            the testcommon.runtest framework.

    Raises:
        AssertionError: If indicator values don't match expected results
            at checkpoints.
    """
    for runonce in [True, False]:
        data = testcommon.getdata(0)
        data.resample(timeframe=bt.TimeFrame.Weeks, compression=1)

        datas = [data]
        testcommon.runtest(
            datas,
            testcommon.TestStrategy,
            main=main,
            runonce=runonce,
            plot=main,
            chkind=chkind,
            chkmin=chkmin,
            chkvals=chkvals,
            chkargs=chkargs,
        )


class ResampleTailStrategy(bt.Strategy):
    def stop(self):
        self.daily_len = len(self.datas[1])
        self.daily_dt = None
        if self.daily_len:
            self.daily_dt = self.datas[1].num2date(self.datas[1].datetime[0])


def _run_intraday_to_daily_resample(last_timestamp):
    index = pd.to_datetime(["2024-01-02 09:00", last_timestamp])
    frame = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "close": [1.0, 2.0],
            "volume": [1.0, 1.0],
            "openinterest": [0.0, 0.0],
        },
        index=index,
    )

    cerebro = bt.Cerebro()
    data = bt.feeds.PandasData(
        dataname=frame,
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
        sessionend=datetime.time(9, 30),
    )
    cerebro.adddata(data, name="m15")
    cerebro.resampledata(
        data,
        timeframe=bt.TimeFrame.Days,
        compression=1,
        name="d1",
    )
    cerebro.addstrategy(ResampleTailStrategy)
    return cerebro.run()[0]


def test_intraday_to_daily_resample_does_not_flush_incomplete_final_day():
    strategy = _run_intraday_to_daily_resample("2024-01-02 09:15")

    assert strategy.daily_len == 0
    assert strategy.daily_dt is None


def test_intraday_to_daily_resample_keeps_completed_final_day():
    strategy = _run_intraday_to_daily_resample("2024-01-02 09:30")

    assert strategy.daily_len == 1
    assert strategy.daily_dt == datetime.datetime(2024, 1, 2, 9, 30)


if __name__ == "__main__":
    test_run(main=True)
