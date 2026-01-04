#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: PSAR 抛物线SAR指标

参考来源: backtrader-master2/samples/psar/psar.py
测试Parabolic SAR指标
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


class PSARStrategy(bt.Strategy):
    """PSAR策略 - 使用抛物线SAR指标"""
    def __init__(self):
        self.psar = bt.ind.ParabolicSAR()
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        if not order.alive():
            self.order = None

    def next(self):
        self.bar_num += 1
        if self.order:
            return
        # 当价格上穿PSAR时买入，下穿时卖出
        if self.data.close[0] > self.psar[0] and not self.position:
            self.order = self.buy()
        elif self.data.close[0] < self.psar[0] and self.position:
            self.order = self.close()

    def stop(self):
        print(f"PSAR: bar_num={self.bar_num}, buy={self.buy_count}, sell={self.sell_count}")


def test_psar_indicator():
    """测试 PSAR 抛物线SAR指标"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))
    cerebro.adddata(data)

    cerebro.addstrategy(PSARStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("PSAR 抛物线SAR指标回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 511, f"Expected bar_num=511, got {strat.bar_num}"
    assert abs(final_value - 105435.8) < 0.01, f"Expected final_value=105435.80, got {final_value}"
    assert abs(sharpe_ratio - (2.423395072162198)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.026394826422567123)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 3.0649081759956647) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("PSAR 抛物线SAR指标测试")
    print("=" * 60)
    test_psar_indicator()
