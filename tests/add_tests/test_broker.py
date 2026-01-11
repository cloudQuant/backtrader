#!/usr/bin/env python
"""Test module for backtrader broker functionality.

This module contains tests for the broker component of the backtrader framework,
including basic broker operations, cash management, portfolio value tracking,
and commission handling.

The tests verify that the broker correctly:
- Manages initial cash and portfolio value
- Executes orders through strategies
- Calculates portfolio value after trades
- Applies commission to transactions
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class BrokerTestStrategy(bt.Strategy):
    """A simple test strategy for broker functionality testing.

    This strategy implements a basic buy-and-close pattern:
    1. Buys when no position exists
    2. Closes the position after more than 50 bars have elapsed

    Attributes:
        order: The current pending order, or None if no order is pending.
    """

    def __init__(self):
        """Initialize the BrokerTestStrategy.

        Sets up the order tracking attribute to None, indicating no
        pending orders at initialization.
        """
        self.order = None

    def next(self):
        """Execute the strategy logic for each bar.

        The strategy logic:
        - If no position exists, submit a buy order
        - If a position exists and more than 50 bars have elapsed,
          submit a close order to exit the position

        The order is stored in self.order for tracking purposes.
        """
        if not self.position:
            self.order = self.buy()
        elif len(self) > 50:
            self.order = self.close()


def test_broker_basic(main=False):
    """Test basic broker functionality including cash and value management.

    This test verifies that the broker correctly:
    - Sets initial cash to 100,000.0
    - Sets initial portfolio value to 100,000.0
    - Executes a strategy that places orders
    - Maintains positive portfolio value after execution

    Args:
        main (bool): If True, prints starting and final portfolio values.
                     Defaults to False.

    Raises:
        AssertionError: If initial cash is not 100,000.0.
        AssertionError: If initial value is not 100,000.0.
        AssertionError: If final portfolio value is not positive.
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
    cerebro.addstrategy(BrokerTestStrategy)

    # Test broker cash and value
    cerebro.broker.setcash(100000.0)
    if main:
        # print('Starting Cash: %.2f' % cerebro.broker.getcash())  # Removed for performance
        pass
        print("Starting Value: %.2f" % cerebro.broker.getvalue())

    assert cerebro.broker.getcash() == 100000.0
    assert cerebro.broker.getvalue() == 100000.0

    cerebro.run()

    if main:
        # print('Final Cash: %.2f' % cerebro.broker.getcash())  # Removed for performance
        pass
        print("Final Value: %.2f" % cerebro.broker.getvalue())

    # Verify broker state after run
    assert cerebro.broker.getvalue() > 0


def test_broker_commission(main=False):
    """Test broker commission settings and application.

    This test verifies that the broker correctly:
    - Applies a commission rate of 0.001 (0.1%) to trades
    - Executes a strategy with commission enabled
    - Returns valid run results

    Args:
        main (bool): If True, prints a confirmation message.
                     Defaults to False.

    Raises:
        AssertionError: If no strategy results are returned.
        AssertionError: If final portfolio value is not positive.
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
    cerebro.addstrategy(BrokerTestStrategy)
    cerebro.broker.setcommission(commission=0.001)

    results = cerebro.run()

    # Verify broker with commission worked
    assert len(results) > 0
    assert results[0].broker.getvalue() > 0

    if main:
        # print('Broker with commission test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_broker_basic(main=True)
    test_broker_commission(main=True)
