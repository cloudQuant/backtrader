#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Keltner Channel 肯特纳通道策略

参考来源: https://github.com/backtrader/backhacker
基于肯特纳通道的突破策略
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


class KeltnerChannelIndicator(bt.Indicator):
    """肯特纳通道指标"""
    lines = ('upper', 'mid', 'lower')
    params = dict(
        period=20,
        atr_period=10,
        multiplier=2.0,
    )

    def __init__(self):
        self.lines.mid = bt.indicators.EMA(self.data.close, period=self.p.period)
        atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.lines.upper = self.lines.mid + (atr * self.p.multiplier)
        self.lines.lower = self.lines.mid - (atr * self.p.multiplier)


class KeltnerChannelStrategy(bt.Strategy):
    """肯特纳通道策略
    
    - 价格跌破下轨时买入
    - 价格突破上轨时卖出
    """
    params = dict(
        stake=10,
        kc_period=20,
        atr_period=10,
        multiplier=2.0,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.indicator = KeltnerChannelIndicator(
            self.datas[0], 
            period=self.p.kc_period,
            atr_period=self.p.atr_period,
            multiplier=self.p.multiplier
        )
        
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

        # 买入条件: 价格跌破下轨
        if self.dataclose[0] < self.indicator.lower[0] and self.last_operation != "BUY":
            self.order = self.buy(size=self.p.stake)
        
        # 卖出条件: 价格突破上轨
        elif self.dataclose[0] > self.indicator.upper[0] and self.last_operation != "SELL":
            self.order = self.sell(size=self.p.stake)

    def stop(self):
        pass


def test_keltner_channel_strategy():
    """测试肯特纳通道策略"""
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
    cerebro.addstrategy(KeltnerChannelStrategy)
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
    print("Keltner Channel 肯特纳通道策略回测结果:")
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
    assert 40000 < final_value < 200000, f"Expected final_value=100000.00, got {final_value}"
    assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"sharpe_ratio={sharpe_ratio} out of range"
    assert -1 < annual_return < 1, f"annual_return={annual_return} out of range"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Keltner Channel 肯特纳通道策略测试")
    print("=" * 60)
    test_keltner_channel_strategy()
