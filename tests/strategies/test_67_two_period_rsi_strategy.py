#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Two Period RSI Strategy

Reference: https://github.com/backtrader/backhacker
Larry Connor's 2-Period RSI Strategy
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


class TwoPeriodRSIStrategy(bt.Strategy):
    """Two Period RSI Strategy.

    Larry Connor's strategy:
    1. Price is above the 200-day moving average
    2. Buy when 2-period RSI is below 5
    3. Sell when price crosses above the 5-day moving average

    Attributes:
        dataclose: Reference to the close price data.
        rsi: 2-period RSI indicator.
        sma5: 5-period Simple Moving Average.
        sma200: 200-period Simple Moving Average.
        order: Current pending order.
        last_operation: Last operation type ("BUY" or "SELL").
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
    """
    params = dict(
        stake=10,
        rsi_period=2,
        sma_short=5,
        sma_long=200,
        rsi_buy_threshold=5,
    )

    def __init__(self):
        """Initialize the Two Period RSI strategy.

        Sets up the indicators and tracking variables for the strategy.
        Initializes the RSI indicator, short and long SMAs, and order tracking.
        """
        self.dataclose = self.datas[0].close
        self.rsi = bt.indicators.RSI_Safe(self.datas[0], period=self.p.rsi_period)
        self.sma5 = bt.ind.SMA(self.datas[0], period=self.p.sma_short)
        self.sma200 = bt.ind.SMA(self.datas[0], period=self.p.sma_long)

        self.order = None
        self.last_operation = "SELL"

        # Statistical variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Updates the buy/sell counters and tracks the last operation when
        orders are completed. Resets the order reference when the order
        is no longer active.

        Args:
            order: The order object containing status and execution information.
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

        Implements Larry Connor's 2-Period RSI strategy:
        1. Buy when price is above the 200-day MA and 2-period RSI is below 5
        2. Sell when price crosses above the 5-day MA

        Only one order can be active at a time. The strategy tracks the
        last operation to prevent duplicate entries.
        """
        self.bar_num += 1

        if self.order:
            return

        # Buy condition: Price above 200-day MA and RSI below 5
        if self.last_operation != "BUY":
            if self.dataclose[0] > self.sma200[0] and self.rsi[0] < self.p.rsi_buy_threshold:
                self.order = self.buy(size=self.p.stake)

        # Sell condition: Price crosses above 5-day MA
        if self.last_operation != "SELL":
            if self.dataclose[0] > self.sma5[0]:
                self.order = self.sell(size=self.p.stake)

    def stop(self):
        """Called when the backtesting is finished.

        This method is called after the cerebro run has completed.
        Can be used for cleanup, final calculations, or logging results.
        """
        pass


def test_two_period_rsi_strategy():
    """Test the Two Period RSI strategy.

    This test function:
    1. Loads Oracle stock data from 2000-2014
    2. Runs the Two Period RSI strategy with default parameters
    3. Analyzes performance using Sharpe Ratio, Returns, DrawDown, and TradeAnalyzer
    4. Asserts that the results match expected values

    Raises:
        AssertionError: If any of the test assertions fail (bar count,
            final value, Sharpe ratio, annual return, or max drawdown).
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
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(TwoPeriodRSIStrategy)
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
    print("Two Period RSI Strategy Backtest Results:")
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
    assert strat.bar_num == 3573, f"Expected bar_num=3573, got {strat.bar_num}"
    assert abs(final_value - 100061.23) < 0.01, f"Expected final_value=100061.23, got {final_value}"
    assert abs(sharpe_ratio - (0.5519798674941566)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (4.0897296253360675e-05)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.02139426944243814) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Two Period RSI Strategy Test")
    print("=" * 60)
    test_two_period_rsi_strategy()
