#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Ichimoku Cloud 一目均衡表策略

参考来源: backtrader-strategies-compendium/strategies/Ichimoku.py
使用一目均衡表云层突破作为入场信号
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


class IchimokuCloudStrategy(bt.Strategy):
    """Ichimoku Cloud 一目均衡表策略
    
    入场条件:
    - 多头: 价格 > Senkou Span A > Senkou Span B (云层上方)
    
    出场条件:
    - 价格跌破云层任一边界
    """
    params = dict(
        stake=10,
        tenkan=9,
        kijun=26,
        senkou=52,
        senkou_lead=26,
        chikou=26,
    )

    def __init__(self):
        self.ichimoku = bt.indicators.Ichimoku(
            self.data,
            tenkan=self.p.tenkan,
            kijun=self.p.kijun,
            senkou=self.p.senkou,
            senkou_lead=self.p.senkou_lead,
            chikou=self.p.chikou,
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
        
        close = self.data.close[0]
        senkou_a = self.ichimoku.senkou_span_a[0]
        senkou_b = self.ichimoku.senkou_span_b[0]
        
        if not self.position:
            # 价格在云层上方 (放宽条件)
            if close > senkou_a and close > senkou_b:
                self.order = self.buy(size=self.p.stake)
        else:
            # 价格跌破云层两边
            if close < senkou_a and close < senkou_b:
                self.order = self.close()


def test_ichimoku_cloud_strategy():
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
    cerebro.addstrategy(IchimokuCloudStrategy)
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
    print("Ichimoku Cloud 一目均衡表策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1180, f"Expected bar_num=1180, got {strat.bar_num}"
    assert abs(final_value - 100088.51) < 0.01, f"Expected final_value=100088.51, got {final_value}"
    assert abs(sharpe_ratio - (0.9063632909371556)) < 1e-6, f"Expected sharpe_ratio=0.9063632909371556, got {sharpe_ratio}"
    assert abs(annual_return - (0.00017737921024728437)) < 1e-6, f"Expected annual_return=0.00017737921024728437, got {annual_return}"
    assert abs(max_drawdown - 0.10317697620290582) < 1e-6, f"Expected max_drawdown=0.10317697620290582, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Ichimoku Cloud 一目均衡表策略测试")
    print("=" * 60)
    test_ichimoku_cloud_strategy()
