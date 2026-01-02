#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Calmar Analyzer 卡尔马分析器

参考来源: backtrader-master2/samples/calmar/calmar-test.py
测试Calmar比率分析器
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


class CalmarTestStrategy(bt.Strategy):
    """测试Calmar分析器的策略"""
    params = (('p1', 15), ('p2', 50))

    def __init__(self):
        ma1 = bt.ind.SMA(period=self.p.p1)
        ma2 = bt.ind.SMA(period=self.p.p2)
        self.crossover = bt.ind.CrossOver(ma1, ma2)
        self.order = None
        self.bar_num = 0

    def notify_order(self, order):
        if not order.alive():
            self.order = None

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
        print(f"CalmarTest: bar_num={self.bar_num}")


def test_calmar_analyzer():
    """测试 Calmar Analyzer"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    data = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2010, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(CalmarTestStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=100)
    cerebro.addanalyzer(bt.analyzers.Calmar, _name="calmar")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    calmar = strat.analyzers.calmar.get_analysis()
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    drawdown = strat.analyzers.drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()
    annual_return = (final_value / 100000.0 - 1) / 6  # 简单计算年化收益

    print("=" * 50)
    print("Calmar Analyzer 回测结果:")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num > 0
    assert 40000 < final_value < 200000, f"Expected final_value=98020.00, got {final_value}"
    assert abs(sharpe_ratio - (-1.8292912417516372)) < 1e-6, f"Expected sharpe_ratio=-1.8292912417516372, got {sharpe_ratio}"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Calmar Analyzer 测试")
    print("=" * 60)
    test_calmar_analyzer()
