#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case for Data Resample data resampling.

Reference source: backtrader-master2/samples/data-resample/data-resample.py
Tests data resampling functionality using a simple dual moving average crossover strategy.
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


class SimpleMAStrategy(bt.Strategy):
    """Simple dual moving average crossover strategy for testing data resampling.

    Strategy logic:
    - Buy when the fast line crosses above the slow line
    - Sell and close position when the fast line crosses below the slow line
    """
    params = (('fast_period', 5), ('slow_period', 15))

    def __init__(self):
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if not order.alive():
            self.order = None
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def next(self):
        self.bar_num += 1
        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def test_data_resample():
    """Test Data Resample data resampling."""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))

    # Resample to weekly timeframe
    cerebro.resampledata(
        data,
        timeframe=bt.TimeFrame.Weeks,
        compression=1
    )

    # Add simple dual moving average crossover strategy
    cerebro.addstrategy(SimpleMAStrategy, fast_period=5, slow_period=15)

    # Add complete analyzers - calculate Sharpe ratio using weekly timeframe
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Weeks, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results in standard format
    print("\n" + "=" * 50)
    print("Data Resample backtest results (weekly timeframe):")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert test results
    assert strat.bar_num == 89, f"Expected bar_num=89, got {strat.bar_num}"
    assert abs(final_value - 100765.01) < 0.01, f"Expected final_value=100765.01, got {final_value}"
    assert abs(sharpe_ratio - 1.0787422654055023) < 1e-6, f"Expected sharpe_ratio=1.0787422654055023, got {sharpe_ratio}"
    assert abs(annual_return - 0.003817762345337259) < 1e-6, f"Expected annual_return=0.003817762345337259, got {annual_return}"
    assert abs(max_drawdown - 0.3038892199564355) < 1e-6, f"Expected max_drawdown=0.3038892199564355, got {max_drawdown}"
    assert total_trades == 3, f"Expected total_trades=3, got {total_trades}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Data Resample data resampling test")
    print("=" * 60)
    test_data_resample()
