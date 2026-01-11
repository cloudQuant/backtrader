#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Triple Cross Moving Average Crossover Strategy.

Reference: https://github.com/backtrader/backhacker
Trend strategy based on the alignment of three moving averages.
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

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.
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


class TripleCrossStrategy(bt.Strategy):
    """Triple Moving Average Crossover Strategy.

    This strategy implements a trend-following approach using three simple
    moving averages (SMA) with different periods.

    Trading Logic:
        - Buy when short-term MA > medium-term MA > long-term MA (bullish alignment)
        - Sell when short-term MA < medium-term MA < long-term MA (bearish alignment)

    Attributes:
        dataclose: Close price data series.
        ma1: Short-term simple moving average.
        ma2: Medium-term simple moving average.
        ma3: Long-term simple moving average.
        order: Current pending order.
        last_operation: Last executed operation ("BUY" or "SELL").
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
    """
    params = dict(
        stake=10,
        ma1_period=5,
        ma2_period=8,
        ma3_period=13,
    )

    def __init__(self):
        """Initialize the TripleCrossStrategy.

        Sets up the three simple moving averages and initializes tracking
        variables for orders and statistics.
        """
        self.dataclose = self.datas[0].close
        self.ma1 = bt.ind.SMA(self.datas[0], period=self.p.ma1_period)
        self.ma2 = bt.ind.SMA(self.datas[0], period=self.p.ma2_period)
        self.ma3 = bt.ind.SMA(self.datas[0], period=self.p.ma3_period)

        self.order = None
        self.last_operation = "SELL"

        # Statistics variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Updates buy/sell counts and tracks the last executed operation when
        orders are completed.

        Args:
            order: The order object with status information.
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
        """Execute trading logic for each bar.

        Implements the triple moving average crossover strategy:
        - Buy when MA1 > MA2 > MA3 (bullish alignment)
        - Sell when MA1 < MA2 < MA3 (bearish alignment)

        Only one order can be active at a time, and the strategy avoids
        duplicate trades in the same direction.
        """
        self.bar_num += 1

        if self.order:
            return

        # Buy condition: MA1 > MA2 > MA3 (bullish alignment)
        if self.last_operation != "BUY":
            if self.ma1[0] > self.ma2[0] > self.ma3[0]:
                self.order = self.buy(size=self.p.stake)

        # Sell condition: MA1 < MA2 < MA3 (bearish alignment)
        if self.last_operation != "SELL":
            if self.ma1[0] < self.ma2[0] < self.ma3[0]:
                self.order = self.sell(size=self.p.stake)

    def stop(self):
        """Called when the strategy execution is complete.

        This method is invoked after all data has been processed.
        Currently performs no action but can be extended for cleanup
        or final reporting.
        """
        pass


def test_triple_cross_strategy():
    """Test the triple moving average crossover strategy.

    This test performs the following operations:
        1. Loads historical Oracle stock data from 2010-2014
        2. Runs the TripleCrossStrategy with default parameters (5/8/13 MA periods)
        3. Validates performance metrics against expected values

    The test validates:
        - Number of bars processed: 1245
        - Final portfolio value: ~100063.63
        - Sharpe ratio: ~0.361
        - Annual return: ~0.00013
        - Maximum drawdown: ~0.109

    Raises:
        AssertionError: If any of the performance metrics don't match
            expected values within tolerance (0.01 for final_value, 1e-6 for others).
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
    cerebro.addstrategy(TripleCrossStrategy)
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
    print("Triple Cross Moving Average Crossover Strategy Backtest Results:")
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
    assert strat.bar_num == 1245, f"Expected bar_num=1245, got {strat.bar_num}"
    assert abs(final_value - 100063.63) < 0.01, f"Expected final_value=100063.63, got {final_value}"
    assert abs(sharpe_ratio - (0.3608428642726115)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.00012752914318585638)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.10941659904491363) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Triple Cross Moving Average Crossover Strategy Test")
    print("=" * 60)
    test_triple_cross_strategy()
