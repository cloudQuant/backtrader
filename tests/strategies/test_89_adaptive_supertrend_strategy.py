#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Adaptive SuperTrend 自适应超级趋势策略

参考来源: https://github.com/Backtrader1.0/strategies/adaptive_supertrend.py
使用自动调优的SuperTrend指标，乘数根据ATR动态调整
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


class AdaptiveSuperTrendIndicator(bt.Indicator):
    """自适应SuperTrend指标
    
    根据ATR动态调整乘数:
    base_mult = a_coef + b_coef * avg_atr
    dyn_mult = base_mult * (avg_atr / atr)
    """
    lines = ('st',)
    params = dict(
        period=20,
        vol_lookback=20,
        a_coef=0.5,
        b_coef=2.0,
        min_mult=0.5,
        max_mult=3.0,
    )

    def __init__(self):
        # ATR
        self.atr = bt.indicators.ATR(self.data, period=self.p.period)
        
        # 平滑ATR作为基准
        self.avg_atr = bt.indicators.EMA(self.atr, period=self.p.vol_lookback)
        
        # 中间价
        self.hl2 = (self.data.high + self.data.low) / 2.0
        
        self.addminperiod(max(self.p.period, self.p.vol_lookback) + 1)

    def next(self):
        atr_val = float(self.atr[0])
        avg_atr_val = float(self.avg_atr[0])
        
        if atr_val <= 0:
            atr_val = 0.0001
        
        # 计算基础乘数
        base_mult = self.p.a_coef + self.p.b_coef * avg_atr_val
        
        # 限制乘数范围
        base_mult = max(self.p.min_mult, min(self.p.max_mult, base_mult))
        
        # 动态乘数
        dyn_mult = base_mult * (avg_atr_val / atr_val) if atr_val > 0 else base_mult
        dyn_mult = max(self.p.min_mult, min(self.p.max_mult, dyn_mult))
        
        # 计算上下轨
        hl2 = float(self.hl2[0])
        upper = hl2 + dyn_mult * atr_val
        lower = hl2 - dyn_mult * atr_val
        
        # 递归SuperTrend逻辑
        if len(self) == 1:
            self.l.st[0] = lower
        else:
            prev_st = self.l.st[-1]
            if self.data.close[0] > prev_st:
                self.l.st[0] = max(lower, prev_st)
            else:
                self.l.st[0] = min(upper, prev_st)


class AdaptiveSuperTrendStrategy(bt.Strategy):
    """自适应SuperTrend策略
    
    入场条件:
    - 多头: 价格突破SuperTrend线
    - 平仓: 价格跌破SuperTrend线
    """
    params = dict(
        stake=10,
        st_period=20,
        vol_lookback=20,
        a_coef=0.5,
        b_coef=2.0,
        min_mult=0.5,
        max_mult=3.0,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        
        # 自适应SuperTrend指标
        self.st = AdaptiveSuperTrendIndicator(
            self.data,
            period=self.p.st_period,
            vol_lookback=self.p.vol_lookback,
            a_coef=self.p.a_coef,
            b_coef=self.p.b_coef,
            min_mult=self.p.min_mult,
            max_mult=self.p.max_mult,
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

        price = self.data.close[0]
        st_val = self.st.st[0]

        if not self.position:
            # 多头入场: 价格在ST线上方
            if price > st_val:
                self.order = self.buy(size=self.p.stake)
        else:
            # 平仓: 价格跌破ST线
            if price < st_val:
                self.order = self.close()


def test_adaptive_supertrend_strategy():
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
    cerebro.addstrategy(AdaptiveSuperTrendStrategy)
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
    print("Adaptive SuperTrend 自适应超级趋势策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 1218, f"Expected bar_num=1218, got {strat.bar_num}"
    assert abs(final_value - 99936.86) < 0.01, f"Expected final_value near 99936.86, got {final_value}"
    assert abs(sharpe_ratio - (-0.356364776287922)) < 0.001, f"Expected sharpe_ratio near -0.356, got {sharpe_ratio}"
    assert abs(annual_return) < 0.001, f"Expected annual_return near 0, got {annual_return}"
    assert abs(max_drawdown - 0.175419779371468) < 0.001, f"Expected max_drawdown near 0.175, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Adaptive SuperTrend 自适应超级趋势策略测试")
    print("=" * 60)
    test_adaptive_supertrend_strategy()
