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

"""
Test module for the TimeReturn analyzer.

This module contains tests for the TimeReturn analyzer, which calculates
returns over specific time periods (e.g., yearly returns). The test
implements a simple moving average crossover strategy to generate trades
and verify that the analyzer correctly calculates time-based returns.

The test strategy:
- Uses a Simple Moving Average (SMA) crossover system
- Buys when price crosses above the SMA
- Sells/closes when price crosses below the SMA
- Tests both stock-like and futures-like commission structures

Example:
    Run the test with output::

        python test_analyzer-timereturn.py

    Run the test in test mode (no output)::

        pytest test_analyzer-timereturn.py
"""

import time

try:
    time_clock = time.process_time
except AttributeError:
    time_clock = time.clock

import testcommon
import backtrader as bt
import backtrader.indicators as btind
from backtrader.utils.py3 import PY2


class RunStrategy(bt.Strategy):
    """Simple Moving Average crossover strategy for testing TimeReturn analyzer.

    This strategy implements a basic trend-following system using SMA crossovers:
    - Enter long when price crosses above the SMA
    - Exit position when price crosses below the SMA

    The strategy tracks all order creation and execution for verification purposes.

    Attributes:
        orderid: The ID of the currently active order, or None if no order is active.
        sma: Simple Moving Average indicator.
        cross: CrossOver indicator detecting price/SMA crossovers.
        buycreate: List of buy order creation prices.
        sellcreate: List of sell order creation prices.
        buyexec: List of executed buy order prices.
        sellexec: List of executed sell order prices.
        tstart: Start time for performance measurement.

    Args:
        period: Period for the SMA calculation. Default is 15.
        printdata: Whether to print data bars. Default is True.
        printops: Whether to print order operations. Default is True.
        stocklike: If True, use stock-like commission; if False, use futures-like.
            Default is True.
    """

    params = (
        ("period", 15),
        ("printdata", True),
        ("printops", True),
        ("stocklike", True),
    )

    def log(self, txt, dt=None, nodate=False):
        """Log a message with optional timestamp.

        Args:
            txt: The message text to log.
            dt: Optional datetime for the log entry. If None, uses current bar.
            nodate: If True, print message without date prefix.
        """
        if not nodate:
            dt = dt or self.data.datetime[0]
            dt = bt.num2date(dt)
            print("{}, {}".format(dt.isoformat(), txt))
        else:
            print("---------- %s" % (txt))

    def notify_order(self, order):
        """Handle order status notifications.

        Processes order execution and other status changes, logging them
        if printops is enabled. Tracks executed prices for verification.

        Args:
            order: The order object with updated status.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return  # Await further notifications

        if order.status == order.Completed:
            if isinstance(order, bt.BuyOrder):
                if self.p.printops:
                    txt = "BUY, %.2f" % order.executed.price
                    self.log(txt, order.executed.dt)
                chkprice = "%.2f" % order.executed.price
                self.buyexec.append(chkprice)
            else:  # elif isinstance(order, SellOrder):
                if self.p.printops:
                    txt = "SELL, %.2f" % order.executed.price
                    self.log(txt, order.executed.dt)

                chkprice = "%.2f" % order.executed.price
                self.sellexec.append(chkprice)

        elif order.status in [order.Expired, order.Canceled, order.Margin]:
            if self.p.printops:
                self.log("%s ," % order.Status[order.status])

        # Allow new orders
        self.orderid = None

    def __init__(self):
        """Initialize the strategy.

        Sets up indicators and tracking lists.
        """
        # Flag to allow new orders in the system or not
        self.orderid = None

        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma, plot=True)

    def start(self):
        """Called once before the strategy starts running.

        Sets up commission structure, logs initial portfolio value,
        and initializes tracking lists.
        """
        if not self.p.stocklike:
            self.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)

        if self.p.printdata:
            self.log("-------------------------", nodate=True)
            self.log("Starting portfolio value: %.2f" % self.broker.getvalue(), nodate=True)

        self.tstart = time_clock()

        self.buycreate = list()
        self.sellcreate = list()
        self.buyexec = list()
        self.sellexec = list()

    def stop(self):
        """Called once after the strategy stops running.

        Logs final portfolio values and execution time.
        """
        tused = time_clock() - self.tstart
        if self.p.printdata:
            self.log("Time used: %s" % str(tused))
            self.log("Final portfolio value: %.2f" % self.broker.getvalue())
            self.log("Final cash value: %.2f" % self.broker.getcash())
            self.log("-------------------------")
        else:
            pass

    def next(self):
        """Called on each bar to implement trading logic.

        Implements the SMA crossover strategy:
        - If no position: Buy when price crosses above SMA
        - If in position: Close when price crosses below SMA
        """
        if self.p.printdata:
            self.log(
                "Open, High, Low, Close, %.2f, %.2f, %.2f, %.2f, Sma, %f"
                % (
                    self.data.open[0],
                    self.data.high[0],
                    self.data.low[0],
                    self.data.close[0],
                    self.sma[0],
                )
            )
            self.log("Close {:.2f} - Sma {:.2f}".format(self.data.close[0], self.sma[0]))

        if self.orderid:
            # if an order is active, no new orders are allowed
            return

        if not self.position.size:
            if self.cross > 0.0:
                if self.p.printops:
                    self.log("BUY CREATE , %.2f" % self.data.close[0])

                self.orderid = self.buy()
                chkprice = "%.2f" % self.data.close[0]
                self.buycreate.append(chkprice)

        elif self.cross < 0.0:
            if self.p.printops:
                self.log("SELL CREATE , %.2f" % self.data.close[0])

            self.orderid = self.close()
            chkprice = "%.2f" % self.data.close[0]
            self.sellcreate.append(chkprice)


chkdatas = 1
"""Number of data feeds to use in the test."""


def test_run(main=False):
    """Run the TimeReturn analyzer test.

    This test function:
    1. Loads test data feeds
    2. Runs the SMA crossover strategy with TimeReturn analyzer
    3. Verifies the analyzer output matches expected values

    The TimeReturn analyzer calculates returns on a yearly timeframe,
    and the test verifies that the calculated return for the first year
    matches the expected value (handling Python 2/3 precision differences).

    Args:
        main: If True, runs in verbose mode with output. If False, runs
            in test mode with assertions. Default is False.

    Raises:
        AssertionError: If the analyzer output doesn't match expected value.
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    cerebros = testcommon.runtest(
        datas,
        RunStrategy,
        printdata=main,
        stocklike=False,
        printops=main,
        plot=main,
        analyzer=(bt.analyzers.TimeReturn, dict(timeframe=bt.TimeFrame.Years)),
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]  # no optimization, only 1
        analyzer = strat.analyzers[0]  # only 1
        analysis = analyzer.get_analysis()
        if main:
            # print(analysis)  # Removed for performance
            pass
            print(str(analysis[next(iter(analysis.keys()))]))
        else:
            # Handle different precision
            if PY2:
                sval = "0.2795"
            else:
                sval = "0.2794999999999983"

            assert str(analysis[next(iter(analysis.keys()))]) == sval


if __name__ == "__main__":
    test_run(main=True)
