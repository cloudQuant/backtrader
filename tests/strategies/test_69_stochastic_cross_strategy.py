#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for Stochastic Cross Strategy.

This module tests a quantitative trading strategy that combines Simple Moving
Average (SMA) trend indicators with Stochastic oscillator signals to generate
buy and sell signals. The strategy enters long positions when the short-term
MA is above the long-term MA and the Stochastic indicator is oversold, and
exits when the short-term MA is below the long-term MA and the Stochastic
indicator is overbought.

Reference: https://github.com/backtrader/backhacker

Example:
    To run the test directly::

        python tests/strategies/test_69_stochastic_cross_strategy.py

    Or using pytest::

        pytest tests/strategies/test_69_stochastic_cross_strategy.py -v
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on the script's directory.

    This function searches for data files in multiple possible locations
    relative to the script's directory, including the current directory,
    parent directory, and 'datas' subdirectories. This allows tests to find
    their data files regardless of how they are executed.

    Args:
        filename: Name of the data file to locate (e.g., 'orcl-1995-2014.txt').

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths. The error message includes the filename being searched for.

    Example:
        >>> path = resolve_data_path('orcl-1995-2014.txt')
        >>> print(path)
        /path/to/tests/strategies/datas/orcl-1995-2014.txt
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


class StochasticCrossStrategy(bt.Strategy):
    """A quantitative trading strategy based on Stochastic oscillator crossover.

    This strategy combines Simple Moving Average (SMA) trend indicators with
    Stochastic oscillator signals to generate buy and sell signals. The strategy
    aims to capture trend reversals by entering positions when the market is
    oversold in an uptrend and exiting when overbought in a downtrend.

    Trading Logic:
        - Buy Signal: Short-term MA > Long-term MA AND Stochastic %K < oversold threshold (20)
        - Sell Signal: Short-term MA < Long-term MA AND Stochastic %K > overbought threshold (80)

    The strategy ensures only one position is active at a time by tracking
    the last operation and preventing duplicate signals.

    Attributes:
        dataclose: Reference to the close price line of the primary data feed.
        ma1: Short-term Simple Moving Average indicator (default 14-period).
        ma2: Long-term Simple Moving Average indicator (default 30-period).
        stoch: Stochastic oscillator indicator providing %K and %D lines.
        order: Reference to the currently pending order, or None if no order is active.
        last_operation: String tracking the last executed operation ("BUY" or "SELL").
        bar_num: Integer counter for the number of bars processed during the backtest.
        buy_count: Integer counter for the total number of buy orders executed.
        sell_count: Integer counter for the total number of sell orders executed.

    Parameters:
        stake: Number of shares/contracts per trade (default: 10).
        ma1: Period for the short-term SMA (default: 14).
        ma2: Period for the long-term SMA (default: 30).
        stoch_period: Period for the Stochastic oscillator calculation (default: 14).
        oversold: Stochastic threshold below which is considered oversold (default: 20).
        overbought: Stochastic threshold above which is considered overbought (default: 80).
    """
    params = dict(
        stake=10,
        ma1=14,
        ma2=30,
        stoch_period=14,
        oversold=20,
        overbought=80,
    )

    def __init__(self):
        """Initialize the StochasticCrossStrategy.

        Sets up the technical indicators (SMA and Stochastic), initializes
        tracking variables for orders and statistics, and prepares the strategy
        for execution. The indicators are automatically registered with the
        strategy's line iterator system.
        """
        self.dataclose = self.datas[0].close
        self.ma1 = bt.ind.SMA(self.datas[0], period=self.p.ma1)
        self.ma2 = bt.ind.SMA(self.datas[0], period=self.p.ma2)
        self.stoch = bt.ind.Stochastic(self.datas[0], period=self.p.stoch_period)

        self.order = None
        self.last_operation = "SELL"

        # Statistics variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        This method is called by the backtrader engine whenever an order's
        status changes. It tracks completed orders to update the operation
        state and maintains statistics on buy/sell counts.

        Args:
            order: The order object that has been updated. Contains status,
                execution price, size, and other order-related information.

        Note:
            - Orders with status Submitted or Accepted are ignored as they
              are still pending execution.
            - Only Completed orders trigger updates to buy/sell counts and
              the last_operation tracking.
            - The order reference is reset to None after processing to allow
              new orders to be placed.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.last_operation = "BUY"
            else:
                self.sell_count += 1
                self.last_operation = "SELL"

        self.order = None

    def next(self):
        """Execute the trading logic for each bar.

        This method is called by the backtrader engine for each new bar of data.
        It implements the core trading strategy: checking conditions and placing
        orders when entry signals are detected.

        The strategy:
            1. Increments the bar counter
            2. Returns early if there's a pending order (prevents over-trading)
            3. Checks for buy signal: uptrend (MA1 > MA2) + oversold Stochastic
            4. Checks for sell signal: downtrend (MA1 < MA2) + overbought Stochastic

        Note:
            Only one order can be active at a time. The strategy uses
            last_operation tracking to prevent duplicate signals (e.g.,
            multiple buy orders in a row without an intervening sell).
        """
        self.bar_num += 1

        if self.order:
            return

        # Buy condition: short-term MA > long-term MA AND Stochastic oversold
        if self.last_operation != "BUY":
            if self.ma1[0] > self.ma2[0] and self.stoch.percK[0] < self.p.oversold:
                self.order = self.buy(size=self.p.stake)

        # Sell condition: short-term MA < long-term MA AND Stochastic overbought
        if self.last_operation != "SELL":
            if self.ma1[0] < self.ma2[0] and self.stoch.percK[0] > self.p.overbought:
                self.order = self.sell(size=self.p.stake)

    def stop(self):
        """Perform cleanup actions when the backtest completes.

        This method is called by the backtrader engine at the end of the
        backtest. It can be used for logging, saving results, or performing
        other cleanup tasks.

        Note:
            Currently empty but maintained for potential future use in
            logging or post-backtest analysis.
        """
        pass


def test_stochastic_cross_strategy():
    """Test the Stochastic crossover strategy with historical data.

    This test function sets up a complete backtest environment using historical
    Oracle Corporation stock data from 2010-2014. It validates the strategy's
    implementation by checking that performance metrics match expected values.

    The test performs the following:
        1. Creates a Cerebro engine instance
        2. Loads historical price data from a CSV file
        3. Configures the StochasticCrossStrategy with default parameters
        4. Sets initial capital and commission structure
        5. Adds performance analyzers (Sharpe Ratio, Returns, Drawdown, Trades)
        6. Runs the backtest over the specified date range
        7. Validates results against expected values

    Expected Results:
        - Bars processed: 1228
        - Final portfolio value: $100,183.85
        - Sharpe ratio: 0.8140783317581928
        - Annual return: 0.00036830689381886077
        - Maximum drawdown: 7.75%

    Raises:
        AssertionError: If any of the performance metrics do not match the
            expected values within tolerance.
        FileNotFoundError: If the Oracle data file cannot be located.
    """
    cerebro = bt.Cerebro()

    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(StochasticCrossStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Stochastic Cross Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1228, f"Expected bar_num=1228, got {strat.bar_num}"
    assert abs(final_value - 100183.85) < 0.01, f"Expected final_value=100183.85, got {final_value}"
    assert abs(sharpe_ratio - (0.8140783317581928)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.00036830689381886077)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.07746163959163185) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Stochastic Cross Strategy Test")
    print("=" * 60)
    test_stochastic_cross_strategy()
