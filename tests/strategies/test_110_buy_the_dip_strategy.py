#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case for Buy The Dip Strategy.

This module contains tests for the BuyTheDipStrategy, which implements a
mean-reversion trading strategy that buys after consecutive down days and
sells after holding for a specified number of days.

Reference: backtrader-strategies-compendium/strategies/BuyTheDip.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching common locations.

    This function searches for a data file in multiple common locations
    relative to the test directory, including the test directory itself,
    its parent directory, and 'datas' subdirectories.

    Args:
        filename: The name of the data file to locate.

    Returns:
        The resolved Path object pointing to the data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search locations.

    """
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR / "datas" / filename,
        BASE_DIR.parent / "datas" / filename,
    ]
    for p in search_paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"Cannot find data file: {filename}")


class BuyTheDipStrategy(bt.Strategy):
    """A mean-reversion strategy that buys after consecutive down days.

    This strategy implements a simple buy-the-dip approach by detecting
    consecutive downward price movements and entering a long position.
    The position is closed after a fixed holding period, regardless of
    profit or loss.

    Entry conditions:
        - Consecutive N days of decline (default: 3 days)

    Exit conditions:
        - Sell after holding for N days (default: 5 days)

    Attributes:
        order: The current pending order object, or None if no order is pending.
        bar_executed: The bar number when the last order was executed.
        bar_num: Total number of bars processed during the backtest.
        buy_count: Total number of buy orders executed.
        sell_count: Total number of sell orders executed.

    Args:
        stake: Number of shares to buy/sell per trade (default: 10).
        hold_days: Number of bars to hold position before selling (default: 5).
        consecutive_down: Number of consecutive down bars to trigger buy signal
            (default: 3).

    """

    params = dict(
        stake=10,
        hold_days=5,
        consecutive_down=3,
    )

    def __init__(self):
        """Initialize the strategy with default tracking variables.

        Sets up instance variables to track orders, execution state, and
        trading statistics.
        """
        self.order = None
        self.bar_executed = 0
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track execution statistics.

        Called by Backtrader when an order changes status. Updates trading
        statistics when orders are completed and clears the pending order
        reference.

        Args:
            order: The order object that has been updated.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
            self.bar_executed = len(self)
        self.order = None

    def next(self):
        """Execute trading logic for each bar.

        This method is called by Backtrader for each bar of data. It implements
        the core strategy logic:
        1. Increments the bar counter
        2. Skips if there's a pending order
        3. For entries: checks for consecutive down days and buys if detected
        4. For exits: closes position after the specified holding period
        """
        self.bar_num += 1

        if self.order:
            return

        if len(self) < self.p.consecutive_down + 1:
            return

        if not self.position:
            # Check for consecutive down days
            all_down = True
            for i in range(self.p.consecutive_down):
                if self.data.close[-i] >= self.data.close[-i-1]:
                    all_down = False
                    break

            if all_down:
                self.order = self.buy(size=self.p.stake)
        else:
            # Sell after holding for N days
            if len(self) >= self.bar_executed + self.p.hold_days:
                self.order = self.close()


def test_buy_the_dip_strategy():
    """Run a backtest of the BuyTheDipStrategy and verify expected results.

    This function sets up a complete backtesting environment using Oracle
    stock data from 2010-2014. It configures the strategy with default
    parameters, sets initial capital to $100,000, and adds performance
    analyzers for Sharpe ratio, returns, and drawdown.

    The test validates that the strategy produces expected results across
    multiple metrics including bar count, final portfolio value, Sharpe
    ratio, annual return, and maximum drawdown.

    Raises:
        AssertionError: If any of the expected values do not match the
            actual results within the specified tolerance. Tolerances are
            0.01 for final_value and 1e-6 for other metrics.

    """
    cerebro = bt.Cerebro()
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(BuyTheDipStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Buy The Dip Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assertions - using precise assertions
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1257, f"Expected bar_num=1257, got {strat.bar_num}"
    assert abs(final_value - 100151.25) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (1.0281051590758732)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.0003030289116772613)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.049493103885201756) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Buy The Dip Strategy Test")
    print("=" * 60)
    test_buy_the_dip_strategy()
