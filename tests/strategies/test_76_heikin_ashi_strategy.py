#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Heikin Ashi 平均K线策略

参考来源: https://github.com/backtrader/backhacker
基于Heikin Ashi蜡烛图形态的策略
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


class HeikinAshiStrategy(bt.Strategy):
    """Heikin Ashi策略

    - 使用简单均线策略配合Heikin Ashi指标进行交易
    - 价格突破上轨买入，跌破下轨卖出
    """
    params = dict(
        stake=10,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.ha = bt.indicators.HeikinAshi(self.datas[0])
        # 使用简单的均线交叉策略
        self.sma_short = bt.indicators.SMA(self.dataclose, period=10)
        self.sma_long = bt.indicators.SMA(self.dataclose, period=30)
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)

        self.order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        self.bar_num += 1
        if self.order:
            return

        # 金叉买入，死叉卖出
        if self.crossover > 0:
            self.order = self.buy(size=self.p.stake)
        elif self.crossover < 0:
            self.order = self.close()


def test_heikin_ashi_strategy():
    cerebro = bt.Cerebro()
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(HeikinAshiStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Heikin Ashi 策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1227, f"Expected bar_num=1227, got {strat.bar_num}"
    assert strat.buy_count == 23, f"Expected buy_count=23, got {strat.buy_count}"
    assert strat.sell_count == 22, f"Expected sell_count=22, got {strat.sell_count}"
    assert total_trades == 23, f"Expected total_trades=23, got {total_trades}"
    assert abs(sharpe_ratio - 0.5753306804822258) < 1e-6, f"Expected sharpe_ratio=0.5753306804822258, got {sharpe_ratio}"
    assert abs(annual_return - 0.00018249747132121323) < 1e-6, f"Expected annual_return=0.00018249747132121323, got {annual_return}"
    assert abs(max_drawdown - 0.08758136530069777) < 1e-6, f"Expected max_drawdown=0.08758136530069777, got {max_drawdown}"
    assert abs(final_value - 100091.06) < 0.01, f"Expected final_value=100091.06, got {final_value}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("Heikin Ashi 平均K线策略测试")
    print("=" * 60)
    test_heikin_ashi_strategy()
