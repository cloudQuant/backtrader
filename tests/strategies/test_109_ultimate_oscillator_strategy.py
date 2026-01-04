#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Ultimate Oscillator 终极震荡指标策略

使用终极震荡指标的超买超卖判断入场
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


class UltimateOscillatorStrategy(bt.Strategy):
    """Ultimate Oscillator 终极震荡指标策略
    
    入场条件:
    - 多头: UO < 30 (超卖)
    
    出场条件:
    - UO > 70 (超买)
    """
    params = dict(
        stake=10,
        p1=7,
        p2=14,
        p3=28,
        oversold=30,
        overbought=70,
    )

    def __init__(self):
        self.uo = bt.indicators.UltimateOscillator(
            self.data, p1=self.p.p1, p2=self.p.p2, p3=self.p.p3
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
        
        if not self.position:
            # UO超卖
            if self.uo[0] < self.p.oversold:
                self.order = self.buy(size=self.p.stake)
        else:
            # UO超买
            if self.uo[0] > self.p.overbought:
                self.order = self.close()


def test_ultimate_oscillator_strategy():
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
    cerebro.addstrategy(UltimateOscillatorStrategy)
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
    print("Ultimate Oscillator 终极震荡指标策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # 断言 - 使用精确断言
    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1229, f"Expected bar_num=1229, got {strat.bar_num}"
    assert abs(final_value - 100199.75) < 0.01, f"Expected final_value=100199.75, got {final_value}"
    assert abs(sharpe_ratio - (2.2256344725800337)) < 1e-6, f"Expected sharpe_ratio=2.2256344725800337, got {sharpe_ratio}"
    assert abs(annual_return - (0.0004001266459915534)) < 1e-6, f"Expected annual_return=0.0004001266459915534, got {annual_return}"
    assert abs(max_drawdown - 0.06371267726839967) < 1e-6, f"Expected max_drawdown=0.06371267726839967, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Ultimate Oscillator 终极震荡指标策略测试")
    print("=" * 60)
    test_ultimate_oscillator_strategy()
