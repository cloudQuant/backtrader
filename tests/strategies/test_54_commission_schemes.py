#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Commission Schemes 佣金方案

参考来源: backtrader-master2/samples/commission-schemes/commission-schemes.py
测试不同佣金计算方案
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


class CommissionStrategy(bt.Strategy):
    """测试佣金方案的策略"""
    params = (('stake', 10), ('period', 30))

    def __init__(self):
        sma = bt.ind.SMA(self.data, period=self.p.period)
        self.signal = bt.ind.CrossOver(self.data, sma)
        self.bar_num = 0
        self.total_commission = 0.0

    def notify_order(self, order):
        if order.status == order.Completed:
            self.total_commission += order.executed.comm

    def next(self):
        self.bar_num += 1
        if self.signal > 0:
            self.buy(size=self.p.stake)
        elif self.position and self.signal < 0:
            self.sell(size=self.p.stake)

    def stop(self):
        print(f"CommissionTest: bar_num={self.bar_num}, total_commission={self.total_commission:.2f}")


def test_commission_schemes():
    """测试 Commission Schemes 佣金方案"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(10000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(CommissionStrategy, stake=10, period=30)

    # 设置百分比佣金
    cerebro.broker.setcommission(
        commission=0.001,  # 0.1%
        commtype=bt.CommInfoBase.COMM_PERC,
        stocklike=True
    )

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
    print("Commission Schemes 佣金方案回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_commission: {strat.total_commission:.2f}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 225, f"Expected bar_num=225, got {strat.bar_num}"
    assert abs(final_value - 10000.00) < 0.01, f"Expected final_value=10000.00, got {final_value}"
    assert sharpe_ratio is None, f"Expected sharpe_ratio=None, got {sharpe_ratio}"
    assert abs(annual_return - 0.0) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.0) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Commission Schemes 佣金方案测试")
    print("=" * 60)
    test_commission_schemes()
