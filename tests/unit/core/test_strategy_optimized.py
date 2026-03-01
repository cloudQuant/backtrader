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

"""Test suite for optimized strategy execution with parameter sweeping.

This module tests the backtrader framework's ability to run optimized strategy
executions across multiple parameter combinations. It validates that the
execution results remain consistent across different execution modes including:

* Preload settings (True/False)
* runonce modes (True/False) for optimized batch processing
* Exact bar loading (True, False, -1, -2) for different data loading scenarios

The test uses a simple Simple Moving Average (SMA) crossover strategy with
varying periods (5-44) and verifies that portfolio values and cash balances
match expected results across all configuration combinations.
"""

import backtrader as bt

import itertools
import time

try:
    time_clock = time.process_time
except:
    time_clock = time.clock

import testcommon

import backtrader.indicators as btind
from backtrader.utils.py3 import range

CHKVALUES = [
    "14525.80",
    "14525.80",
    "15408.20",
    "15408.20",
    "14763.90",
    "14763.90",
    "14763.90",
    "14763.90",
    "14763.90",
    "14763.90",
    "14763.90",
    "14763.90",
    "14763.90",
    "14763.90",
    "13187.10",
    "13187.10",
    "13187.10",
    "13684.40",
    "13684.40",
    "13684.40",
    "13684.40",
    "13684.40",
    "13684.40",
    "13656.10",
    "13656.10",
    "13656.10",
    "13656.10",
    "12988.10",
    "12988.10",
    "12988.10",
    "12988.10",
    "12988.10",
    "12988.10",
    "12988.10",
    "12988.10",
    "12988.10",
    "12988.10",
    "12988.10",
    "12988.10",
    "12988.10",
]

CHKCASH = [
    "13525.80",
    "13525.80",
    "14408.20",
    "14408.20",
    "13763.90",
    "13763.90",
    "13763.90",
    "13763.90",
    "13763.90",
    "13763.90",
    "13763.90",
    "13763.90",
    "13763.90",
    "13763.90",
    "12187.10",
    "12187.10",
    "12187.10",
    "12684.40",
    "12684.40",
    "12684.40",
    "12684.40",
    "12684.40",
    "12684.40",
    "12656.10",
    "12656.10",
    "12656.10",
    "12656.10",
    "11988.10",
    "11988.10",
    "11988.10",
    "11988.10",
    "11988.10",
    "11988.10",
    "11988.10",
    "11988.10",
    "11988.10",
    "11988.10",
    "11988.10",
    "11988.10",
    "11988.10",
]

_chkvalues = []
_chkcash = []


class RunStrategy(bt.Strategy):
    """Simple Moving Average (SMA) crossover trading strategy.

    This strategy implements a basic trend-following approach using SMA crossovers.
    It generates buy signals when price crosses above the SMA and close signals
    when price crosses below the SMA. The strategy is designed to test
    optimized execution across multiple parameter combinations.

    Attributes:
        orderid: Tracks the current active order ID to prevent multiple
            simultaneous orders.
        sma: Simple Moving Average indicator with configurable period.
        cross: Crossover indicator detecting when price crosses the SMA.
        tstart: Timestamp recording when the strategy starts execution.
        buy_create_idx: Counter for tracking buy order creation sequence.

    Args:
        period: The period for the SMA calculation. Default is 15.
        printdata: Whether to print data logs. Default is True.
        printops: Whether to print operational logs. Default is True.
    """

    params = (
        ("period", 15),
        ("printdata", True),
        ("printops", True),
    )

    def log(self, txt, dt=None):
        """Log a message with timestamp.

        Args:
            txt: The message text to log.
            dt: Optional datetime for the log entry. If None, uses current bar.
        """
        dt = dt or self.data.datetime[0]
        dt = bt.num2date(dt)
        print("{}, {}".format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables."""
        self.orderid = None

        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma, plot=True)

    def start(self):
        """Set up broker commission and start timing.

        Called once before the backtest starts. Configures commission structure
        and records the start time for performance measurement.
        """
        self.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)
        self.tstart = time_clock()
        self.buy_create_idx = itertools.count()

    def stop(self):
        """Record final results and performance metrics.

        Called once after the backtest completes. Logs execution time,
        final portfolio value, and cash balance to global verification lists.
        """
        global _chkvalues
        global _chkcash

        tused = time_clock() - self.tstart
        if self.p.printdata:
            self.log(
                ("Time used: %s  - Period % d - " "Start value: %.2f - End value: %.2f")
                % (str(tused), self.p.period, self.broker.startingcash, self.broker.getvalue())
            )

        value = "%.2f" % self.broker.getvalue()
        _chkvalues.append(value)

        cash = "%.2f" % self.broker.getcash()
        _chkcash.append(cash)

    def next(self):
        """Execute trading logic for each bar.

        Implements the crossover strategy:
        * If no position and crossover is positive (price above SMA): Buy
        * If position exists and crossover is negative (price below SMA): Close

        Only allows one active order at a time to prevent order stacking.
        """
        if self.orderid:
            return

        if not self.position.size:
            if self.cross > 0.0:
                self.orderid = self.buy()

        elif self.cross < 0.0:
            self.orderid = self.close()


chkdatas = 1


def test_run(main=False):
    """Run comprehensive tests for optimized strategy execution.

    Tests the strategy execution across all combinations of:
    * runonce: True (batch processing) and False (bar-by-bar)
    * preload: True (load all data upfront) and False (lazy loading)
    * exbar: True, False, -1, -2 (exact bar loading modes)

    The strategy is optimized across periods 5-44 (40 combinations).
    Results are validated against expected portfolio values and cash balances.

    Args:
        main: If True, runs in verbose mode and prints results without
            asserting. If False, runs in test mode and validates results.
            Default is False.

    Raises:
        AssertionError: If portfolio values or cash balances don't match
            expected values when main=False.
    """
    global _chkvalues
    global _chkcash

    for runonce in [True, False]:
        for preload in [True, False]:
            for exbar in [True, False, -1, -2]:
                _chkvalues = list()
                _chkcash = list()

                datas = [testcommon.getdata(i) for i in range(chkdatas)]
                testcommon.runtest(
                    datas,
                    RunStrategy,
                    runonce=runonce,
                    preload=preload,
                    exbar=exbar,
                    optimize=True,
                    period=range(5, 45),
                    printdata=main,
                    printops=main,
                    plot=False,
                )

                if not main:
                    assert CHKVALUES == _chkvalues
                    assert CHKCASH == _chkcash

                else:
                    print("*" * 50)
                    print(CHKVALUES == _chkvalues)
                    print("-" * 50)
                    print(CHKVALUES)
                    print("-" * 50)
                    print(_chkvalues)
                    print("*" * 50)
                    print(CHKCASH == _chkcash)
                    print("-" * 50)
                    print(CHKCASH)
                    print("-" * 50)
                    print(_chkcash)


if __name__ == "__main__":
    test_run(main=True)
