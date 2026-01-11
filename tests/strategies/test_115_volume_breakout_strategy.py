#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case for Volume Breakout Strategy.

Reference: backtrader_NUPL_strategy/hope/Hope_vol.py
Uses volume breakout combined with MACD and RSI for entry signals.
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


class VolumeBreakoutStrategy(bt.Strategy):
    """Volume Breakout Strategy.

    Entry conditions:
        - Long: Volume > N-day average volume * multiplier

    Exit conditions:
        - RSI > 70

    Attributes:
        vol_ma: Simple moving average of volume.
        rsi: Relative Strength Index indicator.
        order: Current pending order.
        bar_num: Total number of bars processed.
        bar_executed: Bar number when last order was executed.
        buy_count: Total number of buy orders executed.
        sell_count: Total number of sell orders executed.
    """
    params = dict(
        stake=10,
        vol_period=20,
        vol_mult=1.05,
        rsi_period=14,
        rsi_exit=70,
    )

    def __init__(self):
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=self.p.vol_period)
        self.rsi = bt.indicators.RSI(self.data, period=self.p.rsi_period)
        
        self.order = None
        self.bar_num = 0
        self.bar_executed = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order notification updates.

        Args:
            order: The order object with status updates.
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
        """Execute trading logic for each bar."""
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Volume breakout (simplified condition)
            if self.data.volume[0] > self.vol_ma[0] * self.p.vol_mult:
                self.order = self.buy(size=self.p.stake)
        else:
            # RSI overbought or holding for more than 5 days
            if self.rsi[0] > self.p.rsi_exit or len(self) > self.bar_executed + 5:
                self.order = self.close()


def test_volume_breakout_strategy():
    """Test the Volume Breakout strategy with historical data.

    This test:
        1. Loads Oracle stock data from 2010-2014
        2. Runs the VolumeBreakoutStrategy backtest
        3. Validates performance metrics against expected values

    Raises:
        AssertionError: If any metric deviates from expected values.
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
    cerebro.addstrategy(VolumeBreakoutStrategy)
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
    print("Volume Breakout Strategy Backtest Results:")
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
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 99987.80) < 0.01, f"Expected final_value=99987.80, got {final_value}"
    assert abs(sharpe_ratio - (-0.1545232366102227)) < 1e-6, f"Expected sharpe_ratio=-0.1545232366102227, got {sharpe_ratio}"
    assert abs(annual_return - (-2.4463477104822622e-05)) < 1e-6, f"Expected annual_return=-2.4463477104822622e-05, got {annual_return}"
    assert abs(max_drawdown - 0.05240649826015478) < 1e-6, f"Expected max_drawdown=0.05240649826015478, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Volume Breakout Strategy Test")
    print("=" * 60)
    test_volume_breakout_strategy()
