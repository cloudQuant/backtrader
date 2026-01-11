#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Donchian Channel 唐奇安通道策略

参考来源: https://github.com/backtrader/backhacker
经典的唐奇安通道突破策略
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """根据脚本所在目录定位数据文件"""
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


class DonchianChannelIndicator(bt.Indicator):
    """唐奇安通道指标"""
    lines = ('dch', 'dcl', 'dcm')
    params = dict(period=20)

    def __init__(self):
        self.lines.dch = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.lines.dcl = bt.indicators.Lowest(self.data.low, period=self.p.period)
        self.lines.dcm = (self.lines.dch + self.lines.dcl) / 2


class DonchianChannelStrategy(bt.Strategy):
    """唐奇安通道突破策略
    
    - 价格突破上轨做多
    - 价格跌破下轨做空
    """
    params = dict(
        stake=10,
        period=20,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.indicator = DonchianChannelIndicator(self.datas[0], period=self.p.period)
        
        self.order = None
        self.last_operation = "SELL"
        
        # 统计变量
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.last_operation = "BUY"
            else:
                self.sell_count += 1
                self.last_operation = "SELL"

        self.order = None

    def next(self):
        self.bar_num += 1

        if self.order:
            return

        if self.dataclose[0] > self.indicator.dch[0] and self.last_operation != "BUY":
            self.order = self.buy(size=self.p.stake)
        elif self.dataclose[0] < self.indicator.dcl[0] and self.last_operation != "SELL":
            self.order = self.sell(size=self.p.stake)

    def stop(self):
        pass


def test_donchian_channel_strategy():
    """测试唐奇安通道策略"""
    cerebro = bt.Cerebro()

    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(DonchianChannelStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    # 获取分析结果
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Donchian Channel 唐奇安通道策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 100000.0) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    # 没有交易，sharpe_ratio为空
    assert sharpe_ratio is None or sharpe_ratio == 0, f"Expected sharpe_ratio=None/0, got {sharpe_ratio}"
    assert abs(annual_return - (0.0)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.0) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("Donchian Channel 唐奇安通道策略测试")
    print("=" * 60)
    test_donchian_channel_strategy()
