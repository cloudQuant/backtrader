#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test Case: Forex EMA Triple Moving Average Strategy.

This module tests a forex trading strategy that uses triple exponential moving
averages (EMAs) to generate entry and exit signals. The strategy is based on
the alignment and crossover relationships between short-term, medium-term, and
long-term EMAs.

Reference: backtrader-strategies/forexema.py

Strategy Overview:
    The strategy uses three EMAs with different periods:
    - Short-term EMA (default: 5 periods)
    - Medium-term EMA (default: 20 periods)
    - Long-term EMA (default: 50 periods)

Entry Conditions:
    Long (Buy):
        - Short-term EMA crosses above medium-term EMA
        - Price low is above long-term EMA
        - EMAs are aligned: short > medium > long

    Short (Sell):
        - Short-term EMA crosses below medium-term EMA
        - Price high is below long-term EMA
        - EMAs are aligned: short < medium < long

Exit Conditions:
    - Position is closed when the crossover signal reverses

Example:
    >>> test_forex_ema_strategy()
    ==================================================
    Forex EMA Triple Moving Average Strategy Backtest Results:
      bar_num: 1208
      buy_count: 8
      sell_count: 8
      sharpe_ratio: -0.6859889019155611
      annual_return: -0.00020318349900697326
      max_drawdown: 0.15891968567586484
      final_value: 99898.69
    ==================================================

    Test passed!
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the full path to a data file by searching multiple locations.

    This function searches for a data file in several common locations relative
    to the current test directory. It checks the current directory, parent
    directory, and 'datas' subdirectory in both locations.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: The absolute path to the data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search locations.

    Search Order:
        1. BASE_DIR / filename
        2. BASE_DIR.parent / filename
        3. BASE_DIR / 'datas' / filename
        4. BASE_DIR.parent / 'datas' / filename

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


class ForexEmaStrategy(bt.Strategy):
    """Forex EMA Triple Moving Average Strategy.

    This strategy implements a triple EMA crossover system commonly used in
    forex trading. It uses three exponential moving averages with different
    periods to identify trend direction and generate trading signals.

    Strategy Logic:
        The strategy enters long positions when the short-term EMA crosses
        above the medium-term EMA, with confirmation from price action and
        EMA alignment. Conversely, it enters short positions when the
        short-term EMA crosses below the medium-term EMA with similar
        confirmations.

        Positions are closed when the crossover signal reverses, providing
        a natural exit mechanism that follows price momentum.

    Parameters:
        stake (int): Number of units/shares per trade. Default is 10.
        shortema (int): Period for the short-term EMA. Default is 5.
        mediumema (int): Period for the medium-term EMA. Default is 20.
        longema (int): Period for the long-term EMA. Default is 50.

    Attributes:
        shortema (ExponentialMovingAverage): Short-term EMA indicator.
        mediumema (ExponentialMovingAverage): Medium-term EMA indicator.
        longema (ExponentialMovingAverage): Long-term EMA indicator.
        shortemacrossover (CrossOver): Crossover indicator for short/medium EMAs.
        order (Order): Current pending order, or None if no pending order.
        bar_num (int): Counter for the number of bars processed.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.

    Entry Conditions:
        Long Entry:
            - Short-term EMA crosses above medium-term EMA (crossover > 0)
            - Current bar's low is above long-term EMA
            - Medium-term EMA is above long-term EMA
            - Short-term EMA is above long-term EMA

        Short Entry:
            - Short-term EMA crosses below medium-term EMA (crossover < 0)
            - Current bar's high is below long-term EMA
            - Medium-term EMA is below long-term EMA
            - Short-term EMA is below long-term EMA

    Exit Conditions:
        - Long position closed when short-term EMA crosses below medium-term EMA
        - Short position closed when short-term EMA crosses above medium-term EMA

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(ForexEmaStrategy, stake=10, shortema=5,
        ...                     mediumema=20, longema=50)
        >>> cerebro.run()
    """
    params = dict(
        stake=10,
        shortema=5,
        mediumema=20,
        longema=50,
    )

    def __init__(self):
        """Initialize the Forex EMA strategy with indicators and state variables.

        This method sets up the three exponential moving average indicators
        and the crossover indicator used for signal generation. It also
        initializes state variables for tracking orders and execution counts.

        Indicators Created:
            - shortema: EMA with period from params.shortema
            - mediumema: EMA with period from params.mediumema
            - longema: EMA with period from params.longema
            - shortemacrossover: CrossOver of shortema and mediumema

        State Variables Initialized:
            - order: Set to None, tracks pending orders
            - bar_num: Set to 0, counts bars processed
            - buy_count: Set to 0, tracks buy executions
            - sell_count: Set to 0, tracks sell executions
        """
        self.shortema = bt.indicators.ExponentialMovingAverage(
            self.data, period=self.p.shortema
        )
        self.mediumema = bt.indicators.ExponentialMovingAverage(
            self.data, period=self.p.mediumema
        )
        self.longema = bt.indicators.ExponentialMovingAverage(
            self.data, period=self.p.longema
        )

        self.shortemacrossover = bt.indicators.CrossOver(self.shortema, self.mediumema)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track executed trades.

        This callback method is invoked by the backtrader engine whenever an
        order's status changes. It counts completed buy and sell orders and
        clears the pending order reference when the order is filled or
        cancelled.

        Args:
            order (Order): The order object with updated status.

        Order Status Handling:
            - Submitted/Acpected: Order is pending, no action taken
            - Completed: Order filled, increment buy_count or sell_count
            - Other statuses (Cancelled, Margin, Expired): Order cleared

        Side Effects:
            - Increments buy_count when a buy order is completed
            - Increments sell_count when a sell order is completed
            - Sets self.order to None when order is no longer pending
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

        This method is called by the backtrader engine for each bar of data.
        It implements the core strategy logic: checking entry conditions,
        placing orders, and managing existing positions.

        Execution Flow:
            1. Increment bar counter
            2. Skip processing if an order is already pending
            3. If no position, check entry conditions (long or short)
            4. If position exists, check exit conditions

        Entry Conditions:
            Long Entry:
                - Crossover signal > 0 (short EMA crossed above medium EMA)
                - Current bar low > long EMA
                - Medium EMA > long EMA
                - Short EMA > long EMA

            Short Entry:
                - Crossover signal < 0 (short EMA crossed below medium EMA)
                - Current bar high < long EMA
                - Medium EMA < long EMA
                - Short EMA < long EMA

        Exit Conditions:
            - Long position: close when crossover < 0
            - Short position: close when crossover > 0

        Side Effects:
            - Places buy/sell/close orders via self.order
            - Updates self.bar_num counter
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Long entry condition
            if (self.shortemacrossover > 0 and
                self.data.low[0] > self.longema[0] and
                self.mediumema[0] > self.longema[0] and
                self.shortema[0] > self.longema[0]):
                self.order = self.buy(size=self.p.stake)
            # Short entry condition
            elif (self.shortemacrossover < 0 and
                  self.data.high[0] < self.longema[0] and
                  self.mediumema[0] < self.longema[0] and
                  self.shortema[0] < self.longema[0]):
                self.order = self.sell(size=self.p.stake)
        else:
            # Exit condition: reverse crossover
            if self.position.size > 0 and self.shortemacrossover < 0:
                self.order = self.close()
            elif self.position.size < 0 and self.shortemacrossover > 0:
                self.order = self.close()


def test_forex_ema_strategy():
    """Test the Forex EMA Triple Moving Average Strategy.

    This function creates a backtest environment using historical data,
    runs the ForexEmaStrategy, and validates the results against expected
    values. The test uses Oracle stock data from 2010-2014 to verify
    strategy behavior and performance metrics.

    Test Configuration:
        - Initial Cash: $100,000
        - Commission: 0.1% per trade
        - Data: Oracle stock prices (2010-2014)
        - Strategy Parameters: Default (shortema=5, mediumema=20, longema=50)

    Performance Metrics Validated:
        - bar_num: Number of bars processed (expected: 1208)
        - final_value: Final portfolio value (expected: $99,898.69)
        - sharpe_ratio: Risk-adjusted return metric (expected: -0.686)
        - annual_return: Annualized return (expected: -0.02%)
        - max_drawdown: Maximum peak-to-trough decline (expected: 15.89%)

    Assertions:
        - bar_num == 1208
        - final_value within 0.01 of 99898.69
        - sharpe_ratio within 1e-6 of -0.6859889019155611
        - annual_return within 1e-12 of -0.00020318349900697326
        - max_drawdown within 1e-6 of 0.15891968567586484

    Raises:
        AssertionError: If any of the performance metrics don't match expected
            values within specified tolerances.
        FileNotFoundError: If the test data file cannot be found.

    Side Effects:
        - Prints backtest results to console
        - Prints test pass confirmation

    Example:
        >>> test_forex_ema_strategy()
        ==================================================
        Forex EMA Triple Moving Average Strategy Backtest Results:
          bar_num: 1208
          buy_count: 8
          sell_count: 8
          sharpe_ratio: -0.6859889019155611
          annual_return: -0.00020318349900697326
          max_drawdown: 0.15891968567586484
          final_value: 99898.69
        ==================================================

        Test passed!
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
    cerebro.addstrategy(ForexEmaStrategy)
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
    print("Forex EMA Triple Moving Average Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1208, f"Expected bar_num=1208, got {strat.bar_num}"
    assert abs(final_value - 99898.69) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (-0.6859889019155611)) < 1e-6, f"Expected sharpe_ratio=-0.6859889019155611, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00020318349900697326)) < 1e-12, f"Expected annual_return=-0.00020318349900697326, got {annual_return}"
    assert abs(max_drawdown - 0.15891968567586484) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Forex EMA Triple Moving Average Strategy Test")
    print("=" * 60)
    test_forex_ema_strategy()
