#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case: Supertrend RSI strategy.

This test implements a strategy that combines SuperTrend and RSI indicators
to determine entry and exit points.

Reference:
    backtrader-strategies-compendium/strategies/SupertrendRSI.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the full path to a data file by searching common locations.

    Args:
        filename: Name of the data file to locate

    Returns:
        Path: Absolute path to the data file

    Raises:
        FileNotFoundError: If the data file cannot be found in any search path
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


class SupertrendIndicator(bt.Indicator):
    """SuperTrend indicator.

    The SuperTrend indicator is a trend-following indicator that uses
    Average True Range (ATR) to determine the direction of the trend.
    It provides dynamic support and resistance levels based on price volatility.
    """
    lines = ('supertrend', 'final_up', 'final_down')
    params = dict(atr_period=14, atr_multiplier=3)
    plotinfo = dict(subplot=False)

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.avg = (self.data.high + self.data.low) / 2
        self.basic_up = self.avg - self.p.atr_multiplier * self.atr
        self.basic_down = self.avg + self.p.atr_multiplier * self.atr

    def prenext(self):
        self.l.final_up[0] = 0
        self.l.final_down[0] = 0
        self.l.supertrend[0] = 0

    def next(self):
        if self.data.close[-1] > self.l.final_up[-1]:
            self.l.final_up[0] = max(self.basic_up[0], self.l.final_up[-1])
        else:
            self.l.final_up[0] = self.basic_up[0]

        if self.data.close[-1] < self.l.final_down[-1]:
            self.l.final_down[0] = min(self.basic_down[0], self.l.final_down[-1])
        else:
            self.l.final_down[0] = self.basic_down[0]

        if self.data.close[0] > self.l.final_down[-1]:
            self.l.supertrend[0] = self.l.final_up[0]
        elif self.data.close[0] < self.l.final_up[-1]:
            self.l.supertrend[0] = self.l.final_down[0]
        else:
            self.l.supertrend[0] = self.l.supertrend[-1]


class SupertrendRsiStrategy(bt.Strategy):
    """Supertrend RSI strategy.

    This strategy combines SuperTrend and RSI indicators to generate
    long-only trading signals.

    Entry conditions:
        - Long: Price > SuperTrend AND RSI > threshold (default 40)

    Exit conditions:
        - Price < SuperTrend

    Attributes:
        supertrend: SuperTrend indicator instance
        rsi: RSI indicator instance
        order: Current pending order
        bar_num: Number of bars processed
        buy_count: Number of buy orders executed
        sell_count: Number of sell orders executed

    Args:
        stake: Number of shares/contracts per trade (default: 10)
        atr_period: ATR period for SuperTrend calculation (default: 14)
        atr_mult: ATR multiplier for SuperTrend calculation (default: 2)
        rsi_period: RSI calculation period (default: 14)
        rsi_threshold: RSI threshold for entry signal (default: 40)
    """
    params = dict(
        stake=10,
        atr_period=14,
        atr_mult=2,
        rsi_period=14,
        rsi_threshold=40,
    )

    def __init__(self):
        self.supertrend = SupertrendIndicator(
            self.data, atr_period=self.p.atr_period, atr_multiplier=self.p.atr_mult
        )
        self.rsi = bt.indicators.RSI(self.data, period=self.p.rsi_period)
        
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object with updated status
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

        Implements the strategy logic:
        - Enter long when price > SuperTrend AND RSI > threshold
        - Exit when price < SuperTrend
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Price > SuperTrend AND RSI is strong
            if self.data.close[0] > self.supertrend.supertrend[0] and self.rsi[0] > self.p.rsi_threshold:
                self.order = self.buy(size=self.p.stake)
        else:
            # Price < SuperTrend
            if self.data.close[0] < self.supertrend.supertrend[0]:
                self.order = self.close()


def test_supertrend_rsi_strategy():
    """Test the Supertrend RSI strategy.

    This function:
    1. Sets up a Cerebro backtesting engine
    2. Loads Oracle historical data (2010-2014)
    3. Runs the Supertrend RSI strategy
    4. Analyzes performance metrics (Sharpe ratio, returns, drawdown)
    5. Asserts that results match expected values

    Raises:
        AssertionError: If any performance metric does not match expected value
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
    cerebro.addstrategy(SupertrendRsiStrategy)
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
    print("Supertrend RSI Strategy Backtest Results:")
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
    assert abs(final_value - 100085.04) < 0.01, f"Expected final_value=100085.04, got {final_value}"
    assert abs(sharpe_ratio - (0.8987542282805036)) < 1e-6, f"Expected sharpe_ratio=0.8987542282805036, got {sharpe_ratio}"
    assert abs(annual_return - (0.0001704277101155587)) < 1e-6, f"Expected annual_return=0.0001704277101155587, got {annual_return}"
    assert abs(max_drawdown - 0.07723036627142686) < 1e-6, f"Expected max_drawdown=0.07723036627142686, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Supertrend RSI Strategy Test")
    print("=" * 60)
    test_supertrend_rsi_strategy()
