#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Chandelier Exit 吊灯止损策略

参考来源: backtrader-strategies-compendium/strategies/MA_Chandelier.py
使用吊灯止损指标结合均线交叉
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


class ChandelierExitIndicator(bt.Indicator):
    """Chandelier Exit 吊灯止损指标"""
    lines = ('long', 'short')
    params = dict(period=22, multip=3)
    plotinfo = dict(subplot=False)

    def __init__(self):
        highest = bt.ind.Highest(self.data.high, period=self.p.period)
        lowest = bt.ind.Lowest(self.data.low, period=self.p.period)
        atr = self.p.multip * bt.ind.ATR(self.data, period=self.p.period)
        self.lines.long = highest - atr
        self.lines.short = lowest + atr


class ChandelierExitStrategy(bt.Strategy):
    """Chandelier Exit 吊灯止损策略
    
    入场条件:
    - 多头: SMA8 > SMA15 且 价格 > Chandelier Short
    
    出场条件:
    - SMA8 < SMA15 且 价格 < Chandelier Long
    """
    params = dict(
        stake=10,
        sma_fast=8,
        sma_slow=15,
        ce_period=22,
        ce_mult=3,
    )

    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data, period=self.p.sma_fast)
        self.sma_slow = bt.indicators.SMA(self.data, period=self.p.sma_slow)
        self.ce = ChandelierExitIndicator(
            self.data, period=self.p.ce_period, multip=self.p.ce_mult
        )
        
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
            # SMA金叉 且 价格在Chandelier Short之上
            if self.sma_fast[0] > self.sma_slow[0] and self.data.close[0] > self.ce.short[0]:
                self.order = self.buy(size=self.p.stake)
        else:
            # SMA死叉 且 价格在Chandelier Long之下
            if self.sma_fast[0] < self.sma_slow[0] and self.data.close[0] < self.ce.long[0]:
                self.order = self.close()


def test_chandelier_exit_strategy():
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
    cerebro.addstrategy(ChandelierExitStrategy)
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
    print("Chandelier Exit 吊灯止损策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # 断言 - 使用精确断言
    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1235, f"Expected bar_num=1235, got {strat.bar_num}"
    assert abs(final_value - 100018.36) < 0.01, f"Expected final_value=100018.36, got {final_value}"
    assert abs(sharpe_ratio - (0.1430114511805932)) < 1e-6, f"Expected sharpe_ratio=0.1430114511805932, got {sharpe_ratio}"
    assert abs(annual_return - (3.681229236697967e-05)) < 1e-6, f"Expected annual_return=3.681229236697967e-05, got {annual_return}"
    assert abs(max_drawdown - 0.08411419340257008) < 1e-6, f"Expected max_drawdown=0.08411419340257008, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Chandelier Exit 吊灯止损策略测试")
    print("=" * 60)
    test_chandelier_exit_strategy()
