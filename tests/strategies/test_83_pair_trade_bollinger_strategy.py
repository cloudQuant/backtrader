#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Pair Trade Bollinger 配对交易布林带策略

参考来源: https://github.com/mean_reversion_strategies
使用布林带和简化的对冲比率进行配对交易
原策略使用Kalman Filter，这里简化为滚动OLS回归
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import numpy as np
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


class PairTradeBollingerStrategy(bt.Strategy):
    """配对交易布林带策略
    
    使用两个相关资产进行配对交易：
    - 计算价差的Z-Score
    - Z-Score低于下轨时做多价差
    - Z-Score高于上轨时做空价差
    - Z-Score回归均值时平仓
    """
    params = dict(
        lookback=20,
        entry_zscore=1.5,
        exit_zscore=0.2,
        stake=10,
    )

    def __init__(self):
        self.data0_close = self.datas[0].close
        self.data1_close = self.datas[1].close
        self.order = None
        
        self.spread_history = []
        self.hedge_ratio = 1.0
        
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        
        # 持仓状态: 0=空仓, 1=做多价差, -1=做空价差
        self.position_state = 0

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def calculate_zscore(self):
        """计算价差的Z-Score"""
        if len(self.spread_history) < self.p.lookback:
            return 0
        
        recent = self.spread_history[-self.p.lookback:]
        mean = np.mean(recent)
        std = np.std(recent)
        if std == 0:
            return 0
        return (self.spread_history[-1] - mean) / std

    def calculate_hedge_ratio(self):
        """使用滚动回归计算对冲比率"""
        if len(self) < self.p.lookback:
            return 1.0
        
        y = [self.data0_close[-i] for i in range(self.p.lookback)]
        x = [self.data1_close[-i] for i in range(self.p.lookback)]
        
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        
        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(len(x)))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(len(x)))
        
        if denominator == 0:
            return 1.0
        return numerator / denominator

    def next(self):
        self.bar_num += 1
        
        # 更新对冲比率
        self.hedge_ratio = self.calculate_hedge_ratio()
        
        # 计算价差
        spread = self.data0_close[0] - self.hedge_ratio * self.data1_close[0]
        self.spread_history.append(spread)
        
        if len(self.spread_history) < self.p.lookback:
            return
            
        zscore = self.calculate_zscore()
        
        if self.order:
            return

        # 交易逻辑
        if self.position_state == 0:
            # 空仓时
            if zscore < -self.p.entry_zscore:
                # 做多价差: 买入data0, 卖出data1
                self.buy(data=self.datas[0], size=self.p.stake)
                self.sell(data=self.datas[1], size=int(self.p.stake * self.hedge_ratio))
                self.position_state = 1
            elif zscore > self.p.entry_zscore:
                # 做空价差: 卖出data0, 买入data1
                self.sell(data=self.datas[0], size=self.p.stake)
                self.buy(data=self.datas[1], size=int(self.p.stake * self.hedge_ratio))
                self.position_state = -1
        
        elif self.position_state == 1:
            # 做多价差时，Z-Score回归均值则平仓
            if zscore > -self.p.exit_zscore:
                self.close(data=self.datas[0])
                self.close(data=self.datas[1])
                self.position_state = 0
        
        elif self.position_state == -1:
            # 做空价差时，Z-Score回归均值则平仓
            if zscore < self.p.exit_zscore:
                self.close(data=self.datas[0])
                self.close(data=self.datas[1])
                self.position_state = 0


def test_pair_trade_bollinger_strategy():
    cerebro = bt.Cerebro()
    
    # 加载两个数据源 (使用同一数据但不同时间段模拟配对)
    data_path = resolve_data_path("orcl-1995-2014.txt")
    
    data0 = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    
    data1 = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    
    cerebro.adddata(data0, name='asset0')
    cerebro.adddata(data1, name='asset1')
    cerebro.addstrategy(PairTradeBollingerStrategy)
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
    print("Pair Trade Bollinger 配对交易布林带策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 1257, f"Expected bar_num=1257, got {strat.bar_num}"
    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert abs(final_value - 99998.89) < 0.01, f"Expected final_value=99998.89, got {final_value}"
    assert abs(sharpe_ratio - (-0.5)) < 1e-6, f"Expected sharpe_ratio=-0.5, got {sharpe_ratio}"
    assert abs(annual_return - (-2.220897623467464e-06)) < 1e-6, f"Expected annual_return=-2.220897623467464e-06, got {annual_return}"
    assert abs(max_drawdown - 0.0011077999800036195) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Pair Trade Bollinger 配对交易布林带策略测试")
    print("=" * 60)
    test_pair_trade_bollinger_strategy()
