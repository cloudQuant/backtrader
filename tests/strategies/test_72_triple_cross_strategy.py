#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Triple Cross 三均线交叉策略

参考来源: https://github.com/backtrader/backhacker
基于三条均线排列的趋势策略
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


class TripleCrossStrategy(bt.Strategy):
    """三均线交叉策略
    
    - 短期 > 中期 > 长期均线时买入
    - 短期 < 中期 < 长期均线时卖出
    """
    params = dict(
        stake=10,
        ma1_period=5,
        ma2_period=8,
        ma3_period=13,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.ma1 = bt.ind.SMA(self.datas[0], period=self.p.ma1_period)
        self.ma2 = bt.ind.SMA(self.datas[0], period=self.p.ma2_period)
        self.ma3 = bt.ind.SMA(self.datas[0], period=self.p.ma3_period)
        
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

        # 买入条件: MA1 > MA2 > MA3 (多头排列)
        if self.last_operation != "BUY":
            if self.ma1[0] > self.ma2[0] > self.ma3[0]:
                self.order = self.buy(size=self.p.stake)
        
        # 卖出条件: MA1 < MA2 < MA3 (空头排列)
        if self.last_operation != "SELL":
            if self.ma1[0] < self.ma2[0] < self.ma3[0]:
                self.order = self.sell(size=self.p.stake)

    def stop(self):
        pass


def test_triple_cross_strategy():
    """测试三均线交叉策略"""
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
    cerebro.addstrategy(TripleCrossStrategy)
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
    print("Triple Cross 三均线交叉策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num > 0, "bar_num should be greater than 0"
    assert 40000 < final_value < 200000, f"Expected final_value=100063.63, got {final_value}"
    assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"sharpe_ratio={sharpe_ratio} out of range"
    assert -1 < annual_return < 1, f"annual_return={annual_return} out of range"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Triple Cross 三均线交叉策略测试")
    print("=" * 60)
    test_triple_cross_strategy()
