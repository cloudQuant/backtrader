#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: BtcSentiment 比特币情绪策略

参考来源: Backtrader-Guide-AlgoTrading101/bt_main_btc.py 和 strategies.py
使用布林带指标基于Google Trends情绪数据进行BTC交易
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """根据脚本所在目录定位数据文件，避免相对路径读取失败"""
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


class BtcSentimentStrategy(bt.Strategy):
    """基于Google Trends情绪数据的BTC交易策略
    
    当情绪指标超过布林带上轨时做多，跌破下轨时做空，回到中间区域时平仓
    """
    params = (
        ('period', 10),
        ('devfactor', 1),
    )

    def __init__(self):
        self.btc_price = self.datas[0].close
        self.google_sentiment = self.datas[1].close
        self.bbands = bt.indicators.BollingerBands(
            self.google_sentiment, 
            period=self.params.period, 
            devfactor=self.params.devfactor
        )
        self.order = None

        # 统计变量
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_count += 1
            elif order.issell():
                self.sell_count += 1

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            pass

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

        # Long signal - 情绪指标超过布林带上轨
        if self.google_sentiment > self.bbands.lines.top[0]:
            if not self.position:
                self.order = self.buy()

        # Short signal - 情绪指标跌破布林带下轨
        elif self.google_sentiment < self.bbands.lines.bot[0]:
            if not self.position:
                self.order = self.sell()

        # Neutral signal - 平仓
        else:
            if self.position:
                self.order = self.close()

    def stop(self):
        """输出统计信息"""
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(
            f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
            f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, "
            f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}"
        )


def test_btc_sentiment_strategy():
    """测试 BtcSentiment 比特币情绪策略"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0.0025)

    print("正在加载BTC价格数据...")
    # 第一个数据源 - BTC价格数据 (Yahoo Finance CSV格式)
    btc_price_path = resolve_data_path("BTCUSD_Weekly.csv")
    data1 = bt.feeds.YahooFinanceCSVData(
        dataname=str(btc_price_path),
        fromdate=datetime.datetime(2018, 1, 1),
        todate=datetime.datetime(2020, 1, 1),
        timeframe=bt.TimeFrame.Weeks
    )
    cerebro.adddata(data1, name="BTCUSD")

    print("正在加载Google Trends情绪数据...")
    # 第二个数据源 - Google Trends情绪数据
    gtrends_path = resolve_data_path("BTC_Gtrends.csv")
    data2 = bt.feeds.GenericCSVData(
        dataname=str(gtrends_path),
        fromdate=datetime.datetime(2018, 1, 1),
        todate=datetime.datetime(2020, 1, 1),
        nullvalue=0.0,
        dtformat='%Y-%m-%d',
        datetime=0,
        time=-1,
        high=-1,
        low=-1,
        open=-1,
        close=1,
        volume=-1,
        openinterest=-1,
        timeframe=bt.TimeFrame.Weeks
    )
    cerebro.adddata(data2, name="BTC_Gtrends")

    cerebro.addstrategy(BtcSentimentStrategy, period=10, devfactor=1)

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    # 获取分析器结果
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("BtcSentiment 比特币情绪策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  win_count: {strat.win_count}")
    print(f"  loss_count: {strat.loss_count}")
    print(f"  sum_profit: {strat.sum_profit:.2f}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # 断言 - 确保策略正常运行
    assert strat.bar_num == 189, f"Expected bar_num=189, got {strat.bar_num}"
    assert strat.buy_count == 16, f"Expected buy_count=16, got {strat.buy_count}"
    assert strat.sell_count == 16, f"Expected sell_count=16, got {strat.sell_count}"
    assert strat.win_count == 8, f"Expected win_count=8, got {strat.win_count}"
    assert strat.loss_count == 8, f"Expected loss_count=8, got {strat.loss_count}"
    assert total_trades == 16, f"Expected total_trades=16, got {total_trades}"
    assert abs(final_value - 15301.43) < 0.01, f"Expected final_value=15301.43, got {final_value}"
    assert abs(sharpe_ratio - 0.8009805278904287) < 1e-6, f"Expected sharpe_ratio=0.8009805278904287, got {sharpe_ratio}"
    assert abs(annual_return - (0.2369894360907055)) < 1e-6, f"Expected annual_return=0.2369894360907055, got {annual_return}"
    assert abs(max_drawdown - 17.49122338684014) < 1e-6, f"Expected max_drawdown=17.49122338684014, got {max_drawdown}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("BtcSentiment 比特币情绪策略测试")
    print("=" * 60)
    test_btc_sentiment_strategy()
