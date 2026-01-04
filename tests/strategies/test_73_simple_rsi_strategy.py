#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Simple RSI 简单RSI策略

参考来源: https://github.com/backtrader/backhacker
结合RSI超卖和EMA趋势的策略
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


class SimpleRSIStrategy(bt.Strategy):
    """简单RSI策略
    
    - RSI低于30且快速EMA在慢速EMA上方时买入
    - RSI高于70时卖出
    """
    params = dict(
        stake=10,
        period_ema_fast=10,
        period_ema_slow=100,
        rsi_period=14,
        rsi_oversold=30,
        rsi_overbought=70,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.ema_fast = bt.ind.EMA(period=self.p.period_ema_fast)
        self.ema_slow = bt.ind.EMA(period=self.p.period_ema_slow)
        self.rsi = bt.ind.RSI(period=self.p.rsi_period)
        
        self.order = None
        self.last_operation = "SELL"
        
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

        if self.last_operation != "BUY":
            if self.rsi[0] < self.p.rsi_oversold and self.ema_fast[0] > self.ema_slow[0]:
                self.order = self.buy(size=self.p.stake)

        if self.last_operation != "SELL":
            if self.rsi[0] > self.p.rsi_overbought:
                self.order = self.sell(size=self.p.stake)


def test_simple_rsi_strategy():
    cerebro = bt.Cerebro()
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SimpleRSIStrategy)
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
    print("Simple RSI 策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 2417, f"Expected bar_num=2417, got {strat.bar_num}"
    assert abs(final_value - 100030.04) < 0.01, f"Expected final_value=100030.04, got {final_value}"
    assert abs(sharpe_ratio - (0.494485344395513)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (3.0086055688528766e-05)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.051379600488515455) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Simple RSI 简单RSI策略测试")
    print("=" * 60)
    test_simple_rsi_strategy()
