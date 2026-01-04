#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Data Pandas 数据加载

参考来源: backtrader-master2/samples/data-pandas/data-pandas.py
测试从Pandas DataFrame加载数据，使用简单双均线交叉策略
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import pandas as pd
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


class SimpleMAStrategy(bt.Strategy):
    """简单双均线交叉策略 - 用于测试Pandas数据加载

    策略逻辑:
    - 快线上穿慢线时买入
    - 快线下穿慢线时卖出平仓
    """
    params = (('fast_period', 10), ('slow_period', 30))

    def __init__(self):
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)
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


def test_data_pandas():
    """测试 Data Pandas 数据加载"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")

    # 读取CSV到DataFrame
    dataframe = pd.read_csv(
        str(data_path),
        header=0,
        parse_dates=True,
        index_col=0,
    )

    print(f"DataFrame shape: {dataframe.shape}")

    # 使用PandasData加载
    data = bt.feeds.PandasData(dataname=dataframe, nocase=True)
    cerebro.adddata(data)

    # 添加简单双均线交叉策略
    cerebro.addstrategy(SimpleMAStrategy, fast_period=10, slow_period=30)

    # 添加完整分析器 - 使用日线级别计算夏普率
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    # 获取分析结果
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # 打印标准格式的结果
    print("\n" + "=" * 50)
    print("Data Pandas 数据加载回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
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

    print("\n测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("Data Pandas 数据加载测试")
    print("=" * 60)
    test_data_pandas()
