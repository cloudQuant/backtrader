#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Price Channel strategy.

Uses price channel breakout to determine trend.
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


class PriceChannelStrategy(bt.Strategy):
    """Price Channel strategy.

    Entry conditions:
    - Long: Price creates N-day high

    Exit conditions:
    - Price falls below N-day low
    """
    params = dict(
        stake=10,
        entry_period=20,
        exit_period=10,
    )

    def __init__(self):
        self.highest_entry = bt.indicators.Highest(self.data.high, period=self.p.entry_period)
        self.lowest_exit = bt.indicators.Lowest(self.data.low, period=self.p.exit_period)
        
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
            # Price creates new high
            if self.data.high[0] >= self.highest_entry[-1]:
                self.order = self.buy(size=self.p.stake)
        else:
            # Price creates new low
            if self.data.low[0] <= self.lowest_exit[-1]:
                self.order = self.close()


def test_price_channel_strategy():
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
    cerebro.addstrategy(PriceChannelStrategy)
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
    print("Price Channel strategy backtest results:")
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
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 100050.36) < 0.01, f"Expected final_value=100050.36, got {final_value}"
    assert abs(sharpe_ratio - (0.5592202866492985)) < 1e-6, f"Expected sharpe_ratio=0.5592202866492985, got {sharpe_ratio}"
    assert abs(annual_return - (0.00010094130513364865)) < 1e-6, f"Expected annual_return=0.00010094130513364865, got {annual_return}"
    assert abs(max_drawdown - 0.06631886254244598) < 1e-6, f"Expected max_drawdown=0.06631886254244598, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Price Channel strategy test")
    print("=" * 60)
    test_price_channel_strategy()
