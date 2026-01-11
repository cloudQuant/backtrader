#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Renko EMA Crossover Strategy

Reference: Backtrader1.0/strategies/renko_ema_crossover.py
Uses EMA crossover filtered by Renko chart as entry signal.
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


class RenkoEmaStrategy(bt.Strategy):
    """Renko EMA Crossover Strategy.

    Uses Renko filter to smooth price data, then applies EMA crossover.

    Entry conditions:
        - Long: Fast EMA crosses above slow EMA

    Exit conditions:
        - Fast EMA crosses below slow EMA

    Attributes:
        stake (int): Number of shares/shares per trade. Default is 10.
        fast_period (int): Period for fast EMA. Default is 10.
        slow_period (int): Period for slow EMA. Default is 20.
        renko_brick_size (float): Brick size for Renko filter. Default is 1.0.
    """
    params = dict(
        stake=10,
        fast_period=10,
        slow_period=20,
        renko_brick_size=1.0,
    )

    def __init__(self):
        # Add Renko filter
        self.data.addfilter(bt.filters.Renko, size=self.p.renko_brick_size)

        # EMA indicators
        self.fast_ema = bt.indicators.EMA(self.data, period=self.p.fast_period)
        self.slow_ema = bt.indicators.EMA(self.data, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ema, self.slow_ema)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        self.bar_num += 1
        
        if self.order:
            return
        
        if not self.position:
            if self.crossover[0] > 0:
                self.order = self.buy(size=self.p.stake)
        elif self.crossover[0] < 0:
            self.order = self.close()


def test_renko_ema_strategy():
    """Test the Renko EMA crossover strategy.

    This function sets up a backtest with the RenkoEmaStrategy using
    historical Oracle data from 2010-2014. It validates the strategy
    performance against expected values including bar count, Sharpe ratio,
    annual return, and maximum drawdown.

    Raises:
        AssertionError: If any of the performance metrics do not match
            expected values within tolerance.
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
    cerebro.addstrategy(RenkoEmaStrategy)
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
    print("Renko EMA Crossover Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1237, f"Expected bar_num=1237, got {strat.bar_num}"
    assert abs(final_value - 100057.43) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (0.3225444080736762)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.00011511425744876694)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.09539954392338255) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Renko EMA Crossover Strategy Test")
    print("=" * 60)
    test_renko_ema_strategy()
