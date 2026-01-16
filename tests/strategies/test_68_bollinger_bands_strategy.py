#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for Bollinger Bands mean reversion strategy.

This module implements and tests a mean reversion trading strategy based on
Bollinger Bands technical indicator. The strategy buys when price rises back
above the middle band after breaking below the lower band, and sells when price
falls back below the middle band after breaking above the upper band.

Reference: https://github.com/backtrader/backhacker

Example:
    To run the test::

        python -m pytest tests/strategies/test_68_bollinger_bands_strategy.py -v

    Or run directly::

        python tests/strategies/test_68_bollinger_bands_strategy.py
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


class BollingerBandsStrategy(bt.Strategy):
    """Bollinger Bands mean reversion strategy.

    This strategy implements a mean reversion approach using Bollinger Bands
    technical indicator. The strategy identifies overbought and oversold
    conditions and executes trades when price reverts to the mean.

    Trading Logic:
        - Marks a buy signal when price breaks below the lower band (oversold)
        - Executes buy when price rises back above the middle band
        - Marks a sell signal when price breaks above the upper band (overbought)
        - Executes sell when price falls back below the middle band

    Attributes:
        dataclose: LineSeries object providing access to close prices.
        bband: Bollinger Bands indicator with top, mid, and bottom lines.
        redline (bool): Flag indicating price broke below lower band.
        blueline (bool): Flag indicating price broke above upper band.
        order: Reference to the current pending order.
        last_operation (str): Last executed operation, either "BUY" or "SELL".
        bar_num (int): Counter for the number of bars processed.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.

    Args:
        stake (int): Number of shares/units per trade. Default is 10.
        bbands_period (int): Period for Bollinger Bands calculation. Default is 20.
        devfactor (float): Standard deviation multiplier for band width. Default is 2.0.
    """
    params = dict(
        stake=10,
        bbands_period=20,
        devfactor=2.0,
    )

    def __init__(self):
        """Initialize the Bollinger Bands strategy.

        Sets up the Bollinger Bands indicator, initializes state variables for
        tracking signals and orders, and prepares counters for trade statistics.
        """
        self.dataclose = self.datas[0].close
        self.bband = bt.indicators.BBands(
            self.datas[0],
            period=self.p.bbands_period,
            devfactor=self.p.devfactor
        )

        self.redline = False  # Price has broken below lower band
        self.blueline = False  # Price has broken above upper band

        self.order = None
        self.last_operation = "SELL"

        # Statistical variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Called when an order status changes. Tracks completed orders and updates
        the last operation and trade counters accordingly.

        Args:
            order: The order object with updated status information.
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

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Called when a trade is closed. This method can be extended to track
        trade P&L or other trade-level metrics.

        Args:
            trade: The trade object containing trade details.
        """
        pass

    def next(self):
        """Execute the strategy logic for each bar.

        This method is called for each bar of data. It implements the mean
        reversion logic by monitoring price relative to Bollinger Bands and
        executing trades when appropriate signals are generated.

        The strategy follows these rules:
            1. If price breaks below lower band, set buy signal flag
            2. If price breaks above upper band, set sell signal flag
            3. If price rises above middle band after buy signal, execute buy
            4. If price breaks above upper band, buy immediately (momentum)
            5. If price falls below middle band after sell signal, execute sell
        """
        self.bar_num += 1

        if self.order:
            return

        # Price breaks below lower band, mark buy signal
        if self.dataclose[0] < self.bband.l.bot[0] and self.last_operation != "BUY":
            self.redline = True

        # Price breaks above upper band, mark sell signal
        if self.dataclose[0] > self.bband.l.top[0] and self.last_operation != "SELL":
            self.blueline = True

        # Price rises back above middle band, execute buy
        if self.dataclose[0] > self.bband.l.mid[0] and self.last_operation != "BUY" and self.redline:
            self.order = self.buy(size=self.p.stake)
            self.redline = False

        # Price breaks above upper band, buy immediately
        if self.dataclose[0] > self.bband.l.top[0] and self.last_operation != "BUY":
            self.order = self.buy(size=self.p.stake)

        # Price falls back below middle band, execute sell
        if self.dataclose[0] < self.bband.l.mid[0] and self.last_operation != "SELL" and self.blueline:
            self.blueline = False
            self.redline = False
            self.order = self.sell(size=self.p.stake)

    def stop(self):
        """Called when the strategy execution is complete.

        This method can be used to perform cleanup or print final statistics.
        Currently a placeholder for future extensions.
        """
        pass


def test_bollinger_bands_strategy():
    """Test the Bollinger Bands mean reversion strategy.

    This function sets up and executes a backtest of the Bollinger Bands
    mean reversion strategy using historical Oracle stock data from 2010-2014.
    It validates the strategy performance against expected metrics including
    Sharpe ratio, annual returns, maximum drawdown, and final portfolio value.

    The test configuration:
        - Initial capital: $100,000
        - Commission: 0.1% per trade
        - Data period: 2010-01-01 to 2014-12-31
        - Bollinger Bands period: 20
        - Standard deviation factor: 2.0

    Expected Results:
        - Bars processed: 1238
        - Final portfolio value: $100,275.98
        - Sharpe ratio: ~1.25
        - Annual return: ~0.055%
        - Maximum drawdown: ~8.52%

    Raises:
        AssertionError: If any of the performance metrics do not match expected
            values within specified tolerance (0.01 for final_value, 1e-6 for others).
        FileNotFoundError: If the required data file 'orcl-1995-2014.txt' cannot
            be located.
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
    cerebro.addstrategy(BollingerBandsStrategy)
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
    print("Bollinger Bands Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Validate results with specified tolerances
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 100275.98) < 0.01, (
        f"Expected final_value=100275.98, got {final_value}"
    )
    assert abs(sharpe_ratio - 1.2477776453402647) < 1e-6, (
        f"Expected sharpe_ratio=1.2477776453402647, got {sharpe_ratio}"
    )
    assert abs(annual_return - 0.0005526698863482884) < 1e-6, (
        f"Expected annual_return=0.0005526698863482884, got {annual_return}"
    )
    assert abs(max_drawdown - 0.08517200936602952) < 1e-6, (
        f"Expected max_drawdown=0.08517200936602952, got {max_drawdown}"
    )

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Bollinger Bands Strategy Test")
    print("=" * 60)
    test_bollinger_bands_strategy()
