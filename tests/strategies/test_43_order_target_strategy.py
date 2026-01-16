#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for Order Target strategy.

This module tests the order_target_percent functionality for position management.
The strategy dynamically adjusts position size based on the day of the month.

Reference: backtrader-master2/samples/order_target/order_target.py
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


class OrderTargetStrategy(bt.Strategy):
    """Order target strategy using dynamic position sizing.

    This strategy adjusts the target position percentage based on the day of month.
    In odd months: target = day/100 (e.g., 15th = 15%)
    In even months: target = (31-day)/100 (e.g., 15th = 16%)

    Attributes:
        order: Current pending order.
        bar_num: Number of bars processed.
        buy_count: Total buy orders executed.
        sell_count: Total sell orders executed.
        win_count: Number of profitable trades.
        loss_count: Number of losing trades.
        sum_profit: Total profit/loss from all closed trades.

    Args:
        use_target_percent: Whether to use order_target_percent (default: True).
    """
    params = (
        ('use_target_percent', True),
    )

    def __init__(self):
        """Initialize strategy state variables."""
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object with updated status.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        if not order.alive():
            self.order = None

    def notify_trade(self, trade):
        """Handle trade completion and track statistics.

        Args:
            trade: The completed trade object.
        """
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute trading logic for each bar.

        Calculates target position based on day of month and submits
        order_target_percent to adjust position.
        """
        self.bar_num += 1

        if self.order:
            return

        # Calculate target size based on day of month
        dt = self.data.datetime.date()
        size = dt.day
        if (dt.month % 2) == 0:
            # Even months: inverse relationship (later day = smaller position)
            size = 31 - size

        percent = size / 100.0
        self.order = self.order_target_percent(target=percent)

    def stop(self):
        """Print final statistics when backtesting ends."""
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
              f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
              f"wins={self.win_count}, losses={self.loss_count}, "
              f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}")


def test_order_target_strategy():
    """Test the Order Target strategy backtest.

    This test runs a backtest on Yahoo stock data (2005-2006) and validates
    that the strategy produces expected performance metrics.

    Raises:
        AssertionError: If any performance metric deviates from expected values.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1000000.0)

    print("Loading data...")
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    data = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="YHOO")

    cerebro.addstrategy(OrderTargetStrategy)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Running backtest...")
    results = cerebro.run()
    strat = results[0]

    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Order Target Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 503, f"Expected bar_num=503, got {strat.bar_num}"
    assert abs(final_value - 935260.98) < 0.01, f"Expected final_value=935260.98, got {final_value}"
    assert abs(sharpe_ratio - (-0.7774908309117542)) < 1e-6, f"Expected sharpe_ratio=-0.7774908309117542, got {sharpe_ratio}"
    assert abs(annual_return - (-0.03297541833201616)) < 1e-6, f"Expected annual_return=-0.03297541833201616, got {annual_return}"
    assert abs(max_drawdown - 9.591524052078132) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Order Target Strategy Test")
    print("=" * 60)
    test_order_target_strategy()
