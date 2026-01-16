#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case: MACD Gradient MACD Momentum Strategy.

Reference source: https://github.com/backtrader/backhacker
Momentum strategy based on consecutive MACD rise/fall.
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


class MACDGradientStrategy(bt.Strategy):
    """MACD Gradient (Momentum) Strategy.

    This strategy uses MACD momentum to generate trading signals:
    - Buy when MACD shows three consecutive periods of upward momentum
    - Sell when MACD shows three consecutive periods of downward momentum

    Entry conditions:
        - MACD[0] > MACD[-1] > MACD[-2] (consecutive rising)

    Exit conditions:
        - MACD[0] < MACD[-1] < MACD[-2] (consecutive falling)
    """
    params = dict(
        stake=10,
        period_me1=12,
        period_me2=26,
    )

    def __init__(self):
        """Initialize strategy indicators and state variables."""
        self.dataclose = self.datas[0].close
        self.macd = bt.ind.MACD(self.data.close, period_me1=self.p.period_me1, period_me2=self.p.period_me2)

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

        # Buy when MACD shows consecutive upward momentum
        if self.last_operation != "BUY":
            if self.macd.macd[0] > self.macd.macd[-1] > self.macd.macd[-2]:
                self.order = self.buy(size=self.p.stake)

        # Sell when MACD shows consecutive downward momentum
        if self.last_operation != "SELL":
            if self.macd.macd[0] < self.macd.macd[-1] < self.macd.macd[-2]:
                self.order = self.sell(size=self.p.stake)


def test_macd_gradient_strategy():
    """Test the MACD Gradient strategy.

    This test validates that the MACD momentum strategy correctly identifies
    consecutive rising/falling patterns and produces expected backtest results.

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
    cerebro.addstrategy(MACDGradientStrategy)
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
    print("MACD Gradient Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Tolerance: final_value 0.01, other metrics 1e-6
    assert strat.bar_num == 1224, f"Expected bar_num=1224, got {strat.bar_num}"
    assert abs(final_value - 99975.9) < 0.01, f"Expected final_value=99975.90, got {final_value}"
    assert abs(sharpe_ratio - (-0.13853775963605322)) < 1e-6, f"Expected sharpe_ratio=-0.13853775963605322, got {sharpe_ratio}"
    assert abs(annual_return - (-4.8324864374536716e-05)) < 1e-9, f"Expected annual_return=-4.8324864374536716e-05, got {annual_return}"
    assert abs(max_drawdown - 0.13844628396097686) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("MACD Gradient Strategy Test")
    print("=" * 60)
    test_macd_gradient_strategy()
