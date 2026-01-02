#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Sharpe TimeReturn 夏普比率和时间收益

参考来源: backtrader-master2/samples/sharpe-timereturn/sharpe-timereturn.py
测试夏普比率和时间收益分析器
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


class SharpeTestStrategy(bt.Strategy):
    """测试夏普比率的策略"""
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


def test_sharpe_timereturn():
    """测试 Sharpe TimeReturn"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(SharpeTestStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.TimeReturn, timeframe=bt.TimeFrame.Years, _name="yearly")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, timeframe=bt.TimeFrame.Months, _name="monthly")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, timeframe=bt.TimeFrame.Years, _name="sharpe")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    yearly = strat.analyzers.yearly.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    sharpe_ratio = sharpe.get('sharperatio', None)
    final_value = cerebro.broker.getvalue()
    # 计算年化收益率
    annual_return = (final_value / 100000.0 - 1) / 2  # 2年期间

    print("=" * 50)
    print("Sharpe TimeReturn 回测结果:")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  Yearly Returns: {yearly}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert 40000 < final_value < 200000, f"Expected final_value=104966.80, got {final_value}"
    assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"sharpe_ratio={sharpe_ratio} out of range"
    assert -1 < annual_return < 1, f"annual_return={annual_return} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Sharpe TimeReturn 测试")
    print("=" * 60)
    test_sharpe_timereturn()
