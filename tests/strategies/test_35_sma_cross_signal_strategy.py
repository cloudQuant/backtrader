#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: SMA Cross Signal moving average crossover strategy.

Reference: backtrader-master2/samples/sigsmacross/sigsmacross.py
Uses SignalStrategy to generate trading signals based on SMA crossover.
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


class SmaCrossSignalStrategy(bt.Strategy):
    """SMA crossover signal strategy.

    Generates a buy signal when the short-term moving average crosses above
    the long-term moving average. Generates a sell signal when the short-term
    moving average crosses below the long-term moving average.
    """
    params = dict(
        sma1=10,
        sma2=20,
    )

    def __init__(self):
        sma1 = bt.ind.SMA(period=self.params.sma1)
        sma2 = bt.ind.SMA(period=self.params.sma2)
        self.crossover = bt.ind.CrossOver(sma1, sma2)

        self.order = None
        # Statistical variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        if not order.alive():
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

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

    def stop(self):
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(
            f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
            f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, "
            f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}"
        )


def test_sma_cross_signal_strategy():
    """Test the SMA Cross Signal moving average crossover strategy.

    This test sets up a backtesting environment with the SmaCrossSignalStrategy,
    runs the backtest on historical data, and verifies the results match expected
    values for various performance metrics.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="DATA")

    cerebro.addstrategy(SmaCrossSignalStrategy, sma1=10, sma2=20)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("SMA Cross Signal moving average crossover strategy backtest results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  win_count: {strat.win_count}")
    print(f"  loss_count: {strat.loss_count}")
    print(f"  sum_profit: {strat.sum_profit:.2f}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 492, f"Expected bar_num=492, got {strat.bar_num}"
    assert strat.buy_count == 14, f"Expected buy_count=14, got {strat.buy_count}"
    assert strat.sell_count == 13, f"Expected sell_count=13, got {strat.sell_count}"
    assert strat.win_count == 6, f"Expected win_count=6, got {strat.win_count}"
    assert strat.loss_count == 7, f"Expected loss_count=7, got {strat.loss_count}"
    assert total_trades == 14, f"Expected total_trades=14, got {total_trades}"
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert abs(final_value - 105288.6) < 0.01, f"Expected final_value=105288.60, got {final_value}"
    assert abs(sharpe_ratio - (1.6727759789938865)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.02568929107574943)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 3.1366613257893725) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("SMA Cross Signal moving average crossover strategy test")
    print("=" * 60)
    test_sma_cross_signal_strategy()
