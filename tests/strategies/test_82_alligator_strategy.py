#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Alligator 鳄鱼线策略

参考来源: https://github.com/Backtesting/strategies
Bill Williams的鳄鱼线指标策略
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


class AlligatorIndicator(bt.Indicator):
    """鳄鱼线指标 - Bill Williams
    
    - Jaw (颚线): 13周期SMMA，向未来偏移8根
    - Teeth (齿线): 8周期SMMA，向未来偏移5根
    - Lips (唇线): 5周期SMMA，向未来偏移3根
    """
    lines = ('jaw', 'teeth', 'lips')
    params = dict(
        jaw_period=13,
        teeth_period=8,
        lips_period=5,
    )

    def __init__(self):
        # 使用SMMA (Smoothed Moving Average) = EMA with alpha = 1/period
        self.lines.jaw = bt.indicators.SmoothedMovingAverage(
            self.data.close, period=self.p.jaw_period
        )
        self.lines.teeth = bt.indicators.SmoothedMovingAverage(
            self.data.close, period=self.p.teeth_period
        )
        self.lines.lips = bt.indicators.SmoothedMovingAverage(
            self.data.close, period=self.p.lips_period
        )


class AlligatorStrategy(bt.Strategy):
    """鳄鱼线策略
    
    - 价格突破颚线向上时买入
    - 价格跌破颚线时卖出
    """
    params = dict(
        stake=10,
        jaw_period=13,
        teeth_period=8,
        lips_period=5,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.alligator = AlligatorIndicator(
            self.datas[0], 
            jaw_period=self.p.jaw_period,
            teeth_period=self.p.teeth_period,
            lips_period=self.p.lips_period
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

        # 价格在颚线上方买入
        if not self.position:
            if self.dataclose[0] > self.alligator.jaw[0]:
                self.order = self.buy(size=self.p.stake)
        else:
            # 价格跌破颚线卖出
            if self.dataclose[0] < self.alligator.jaw[0]:
                self.order = self.sell(size=self.p.stake)


def test_alligator_strategy():
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
    cerebro.addstrategy(AlligatorStrategy)
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
    print("Alligator 鳄鱼线策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1245, f"Expected bar_num=1245, got {strat.bar_num}"
    assert abs(final_value - 100011.2) < 0.01, f"Expected final_value=100011.2, got {final_value}"
    assert abs(sharpe_ratio - (0.04724483526577409)) < 1e-6, f"Expected sharpe_ratio=0.04724483526577409, got {sharpe_ratio}"
    assert abs(annual_return - (2.2461836991998968e-05)) < 1e-6, f"Expected annual_return=2.2461836991998968e-05, got {annual_return}"
    assert abs(max_drawdown - 0.1353106121383434) < 1e-6, f"Expected max_drawdown=0.1353106121383434, got {max_drawdown}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("Alligator 鳄鱼线策略测试")
    print("=" * 60)
    test_alligator_strategy()
