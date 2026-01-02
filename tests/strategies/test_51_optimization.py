#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Optimization 参数优化

参考来源: backtrader-master2/samples/optimization/optimization.py
测试策略参数优化功能
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


class OptimizeStrategy(bt.Strategy):
    """用于参数优化的策略"""
    params = (
        ('smaperiod', 15),
        ('macdperiod1', 12),
        ('macdperiod2', 26),
        ('macdperiod3', 9),
    )

    def __init__(self):
        self.sma = bt.ind.SMA(period=self.p.smaperiod)
        self.macd = bt.ind.MACD(
            period_me1=self.p.macdperiod1,
            period_me2=self.p.macdperiod2,
            period_signal=self.p.macdperiod3
        )
        self.crossover = bt.ind.CrossOver(self.macd.macd, self.macd.signal)
        self.order = None

    def notify_order(self, order):
        if not order.alive():
            self.order = None

    def next(self):
        if self.order:
            return
        if self.crossover > 0:
            if not self.position:
                self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def test_optimization():
    """测试 Optimization 参数优化"""
    cerebro = bt.Cerebro(maxcpus=1)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    # 使用小范围参数优化以加快测试速度
    cerebro.optstrategy(
        OptimizeStrategy,
        smaperiod=range(10, 13),  # 3个值
        macdperiod1=[12],
        macdperiod2=[26],
        macdperiod3=[9],
    )

    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    print("开始运行优化...")
    results = cerebro.run()

    print("=" * 50)
    print("Optimization 参数优化结果:")
    for i, stratrun in enumerate(results):
        for strat in stratrun:
            params = strat.p._getkwargs()
            ret = strat.analyzers.returns.get_analysis()
            annual = ret.get('rnorm', 0)
            print(f"  组合{i}: smaperiod={params.get('smaperiod')}, annual_return={annual}")
    print(f"  优化组合数: {len(results)}")
    print("=" * 50)

    assert len(results) == 3  # 3个smaperiod值
    # 检查每个结果都有年化收益率
    for stratrun in results:
        for strat in stratrun:
            ret = strat.analyzers.returns.get_analysis()
            assert 'rnorm' in ret, "annual_return should be present"

    print("\n测试通过!")
    return results


if __name__ == "__main__":
    print("=" * 60)
    print("Optimization 参数优化测试")
    print("=" * 60)
    test_optimization()
