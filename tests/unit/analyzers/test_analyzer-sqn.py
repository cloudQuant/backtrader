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

"""Test module for the System Quality Number (SQN) analyzer.

This module contains test cases for the backtrader SQN analyzer, which
calculates the System Quality Number metric for trading strategies. The SQN
is a performance metric developed by Van Tharp that measures the quality of
a trading system by relating the mean reward to the standard deviation of
rewards.

The test strategy uses a Simple Moving Average (SMA) crossover system:
- Buy when price crosses above the SMA
- Sell/Close when price crosses below the SMA

Example:
    To run the tests with verbose output::
        python test_analyzer-sqn.py

    To run the tests programmatically::
        test_run(main=False)
"""

import time

try:
    time_clock = time.process_time
except:
    time_clock = time.clock

import testcommon

import backtrader as bt
import backtrader.indicators as btind


class RunStrategy(bt.Strategy):
    """A simple moving average crossover trading strategy for testing SQN analyzer.

    This strategy implements a basic trend-following system that:
    1. Buys when price crosses above the SMA (bullish signal)
    2. Closes position when price crosses below the SMA (bearish signal)

    The strategy is designed to generate multiple trades to test the SQN
    analyzer's ability to calculate the System Quality Number metric across
    different numbers of trades.

    Attributes:
        orderid: The ID of the currently active order, or None if no order is active.
        sma: Simple Moving Average indicator instance.
        cross: CrossOver indicator tracking price vs SMA crossovers.
        tstart: Timestamp when the strategy starts running.
        buycreate: List of buy order creation prices.
        sellcreate: List of sell/close order creation prices.
        buyexec: List of executed buy order prices.
        sellexec: List of executed sell order prices.
        tradecount: Counter for the number of completed trades.

    Args:
        period: The period for the SMA calculation. Defaults to 15.
        maxtrades: Maximum number of trades to execute. None for unlimited. Defaults to None.
        printdata: Whether to print data bars during execution. Defaults to True.
        printops: Whether to print order operations. Defaults to True.
        stocklike: Whether to use stock-like commission structure. Defaults to True.
    """

    params = (
        ("period", 15),
        ("maxtrades", None),
        ("printdata", True),
        ("printops", True),
        ("stocklike", True),
    )

    def log(self, txt, dt=None, nodate=False):
        """Log a message with optional timestamp.

        Args:
            txt (str): The message text to log.
            dt: Optional datetime object for the timestamp. If None, uses current bar.
            nodate (bool): If True, print message without date prefix. Defaults to False.
        """
        if not nodate:
            dt = dt or self.data.datetime[0]
            dt = bt.num2date(dt)
            print("{}, {}".format(dt.isoformat(), txt))
        else:
            print("---------- %s" % (txt))

    def notify_trade(self, trade):
        """Called when a trade is completed or updated.

        Args:
            trade: The Trade object that was notified.
        """
        if trade.isclosed:
            self.tradecount += 1

    def notify_order(self, order):
        """Called when an order status changes.

        Handles order execution, logging, and tracks executed prices for
        verification purposes.

        Args:
            order: The Order object that was notified.
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
        """Initialize the strategy with indicators and state variables.

        Sets up the SMA indicator, crossover tracker, and initializes
        lists for tracking order execution and trade counts.
        """
        # Flag to allow new orders in the system or not
        self.orderid = None

        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma, plot=True)

    def start(self):
        """Called once before the backtesting starts.

        Initializes commission structure, logs starting portfolio value,
        and sets up timing and tracking lists.
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
        self.tradecount = 0

    def stop(self):
        """Called once after the backtesting ends.

        Logs execution time and final portfolio/cash values.
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
        """Called for each bar of data.

        Implements the trading logic:
        1. Logs current bar data (OHLC and SMA)
        2. Checks if an order is already active
        3. If no position, buys on bullish crossover
        4. If in position, closes on bearish crossover
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
            if self.p.maxtrades is None or self.tradecount < self.p.maxtrades:
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


def test_run(main=False):
    """Run the SQN analyzer test with various trade count scenarios.

    This function tests the SQN (System Quality Number) analyzer with
    different maximum trade limits:
    - Unlimited trades (None): Should produce a positive SQN value
    - 0 trades: Should produce SQN of 0
    - 1 trade: Should produce SQN of 0

    The test verifies that:
    1. SQN is calculated correctly for different trade counts
    2. Trade count is accurately tracked
    3. Expected precision is maintained

    Args:
        main (bool): If True, prints detailed output and skips assertions.
                     If False, runs assertions to verify correctness. Defaults to False.

    Raises:
        AssertionError: If SQN or trade count values don't match expected results
                       (only when main=False).
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    for maxtrades in [None, 0, 1]:
        cerebros = testcommon.runtest(
            datas,
            RunStrategy,
            printdata=main,
            stocklike=False,
            maxtrades=maxtrades,
            printops=main,
            plot=main,
            analyzer=(bt.analyzers.SQN, {}),
        )

        for cerebro in cerebros:
            strat = cerebro.runstrats[0][0]  # no optimization, only 1
            analyzer = strat.analyzers[0]  # only 1
            analysis = analyzer.get_analysis()
            if main:
                # print(analysis)  # Removed for performance
                pass
                print(str(analysis.sqn))
            else:
                if maxtrades == 0 or maxtrades == 1:
                    assert analysis.sqn == 0
                    assert analysis.trades == maxtrades
                else:
                    # Handle different precision
                    assert str(analysis.sqn)[0:14] == "0.912550316439"
                    assert str(analysis.trades) == "11"


if __name__ == "__main__":
    test_run(main=True)
