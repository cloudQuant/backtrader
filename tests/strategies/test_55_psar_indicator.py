#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: PSAR Parabolic SAR indicator.

Reference: backtrader-master2/samples/psar/psar.py
Tests the Parabolic SAR indicator.
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


class PSARStrategy(bt.Strategy):
    """Parabolic SAR (Stop and Reverse) strategy.

    This strategy uses the Parabolic SAR indicator to generate buy/sell
    signals based on price momentum and trend direction.

    Entry conditions:
        - Price crosses above PSAR (go long)

    Exit conditions:
        - Price crosses below PSAR (close position)
    """

    def __init__(self):
        """Initialize strategy indicators and state variables."""
        self.psar = bt.ind.ParabolicSAR()
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

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
        if not order.alive():
            self.order = None

    def next(self):
        """Execute trading logic for each bar."""
        self.bar_num += 1
        if self.order:
            return
        # Buy when price crosses above PSAR, sell when price crosses below PSAR
        if self.data.close[0] > self.psar[0] and not self.position:
            self.order = self.buy()
        elif self.data.close[0] < self.psar[0] and self.position:
            self.order = self.close()

    def stop(self):
        """Print strategy statistics after backtest completion."""
        print(f"PSAR: bar_num={self.bar_num}, buy={self.buy_count}, sell={self.sell_count}")


def test_psar_indicator():
    """Tests the PSAR Parabolic SAR indicator.

    This test loads historical data and runs a backtesting strategy using
    the Parabolic SAR indicator for generating buy/sell signals.

    Raises:
        AssertionError: If any of the expected values do not match the
            actual results within the specified tolerance.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))
    cerebro.adddata(data)

    cerebro.addstrategy(PSARStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)
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
    print("PSAR Parabolic SAR Indicator Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Tolerance: final_value 0.01, other metrics 1e-6
    assert strat.bar_num == 511, f"Expected bar_num=511, got {strat.bar_num}"
    assert abs(final_value - 105435.8) < 0.01, f"Expected final_value=105435.80, got {final_value}"
    assert abs(sharpe_ratio - (2.423395072162198)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.026394826422567123)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 3.0649081759956647) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("PSAR Parabolic SAR Indicator Test")
    print("=" * 60)
    test_psar_indicator()
