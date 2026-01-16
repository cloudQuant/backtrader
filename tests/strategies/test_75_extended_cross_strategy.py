#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Extended Cross strategy.

Reference: https://github.com/backtrader/backhacker
Moving average crossover strategy using ATR expansion.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching common directories.

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


class ExtendedCrossStrategy(bt.Strategy):
    """Extended cross strategy.

    This strategy implements an ATR-expanded moving average crossover:
    - Buy when fast EMA crosses above (slow EMA + ATR) and price is above long-term EMA
    - Sell when fast EMA crosses below (slow EMA - ATR) and price is below long-term EMA
    """
    params = dict(
        stake=10,
        ma1=5,
        ma2=20,
        ma3=50,
        atr_mult=1,
    )

    def __init__(self):
        """Initialize strategy indicators and state variables."""
        self.dataclose = self.datas[0].close
        self.ma1 = bt.ind.EMA(self.datas[0], period=self.p.ma1)
        self.ma2 = bt.ind.EMA(self.datas[0], period=self.p.ma2)
        self.ma3 = bt.ind.EMA(self.datas[0], period=self.p.ma3)
        self.atr = bt.ind.ATR(self.datas[0])

        self.order = None
        self.last_operation = "SELL"

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object that was updated.
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
        """Execute trading logic for each bar."""
        self.bar_num += 1
        if self.order:
            return

        # Buy: MA1 > (MA2 + ATR) and price > MA3
        if self.last_operation != "BUY":
            if self.ma1[0] > (self.ma2[0] + self.p.atr_mult * self.atr[0]) and self.dataclose[0] > self.ma3[0]:
                self.order = self.buy(size=self.p.stake)

        # Sell: MA1 < (MA2 - ATR) and price < MA3
        if self.last_operation != "SELL":
            if self.ma1[0] < (self.ma2[0] - self.p.atr_mult * self.atr[0]) and self.dataclose[0] < self.ma3[0]:
                self.order = self.sell(size=self.p.stake)


def test_extended_cross_strategy():
    """Test the Extended Cross strategy.

    This test validates that the ATR-expanded moving average crossover
    strategy correctly identifies entry and exit points and produces
    expected backtest results.

    Raises:
        AssertionError: If any of the expected values do not match the
            actual results within the specified tolerance.
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
    cerebro.addstrategy(ExtendedCrossStrategy)
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
    print("Extended Cross strategy backtest results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Tolerance: final_value 0.01, other metrics 1e-6
    assert strat.bar_num == 1208, f"Expected bar_num=1208, got {strat.bar_num}"
    assert abs(final_value - 99898.01) < 0.01, f"Expected final_value=99898.01, got {final_value}"
    assert abs(sharpe_ratio - (-0.8182498376340828)) < 1e-6, f"Expected sharpe_ratio=-0.8182498376340828, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00020455816666682268)) < 1e-6, f"Expected annual_return=-0.00020455816666682268, got {annual_return}"
    assert abs(max_drawdown - 0.1782677934154473) < 1e-6, f"Expected max_drawdown=0.1782677934154473, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Extended Cross Strategy Test")
    print("=" * 60)
    test_extended_cross_strategy()
