#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Bollinger Bands 布林带策略

参考来源: https://github.com/backtrader/backhacker
基于布林带的均值回归策略
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


class BollingerBandsStrategy(bt.Strategy):
    """布林带策略
    
    - 价格跌破下轨时标记买入信号
    - 价格回升至中轨上方时买入
    - 价格突破上轨时标记卖出信号
    - 价格回落至中轨下方时卖出
    """
    params = dict(
        stake=10,
        bbands_period=20,
        devfactor=2.0,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.bband = bt.indicators.BBands(self.datas[0], period=self.p.bbands_period, devfactor=self.p.devfactor)
        
        self.redline = False  # 价格曾跌破下轨
        self.blueline = False  # 价格曾突破上轨
        
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

        # 价格跌破下轨，标记买入信号
        if self.dataclose[0] < self.bband.l.bot[0] and self.last_operation != "BUY":
            self.redline = True

        # 价格突破上轨，标记卖出信号
        if self.dataclose[0] > self.bband.l.top[0] and self.last_operation != "SELL":
            self.blueline = True

        # 价格回升至中轨上方，执行买入
        if self.dataclose[0] > self.bband.l.mid[0] and self.last_operation != "BUY" and self.redline:
            self.order = self.buy(size=self.p.stake)
            self.redline = False

        # 价格突破上轨，直接买入
        if self.dataclose[0] > self.bband.l.top[0] and self.last_operation != "BUY":
            self.order = self.buy(size=self.p.stake)

        # 价格回落至中轨下方，执行卖出
        if self.dataclose[0] < self.bband.l.mid[0] and self.last_operation != "SELL" and self.blueline:
            self.blueline = False
            self.redline = False
            self.order = self.sell(size=self.p.stake)

    def stop(self):
        pass


def test_bollinger_bands_strategy():
    """测试布林带策略"""
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
    cerebro.addstrategy(BollingerBandsStrategy)
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
    print("Bollinger Bands 布林带策略回测结果:")
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
    assert abs(final_value - 100275.98) < 0.01, f"Expected final_value=100275.98, got {final_value}"
    assert abs(sharpe_ratio - (1.2477776453402647)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.0005526698863482884)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.08517200936602952) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("Bollinger Bands 布林带策略测试")
    print("=" * 60)
    test_bollinger_bands_strategy()
