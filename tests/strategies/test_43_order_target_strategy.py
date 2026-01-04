#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Order Target 目标订单策略

参考来源: backtrader-master2/samples/order_target/order_target.py
使用order_target系列函数进行仓位管理
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


class OrderTargetStrategy(bt.Strategy):
    """目标订单策略
    
    使用order_target_percent根据日期动态调整仓位
    """
    params = (
        ('use_target_percent', True),
    )

    def __init__(self):
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
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
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        self.bar_num += 1

        if self.order:
            return

        dt = self.data.datetime.date()
        size = dt.day
        if (dt.month % 2) == 0:
            size = 31 - size

        percent = size / 100.0
        self.order = self.order_target_percent(target=percent)

    def stop(self):
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
              f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
              f"wins={self.win_count}, losses={self.loss_count}, "
              f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}")


def test_order_target_strategy():
    """测试 Order Target 目标订单策略"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(1000000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    data = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="YHOO")

    cerebro.addstrategy(OrderTargetStrategy)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Order Target 目标订单策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 503, f"Expected bar_num=503, got {strat.bar_num}"
    assert abs(final_value - 935260.98) < 0.01, f"Expected final_value=935260.98, got {final_value}"
    assert abs(sharpe_ratio - (-0.7774908309117542)) < 1e-6, f"Expected sharpe_ratio=-0.7774908309117542, got {sharpe_ratio}"
    assert abs(annual_return - (-0.03297541833201616)) < 1e-6, f"Expected annual_return=-0.03297541833201616, got {annual_return}"
    assert abs(max_drawdown - 9.591524052078132) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Order Target 目标订单策略测试")
    print("=" * 60)
    test_order_target_strategy()
