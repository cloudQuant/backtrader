#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for Ultimate Oscillator strategy.

This module tests a trading strategy based on the Ultimate Oscillator (UO)
technical indicator, which integrates three different time periods to reduce
false signals and provide more reliable overbought/oversold readings.

Example:
    To run the test::

        python test_109_ultimate_oscillator_strategy.py

The test uses historical Oracle Corporation (ORCL) stock data from 2010-2014.
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


class UltimateOscillatorStrategy(bt.Strategy):
    """Ultimate Oscillator momentum trading strategy.

    This strategy uses the Ultimate Oscillator (UO) indicator to identify
    overbought and oversold conditions. UO combines three time periods
    (7, 14, and 28 periods) to reduce false signals and provide more
    reliable trading signals.

    Entry Conditions:
        - Long: UO < 30 (oversold condition)

    Exit Conditions:
        - UO > 70 (overbought condition)

    Attributes:
        uo: Ultimate Oscillator indicator instance.
        order: Current pending order.
        bar_num: Counter for processed bars.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
    """
    params = dict(
        stake=10,
        p1=7,
        p2=14,
        p3=28,
        oversold=30,
        overbought=70,
    )

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables."""
        self.uo = bt.indicators.UltimateOscillator(
            self.data, p1=self.p.p1, p2=self.p.p2, p3=self.p.p3
        )

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track completed trades.

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

        Implements the core strategy logic:
        1. Track bar progression
        2. Check for pending orders
        3. Generate entry/exit signals based on UO thresholds
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Entry: UO in oversold territory
            if self.uo[0] < self.p.oversold:
                self.order = self.buy(size=self.p.stake)
        else:
            # Exit: UO in overbought territory
            if self.uo[0] > self.p.overbought:
                self.order = self.close()


def test_ultimate_oscillator_strategy():
    """Test Ultimate Oscillator strategy with historical data.

    Sets up a backtest with ORCL data from 2010-2014, runs the strategy,
    and validates performance metrics against expected values.

    Raises:
        AssertionError: If any performance metric does not match expected value.
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
    cerebro.addstrategy(UltimateOscillatorStrategy)
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
    print("Ultimate Oscillator Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Validate results against expected values
    # Tolerance: 0.01 for final_value, 1e-6 for other metrics
    assert strat.bar_num == 1229, f"Expected bar_num=1229, got {strat.bar_num}"
    assert abs(final_value - 100199.75) < 0.01, f"Expected final_value=100199.75, got {final_value}"
    assert abs(sharpe_ratio - (2.2256344725800337)) < 1e-6, f"Expected sharpe_ratio=2.2256344725800337, got {sharpe_ratio}"
    assert abs(annual_return - (0.0004001266459915534)) < 1e-6, f"Expected annual_return=0.0004001266459915534, got {annual_return}"
    assert abs(max_drawdown - 0.06371267726839967) < 1e-6, f"Expected max_drawdown=0.06371267726839967, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Ultimate Oscillator Strategy Test")
    print("=" * 60)
    test_ultimate_oscillator_strategy()
