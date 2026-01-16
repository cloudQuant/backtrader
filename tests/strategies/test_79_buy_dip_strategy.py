#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for Buy Dip strategy.

This module tests a simple mean reversion strategy that buys after two
consecutive down candles and holds for a fixed number of bars.

Reference: https://github.com/Backtesting/strategies
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching common locations.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any search path.
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


class BuyDipStrategy(bt.Strategy):
    """Buy Dip strategy for catching short-term pullbacks.

    This is a simple mean reversion strategy that buys after two consecutive
    down candles (indicating a short-term dip) and holds for a fixed period.

    Trading Rules:
        - Buy when close[0] < close[-1] and close[-1] < close[-2] (two down candles)
        - Sell after holding for hold_bars periods (default: 5 bars)

    Attributes:
        dataclose: Close price data series.
        order: Current pending order.
        bar_executed: The bar number when the current position was entered.
        bar_num: Number of bars processed.
        buy_count: Total buy orders executed.
        sell_count: Total sell orders executed.

    Args:
        stake: Number of shares per trade (default: 10).
        hold_bars: Number of bars to hold position before selling (default: 5).
    """
    params = dict(
        stake=10,
        hold_bars=5,
    )

    def __init__(self):
        """Initialize strategy state variables."""
        self.dataclose = self.datas[0].close
        self.order = None
        self.bar_executed = 0

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object with updated status.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.bar_executed = len(self)
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        """Execute trading logic for each bar.

        Implements a dip-buying strategy with fixed holding period.
        """
        self.bar_num += 1
        if self.order:
            return

        if not self.position:
            # Entry: Buy after two consecutive down candles
            if self.dataclose[0] < self.dataclose[-1]:
                if self.dataclose[-1] < self.dataclose[-2]:
                    self.order = self.buy(size=self.p.stake)
        else:
            # Exit: Sell after holding for N bars
            if len(self) >= (self.bar_executed + self.p.hold_bars):
                self.order = self.sell(size=self.p.stake)


def test_buy_dip_strategy():
    """Test the Buy Dip strategy backtest.

    This test runs a backtest on Oracle stock data (2010-2014) and validates
    that the strategy produces expected performance metrics.

    Raises:
        AssertionError: If any performance metric deviates from expected values.
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
    cerebro.addstrategy(BuyDipStrategy)
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
    print("Buy Dip Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1257, f"Expected bar_num=1257, got {strat.bar_num}"
    assert abs(final_value - 100087.43) < 0.01, f"Expected final_value=100087.43, got {final_value}"
    assert abs(sharpe_ratio - (1.030465261762291)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.00017522539339535496)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.08379818319219477) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Buy Dip Strategy Test")
    print("=" * 60)
    test_buy_dip_strategy()
