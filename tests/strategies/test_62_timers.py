#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Timers

Reference source: backtrader-master2/samples/timers/scheduled.py
Tests strategy timer functionality using a dual moving average crossover strategy
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


class TimerStrategy(bt.Strategy):
    """Timer strategy - Dual moving average crossover.

    Strategy logic:
        - Buy when the fast line crosses above the slow line
        - Sell and close position when the fast line crosses below the slow line
        - Simultaneously test timer functionality
    """
    params = dict(
        when=bt.timer.SESSION_START,
        timer=True,
        fast_period=10,
        slow_period=30,
    )

    def __init__(self):
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)

        if self.p.timer:
            self.add_timer(when=self.p.when)

        self.bar_num = 0
        self.timer_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.order = None

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

    def notify_timer(self, timer, when, *args, **kwargs):
        self.timer_count += 1


def test_timers():
    """Test Timers functionality."""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        timeframe=bt.TimeFrame.Days,
        compression=1,
        sessionstart=datetime.time(9, 0),
        sessionend=datetime.time(17, 30),
    )
    cerebro.adddata(data)

    cerebro.addstrategy(TimerStrategy, timer=True, fast_period=10, slow_period=30)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # Add complete analyzers - calculate Sharpe ratio using daily timeframe
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe = strat.analyzers.sharpe.get_analysis()
    ret = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    sharpe_ratio = sharpe.get('sharperatio', None)
    annual_return = ret.get('rnorm', 0)
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    total_trades = trades.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results in standard format
    print("\n" + "=" * 50)
    print("Timers Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  timer_count: {strat.timer_count}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert test results
    assert strat.bar_num == 482, f"Expected bar_num=482, got {strat.bar_num}"
    assert strat.timer_count == 512, f"Expected timer_count=512, got {strat.timer_count}"
    assert abs(final_value - 104966.80) < 0.01, f"Expected final_value=104966.80, got {final_value}"
    assert abs(sharpe_ratio - 0.7210685207398165) < 1e-6, f"Expected sharpe_ratio=0.7210685207398165, got {sharpe_ratio}"
    assert abs(annual_return - 0.024145144571516192) < 1e-6, f"Expected annual_return=0.024145144571516192, got {annual_return}"
    assert abs(max_drawdown - 3.430658473286522) < 1e-6, f"Expected max_drawdown=3.430658473286522, got {max_drawdown}"
    assert total_trades == 9, f"Expected total_trades=9, got {total_trades}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Timers Test")
    print("=" * 60)
    test_timers()
