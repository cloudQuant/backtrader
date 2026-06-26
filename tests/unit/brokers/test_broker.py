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
from types import SimpleNamespace

import pytest

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


class OffsetCommissionStrategy(bt.Strategy):
    """Open a futures position and close it as close_today."""

    def __init__(self):
        self.pending_order = None
        self.entry_submitted = False
        self.close_submitted = False
        self.completed_orders = []

    def next(self):
        if self.pending_order is not None:
            return

        if not self.entry_submitted:
            self.entry_submitted = True
            self.pending_order = self.buy(size=1)
            return

        if self.position and not self.close_submitted:
            self.close_submitted = True
            self.pending_order = self.sell(size=1, offset="close_today")

    def notify_order(self, order):
        if order.status not in {
            order.Completed,
            order.Canceled,
            order.Margin,
            order.Rejected,
        }:
            return

        if order.status == order.Completed:
            self.completed_orders.append(order)
        self.pending_order = None


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
    datapath = os.path.join(modpath, "../../datas/2006-day-001.txt")

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
        print("Starting Value: %.2f" % cerebro.broker.getvalue())

    assert cerebro.broker.getcash() == 100000.0
    assert cerebro.broker.getvalue() == 100000.0

    cerebro.run()

    if main:
        # print('Final Cash: %.2f' % cerebro.broker.getcash())  # Removed for performance
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
    datapath = os.path.join(modpath, "../../datas/2006-day-001.txt")

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


def test_broker_getcommissioninfo_matches_private_data_name():
    """Named commission schemes must work for feeds that only expose _name."""
    broker = bt.BrokerBase()
    default_info = broker.getcommissioninfo(SimpleNamespace())
    future_info = bt.ComminfoFuturesPercent(commission=0.000023, margin=0.1, mult=300)

    broker.addcommissioninfo(future_info, name="IF2609")

    assert broker.getcommissioninfo(SimpleNamespace(_name="IF2609")) is future_info
    assert broker.getcommissioninfo(SimpleNamespace(symbol="if2609")) is future_info
    assert broker.getcommissioninfo(SimpleNamespace(_name="OTHER")) is default_info


def test_backbroker_close_today_order_uses_close_today_commission():
    """BackBroker must value futures close-today fills with close_today fees."""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 1, 10),
    )

    cerebro.adddata(data, name="IF2609")
    cerebro.addstrategy(OffsetCommissionStrategy)
    cerebro.broker.setcash(1000000.0)
    cerebro.broker.addcommissioninfo(
        bt.ComminfoFuturesPercent(
            commission=0.0001,
            open_commission=0.000023,
            close_commission=0.00003,
            close_today_commission=0.000345,
            margin=0.12,
            mult=300,
        ),
        name="IF2609",
    )

    strategy = cerebro.run()[0]

    assert len(strategy.completed_orders) == 2
    entry_order, close_order = strategy.completed_orders
    entry_bit = entry_order.executed.exbits[0]
    close_bit = close_order.executed.exbits[0]

    assert entry_bit.openedcomm == pytest.approx(
        entry_order.executed.price * 300 * 0.000023
    )
    assert close_bit.openedcomm == pytest.approx(0.0)
    assert close_bit.closedcomm == pytest.approx(
        close_order.executed.price * 300 * 0.000345
    )
    assert strategy.getposition(data).size == 0


if __name__ == "__main__":
    test_broker_basic(main=True)
    test_broker_commission(main=True)
