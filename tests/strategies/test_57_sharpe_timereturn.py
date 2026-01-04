#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Sharpe TimeReturn 夏普比率和时间收益

参考来源: backtrader-master2/samples/sharpe-timereturn/sharpe-timereturn.py
测试夏普比率和时间收益分析器，使用双均线交叉策略
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


class SharpeTestStrategy(bt.Strategy):
    """测试夏普比率的策略 - 双均线交叉"""
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


def test_sharpe_timereturn():
    """测试 Sharpe TimeReturn"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(SharpeTestStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # 添加完整分析器 - 使用日线级别计算夏普率
    cerebro.addanalyzer(bt.analyzers.TimeReturn, timeframe=bt.TimeFrame.Years, _name="yearly")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, timeframe=bt.TimeFrame.Months, _name="monthly")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    # 获取分析结果
    yearly = strat.analyzers.yearly.get_analysis()
    monthly = strat.analyzers.monthly.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    ret = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    sharpe_ratio = sharpe.get('sharperatio', None)
    annual_return = ret.get('rnorm', 0)
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    total_trades = trades.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # 打印标准格式的结果
    print("\n" + "=" * 50)
    print("Sharpe TimeReturn 回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print(f"  Yearly Returns: {yearly}")
    print("=" * 50)

    # 断言测试结果
    assert strat.bar_num == 482, f"Expected bar_num=482, got {strat.bar_num}"
    assert abs(final_value - 104966.80) < 0.01, f"Expected final_value=104966.80, got {final_value}"
    assert abs(sharpe_ratio - 0.7210685207398165) < 1e-6, f"Expected sharpe_ratio=0.7210685207398165, got {sharpe_ratio}"
    assert abs(annual_return - 0.024145144571516192) < 1e-6, f"Expected annual_return=0.024145144571516192, got {annual_return}"
    assert abs(max_drawdown - 3.430658473286522) < 1e-6, f"Expected max_drawdown=3.430658473286522, got {max_drawdown}"
    assert total_trades == 9, f"Expected total_trades=9, got {total_trades}"

    print("\n测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("Sharpe TimeReturn 测试")
    print("=" * 60)
    test_sharpe_timereturn()
