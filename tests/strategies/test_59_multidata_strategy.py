#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for MultiData Strategy.

This module tests the multi-data source functionality where a strategy
can use signals from one data source to trade on another.

Reference: backtrader-master2/samples/multidata-strategy/multidata-strategy.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching in common locations.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Absolute path to the data file.

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


class MultiDataStrategy(bt.Strategy):
    """Multi-data strategy using signals from data1 to trade on data0.

    This strategy demonstrates how to use signals generated from one data
    source (data1) to execute trades on another data source (data0).
    This is useful for pairs trading or using one indicator as a signal
    for trading another asset.

    Attributes:
        params: Dictionary containing strategy parameters.
            period (int): SMA period for signal generation (default: 15).
            stake (int): Number of shares/contracts per trade (default: 10).
    """

    params = dict(period=15, stake=10)

    def __init__(self):
        """Initialize the MultiData strategy with indicators and counters.

        Sets up the technical indicators and tracking variables needed for
        the multi-data strategy. The strategy uses data1 to generate signals
        and trades on data0.

        Indicator Setup:
            - SMA (Simple Moving Average): Calculated on data1 close prices
            - CrossOver: Detects when price crosses above/below SMA
            - signal > 0: Bullish crossover (price crosses above SMA)
            - signal < 0: Bearish crossover (price crosses below SMA)
        """
        self.orderid = None  # Track active order to prevent duplicate orders
        # Create SMA and crossover signal on the second data source
        # data1 serves as the signal generator for trading data0
        sma = bt.ind.SMA(self.data1, period=self.p.period)
        # CrossOver produces: +1 on bullish cross, -1 on bearish cross, 0 otherwise
        self.signal = bt.ind.CrossOver(self.data1.close, sma)
        # Initialize counters for tracking execution statistics
        self.bar_num = 0  # Total bars processed during backtest
        self.buy_count = 0  # Number of buy orders completed
        self.sell_count = 0  # Number of sell orders completed

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object with status information.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.orderid = None

    def next(self):
        """Execute trading logic for each bar.

        Strategy logic:
        1. Generate signals from data1 (SMA crossover)
        2. Execute trades on data0 based on those signals
        3. Buy on bullish crossover, sell on bearish crossover
        """
        self.bar_num += 1
        # Skip if order already pending
        if self.orderid:
            return

        if not self.position:
            # Open long position on bullish crossover
            if self.signal > 0.0:
                self.buy(size=self.p.stake)
        else:
            # Close position on bearish crossover
            if self.signal < 0.0:
                self.sell(size=self.p.stake)

    def stop(self):
        """Print strategy performance summary after backtest completion."""
        print(f"MultiData: bar_num={self.bar_num}, buy={self.buy_count}, sell={self.sell_count}")
        print(f"  Starting Value: {self.broker.startingcash:.2f}")
        print(f"  Ending Value: {self.broker.getvalue():.2f}")


def test_multidata_strategy():
    """Test the MultiData strategy backtest execution.

    This test verifies that multi-data source functionality works correctly
    by running a backtest with two data sources and asserting the expected
    performance metrics.

    Raises:
        AssertionError: If any performance metric deviates from expected values.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    # Use the same data file twice to simulate multiple data sources
    data_path = resolve_data_path("yhoo-1996-2014.txt")

    data0 = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data0, name='Data0')

    data1 = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data1, name='Data1')

    cerebro.addstrategy(MultiDataStrategy, period=15, stake=10)
    cerebro.broker.setcommission(commission=0.005)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    print("Running backtest...")
    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("MultiData Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Tolerance: 0.01 for final_value, 1e-6 for other metrics
    assert strat.bar_num == 488, f"Expected bar_num=488, got {strat.bar_num}"
    assert abs(final_value - 99847.01) < 0.01, f"Expected final_value=99847.01, got {final_value}"
    assert abs(sharpe_ratio - (-56.94920781443037)) < 1e-6, f"Expected sharpe_ratio=-56.94920781443037, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0007667861342752088)) < 1e-6, f"Expected annual_return=-0.0007667861342752088, got {annual_return}"
    assert abs(max_drawdown - 0.1646592612119436) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("MultiData Strategy Test")
    print("=" * 60)
    test_multidata_strategy()
