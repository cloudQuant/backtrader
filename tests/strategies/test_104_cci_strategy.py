#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for Commodity Channel Index (CCI) strategy.

This module tests a trading strategy based on the CCI technical indicator,
which identifies cyclical trends in commodity prices and generates trading
signals based on overbought and oversold conditions.

Example:
    To run the test::

        python test_104_cci_strategy.py

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


class CciStrategy(bt.Strategy):
    """Commodity Channel Index (CCI) momentum trading strategy.

    This strategy uses the CCI indicator to identify overbought and oversold
    conditions for generating trading signals.

    Entry Conditions:
        - Long: CCI crosses above -100 from below (rising from oversold)

    Exit Conditions:
        - CCI crosses below +100 from above (falling from overbought)

    Attributes:
        cci: CCI indicator instance.
        order: Current pending order.
        bar_num: Counter for processed bars.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
    """
    params = dict(
        stake=10,
        period=20,
        oversold=-100,
        overbought=100,
    )

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables."""
        self.cci = bt.indicators.CommodityChannelIndex(self.data, period=self.p.period)

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
        3. Ensure minimum data availability
        4. Generate entry/exit signals based on CCI
        """
        self.bar_num += 1

        if self.order:
            return

        if len(self) < 2:
            return

        if not self.position:
            # Entry: CCI crossing above oversold threshold
            if self.cci[-1] < self.p.oversold and self.cci[0] >= self.p.oversold:
                self.order = self.buy(size=self.p.stake)
        else:
            # Exit: CCI crossing below overbought threshold
            if self.cci[-1] > self.p.overbought and self.cci[0] <= self.p.overbought:
                self.order = self.close()


def test_cci_strategy():
    """Test CCI strategy with historical data.

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
    cerebro.addstrategy(CciStrategy)
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
    print("CCI Strategy Backtest Results:")
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
    assert strat.bar_num == 1219, f"Expected bar_num=1219, got {strat.bar_num}"
    assert abs(final_value - 100196.64) < 0.01, f"Expected final_value=100196.64, got {final_value}"
    assert abs(sharpe_ratio - (1.1360835891105705)) < 1e-6, f"Expected sharpe_ratio=1.1360835891105705, got {sharpe_ratio}"
    assert abs(annual_return - (0.0003939069673859038)) < 1e-6, f"Expected annual_return=0.0003939069673859038, got {annual_return}"
    assert abs(max_drawdown - 0.06384165324254176) < 1e-6, f"Expected max_drawdown=0.06384165324254176, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("CCI Strategy Test")
    print("=" * 60)
    test_cci_strategy()
