#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: VWR (Variability-Weighted Return) 分析器

参考来源: backtrader-master2/samples/vwr/vwr.py
测试VWR分析器
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


class VWRTestStrategy(bt.Strategy):
    """测试VWR分析器的策略"""
    params = (('p1', 10), ('p2', 30))

    def __init__(self):
        ma1 = bt.ind.SMA(period=self.p.p1)
        ma2 = bt.ind.SMA(period=self.p.p2)
        self.crossover = bt.ind.CrossOver(ma1, ma2)
        self.order = None

    def notify_order(self, order):
        if not order.alive():
            self.order = None

    def next(self):
        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def test_vwr_analyzer():
    """测试 VWR Analyzer"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))
    cerebro.adddata(data)

    cerebro.addstrategy(VWRTestStrategy)
    
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.VWR, _name="vwr")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, timeframe=bt.TimeFrame.Months, _name="monthly")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, timeframe=bt.TimeFrame.Years, _name="yearly")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    returns = strat.analyzers.returns.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    vwr = strat.analyzers.vwr.get_analysis()
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = returns.get('rnorm', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("VWR Analyzer 回测结果:")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  VWR: {vwr}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert 40000 < final_value < 200000, f"Expected final_value=100496.68, got {final_value}"
    assert abs(sharpe_ratio - (-49.55772065326132)) < 1e-6, f"Expected sharpe_ratio=-49.55772065326132, got {sharpe_ratio}"
    assert -1 < annual_return < 1, f"annual_return={annual_return} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("VWR Analyzer 测试")
    print("=" * 60)
    test_vwr_analyzer()
