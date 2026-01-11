#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case for Data Resample data resampling functionality.

This module tests the data resampling functionality of Backtrader by implementing
a simple dual moving average crossover strategy. It demonstrates how to resample
daily data to weekly timeframes and validates that the resampled data produces
expected backtesting results.

Reference source: backtrader-master2/samples/data-resample/data-resample.py

Example:
    Run the test directly:
        python tests/strategies/test_53_data_resample.py

    Or use pytest:
        pytest tests/strategies/test_53_data_resample.py -v
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the absolute path of a data file by searching common directories.

    This function searches for data files in several common locations relative
    to the test directory, including the current directory, parent directory,
    and 'datas' subdirectories.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: The absolute path to the first matching data file found.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search locations.

    Example:
        >>> data_path = resolve_data_path('2005-2006-day-001.txt')
        >>> print(data_path)
        /path/to/tests/strategies/datas/2005-2006-day-001.txt
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


class SimpleMAStrategy(bt.Strategy):
    """Simple dual moving average crossover strategy for testing data resampling.

    This strategy implements a classic dual moving average crossover approach
    to test Backtrader's data resampling functionality. It generates buy and sell
    signals based on the crossover of a fast simple moving average (SMA) and a
    slow SMA.

    Trading Logic:
        - Entry (Buy): When the fast SMA crosses above the slow SMA
        - Exit (Sell): When the fast SMA crosses below the slow SMA
        - Position management: Only one position (long or short) at a time

    Attributes:
        fast_ma (bt.ind.SMA): Fast simple moving average indicator.
        slow_ma (bt.ind.SMA): Slow simple moving average indicator.
        crossover (bt.ind.CrossOver): Crossover indicator tracking fast/slow MA crosses.
        order (bt.Order): Reference to the current pending order (None if no pending order).
        bar_num (int): Counter for the number of bars processed.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.

    params:
        fast_period (int): Period for the fast moving average. Default is 5.
        slow_period (int): Period for the slow moving average. Default is 15.

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(SimpleMAStrategy, fast_period=5, slow_period=15)
        >>> cerebro.run()
    """
    params = (('fast_period', 5), ('slow_period', 15))

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables.

        Creates the fast and slow simple moving averages, the crossover indicator,
        and initializes counters for tracking orders and bars. All indicators are
        automatically registered with the strategy during initialization.
        """
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track completed trades.

        Called by Backtrader when an order's status changes. Tracks the number
        of completed buy and sell orders and clears the pending order reference
        when the order is no longer alive.

        Args:
            order (bt.Order): The order object with updated status information.

        Note:
            This method is called automatically by the Backtrader engine
            during order execution.
        """
        if not order.alive():
            self.order = None
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def next(self):
        """Execute trading logic for each bar.

        This method is called for each bar of data (after the minimum period
        has been reached). It implements the core trading logic:

        1. Increments the bar counter
        2. Checks if there's a pending order (skip if so)
        3. Generates buy order when fast MA crosses above slow MA
        4. Generates sell/close order when fast MA crosses below slow MA

        Note:
            This method is called automatically by the Backtrader engine
            during the backtesting loop.
        """
        self.bar_num += 1
        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def test_data_resample():
    """Test data resampling functionality with a dual moving average strategy.

    This function tests Backtrader's data resampling capabilities by:
    1. Loading daily price data from a CSV file
    2. Resampling the data to weekly timeframe
    3. Running a dual moving average crossover strategy
    4. Validating performance metrics against expected values

    The test verifies that:
        - Exactly 89 weekly bars are processed
        - Final portfolio value matches expected value (100765.01)
        - Sharpe ratio is calculated correctly for weekly data
        - Annual returns and maximum drawdown meet expectations
        - Exactly 3 total trades are executed

    Raises:
        AssertionError: If any of the validation assertions fail.
        FileNotFoundError: If the data file cannot be located.

    Example:
        >>> test_data_resample()
        ==================================================
        Data Resample data resampling test
        ==================================================
        Loading data...
        Starting backtest...

        ==================================================
        Data Resample backtest results (weekly timeframe):
          bar_num: 89
          buy_count: 4
          sell_count: 4
          total_trades: 3
          sharpe_ratio: 1.0787422654055023
          annual_return: 0.003817762345337259
          max_drawdown: 0.3038892199564355
          final_value: 100765.01
        ==================================================

        Test passed!
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))

    # Resample to weekly timeframe
    cerebro.resampledata(
        data,
        timeframe=bt.TimeFrame.Weeks,
        compression=1
    )

    # Add simple dual moving average crossover strategy
    cerebro.addstrategy(SimpleMAStrategy, fast_period=5, slow_period=15)

    # Add complete analyzers - calculate Sharpe ratio using weekly timeframe
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Weeks, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results in standard format
    print("\n" + "=" * 50)
    print("Data Resample backtest results (weekly timeframe):")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert test results
    assert strat.bar_num == 89, f"Expected bar_num=89, got {strat.bar_num}"
    assert abs(final_value - 100765.01) < 0.01, f"Expected final_value=100765.01, got {final_value}"
    assert abs(sharpe_ratio - 1.0787422654055023) < 1e-6, f"Expected sharpe_ratio=1.0787422654055023, got {sharpe_ratio}"
    assert abs(annual_return - 0.003817762345337259) < 1e-6, f"Expected annual_return=0.003817762345337259, got {annual_return}"
    assert abs(max_drawdown - 0.3038892199564355) < 1e-6, f"Expected max_drawdown=0.3038892199564355, got {max_drawdown}"
    assert total_trades == 3, f"Expected total_trades=3, got {total_trades}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Data Resample data resampling test")
    print("=" * 60)
    test_data_resample()
