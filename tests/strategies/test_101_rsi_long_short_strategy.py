#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: RSI Long/Short Dual RSI Strategy

Reference: backtrader-strategies-compendium/strategies/RsiLongShort.py
Uses a combination of long and short period RSI to determine entry timing
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


class RsiLongShortStrategy(bt.Strategy):
    """RSI Long/Short Dual RSI Strategy.

    Entry conditions:
    - Long: Long period RSI > 50 AND Short period RSI > 65

    Exit conditions:
    - Short period RSI < 45

    Args:
        stake (int): Number of shares/shares per trade. Default is 10.
        period_long (int): Period for long-term RSI calculation. Default is 14.
        period_short (int): Period for short-term RSI calculation. Default is 5.
        buy_rsi_long (float): RSI threshold for long period to trigger buy. Default is 50.
        buy_rsi_short (float): RSI threshold for short period to trigger buy. Default is 65.
        sell_rsi_short (float): RSI threshold for short period to trigger sell. Default is 45.

    Attributes:
        rsi_long: Long period RSI indicator.
        rsi_short: Short period RSI indicator.
        order: Current pending order.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
    """
    params = dict(
        stake=10,
        period_long=14,
        period_short=5,
        buy_rsi_long=50,
        buy_rsi_short=65,
        sell_rsi_short=45,
    )

    def __init__(self):
        self.rsi_long = bt.indicators.RSI(self.data, period=self.p.period_long)
        self.rsi_short = bt.indicators.RSI(self.data, period=self.p.period_short)
        
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
            # Long period RSI strong AND Short period RSI strong
            if self.rsi_long[0] > self.p.buy_rsi_long and self.rsi_short[0] > self.p.buy_rsi_short:
                self.order = self.buy(size=self.p.stake)
        else:
            # Short period RSI falls back
            if self.rsi_short[0] < self.p.sell_rsi_short:
                self.order = self.close()


def test_rsi_long_short_strategy():
    """Test the RSI Long/Short strategy with historical data.

    This test function:
    1. Loads historical Oracle stock data from 2010-2014
    2. Applies the RSI Long/Short strategy
    3. Runs the backtest with analyzers for Sharpe Ratio, Returns, and DrawDown
    4. Prints backtest results
    5. Validates results against expected values

    Raises:
        AssertionError: If any of the backtest metrics don't match expected values.
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
    cerebro.addstrategy(RsiLongShortStrategy)
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
    print("RSI Long/Short Dual RSI Strategy Backtest Results:")
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
    assert strat.bar_num == 1243, f"Expected bar_num=1243, got {strat.bar_num}"
    assert abs(final_value - 100023.95) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (0.12109913246951494)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (4.800683696093361e-05)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.09601330432360433) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("RSI Long/Short Dual RSI Strategy Test")
    print("=" * 60)
    test_rsi_long_short_strategy()
