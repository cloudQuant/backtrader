#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Parabolic SAR (Stop and Reverse) indicator strategy.

Reference: strategies_backtrader/SAR (STOP AND REVERSE) METHOD.ipynb
Uses the SAR indicator to determine trend reversals.
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


class ParabolicSarStrategy(bt.Strategy):
    """Parabolic SAR (Stop and Reverse) indicator strategy.

    Entry conditions:
        - Long: Price crosses above SAR

    Exit conditions:
        - Price crosses below SAR

    Attributes:
        sar: Parabolic SAR indicator instance.
        crossover: CrossOver indicator detecting price/SAR crossovers.
        order: Current pending order.
        bar_num: Number of bars processed.
        buy_count: Total number of buy orders executed.
        sell_count: Total number of sell orders executed.
    """
    params = dict(
        stake=10,
        af=0.02,
        afmax=0.2,
    )

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables."""
        self.sar = bt.indicators.ParabolicSAR(
            self.data, af=self.p.af, afmax=self.p.afmax
        )
        self.crossover = bt.indicators.CrossOver(self.data.close, self.sar)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track executed orders.

        Args:
            order: The order object with status information.
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
        """Execute trading logic on each bar.

        Implements the Parabolic SAR strategy:
        - Enter long when price crosses above SAR
        - Exit position when price crosses below SAR
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Price crosses above SAR - entry signal
            if self.crossover[0] > 0:
                self.order = self.buy(size=self.p.stake)
        else:
            # Price crosses below SAR - exit signal
            if self.crossover[0] < 0:
                self.order = self.close()


def test_parabolic_sar_strategy():
    """Test the Parabolic SAR strategy implementation.

    This test:
    1. Loads historical price data for Oracle (2010-2014)
    2. Runs the ParabolicSarStrategy with default parameters
    3. Validates performance metrics against expected values

    Raises:
        AssertionError: If any metric does not match expected values.
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
    cerebro.addstrategy(ParabolicSarStrategy)
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
    print("Parabolic SAR Strategy Backtest Results:")
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
    assert strat.bar_num == 1255, f"Expected bar_num=1255, got {strat.bar_num}"
    assert abs(final_value - 100044.47) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (0.15768877971108886)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (8.914473921766317e-05)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.1446509264396303) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Parabolic SAR Strategy Test")
    print("=" * 60)
    test_parabolic_sar_strategy()
