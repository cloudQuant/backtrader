#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for Ichimoku Cloud trading strategy.

This module tests the Ichimoku Cloud strategy implementation, which uses
the Ichimoku Kinko Hyo technical indicator to generate trading signals based
on price position relative to the cloud (Kumo).

Reference: backtrader-strategies-compendium/strategies/Ichimoku.py

The strategy enters long positions when price is above the cloud and exits
when price breaks below the cloud boundaries.
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
    to the test directory, allowing flexibility in test file organization.

    Args:
        filename: The name of the data file to locate.

    Returns:
        The absolute Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched locations.

    Search Locations:
        1. Current test directory (tests/strategies/)
        2. Parent tests directory (tests/)
        3. Current test directory/datas/
        4. Parent tests directory/datas/
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


class IchimokuCloudStrategy(bt.Strategy):
    """Ichimoku Cloud trading strategy.

    This strategy implements a trend-following approach using the Ichimoku Kinko
    Hyo technical indicator. The Ichimoku Cloud (Kumo) is used to determine
    market trend direction and generate trading signals based on price position
    relative to the cloud boundaries.

    Entry Conditions:
        - Long: Price > Senkou Span A and Price > Senkou Span B (price is above
          the cloud, indicating bullish trend)

    Exit Conditions:
        - Price < Senkou Span A and Price < Senkou Span B (price breaks below
          both cloud boundaries, indicating trend reversal)

    Attributes:
        ichimoku: The Ichimoku indicator instance providing cloud calculations.
        order: Reference to the current pending order, or None if no order is
            pending.
        bar_num: Counter tracking the total number of bars processed.
        buy_count: Counter tracking the number of executed buy orders.
        sell_count: Counter tracking the number of executed sell orders.

    Parameters:
        stake: Number of shares/units per trade (default: 10).
        tenkan: Tenkan-sen (Conversion Line) period in bars (default: 9).
        kijun: Kijun-sen (Base Line) period in bars (default: 26).
        senkou: Senkou Span B period in bars (default: 52).
        senkou_lead: Forward displacement for cloud in bars (default: 26).
        chikou: Chikou Span (Lagging Line) displacement in bars (default: 26).
    """
    params = dict(
        stake=10,
        tenkan=9,
        kijun=26,
        senkou=52,
        senkou_lead=26,
        chikou=26,
    )

    def __init__(self):
        """Initialize the Ichimoku Cloud strategy.

        Sets up the Ichimoku indicator with configurable parameters and
        initializes tracking variables for order management and statistics.
        """
        self.ichimoku = bt.indicators.Ichimoku(
            self.data,
            tenkan=self.p.tenkan,
            kijun=self.p.kijun,
            senkou=self.p.senkou,
            senkou_lead=self.p.senkou_lead,
            chikou=self.p.chikou,
        )

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track trade execution statistics.

        This method is called by the backtrader engine when an order's status
        changes. It updates the buy/sell counters when orders are completed
        and resets the order reference when the order is no longer active.

        Args:
            order: The backtrader Order object with updated status information.
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

        This method is called by the backtrader engine for each new bar.
        It implements the core strategy logic:
        1. Checks for pending orders and returns if one exists
        2. Retrieves current price and Ichimoku cloud values
        3. Enters long position when price is above cloud
        4. Exits position when price breaks below cloud

        Trading Logic:
            - No position: Enter long if close > senkou_a AND close > senkou_b
            - Has position: Close position if close < senkou_a AND close < senkou_b
        """
        self.bar_num += 1

        if self.order:
            return

        close = self.data.close[0]
        senkou_a = self.ichimoku.senkou_span_a[0]
        senkou_b = self.ichimoku.senkou_span_b[0]

        if not self.position:
            # Price is above cloud (relaxed condition)
            if close > senkou_a and close > senkou_b:
                self.order = self.buy(size=self.p.stake)
        else:
            # Price breaks below both cloud boundaries
            if close < senkou_a and close < senkou_b:
                self.order = self.close()


def test_ichimoku_cloud_strategy():
    """Test the Ichimoku Cloud strategy implementation.

    This function sets up a complete backtesting environment with historical
    Oracle Corporation stock data, runs the Ichimoku Cloud strategy, and
    validates the results against expected performance metrics.

    The test:
    1. Loads historical price data for Oracle (2010-2014)
    2. Configures the backtest with initial capital and commission
    3. Adds performance analyzers (Sharpe Ratio, Returns, Drawdown)
    4. Runs the backtest and collects results
    5. Validates metrics against expected values with tight tolerances

    Test Data:
        - Symbol: Oracle Corporation (ORCL)
        - Period: 2010-01-01 to 2014-12-31
        - Initial Capital: $100,000
        - Commission: 0.1% per trade

    Expected Results:
        - Bars processed: 1180
        - Final portfolio value: $100,088.51
        - Sharpe Ratio: 0.9063632909371556
        - Annual return: 0.00017737921024728437
        - Maximum drawdown: 10.32%

    Raises:
        AssertionError: If any performance metric deviates from expected values
            beyond the specified tolerance. Final value tolerance is 0.01,
            other metrics use 1e-6 tolerance.
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
    cerebro.addstrategy(IchimokuCloudStrategy)
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
    print("Ichimoku Cloud strategy backtest results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1180, f"Expected bar_num=1180, got {strat.bar_num}"
    assert abs(final_value - 100088.51) < 0.01, f"Expected final_value=100088.51, got {final_value}"
    assert abs(sharpe_ratio - (0.9063632909371556)) < 1e-6, f"Expected sharpe_ratio=0.9063632909371556, got {sharpe_ratio}"
    assert abs(annual_return - (0.00017737921024728437)) < 1e-6, f"Expected annual_return=0.00017737921024728437, got {annual_return}"
    assert abs(max_drawdown - 0.10317697620290582) < 1e-6, f"Expected max_drawdown=0.10317697620290582, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Ichimoku Cloud strategy test")
    print("=" * 60)
    test_ichimoku_cloud_strategy()
