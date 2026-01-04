#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Calmar Analyzer 卡尔马分析器

参考来源: backtrader-master2/samples/calmar/calmar-test.py
测试Calmar比率分析器

Calmar比率 = 年化收益率 / 最大回撤
用于衡量策略的风险调整后收益
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


class CalmarTestStrategy(bt.Strategy):
    """测试Calmar分析器的策略"""
    params = (('p1', 15), ('p2', 50))

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


def test_calmar_analyzer():
    """测试 Calmar Analyzer"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    data = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2010, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(CalmarTestStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=100)

    # 添加分析器 - 使用日线级别计算夏普率
    cerebro.addanalyzer(bt.analyzers.Calmar, _name="calmar")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    # 获取分析结果
    calmar_analysis = strat.analyzers.calmar.get_analysis()
    # Calmar返回OrderedDict，键是日期，值是当期的Calmar比率
    if calmar_analysis:
        last_date = list(calmar_analysis.keys())[-1]
        calmar_ratio = calmar_analysis[last_date]
    else:
        calmar_ratio = None

    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    drawdown = strat.analyzers.drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # 打印标准格式的结果
    print("\n" + "=" * 50)
    print("Calmar Analyzer 回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  calmar_ratio: {calmar_ratio}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # 断言测试结果
    assert strat.bar_num == 1460, f"Expected bar_num=1460, got {strat.bar_num}"
    assert abs(final_value - 98020.00) < 0.01, f"Expected final_value=98020.00, got {final_value}"
    assert abs(sharpe_ratio - (-0.4689333841227036)) < 1e-6, f"Expected sharpe_ratio=-0.4689333841227036, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0033319591262466032)) < 1e-6, f"Expected annual_return=-0.0033319591262466032, got {annual_return}"
    assert abs(max_drawdown - 3.2398371164458886) < 1e-6, f"Expected max_drawdown=3.2398371164458886, got {max_drawdown}"
    assert total_trades == 16, f"Expected total_trades=16, got {total_trades}"
    # Calmar比率断言
    assert calmar_ratio is not None, "Calmar ratio should not be None"
    assert abs(calmar_ratio - (-4.713556837089328e-05)) < 1e-6, f"Expected calmar_ratio=-4.713556837089328e-05, got {calmar_ratio}"

    print("\n测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("Calmar Analyzer 测试")
    print("=" * 60)
    test_calmar_analyzer()
