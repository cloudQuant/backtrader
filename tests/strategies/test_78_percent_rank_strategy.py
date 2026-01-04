#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Percent Rank 百分位排名策略

参考来源: https://github.com/backtrader/backhacker
基于MACD差值百分位排名的均值回归策略
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


class PercentRankStrategy(bt.Strategy):
    """百分位排名策略
    
    - MACD差值百分位极低后回升时买入
    - MACD差值百分位极高后回落时卖出
    """
    params = dict(
        stake=10,
        percent_period=200,
        limit1=10,
        limit2=30,
        period1=12,
        period2=26,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.ma1 = bt.ind.EMA(self.datas[0], period=self.p.period1)
        self.ma2 = bt.ind.EMA(self.datas[0], period=self.p.period2)
        self.diff = self.ma1 - self.ma2
        self.prank = bt.ind.PercentRank(self.diff, period=self.p.percent_period) * 100
        
        self.buy_limit1 = self.p.limit1
        self.sell_limit1 = 100 - self.buy_limit1
        self.buy_limit2 = self.p.limit2
        self.sell_limit2 = 100 - self.buy_limit2
        
        self.pending_buy = False
        self.pending_sell = False
        
        self.order = None
        self.last_operation = "SELL"
        
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

        # 买入逻辑
        if self.last_operation != "BUY":
            if self.prank[0] <= self.buy_limit1:
                self.pending_buy = True
            elif self.pending_buy and self.prank[0] >= self.buy_limit2:
                self.pending_buy = False
                self.order = self.buy(size=self.p.stake)
        
        # 卖出逻辑
        if self.last_operation != "SELL":
            if self.prank[0] >= self.sell_limit1:
                self.pending_sell = True
            elif self.pending_sell and self.prank[0] <= self.sell_limit2:
                self.pending_sell = False
                self.order = self.sell(size=self.p.stake)


def test_percent_rank_strategy():
    cerebro = bt.Cerebro()
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(PercentRankStrategy)
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
    print("Percent Rank 百分位排名策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 3548, f"Expected bar_num=3548, got {strat.bar_num}"
    assert abs(final_value - 100302.26) < 0.01, f"Expected final_value=100302.26, got {final_value}"
    assert abs(sharpe_ratio - (0.8675517538455737)) < 1e-6, f"Expected sharpe_ratio=0.8675517538455737, got {sharpe_ratio}"
    assert abs(annual_return - (0.00020164856372564902)) < 1e-6, f"Expected annual_return=0.00020164856372564902, got {annual_return}"
    assert abs(max_drawdown - 0.11557448332367173) < 1e-6, f"Expected max_drawdown=0.11557448332367173, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Percent Rank 百分位排名策略测试")
    print("=" * 60)
    test_percent_rank_strategy()
