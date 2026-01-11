#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Sizer position manager test.

Reference: backtrader-master2/samples/sizertest/sizertest.py
Tests different Sizer implementations.
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


class LongOnlySizer(bt.Sizer):
    """Sizer that only allows long position sizing.

    This sizer enforces long-only trading by:
    1. Returning the configured stake for buy orders
    2. Only allowing sells up to the current position size
    3. Preventing short selling
    """

    params = (('stake', 1),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        """Calculate the position size for an order.

        Args:
            comminfo: Commission info object.
            cash: Available cash.
            data: Data feed.
            isbuy: True if this is a buy order, False for sell.

        Returns:
            int: The number of units/shares to trade.
        """
        if isbuy:
            return self.p.stake
        position = self.broker.getposition(data)
        if not position.size:
            return 0
        return self.p.stake


class SizerTestStrategy(bt.Strategy):
    """Strategy for testing Sizer functionality.

    This strategy uses a simple SMA crossover to generate buy/sell signals
    and tracks the number of trades executed to verify sizer behavior.
    """

    params = (('period', 15),)

    def __init__(self):
        """Initialize the SizerTestStrategy with indicators and tracking variables.

        Sets up a Simple Moving Average (SMA) indicator and a crossover indicator
        to generate buy/sell signals. Also initializes counters to track the
        number of bars processed and trades executed.
        """
        # Create SMA indicator with the configured period
        sma = bt.ind.SMA(self.data, period=self.p.period)
        # CrossOver indicator: >0 when price crosses above SMA, <0 when below
        self.crossover = bt.ind.CrossOver(self.data, sma)
        # Initialize tracking variables for strategy execution
        self.bar_num = 0  # Count of bars processed
        self.buy_count = 0  # Count of completed buy orders
        self.sell_count = 0  # Count of completed sell orders

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object that was updated.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def next(self):
        """Execute trading logic for each bar."""
        self.bar_num += 1
        if self.crossover > 0:
            self.buy()
        elif self.crossover < 0:
            self.sell()

    def stop(self):
        """Print strategy statistics after backtest completion."""
        print(f"SizerTest: bar_num={self.bar_num}, buy={self.buy_count}, sell={self.sell_count}")


def test_sizer():
    """Test Sizer position manager.

    This test validates that the LongOnlySizer correctly controls position
    sizes during trading and produces expected backtest results.

    Raises:
        AssertionError: If any of the expected values do not match the
            actual results within the specified tolerance.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(50000.0)

    print("Loading data...")
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    data = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(SizerTestStrategy, period=15)
    cerebro.addsizer(LongOnlySizer, stake=100)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Sizer Position Manager Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Tolerance: final_value 0.01, other metrics 1e-6
    assert strat.bar_num == 488, f"Expected bar_num=488, got {strat.bar_num}"
    assert abs(final_value - 49499.0) < 0.01, f"Expected final_value=49499.00, got {final_value}"
    assert abs(sharpe_ratio - (-3.032200553947264)) < 1e-6, f"Expected sharpe_ratio=-3.032200553947264, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00503257346891984)) < 1e-6, f"Expected annual_return=-0.00503257346891984, got {annual_return}"
    assert abs(max_drawdown - 2.009631963850407) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Sizer Position Manager Test")
    print("=" * 60)
    test_sizer()
