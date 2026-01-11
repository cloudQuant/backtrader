#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: ATR Momentum 动量策略

参考来源: https://github.com/papodetrader/backtest
基于ATR、RSI和SMA的动量交易策略
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


class ATRMomentumStrategy(bt.Strategy):
    """ATR动量策略
    
    使用RSI、SMA200作为趋势过滤
    使用ATR进行止损止盈管理
    """
    params = dict(
        bet=100,
        stop_atr_multiplier=2,
        target_atr_multiplier=5,
        rsi_period=14,
        sma_period=200,
        atr_period=14,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.datahigh = self.datas[0].high
        self.datalow = self.datas[0].low
        
        # 指标
        self.atr = bt.indicators.ATR(self.datas[0], period=self.p.atr_period)
        self.rsi = bt.indicators.RSI(self.datas[0], period=self.p.rsi_period)
        self.sma200 = bt.indicators.SMA(self.datas[0], period=self.p.sma_period)
        
        # 交易管理
        self.order = None
        self.stop_loss = None
        self.take_profit = None
        self.entry_price = None
        
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
                self.entry_price = order.executed.price
            else:
                self.sell_count += 1

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            pass

        self.order = None

    def next(self):
        self.bar_num += 1
        
        if self.order:
            return

        # 检查是否有持仓需要管理
        if self.position.size > 0:
            # 多头止损止盈
            if self.datahigh[0] >= self.take_profit:
                self.close()
            elif self.datalow[0] <= self.stop_loss:
                self.close()
                
        elif self.position.size < 0:
            # 空头止损止盈
            if self.datalow[0] <= self.take_profit:
                self.close()
            elif self.datahigh[0] >= self.stop_loss:
                self.close()
        
        else:
            # 无持仓时检查入场条件
            # 多头条件: RSI上穿50 + 价格在SMA200上方
            cond_long = (self.rsi[0] > 50 and self.rsi[-1] <= 50 and 
                        self.dataclose[0] > self.sma200[0])
            
            # 空头条件: RSI下穿50 + 价格在SMA200下方
            cond_short = (self.rsi[0] < 50 and self.rsi[-1] >= 50 and 
                         self.dataclose[0] < self.sma200[0])

            if cond_long:
                atr_val = self.atr[0] if self.atr[0] > 0 else 0.01
                size = max(1, int(self.p.bet / (self.p.stop_atr_multiplier * atr_val)))
                self.buy(size=size)
                self.stop_loss = self.dataclose[0] - (self.p.stop_atr_multiplier * self.atr[0])
                self.take_profit = self.dataclose[0] + (self.p.target_atr_multiplier * self.atr[0])

            elif cond_short:
                atr_val = self.atr[0] if self.atr[0] > 0 else 0.01
                size = max(1, int(self.p.bet / (self.p.stop_atr_multiplier * atr_val)))
                self.sell(size=size)
                self.stop_loss = self.dataclose[0] + (self.p.stop_atr_multiplier * self.atr[0])
                self.take_profit = self.dataclose[0] - (self.p.target_atr_multiplier * self.atr[0])

    def stop(self):
        pass


def test_atr_momentum_strategy():
    """测试ATR动量策略"""
    cerebro = bt.Cerebro()

    # 使用已有的数据文件
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
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2010, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(ATRMomentumStrategy)
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
    print("ATR Momentum 动量策略回测结果:")
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
    assert strat.bar_num == 1311, f"Expected bar_num=1311, got {strat.bar_num}"
    assert abs(final_value - 99399.52) < 0.01, f"Expected final_value=99399.52, got {final_value}"
    assert abs(sharpe_ratio - (-0.32367458244300346)) < 1e-6, f"Expected sharpe_ratio=-0.32367458244300346, got {sharpe_ratio}"
    assert abs(annual_return - (-0.001004641690653692)) < 1e-6, f"Expected annual_return=-0.001004641690653692, got {annual_return}"
    assert abs(max_drawdown - 0.9986173826924808) < 1e-6, f"Expected max_drawdown=0.9986173826924808, got {max_drawdown}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("ATR Momentum 动量策略测试")
    print("=" * 60)
    test_atr_momentum_strategy()
