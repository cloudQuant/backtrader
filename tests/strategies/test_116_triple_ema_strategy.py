#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Triple EMA (Triple Exponential Moving Average) Strategy.

This strategy uses the alignment of three EMAs to determine trends.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching common directory locations.

    Searches for data files in multiple directories including the current
    file's directory, parent directory, and 'datas' subdirectories.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any
            of the search locations.
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


class TripleEmaStrategy(bt.Strategy):
    """Triple EMA (Triple Exponential Moving Average) Strategy.

    This strategy uses three EMAs with different periods to identify trend
    direction and generate trading signals based on their alignment.

    Entry conditions:
    - Long: EMA5 > EMA10 > EMA20 (bullish alignment)

    Exit conditions:
    - Exit long when EMA5 < EMA10 < EMA20 (bearish alignment)
    """
    params = dict(
        stake=10,
        fast=5,
        mid=10,
        slow=20,
    )

    def __init__(self):
        """Initialize the Triple EMA strategy.

        Sets up the three EMA indicators with different periods and
        initializes tracking variables for order management and statistics.
        """
        self.ema_fast = bt.indicators.EMA(self.data, period=self.p.fast)
        self.ema_mid = bt.indicators.EMA(self.data, period=self.p.mid)
        self.ema_slow = bt.indicators.EMA(self.data, period=self.p.slow)
        
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status notifications.

        Updates buy/sell counters when orders complete and clears the
        pending order reference.

        Args:
            order: The order object with updated status.
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

        Implements the triple EMA trend-following strategy:
        - Enter long when EMA5 > EMA10 > EMA20 (bullish alignment)
        - Exit long when EMA5 < EMA10 < EMA20 (bearish alignment)
        - Only one position at a time (no pyramiding)
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Bullish alignment
            if self.ema_fast[0] > self.ema_mid[0] > self.ema_slow[0]:
                self.order = self.buy(size=self.p.stake)
        else:
            # Bearish alignment
            if self.ema_fast[0] < self.ema_mid[0] < self.ema_slow[0]:
                self.order = self.close()


def test_triple_ema_strategy():
    """Test the Triple EMA strategy implementation.

    Sets up a backtest with Oracle data from 2010-2014, runs the strategy,
    and validates the results against expected values.

    The test validates:
        - bar_num: 1238
        - final_value: ~100065.31
        - sharpe_ratio: ~0.376
        - annual_return: ~0.00013
        - max_drawdown: ~0.095

    Raises:
        AssertionError: If any of the validation checks fail.
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
    cerebro.addstrategy(TripleEmaStrategy)
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
    print("Triple EMA Strategy Backtest Results:")
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
    assert abs(final_value - 100065.31) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (0.3757309556964078)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.00013090572633809417)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.09539203307003034) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Triple EMA Strategy Test")
    print("=" * 60)
    test_triple_ema_strategy()
