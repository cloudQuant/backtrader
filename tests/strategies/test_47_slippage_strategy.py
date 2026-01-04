#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Slippage 滑点策略

参考来源: backtrader-master2/samples/slippage/slippage.py
演示滑点设置对交易的影响
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


class SlippageStrategy(bt.Strategy):
    """滑点测试策略
    
    使用SMA交叉信号，测试滑点对交易价格的影响
    """
    params = (
        ('p1', 10),
        ('p2', 30),
    )

    def __init__(self):
        sma1 = bt.ind.SMA(period=self.p.p1)
        sma2 = bt.ind.SMA(period=self.p.p2)
        self.signal = bt.ind.CrossOver(sma1, sma2)
        self.order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        if order.status == bt.Order.Completed:
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

        if self.signal > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.signal < 0:
            if self.position:
                self.order = self.close()

    def stop(self):
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
              f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
              f"wins={self.win_count}, losses={self.loss_count}, "
              f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}")


def test_slippage_strategy():
    """测试 Slippage 滑点策略"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(50000.0)
    cerebro.broker.set_slippage_perc(0.01)  # 1%滑点

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="DATA")

    cerebro.addstrategy(SlippageStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

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
    print("Slippage 滑点策略回测结果:")
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
    assert strat.bar_num == 482, f"Expected bar_num=482, got {strat.bar_num}"
    assert abs(final_value - 52702.98) < 0.01, f"Expected final_value=52702.98, got {final_value}"
    assert abs(sharpe_ratio - (7.146238384824227)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.026251880915366368)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 7.696752586616294) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Slippage 滑点策略测试")
    print("=" * 60)
    test_slippage_strategy()
