#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Writer 输出测试

参考来源: backtrader-master2/samples/writer-test/
测试Writer输出功能，使用价格与SMA交叉策略
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


class WriterTestStrategy(bt.Strategy):
    """测试Writer的策略 - 价格与SMA交叉

    策略逻辑:
    - 价格上穿SMA时买入
    - 价格下穿SMA时卖出平仓
    """
    params = (('period', 15),)

    def __init__(self):
        sma = bt.ind.SMA(self.data, period=self.p.period)
        self.crossover = bt.ind.CrossOver(self.data.close, sma)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def next(self):
        self.bar_num += 1
        if self.crossover > 0 and not self.position:
            self.buy()
        elif self.crossover < 0 and self.position:
            self.close()


def test_writer():
    """测试 Writer 输出功能"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(WriterTestStrategy, period=15)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # 添加Writer（不输出CSV，只用于测试功能）
    cerebro.addwriter(bt.WriterFile, csv=False, rounding=4)

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
    print("Writer 输出功能回测结果:")
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
    assert strat.bar_num == 240, f"Expected bar_num=240, got {strat.bar_num}"
    assert abs(final_value - 102841.00) < 0.01, f"Expected final_value=102841.00, got {final_value}"
    assert abs(sharpe_ratio - 0.8252115748419219) < 1e-6, f"Expected sharpe_ratio=0.8252115748419219, got {sharpe_ratio}"
    assert abs(annual_return - 0.0280711170741429) < 1e-6, f"Expected annual_return=0.0280711170741429, got {annual_return}"
    assert abs(max_drawdown - 2.615813541154893) < 1e-6, f"Expected max_drawdown=2.615813541154893, got {max_drawdown}"
    assert total_trades == 12, f"Expected total_trades=12, got {total_trades}"

    print("\n测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("Writer 输出功能测试")
    print("=" * 60)
    test_writer()
