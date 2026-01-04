#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: HMA Crossover Hull均线交叉策略

参考来源: https://github.com/Backtrader1.0/strategies/hma_crossover.py
使用快速和慢速Hull均线交叉作为入场信号
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


class HmaCrossoverStrategy(bt.Strategy):
    """HMA Crossover Hull均线交叉策略
    
    入场条件:
    - 多头: 快速HMA上穿慢速HMA
    - 空头: 快速HMA下穿慢速HMA
    
    使用ATR作为波动性参考
    """
    params = dict(
        stake=10,
        hma_fast=60,
        hma_slow=90,
        atr_period=14,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        
        # Hull均线指标
        self.hma_fast = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.hma_fast
        )
        self.hma_slow = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.hma_slow
        )
        
        # ATR
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        
        self.order = None
        self.prev_rel = None  # fast > slow on previous bar
        
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

        f0, s0 = float(self.hma_fast[0]), float(self.hma_slow[0])
        rel_now = f0 > s0

        if self.prev_rel is None:
            self.prev_rel = rel_now
            return

        pos_sz = self.position.size

        # 多头入场: 快线从下方穿越慢线
        if pos_sz == 0 and (not self.prev_rel) and rel_now:
            self.order = self.buy(size=self.p.stake)

        # 空头入场: 快线从上方穿越慢线
        elif pos_sz == 0 and self.prev_rel and (not rel_now):
            self.order = self.sell(size=self.p.stake)

        # 多头平仓: 快线跌破慢线
        elif pos_sz > 0 and not rel_now:
            self.order = self.close()
        
        # 空头平仓: 快线突破慢线
        elif pos_sz < 0 and rel_now:
            self.order = self.close()

        self.prev_rel = rel_now


def test_hma_crossover_strategy():
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
    cerebro.addstrategy(HmaCrossoverStrategy)
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
    print("HMA Crossover Hull均线交叉策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1160, f"Expected bar_num=1160, got {strat.bar_num}"
    assert abs(final_value - 100081.45) < 0.01, f"Expected final_value=100081.45, got {final_value}"
    assert abs(sharpe_ratio - (0.5100011168586044)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.00016323774473640581)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.10334345093914488) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("HMA Crossover Hull均线交叉策略测试")
    print("=" * 60)
    test_hma_crossover_strategy()
