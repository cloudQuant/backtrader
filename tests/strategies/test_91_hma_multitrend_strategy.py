#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: HMA MultiTrend multi-period Hull Moving Average trend strategy.

Reference source: Backtrader1.0/strategies/hma_multitrend.py
Uses 4 Hull Moving Averages with different periods to determine trend direction.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common locations.

    Searches for a data file in several predefined directories relative to the
    current test file location. This allows tests to find data files regardless
    of how the test suite is executed.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path: The resolved path object pointing to the existing data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.

    Search Paths:
        1. Current test directory
        2. Parent test directory
        3. Current test directory/datas/
        4. Parent test directory/datas/
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


class HmaMultiTrendStrategy(bt.Strategy):
    """HMA MultiTrend multi-period Hull Moving Average trend strategy.

    Entry conditions:
        - Long: fast > mid1 > mid2 > mid3 (all HMAs in ascending order)
        - Short: fast < mid1 < mid2 < mid3 (all HMAs in descending order)

    Exit conditions:
        - Reverse trend signal
    """
    params = dict(
        stake=10,
        fast=10,
        mid1=20,
        mid2=30,
        mid3=50,
        atr_period=14,
        adx_period=14,
        adx_threshold=0.0,  # Disable ADX filter
    )

    def __init__(self):
        """Initialize the HMA MultiTrend strategy with indicators and tracking variables.

        Creates four Hull Moving Average indicators with different periods to
        establish a trend-following system. Also initializes ATR for volatility
        measurement and ADX for trend strength filtering. Sets up counters to
        track trading activity.
        """
        self.hma_fast = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.fast
        )
        self.hma_mid1 = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.mid1
        )
        self.hma_mid2 = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.mid2
        )
        self.hma_mid3 = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.mid3
        )

        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.adx = bt.indicators.ADX(self.data, period=self.p.adx_period)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track completed trades.

        Called by Backtrader when an order changes status. Counts completed
        buy and sell orders for performance tracking. Resets the order reference
        when the order is complete or cancelled.

        Args:
            order: The Backtrader Order object with updated status.
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
        """Execute trading logic for each bar in the backtest.

        Implements the core strategy logic:
        1. Checks if there's a pending order (no action if order pending)
        2. Applies ADX filter if enabled
        3. Evaluates trend conditions using HMA alignment
        4. Enters long when all HMAs are in ascending order
        5. Enters short when all HMAs are in descending order
        6. Exits positions when the trend reverses
        """
        self.bar_num += 1

        if self.order:
            return

        # ADX filter
        if self.adx[0] < self.p.adx_threshold:
            return

        # Trend conditions
        long_cond = (self.hma_fast[0] > self.hma_mid1[0] >
                     self.hma_mid2[0] > self.hma_mid3[0])
        short_cond = (self.hma_fast[0] < self.hma_mid1[0] <
                      self.hma_mid2[0] < self.hma_mid3[0])

        if not self.position:
            if long_cond:
                self.order = self.buy(size=self.p.stake)
            elif short_cond:
                self.order = self.sell(size=self.p.stake)
        else:
            # Close position on reverse signal
            if self.position.size > 0 and short_cond:
                self.order = self.close()
            elif self.position.size < 0 and long_cond:
                self.order = self.close()


def test_hma_multitrend_strategy():
    """Test the HMA MultiTrend strategy with historical Oracle data.

    Sets up a backtest using Oracle Corporation stock data from 2010-2014,
    runs the HMA MultiTrend strategy, and validates the results against
    expected values. This test ensures the strategy produces consistent
    results after refactoring or code changes.

    Test Configuration:
        - Data: Oracle (ORCL) daily prices from 2010-01-01 to 2014-12-31
        - Initial Capital: $100,000
        - Commission: 0.1% per trade
        - Strategy Parameters: fast=10, mid1=20, mid2=30, mid3=50

    Assertions:
        - bar_num: Exactly 1202 bars processed
        - final_value: Approximately $100,003.09 (nearly break-even)
        - sharpe_ratio: Approximately 0.00618 (very low returns)
        - annual_return: Approximately 0.0000062 (minimal)
        - max_drawdown: Approximately 25.88%

    Raises:
        AssertionError: If any of the performance metrics don't match
            expected values within specified tolerances.
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
    cerebro.addstrategy(HmaMultiTrendStrategy)
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
    print("HMA MultiTrend multi-period Hull Moving Average trend strategy backtest results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1202, f"Expected bar_num=1202, got {strat.bar_num}"
    assert abs(final_value - 100003.09) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (0.006181944585090366)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (6.194873476064192e-06)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.258774207577785) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("HMA MultiTrend multi-period Hull Moving Average trend strategy test")
    print("=" * 60)
    test_hma_multitrend_strategy()
