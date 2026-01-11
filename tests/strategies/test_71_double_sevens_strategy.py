#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case: Double Sevens Strategy.

Reference: https://github.com/backtrader/backhacker
Larry Connor's Double 7's strategy.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on the script's directory.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the located data file.

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


class DoubleSevensStrategy(bt.Strategy):
    """Double Sevens Strategy.

    Larry Connor's strategy:
    1. Price is above the 200-day or 70-day moving average
    2. Buy when price makes a new N-day low
    3. Sell when price makes a new N-day high
    """
    params = dict(
        stake=10,
        period=7,  # N-day high/low period
        sma_short=70,
        sma_long=200,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.sma200 = bt.ind.SMA(self.datas[0], period=self.p.sma_long)
        self.sma = bt.ind.SMA(self.datas[0], period=self.p.sma_short)
        self.high_bar = bt.ind.Highest(self.datas[0].close, period=self.p.period)
        self.low_bar = bt.ind.Lowest(self.datas[0].close, period=self.p.period)
        
        self.order = None
        self.last_operation = "SELL"

        # Statistics variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
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
        self.bar_num += 1

        if self.order:
            return

        # Buy condition: Price above moving average + new N-day low
        if self.last_operation != "BUY":
            above_ma = self.dataclose[0] > self.sma200[0] or self.dataclose[0] > self.sma[0]
            at_low = self.dataclose[0] <= self.low_bar[0]
            if above_ma and at_low:
                self.order = self.buy(size=self.p.stake)

        # Sell condition: new N-day high
        if self.last_operation != "SELL":
            if self.dataclose[0] >= self.high_bar[0]:
                self.order = self.sell(size=self.p.stake)

    def stop(self):
        pass


def test_double_sevens_strategy():
    """Test the Double Sevens strategy.

    This test:
    1. Loads historical price data for Oracle (ORCL) from 2005-2014
    2. Runs the Double Sevens trading strategy with default parameters
    3. Validates strategy performance metrics including Sharpe ratio,
       annual returns, maximum drawdown, and final portfolio value
    """
    cerebro = bt.Cerebro()

    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(DoubleSevensStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Double Sevens Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 2317, f"Expected bar_num=2317, got {strat.bar_num}"
    assert abs(final_value - 100090.36) < 0.01, f"Expected final_value=100090.36, got {final_value}"
    assert abs(sharpe_ratio - (0.19450685966492476)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (9.047151710597933e-05)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.1424209289556953) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Double Sevens Strategy Test")
    print("=" * 60)
    test_double_sevens_strategy()
