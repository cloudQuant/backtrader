#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Strategy Selection 策略选择

参考来源: backtrader-master2/samples/strategy-selection/strategy-selection.py
演示如何在运行时选择不同的策略
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


class StrategyA(bt.Strategy):
    """策略A: 双均线交叉"""
    params = (('p1', 10), ('p2', 30))

    def __init__(self):
        sma1 = bt.ind.SMA(period=self.p.p1)
        sma2 = bt.ind.SMA(period=self.p.p2)
        self.crossover = bt.ind.CrossOver(sma1, sma2)
        self.order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        if not order.alive():
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm

    def next(self):
        self.bar_num += 1
        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()

    def stop(self):
        print(f"StrategyA: bar_num={self.bar_num}, buy={self.buy_count}, sell={self.sell_count}, profit={self.sum_profit:.2f}")


class StrategyB(bt.Strategy):
    """策略B: 价格与均线交叉"""
    params = (('period', 10),)

    def __init__(self):
        sma = bt.ind.SMA(period=self.p.period)
        self.crossover = bt.ind.CrossOver(self.data.close, sma)
        self.order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        if not order.alive():
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm

    def next(self):
        self.bar_num += 1
        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()

    def stop(self):
        print(f"StrategyB: bar_num={self.bar_num}, buy={self.buy_count}, sell={self.sell_count}, profit={self.sum_profit:.2f}")


def test_strategy_selection():
    """测试 Strategy Selection 策略选择"""
    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")

    # 测试策略A
    print("\n--- 测试策略A ---")
    cerebro_a = bt.Cerebro(stdstats=True)
    cerebro_a.broker.setcash(100000.0)
    data_a = bt.feeds.BacktraderCSVData(dataname=str(data_path))
    cerebro_a.adddata(data_a)
    cerebro_a.addstrategy(StrategyA)
    cerebro_a.addsizer(bt.sizers.FixedSize, stake=10)
    cerebro_a.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro_a.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro_a.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    results_a = cerebro_a.run()
    strat_a = results_a[0]
    final_value_a = cerebro_a.broker.getvalue()
    sharpe_a = strat_a.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_a = strat_a.analyzers.returns.get_analysis().get('rnorm', 0)
    maxdd_a = strat_a.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)

    # 测试策略B
    print("\n--- 测试策略B ---")
    cerebro_b = bt.Cerebro(stdstats=True)
    cerebro_b.broker.setcash(100000.0)
    data_b = bt.feeds.BacktraderCSVData(dataname=str(data_path))
    cerebro_b.adddata(data_b)
    cerebro_b.addstrategy(StrategyB)
    cerebro_b.addsizer(bt.sizers.FixedSize, stake=10)
    cerebro_b.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro_b.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro_b.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    results_b = cerebro_b.run()
    strat_b = results_b[0]
    final_value_b = cerebro_b.broker.getvalue()
    sharpe_b = strat_b.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_b = strat_b.analyzers.returns.get_analysis().get('rnorm', 0)
    maxdd_b = strat_b.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)

    print("=" * 50)
    print("Strategy Selection 策略选择回测结果:")
    print(f"  策略A: sharpe={sharpe_a}, annual={annual_a}, maxdd={maxdd_a}, final={final_value_a:.2f}")
    print(f"  策略B: sharpe={sharpe_b}, annual={annual_b}, maxdd={maxdd_b}, final={final_value_b:.2f}")
    print("=" * 50)

    assert abs(final_value_a - 104966.80) < 0.01, f"Expected final_value_a=104966.80, got {final_value_a}"
    assert abs(final_value_b - 105258.30) < 0.01, f"Expected final_value_b=105258.30, got {final_value_b}"
    assert abs(sharpe_a - 11.647332609673429) < 1e-6, f"Expected sharpe_a=11.647332609673429, got {sharpe_a}"
    assert abs(sharpe_b - 1.5914771127325362) < 1e-6, f"Expected sharpe_b=1.5914771127325362, got {sharpe_b}"
    assert abs(annual_a - 0.024145144571516192) < 1e-6, f"Expected annual_a=0.024145144571516192, got {annual_a}"
    assert abs(annual_b - 0.025543999840699848) < 1e-6, f"Expected annual_b=0.025543999840699848, got {annual_b}"
    assert abs(maxdd_a - 3.430658473286522) < 1e-6, f"Expected maxdd_a=3.430658473286522, got {maxdd_a}"
    assert abs(maxdd_b - 3.474930243071327) < 1e-6, f"Expected maxdd_b=3.474930243071327, got {maxdd_b}"

    print("\n测试通过!")
    return results_a, results_b


if __name__ == "__main__":
    print("=" * 60)
    print("Strategy Selection 策略选择测试")
    print("=" * 60)
    test_strategy_selection()
