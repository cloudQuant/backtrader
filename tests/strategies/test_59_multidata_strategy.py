#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: MultiData Strategy 多数据策略

参考来源: backtrader-master2/samples/multidata-strategy/multidata-strategy.py
测试多数据源策略
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


class MultiDataStrategy(bt.Strategy):
    """多数据策略 - 使用第二个数据源的信号在第一个数据源上交易"""
    params = dict(period=15, stake=10)

    def __init__(self):
        self.orderid = None
        # 在第二个数据上创建SMA和交叉信号
        sma = bt.ind.SMA(self.data1, period=self.p.period)
        self.signal = bt.ind.CrossOver(self.data1.close, sma)
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
        self.orderid = None

    def next(self):
        self.bar_num += 1
        if self.orderid:
            return

        if not self.position:
            if self.signal > 0.0:
                self.buy(size=self.p.stake)
        else:
            if self.signal < 0.0:
                self.sell(size=self.p.stake)

    def stop(self):
        print(f"MultiData: bar_num={self.bar_num}, buy={self.buy_count}, sell={self.sell_count}")
        print(f"  Starting Value: {self.broker.startingcash:.2f}")
        print(f"  Ending Value: {self.broker.getvalue():.2f}")


def test_multidata_strategy():
    """测试 MultiData Strategy 多数据策略"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    # 使用同一个数据文件两次模拟多数据源
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    
    data0 = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data0, name='Data0')

    data1 = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data1, name='Data1')

    cerebro.addstrategy(MultiDataStrategy, period=15, stake=10)
    cerebro.broker.setcommission(commission=0.005)
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
    print("MultiData Strategy 多数据策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 488, f"Expected bar_num=488, got {strat.bar_num}"
    assert abs(final_value - 99847.01) < 0.01, f"Expected final_value=99847.01, got {final_value}"
    assert abs(sharpe_ratio - (-56.94920781443037)) < 1e-6, f"Expected sharpe_ratio=-56.94920781443037, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0007667861342752088)) < 1e-6, f"Expected annual_return=-0.0007667861342752088, got {annual_return}"
    assert abs(max_drawdown - 0.1646592612119436) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("MultiData Strategy 多数据策略测试")
    print("=" * 60)
    test_multidata_strategy()
