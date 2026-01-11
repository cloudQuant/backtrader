#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: RSI MTF (Multiple Time Frame) Strategy.

Reference: backtrader-strategies-compendium/strategies/RsiMtf.py
Uses a combination of long and short period RSI to determine entry timing.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
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


class RsiMtfStrategy(bt.Strategy):
    """RSI MTF (Multiple Time Frame) Strategy.

    This strategy uses a combination of long and short period RSI indicators
    to generate trading signals.

    Entry conditions:
        - Long: Long period RSI > 50 AND Short period RSI > 70

    Exit conditions:
        - Short period RSI < 35

    Attributes:
        rsi_long (bt.indicators.RSI): Long period RSI indicator.
        rsi_short (bt.indicators.RSI): Short period RSI indicator.
        order (bt.Order): Current pending order.
        bar_num (int): Number of bars processed.
        buy_count (int): Number of buy orders executed.
        sell_count (int): Number of sell orders executed.
    """
    params = dict(
        stake=10,
        period_long=14,
        period_short=3,
        buy_rsi_long=50,
        buy_rsi_short=70,
        sell_rsi_short=35,
    )

    def __init__(self):
        self.rsi_long = bt.indicators.RSI(self.data, period=self.p.period_long)
        self.rsi_short = bt.indicators.RSI(self.data, period=self.p.period_short)
        
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status notifications.

        Args:
            order (bt.Order): The order object with status updates.
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

        Implements the RSI MTF strategy:
        - Entry when long period RSI is strong and short period RSI is strong
        - Exit when short period RSI declines
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Long period RSI strong AND Short period RSI strong
            if self.rsi_long[0] > self.p.buy_rsi_long and self.rsi_short[0] > self.p.buy_rsi_short:
                self.order = self.buy(size=self.p.stake)
        else:
            # Short period RSI declines
            if self.rsi_short[0] < self.p.sell_rsi_short:
                self.order = self.close()


def test_rsi_mtf_strategy():
    """Test the RSI MTF strategy implementation.

    This test:
        1. Loads historical Oracle stock data
        2. Runs the RSI MTF strategy with specified parameters
        3. Collects performance metrics (Sharpe ratio, returns, drawdown)
        4. Validates results against expected values

    Raises:
        AssertionError: If any performance metric does not match expected values.
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
    cerebro.addstrategy(RsiMtfStrategy)
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
    print("RSI MTF (Multiple Time Frame) Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assertions - Using precise assertions
    # final_value tolerance: 0.01, other indicators tolerance: 1e-6
    assert strat.bar_num == 1243, f"Expected bar_num=1243, got {strat.bar_num}"
    assert abs(final_value - 99944.33) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (-0.2930928685297336)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00011163604936501658)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.14506963091824412) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("RSI MTF (Multiple Time Frame) Strategy Test")
    print("=" * 60)
    test_rsi_mtf_strategy()
