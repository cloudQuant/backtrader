#!/usr/bin/env python
"""Test suite for Backtrader strategy functionality.

This module contains tests for basic strategy operations including:
- Basic strategy execution with indicators
- Multi-data feed strategies
- Strategy parameter optimization

The tests use a simple moving average crossover strategy (SampleStrategy1)
to verify that strategies can be instantiated, executed, and optimized correctly.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import pytest

import backtrader as bt


class SampleStrategy1(bt.Strategy):
    """Simple moving average crossover trading strategy.

    This strategy implements a basic trend-following approach:
    - Buy when price crosses above the SMA
    - Sell when price crosses below the SMA

    Attributes:
        params: Tuple containing strategy parameters:
            - period (int): SMA period in days. Default is 15.
            - printlog (bool): Whether to print log messages. Default is False.
        sma: Simple Moving Average indicator.
        order: Reference to the current pending order.

    Example:
        Create a Cerebro instance and add this strategy::

            cerebro = bt.Cerebro()
            cerebro.addstrategy(SampleStrategy1, period=20, printlog=True)
    """

    params = (
        ("period", 15),
        ("printlog", False),
    )

    def __init__(self):
        """Initialize the strategy with indicators and state variables.

        Creates the Simple Moving Average indicator and initializes the order
        reference to None.
        """
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.order = None

    def notify_order(self, order):
        """Handle order status changes.

        Called by the broker when an order's status changes. Logs execution
        information when orders are completed and clears the order reference.

        Args:
            order (backtrader.Order): The order object with updated status.
        """
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"BUY EXECUTED, Price: {order.executed.price:.2f}")
            else:
                self.log(f"SELL EXECUTED, Price: {order.executed.price:.2f}")
        self.order = None

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Called by the broker when a trade is closed. Logs the profit/loss
        for the completed trade.

        Args:
            trade (backtrader.Trade): The trade object that was closed.
        """
        if trade.isclosed:
            self.log(f"TRADE PROFIT, GROSS {trade.pnl:.2f}, NET {trade.pnlcomm:.2f}")

    def log(self, txt):
        """Log a message with timestamp if printlog is enabled.

        Args:
            txt (str): The message text to log.

        Note:
            Actual printing is commented out for performance reasons.
            The method structure is preserved for debugging purposes.
        """
        if self.p.printlog:
            dt = self.datas[0].datetime.date(0)
            # print(f'{dt.isoformat()}, {txt}')  # Removed for performance
            pass

    def next(self):
        """Execute trading logic for each bar.

        Implements the core strategy logic:
        1. Check if there's a pending order and return if so
        2. If not in position, buy when price crosses above SMA
        3. If in position, sell when price crosses below SMA

        Note:
            This method is called by Backtrader for each bar after
            all indicators have been calculated.
        """
        if self.order:
            return

        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.order = self.buy()
        else:
            if self.data.close[0] < self.sma[0]:
                self.order = self.sell()


def test_strategy_basic(main=False):
    """Test basic strategy functionality with a single data feed.

    This test verifies that:
    1. A strategy can be added to Cerebro
    2. The strategy executes through all data bars
    3. The broker value changes due to trading activity
    4. Orders are executed and positions are managed

    Args:
        main (bool): If True, print additional output. Default is False.

    Raises:
        AssertionError: If the strategy doesn't run, processes zero bars,
            or if the broker value is invalid.
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(SampleStrategy1, printlog=main)
    cerebro.broker.setcash(10000.0)

    if main:
        # print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')  # Removed for performance
        pass

    results = cerebro.run()

    # Verify strategy ran successfully
    assert len(results) > 0
    strat = results[0]
    assert len(strat) > 0  # Processed bars

    final_value = cerebro.broker.getvalue()
    if main:
        # print(f'Final Portfolio Value: {final_value:.2f}')  # Removed for performance
        pass

    # Verify broker value is valid
    assert final_value > 0
    # Verify value changed (either profit or loss)
    assert final_value != 10000.0 or len(strat) == 0  # Changed unless no bars


def test_strategy_multiple_datas(main=False):
    """Test strategy functionality with multiple data feeds.

    This test verifies that a strategy can handle multiple data sources:
    1. Multiple data feeds can be added to Cerebro
    2. The strategy can access all data feeds via self.datas
    3. The strategy processes bars from all feeds

    Args:
        main (bool): If True, print additional output. Default is False.

    Raises:
        AssertionError: If the strategy doesn't run or doesn't have
            the expected number of data feeds.
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))

    # Add two data feeds
    for datafile in ["2006-day-001.txt", "2006-day-002.txt"]:
        datapath = os.path.join(modpath, "../datas", datafile)
        data = bt.feeds.BacktraderCSVData(
            dataname=datapath,
            fromdate=datetime.datetime(2006, 1, 1),
            todate=datetime.datetime(2006, 12, 31),
        )
        cerebro.adddata(data)

    cerebro.addstrategy(SampleStrategy1)
    results = cerebro.run()

    # Verify strategy handled multiple data feeds
    assert len(results) > 0
    strat = results[0]
    assert len(strat.datas) == 2  # Should have 2 data feeds

    if main:
        print("Strategy with multiple datas test passed")
        print(f"Processed {len(strat)} bars with {len(strat.datas)} data feeds")


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Multiprocessing pickle issue on Python < 3.11"
)
def test_strategy_optimization(main=False):
    """Test strategy parameter optimization functionality.

    This test verifies that:
    1. Strategies can be run with multiple parameter combinations
    2. The optstrategy method creates multiple strategy instances
    3. Results are returned for each parameter combination

    Args:
        main (bool): If True, print additional output. Default is False.

    Raises:
        AssertionError: If optimization doesn't produce multiple results.
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.optstrategy(SampleStrategy1, period=range(10, 20, 5))

    results = cerebro.run()

    if main:
        print(f"Optimization tested {len(results)} parameter combinations")

    assert len(results) > 1


if __name__ == "__main__":
    test_strategy_basic(main=True)
    test_strategy_multiple_datas(main=True)
    test_strategy_optimization(main=True)
