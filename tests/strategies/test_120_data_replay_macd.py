#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Data Replay 数据回放 - MACD策略

参考来源: test_58_data_replay.py
测试数据回放功能，使用MACD交叉策略
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


class ReplayMACDStrategy(bt.Strategy):
    """测试数据回放的策略 - MACD交叉

    策略逻辑:
    - MACD线上穿信号线时买入
    - MACD线下穿信号线时卖出平仓
    """
    params = (('fast_period', 12), ('slow_period', 26), ('signal_period', 9))

    def __init__(self):
        self.macd = bt.ind.MACD(
            period_me1=self.p.fast_period,
            period_me2=self.p.slow_period,
            period_signal=self.p.signal_period
        )
        self.crossover = bt.ind.CrossOver(self.macd.macd, self.macd.signal)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def log(self, txt, dt=None):
        ''' Logging function fot this strategy'''
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def notify_order(self, order):
        if not order.alive():
            self.order = None

        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Rejected:
            self.log(f"Rejected : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Margin:
            self.log(f"Margin : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Cancelled:
            self.log(f"Concelled : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Partial:
            self.log(f"Partial : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.log(
                    f" BUY : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

            else:  # Sell
                self.sell_count += 1
                self.log(
                    f" SELL : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))

        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))

    def next(self):
        self.bar_num += 1
        # 在前10个bar和关键位置打印详细的MACD值用于调试
        macd_val = self.macd.macd[0] if len(self.macd.macd) > 0 else 'N/A'
        signal_val = self.macd.signal[0] if len(self.macd.signal) > 0 else 'N/A'
        me1_val = self.macd.me1[0] if len(self.macd.me1) > 0 else 'N/A'
        me2_val = self.macd.me2[0] if len(self.macd.me2) > 0 else 'N/A'
        self.log(f"bar_num: {self.bar_num}, close: {self.data.close[0]}, len: {len(self.data)}, me1: {me1_val}, me2: {me2_val}, MACD: {macd_val}, signal: {signal_val}, crossover: {self.crossover[0]}")
        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def test_data_replay_macd():
    """测试 Data Replay 数据回放 - MACD策略"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))

    # 使用回放功能，将日线回放为周线
    cerebro.replaydata(
        data,
        timeframe=bt.TimeFrame.Weeks,
        compression=1
    )

    cerebro.addstrategy(ReplayMACDStrategy, fast_period=12, slow_period=26, signal_period=9)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # 添加完整分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Weeks, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("开始运行回测...")
    results = cerebro.run(preload=False)
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
    print("Data Replay MACD策略回测结果 (周线):")
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
    assert strat.bar_num == 344, f"Expected bar_num=344, got {strat.bar_num}"
    assert abs(final_value - 106870.40) < 0.01, f"Expected final_value=107568.30, got {final_value}"
    assert abs(sharpe_ratio - 1.3228391876325063) < 1e-6, f"Expected sharpe_ratio=1.353877653906896, got {sharpe_ratio}"
    assert abs(annual_return - 0.033781408229031695) < 1e-6, f"Expected annual_return=0.03715138721403644, got {annual_return}"
    assert abs(max_drawdown - 1.6636055151304665) < 1e-6, f"Expected max_drawdown=1.6528018163884495, got {max_drawdown}"
    assert total_trades == 9, f"Expected total_trades=10, got {total_trades}"

    print("\n测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("Data Replay MACD策略测试")
    print("=" * 60)
    test_data_replay_macd()
