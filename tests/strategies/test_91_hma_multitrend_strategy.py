#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: HMA MultiTrend 多周期Hull均线趋势策略

参考来源: Backtrader1.0/strategies/hma_multitrend.py
使用4条不同周期的Hull均线判断趋势方向
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


class HmaMultiTrendStrategy(bt.Strategy):
    """HMA MultiTrend 多周期Hull均线趋势策略
    
    入场条件:
    - 多头: fast > mid1 > mid2 > mid3 (所有HMA递增排列)
    - 空头: fast < mid1 < mid2 < mid3 (所有HMA递减排列)
    
    出场条件:
    - 反向趋势信号
    """
    params = dict(
        stake=10,
        fast=10,
        mid1=20,
        mid2=30,
        mid3=50,
        atr_period=14,
        adx_period=14,
        adx_threshold=0.0,  # 禁用ADX过滤
    )

    def __init__(self):
        self.hma_fast = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.fast
        )
        self.hma_mid1 = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.mid1
        )
        self.hma_mid2 = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.mid2
        )
        self.hma_mid3 = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.mid3
        )
        
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.adx = bt.indicators.ADX(self.data, period=self.p.adx_period)
        
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
        
        # ADX过滤
        if self.adx[0] < self.p.adx_threshold:
            return
        
        # 趋势条件
        long_cond = (self.hma_fast[0] > self.hma_mid1[0] > 
                     self.hma_mid2[0] > self.hma_mid3[0])
        short_cond = (self.hma_fast[0] < self.hma_mid1[0] < 
                      self.hma_mid2[0] < self.hma_mid3[0])
        
        if not self.position:
            if long_cond:
                self.order = self.buy(size=self.p.stake)
            elif short_cond:
                self.order = self.sell(size=self.p.stake)
        else:
            # 反向信号平仓
            if self.position.size > 0 and short_cond:
                self.order = self.close()
            elif self.position.size < 0 and long_cond:
                self.order = self.close()


def test_hma_multitrend_strategy():
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
    cerebro.addstrategy(HmaMultiTrendStrategy)
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
    print("HMA MultiTrend 多周期Hull均线趋势策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num > 0
    assert 90000 < final_value < 200000, f"final_value={final_value} out of range"
    assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"sharpe_ratio={sharpe_ratio} out of range"
    assert -1 < annual_return < 1, f"annual_return={annual_return} out of range"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("HMA MultiTrend 多周期Hull均线趋势策略测试")
    print("=" * 60)
    test_hma_multitrend_strategy()
