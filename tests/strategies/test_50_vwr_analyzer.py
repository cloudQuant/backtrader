#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: VWR (Variability-Weighted Return) 分析器

参考来源: backtrader-master2/samples/vwr/vwr.py
测试VWR分析器

VWR (Variability-Weighted Return) 是一种风险调整后收益指标，
考虑收益率的波动性，类似于夏普比率但使用不同的计算方法
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


class VWRTestStrategy(bt.Strategy):
    """测试VWR分析器的策略"""
    params = (('p1', 10), ('p2', 30))

    def __init__(self):
        ma1 = bt.ind.SMA(period=self.p.p1)
        ma2 = bt.ind.SMA(period=self.p.p2)
        self.crossover = bt.ind.CrossOver(ma1, ma2)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if not order.alive():
            self.order = None
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

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


def test_vwr_analyzer():
    """测试 VWR Analyzer"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))
    cerebro.adddata(data)

    cerebro.addstrategy(VWRTestStrategy)

    # 添加分析器 - 使用日线级别计算夏普率
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.VWR, _name="vwr")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    # 获取分析结果
    returns = strat.analyzers.returns.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    vwr = strat.analyzers.vwr.get_analysis()
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # 提取 VWR 和 SQN 值
    vwr_ratio = vwr.get('vwr', None) if vwr else None
    sqn_ratio = sqn.get('sqn', None) if sqn else None

    # 打印标准格式的结果
    print("\n" + "=" * 50)
    print("VWR Analyzer 回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  vwr_ratio: {vwr_ratio}")
    print(f"  sqn_ratio: {sqn_ratio}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # 断言测试结果
    assert strat.bar_num == 482, f"Expected bar_num=482, got {strat.bar_num}"
    assert abs(final_value - 100496.68) < 0.01, f"Expected final_value=100496.68, got {final_value}"
    assert abs(sharpe_ratio - 0.7052880693319075) < 1e-6, f"Expected sharpe_ratio=0.7052880693319075, got {sharpe_ratio}"
    assert abs(annual_return - 0.0024415216620913218) < 1e-6, f"Expected annual_return=0.0024415216620913218, got {annual_return}"
    assert abs(max_drawdown - 0.35642156216533016) < 1e-6, f"Expected max_drawdown=0.35642156216533016, got {max_drawdown}"
    assert total_trades == 9, f"Expected total_trades=9, got {total_trades}"
    # VWR 比率断言
    assert vwr_ratio is not None, "VWR ratio should not be None"
    assert abs(vwr_ratio - 0.18671202740080534) < 1e-6, f"Expected vwr_ratio=0.18671202740080534, got {vwr_ratio}"
    # SQN 比率断言
    assert sqn_ratio is not None, "SQN ratio should not be None"
    assert abs(sqn_ratio - 1.1860238182921676) < 1e-6, f"Expected sqn_ratio=1.1860238182921676, got {sqn_ratio}"

    print("\n测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("VWR Analyzer 测试")
    print("=" * 60)
    test_vwr_analyzer()
