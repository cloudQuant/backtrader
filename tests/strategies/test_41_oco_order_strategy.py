#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: OCO (One Cancels Other) 订单策略

参考来源: backtrader-master2/samples/oco/oco.py
当一个订单成交时自动取消其他关联订单
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


class OCOOrderStrategy(bt.Strategy):
    """OCO订单策略
    
    使用OCO订单，当一个订单成交时自动取消其他关联订单
    """
    params = dict(
        p1=5,
        p2=15,
        limit=0.005,
        limdays=3,
        limdays2=1000,
        hold=10,
    )

    def __init__(self):
        ma1 = bt.ind.SMA(period=self.p.p1)
        ma2 = bt.ind.SMA(period=self.p.p2)
        self.cross = bt.ind.CrossOver(ma1, ma2)
        self.orefs = list()
        self.holdstart = 0

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
            self.holdstart = len(self)

        if not order.alive() and order.ref in self.orefs:
            self.orefs.remove(order.ref)

    def notify_trade(self, trade):
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        self.bar_num += 1

        if self.orefs:
            return

        if not self.position:
            if self.cross > 0.0:
                p1 = self.data.close[0] * (1.0 - self.p.limit)
                p2 = self.data.close[0] * (1.0 - 2 * 2 * self.p.limit)
                p3 = self.data.close[0] * (1.0 - 3 * 3 * self.p.limit)

                valid1 = datetime.timedelta(self.p.limdays)
                valid2 = valid3 = datetime.timedelta(self.p.limdays2)

                o1 = self.buy(exectype=bt.Order.Limit, price=p1, valid=valid1, size=1)
                o2 = self.buy(exectype=bt.Order.Limit, price=p2, valid=valid2, oco=o1, size=1)
                o3 = self.buy(exectype=bt.Order.Limit, price=p3, valid=valid3, oco=o1, size=1)

                self.orefs = [o1.ref, o2.ref, o3.ref]

        else:
            if (len(self) - self.holdstart) >= self.p.hold:
                self.close()

    def stop(self):
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
              f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
              f"wins={self.win_count}, losses={self.loss_count}, "
              f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}")


def test_oco_order_strategy():
    """测试 OCO 订单策略"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="DATA")

    cerebro.addstrategy(OCOOrderStrategy)

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
    print("OCO 订单策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 497, f"Expected bar_num=497, got {strat.bar_num}"
    assert abs(final_value - 99936.2) < 0.01, f"Expected final_value=99936.20, got {final_value}"
    assert abs(sharpe_ratio - (-728.1006016110281)) < 1e-6, f"Expected sharpe_ratio=-728.1006016110281, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00031405198515841587)) < 1e-6, f"Expected annual_return=-0.000314051985158415, got {annual_return}"
    assert abs(max_drawdown - 0.3665283801049814) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("OCO 订单策略测试")
    print("=" * 60)
    test_oco_order_strategy()
