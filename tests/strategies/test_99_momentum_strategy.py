#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Momentum Strategy Test Module.

This module provides a test implementation of a momentum-based trading strategy
using Backtrader. The strategy uses price momentum indicators to generate
trading signals based on trend changes.

The module includes:
    - MomentumStrategy: A strategy class that implements momentum-based trading
    - test_momentum_strategy(): A test function that validates the strategy

Reference: Time_Series_Backtesting/strategy_library/MOM_strategy_1.0.py
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching common directories.

    This function searches for data files in multiple potential locations
    relative to the test directory, making tests more robust to different
    execution contexts.

    Args:
        filename: Name of the data file to locate (e.g., "orcl-1995-2014.txt").

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.

    Example:
        >>> path = resolve_data_path("orcl-1995-2014.txt")
        >>> print(path)  # Points to the data file location
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


class MomentumStrategy(bt.Strategy):
    """Momentum-based trading strategy.

    This strategy uses the Momentum indicator to identify trend changes and
    generate trading signals. It goes long when momentum turns positive and
    exits when momentum turns negative.

    Trading Logic:
        - Entry (Long): When momentum changes from negative to positive (crosses above 0)
        - Exit: When momentum changes from positive to negative (crosses below 0)

    Attributes:
        momentum (bt.indicators.Momentum): The momentum indicator with configurable period.
        order (bt.Order): Current pending order, or None if no order is pending.
        bar_num (int): Counter for the number of bars processed.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.

    Parameters:
        stake (int): Number of shares/contracts per trade. Default is 10.
        period (int): Period for the momentum indicator calculation. Default is 20.

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(MomentumStrategy, stake=10, period=20)
        >>> results = cerebro.run()
    """

    params = dict(
        stake=10,
        period=20,
    )

    def __init__(self):
        """Initialize strategy indicators and state variables.

        Creates the momentum indicator and initializes tracking variables
        for order management and statistics.
        """
        # Calculate momentum indicator on closing prices
        self.momentum = bt.indicators.Momentum(self.data.close, period=self.p.period)

        # Initialize state variables
        self.order = None  # Track current pending order
        self.bar_num = 0   # Count of bars processed
        self.buy_count = 0  # Statistics tracking
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Called by Backtrader when an order's status changes. Updates statistics
        and clears the pending order reference when the order is completed or
        cancelled.

        Args:
            order (bt.Order): The order object that was updated. Status can be
                Submitted, Accepted, Completed, Canceled, Margin, or Rejected.

        Note:
            This method does not process orders in Submitted or Accepted states
            as they are still pending execution.
        """
        # Ignore pending orders
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        # Update trade statistics
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

        # Clear order reference
        self.order = None

    def next(self):
        """Execute trading logic for each bar.

        This method is called by Backtrader for each bar of data. It implements
        the core trading logic:

        1. Check if there's a pending order (skip if yes)
        2. Ensure we have enough data for momentum calculation
        3. If not in position: Check for momentum cross above 0 (buy signal)
        4. If in position: Check for momentum cross below 0 (exit signal)

        The momentum crossover is detected by comparing the previous bar's
        momentum value with the current bar's value.
        """
        self.bar_num += 1

        # Wait for pending order to complete
        if self.order:
            return

        # Ensure minimum data for momentum calculation
        if len(self) < 2:
            return

        if not self.position:
            # Entry logic: Momentum changes from negative to positive
            # [-1] is previous bar, [0] is current bar
            if self.momentum[-1] <= 0 and self.momentum[0] > 0:
                self.order = self.buy(size=self.p.stake)
        else:
            # Exit logic: Momentum changes from positive to negative
            if self.momentum[-1] > 0 and self.momentum[0] <= 0:
                self.order = self.close()


def test_momentum_strategy():
    """Test the Momentum strategy with historical data.

    This test function:
    1. Loads Oracle Corporation historical price data (2010-2014)
    2. Configures a Backtrader Cerebro engine with the strategy
    3. Runs the backtest with initial capital of $100,000
    4. Validates performance metrics against expected values

    Expected Results:
        - bar_num: 1237 (number of bars processed)
        - final_value: ~100040.76 (ending portfolio value)
        - sharpe_ratio: ~0.263 (risk-adjusted return metric)
        - annual_return: ~8.17e-05 (annualized return rate)
        - max_drawdown: ~0.083 (maximum peak-to-trough decline)

    Raises:
        AssertionError: If any of the expected values do not match the
            actual results within the specified tolerance.

    Note:
        The test uses a tolerance of 0.01 for final_value and 1e-6 for
        other metrics to account for minor numerical differences.
    """
    cerebro = bt.Cerebro()

    # Load historical data
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)

    # Add strategy with default parameters
    cerebro.addstrategy(MomentumStrategy)

    # Configure broker settings
    cerebro.broker.setcash(100000)  # Initial capital
    cerebro.broker.setcommission(commission=0.001)  # 0.1% commission

    # Add performance analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    # Run backtest
    results = cerebro.run()
    strat = results[0]

    # Extract performance metrics
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("=" * 50)
    print("Momentum Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Validate results against expected values
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1237, f"Expected bar_num=1237, got {strat.bar_num}"
    assert abs(final_value - 100040.76) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (0.26328384417769385)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (8.169647692811904e-05)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.08327600866592394) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Momentum Strategy Test")
    print("=" * 60)
    test_momentum_strategy()
