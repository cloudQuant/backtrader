#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Sizer 仓位管理器测试

参考来源: backtrader-master2/samples/sizertest/sizertest.py
测试不同的Sizer实现
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


class LongOnlySizer(bt.Sizer):
    """只做多仓位管理器"""
    params = (('stake', 1),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        if isbuy:
            return self.p.stake
        position = self.broker.getposition(data)
        if not position.size:
            return 0
        return self.p.stake


class SizerTestStrategy(bt.Strategy):
    """测试Sizer的策略"""
    params = (('period', 15),)

    def __init__(self):
        sma = bt.ind.SMA(self.data, period=self.p.period)
        self.crossover = bt.ind.CrossOver(self.data, sma)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def next(self):
        self.bar_num += 1
        if self.crossover > 0:
            self.buy()
        elif self.crossover < 0:
            self.sell()

    def stop(self):
        print(f"SizerTest: bar_num={self.bar_num}, buy={self.buy_count}, sell={self.sell_count}")


def test_sizer():
    """测试 Sizer 仓位管理器"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(50000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    data = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(SizerTestStrategy, period=15)
    cerebro.addsizer(LongOnlySizer, stake=100)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Sizer 仓位管理器回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num > 0
    assert 40000 < final_value < 200000, f"Expected final_value=49499.00, got {final_value}"
    assert abs(sharpe_ratio - (-3.032200553947264)) < 1e-6, f"Expected sharpe_ratio=-3.032200553947264, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00503257346891984)) < 1e-6, f"Expected annual_return=-0.00503257346891984, got {annual_return}"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Sizer 仓位管理器测试")
    print("=" * 60)
    test_sizer()
