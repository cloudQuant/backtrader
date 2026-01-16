#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for Renko EMA Crossover Strategy.

This module tests a trading strategy that combines Renko chart filtering
with Exponential Moving Average (EMA) crossover signals. The Renko filter
smooths price data by only updating when price moves a specified brick size,
reducing noise and potentially improving signal quality.

Reference: Backtrader1.0/strategies/renko_ema_crossover.py

Example:
    To run the test directly:
        python tests/strategies/test_92_renko_ema_strategy.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching common directories.

    This function searches for a data file in multiple standard locations
    relative to the test directory, including the current directory, parent
    directory, and 'datas' subdirectories.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: The absolute path to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search locations.

    Example:
        >>> path = resolve_data_path("orcl-1995-2014.txt")
        >>> print(path)
        /path/to/tests/datas/orcl-1995-2014.txt
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


class RenkoEmaStrategy(bt.Strategy):
    """Renko EMA Crossover Strategy.

    This strategy combines Renko chart filtering with Exponential Moving Average
    (EMA) crossover signals to generate trade entries and exits. The Renko filter
    smooths price data by only updating when price moves by a specified brick size,
    which can help reduce noise and false signals.

    Entry conditions:
        - Long: Fast EMA crosses above slow EMA

    Exit conditions:
        - Fast EMA crosses below slow EMA

    Attributes:
        order (bt.Order): Reference to the current pending order. None if no order.
        bar_num (int): Counter for the number of bars processed.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.
        fast_ema (bt.indicators.EMA): Fast exponential moving average indicator.
        slow_ema (bt.indicators.EMA): Slow exponential moving average indicator.
        crossover (bt.indicators.CrossOver): Crossover indicator for the two EMAs.
        p (AutoOrderedDict): Strategy parameters containing:
            - stake (int): Number of shares per trade. Default is 10.
            - fast_period (int): Period for fast EMA. Default is 10.
            - slow_period (int): Period for slow EMA. Default is 20.
            - renko_brick_size (float): Brick size for Renko filter. Default is 1.0.
    """
    params = dict(
        stake=10,
        fast_period=10,
        slow_period=20,
        renko_brick_size=1.0,
    )

    def __init__(self):
        """Initialize the Renko EMA Crossover Strategy.

        Sets up the Renko filter on the data feed, creates the fast and slow
        EMA indicators, initializes the crossover indicator, and sets up
        tracking variables for orders and bar counts.
        """
        # Add Renko filter to smooth price data
        self.data.addfilter(bt.filters.Renko, size=self.p.renko_brick_size)

        # Create EMA indicators for crossover signals
        self.fast_ema = bt.indicators.EMA(self.data, period=self.p.fast_period)
        self.slow_ema = bt.indicators.EMA(self.data, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ema, self.slow_ema)

        # Initialize tracking variables
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        This method is called by the backtrader engine whenever an order's
        status changes. It tracks completed orders to maintain buy/sell counts.

        Args:
            order (bt.Order): The order object with updated status information.

        Note:
            Orders with status Submitted or Accepted are ignored as they are
            still pending execution. Only Completed orders update the tracking
            counters.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        """Execute trading logic for each bar.

        This method is called on every bar of data after indicator calculations.
        It implements the core trading logic:

        1. Increments the bar counter
        2. Skips if there's a pending order
        3. Enters long when fast EMA crosses above slow EMA (no position)
        4. Exits position when fast EMA crosses below slow EMA

        Note:
            The strategy only takes long positions. Short positions are not used.
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            if self.crossover[0] > 0:
                self.order = self.buy(size=self.p.stake)
        elif self.crossover[0] < 0:
            self.order = self.close()


def test_renko_ema_strategy():
    """Test the Renko EMA crossover strategy with historical data.

    This function sets up a backtest with the RenkoEmaStrategy using
    historical Oracle Corporation (ORCL) stock data from 2010-2014.
    It validates the strategy performance against expected values including
    bar count, Sharpe ratio, annual return, and maximum drawdown.

    The test uses the following configuration:
        - Initial capital: $100,000
        - Commission: 0.1% per trade
        - Risk-free rate: 0% (for Sharpe ratio calculation)
        - Fast EMA period: 10
        - Slow EMA period: 20
        - Renko brick size: 1.0
        - Position size: 10 shares per trade

    Raises:
        AssertionError: If any of the performance metrics do not match
            expected values within tolerance. Expected values are:
            - bar_num: 1237
            - final_value: 100057.43 (±0.01)
            - sharpe_ratio: 0.3225444080736762 (±1e-6)
            - annual_return: 0.00011511425744876694 (±1e-6)
            - max_drawdown: 0.09539954392338255 (±1e-6)

    Note:
        The test prints detailed results before assertion, making it easy
        to diagnose failures by comparing expected vs actual values.
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
    cerebro.addstrategy(RenkoEmaStrategy)
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
    print("Renko EMA Crossover Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1237, f"Expected bar_num=1237, got {strat.bar_num}"
    assert abs(final_value - 100057.43) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (0.3225444080736762)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.00011511425744876694)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.09539954392338255) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    # Run the test directly when executed as a script
    print("=" * 60)
    print("Renko EMA Crossover Strategy Test")
    print("=" * 60)
    test_renko_ema_strategy()
