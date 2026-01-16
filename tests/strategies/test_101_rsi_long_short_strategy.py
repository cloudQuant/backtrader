#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test Case: RSI Long/Short Dual RSI Strategy.

This module implements and tests a trading strategy that uses a combination
of long and short period Relative Strength Index (RSI) indicators to determine
entry and exit timing.

Reference: backtrader-strategies-compendium/strategies/RsiLongShort.py

The strategy uses two RSI indicators with different periods:
- Long period RSI (default 14 bars): Identifies overall trend strength
- Short period RSI (default 5 bars): Identifies short-term momentum

Entry conditions:
- Long: Long period RSI > 50 AND Short period RSI > 65

Exit conditions:
- Short period RSI < 45
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching common locations.

    This function searches for a data file in several common locations
    relative to the test directory, allowing tests to run from different
    working directories.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: The absolute path to the first matching data file found.

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


class RsiLongShortStrategy(bt.Strategy):
    """RSI Long/Short Dual RSI Strategy.

    This strategy implements a dual-RSI approach combining long and short period
    RSI indicators to identify entry and exit points. The long period RSI provides
    confirmation of overall trend strength, while the short period RSI identifies
    short-term momentum for precise entry/exit timing.

    Entry conditions:
        - Long: Long period RSI > 50 AND Short period RSI > 65

    Exit conditions:
        - Short period RSI < 45

    Attributes:
        params (dict): Strategy parameters with the following keys:
            stake (int): Number of shares/contracts per trade. Default is 10.
            period_long (int): Period for long-term RSI calculation. Default is 14.
            period_short (int): Period for short-term RSI calculation. Default is 5.
            buy_rsi_long (float): RSI threshold for long period to trigger buy.
                Default is 50.
            buy_rsi_short (float): RSI threshold for short period to trigger buy.
                Default is 65.
            sell_rsi_short (float): RSI threshold for short period to trigger sell.
                Default is 45.
        rsi_long (bt.indicators.RSI): Long period RSI indicator instance.
        rsi_short (bt.indicators.RSI): Short period RSI indicator instance.
        order (bt.Order): Current pending order, or None if no pending orders.
        bar_num (int): Counter for the number of bars processed during backtest.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.
    """
    params = dict(
        stake=10,
        period_long=14,
        period_short=5,
        buy_rsi_long=50,
        buy_rsi_short=65,
        sell_rsi_short=45,
    )

    def __init__(self):
        """Initialize the RSI Long/Short strategy.

        Creates the long and short period RSI indicators and initializes
        tracking variables for orders and statistics.
        """
        self.rsi_long = bt.indicators.RSI(self.data, period=self.p.period_long)
        self.rsi_short = bt.indicators.RSI(self.data, period=self.p.period_short)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Called by Backtrader when an order changes status. Updates buy/sell
        counters when orders complete and clears the pending order reference.

        Args:
            order (bt.Order): The order object with updated status.
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

        This method is called by Backtrader for each new bar of data.
        Implements the dual-RSI strategy logic:
        1. Skip if there's a pending order
        2. If not in position: Enter long when both RSI conditions are met
        3. If in position: Exit when short RSI falls below sell threshold
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Entry: Long period RSI strong AND Short period RSI strong
            if self.rsi_long[0] > self.p.buy_rsi_long and self.rsi_short[0] > self.p.buy_rsi_short:
                self.order = self.buy(size=self.p.stake)
        else:
            # Exit: Short period RSI falls back
            if self.rsi_short[0] < self.p.sell_rsi_short:
                self.order = self.close()


def test_rsi_long_short_strategy():
    """Test the RSI Long/Short strategy with historical data.

    This test function validates the RSI Long/Short strategy by:
    1. Loading historical Oracle stock data from 2010-2014
    2. Applying the RSI Long/Short strategy with default parameters
    3. Running the backtest with analyzers for Sharpe Ratio, Returns, and DrawDown
    4. Printing detailed backtest results
    5. Validating results against expected values with precise assertions

    The test uses the following expected values:
    - Number of bars: 1243
    - Final portfolio value: 100023.95 (starting from 100000)
    - Sharpe Ratio: 0.12109913246951494
    - Annual Return: 4.800683696093361e-05
    - Maximum Drawdown: 0.09601330432360433 (9.60%)

    Raises:
        AssertionError: If any of the backtest metrics don't match expected values
            within the specified tolerance (0.01 for final_value, 1e-6 for others).
        FileNotFoundError: If the required data file (orcl-1995-2014.txt) cannot
            be found in any of the search locations.
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
    cerebro.addstrategy(RsiLongShortStrategy)
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
    print("RSI Long/Short Dual RSI Strategy Backtest Results:")
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
    assert strat.bar_num == 1243, f"Expected bar_num=1243, got {strat.bar_num}"
    assert abs(final_value - 100023.95) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (0.12109913246951494)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (4.800683696093361e-05)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.09601330432360433) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("RSI Long/Short Dual RSI Strategy Test")
    print("=" * 60)
    test_rsi_long_short_strategy()
