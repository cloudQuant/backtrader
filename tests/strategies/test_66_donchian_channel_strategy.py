#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Donchian Channel Strategy

Reference: https://github.com/backtrader/backhacker
Classic Donchian Channel breakout strategy
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
    """Locate data file based on the script directory.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the located data file.

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


class DonchianChannelIndicator(bt.Indicator):
    """Donchian Channel indicator.

    The Donchian Channel is a trend-following indicator that calculates
    the highest high and lowest low over a specified period.

    Attributes:
        dch: Donchian Channel High (upper band) - highest high over period.
        dcl: Donchian Channel Low (lower band) - lowest low over period.
        dcm: Donchian Channel Middle (middle band) - average of upper and lower.

    Parameters:
        period: Number of bars to use for calculating the channel (default: 20).
    """
    lines = ('dch', 'dcl', 'dcm')
    params = dict(period=20)

    def __init__(self):
        """Initialize the Donchian Channel indicator.

        Sets up the three channel lines using the Highest and Lowest indicators:
        - Upper channel (dch): Highest high over the period
        - Lower channel (dcl): Lowest low over the period
        - Middle channel (dcm): Average of upper and lower channels
        """
        self.lines.dch = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.lines.dcl = bt.indicators.Lowest(self.data.low, period=self.p.period)
        self.lines.dcm = (self.lines.dch + self.lines.dcl) / 2


class DonchianChannelStrategy(bt.Strategy):
    """Donchian Channel breakout strategy.

    This strategy implements a classic trend-following approach using the
    Donchian Channel indicator:

    - Go long when price breaks above the upper channel
    - Go short when price breaks below the lower channel

    Attributes:
        dataclose: Reference to the close price data.
        indicator: Donchian Channel indicator instance.
        order: Current pending order.
        last_operation: Last executed operation ("BUY" or "SELL").
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.

    Parameters:
        stake: Number of shares/contracts per trade (default: 10).
        period: Lookback period for Donchian Channel calculation (default: 20).
    """
    params = dict(
        stake=10,
        period=20,
    )

    def __init__(self):
        """Initialize the Donchian Channel strategy.

        Sets up the indicator, data references, and tracking variables for
        orders and statistics.
        """
        self.dataclose = self.datas[0].close
        self.indicator = DonchianChannelIndicator(self.datas[0], period=self.p.period)

        self.order = None
        self.last_operation = "SELL"

        # Statistics variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Called by the backtrader engine when an order's status changes.
        Updates buy/sell counters and tracks the last operation when orders
        are completed. Clears the pending order reference when done.

        Args:
            order: The order object with updated status.
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

        This method is called by the backtrader engine for each new bar.
        Implements the Donchian Channel breakout strategy:
        - Buy when close price breaks above the upper channel
        - Sell when close price breaks below the lower channel
        - Only allows one position at a time (no reverse orders)
        """
        self.bar_num += 1

        if self.order:
            return

        if self.dataclose[0] > self.indicator.dch[0] and self.last_operation != "BUY":
            self.order = self.buy(size=self.p.stake)
        elif self.dataclose[0] < self.indicator.dcl[0] and self.last_operation != "SELL":
            self.order = self.sell(size=self.p.stake)

    def stop(self):
        """Called when the backtest is finished.

        This method is called by the backtrader engine after all data
        has been processed. Can be used for cleanup or final reporting.
        """
        pass


def test_donchian_channel_strategy():
    """Test the Donchian Channel strategy.

    This test function runs a backtest of the Donchian Channel strategy
    on Oracle stock data from 2010-2014 and verifies the results match
    expected values.

    The test validates:
    - Number of bars processed
    - Final portfolio value
    - Sharpe ratio
    - Annual return
    - Maximum drawdown
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
    cerebro.addstrategy(DonchianChannelStrategy)
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
    print("Donchian Channel Strategy Backtest Results:")
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
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 100000.0) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    # No trades executed, sharpe_ratio is None
    assert sharpe_ratio is None or sharpe_ratio == 0, f"Expected sharpe_ratio=None/0, got {sharpe_ratio}"
    assert abs(annual_return - (0.0)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.0) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Donchian Channel Strategy Test")
    print("=" * 60)
    test_donchian_channel_strategy()
